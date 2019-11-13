# /***********************************************************************
# Copyright 2019 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the 'License');
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an 'AS IS' BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Note that these code samples being shared are not official Google
# products and are not formally supported.
# ************************************************************************/

"""
Decodes CSV files. If given a folder, recursively opens.

Handles ZIP files.
"""
import os
import shutil
import tarfile
import zipfile
from datetime import datetime

import pandas as pd
from absl import logging
from xlrd import XLRDError


class Decoder(object):
    SINGLE_FILE = 1
    SEPARATE_FILES = 2

    def __init__(self, desired_encoding, path, dict_map,
                 out_type=SINGLE_FILE, dest='out.csv', callback=None):
        self.first = True  # ignore headers when False
        self.map: dict = {k.lower():v for k,v in dict_map.items()}
        self.dtypes = {k: str for k in self.map.keys()}
        self.out_type = out_type
        self.desired_encoding = desired_encoding
        self.path = path
        self.dest = dest
        self._file_count = 0
        self.dir = None
        self.rows_opened: int = 0
        self.callback = callback

    @property
    def filename(self):
        if self.out_type == Decoder.SINGLE_FILE:
            return self.dest
        self._file_count += 1
        return self._file_count

    def run(self):
        self.dir = '/tmp/updir-' + self.time
        os.mkdir(self.dir)
        Decoder.ChooseyDecoder(self, self.path).run()
        return (
            self.dir
            if self.out_type != Decoder.SINGLE_FILE
            else '{}/{}'.format(
                self.dir, self.dest
            )
        )

    def guess_schema(self, df: pd.DataFrame):
        for c in df:
            column = df[c]
            val = column[0]
            if self.callback is not None:
                self.callback(val)

    @property
    def time(self) -> str:
        return str(datetime.now().strftime('%Y%m%d%H%m%S%f'))

    class AbstractDecoder(object):
        def __init__(self, parent: 'Decoder', path: str):
            self.path = path
            self.parent = parent

    class ChooseyDecoder(AbstractDecoder):
        def run(self):
            if os.path.isdir(self.path):
                return Decoder.DirectoryDecoder(self.parent, self.path).run()
            elif self.path.endswith('.csv') or self.path.endswith('.xlsx'):
                return Decoder.FileDecoder(self.parent, self.path).run()
            elif tarfile.is_tarfile(self.path):
                return Decoder.TarfileDecoder(self.parent, self.path).run()
            elif zipfile.is_zipfile(self.path):
                return Decoder.ZipfileDecoder(self.parent, self.path).run()
            else:
                logging.info('Skipping ' + self.path)

    class DirectoryDecoder(AbstractDecoder):
        def run(self):
            for path in os.listdir(self.path):
                p = self.path + '/' + path
                Decoder.ChooseyDecoder(
                    self.parent, p
                ).run()

    class FileDecoder(AbstractDecoder):
        def run(self):
            try:
                self.decode_excel()
            except XLRDError as err:
                self.decode_csv()
                return

        def decode_excel(self):
            df: pd.DataFrame = pd.read_excel(
                self.path,
                dtype=self.parent.dtypes,
            )
            df.rename(columns=self.parent.map)
            self.write(df)
            logging.info('Wrote to ' + self.path)
            return

        def decode_csv(self):
            for encoding in ['utf-8', 'utf-16', 'latin-1']:
                try:
                    df = pd.read_csv(
                        self.path,
                        encoding=encoding,
                        dtype=self.parent.dtypes,
                    )
                    self.write(df)
                    logging.info('Decoded %s from %s',
                                 self.path, encoding)
                    break
                except (UnicodeDecodeError, UnicodeError):
                    if encoding == 'latin-1':
                        raise
                    logging.info(
                        'Unicode error for %s with %s',
                        self.path,
                        encoding
                    )

        def write(self, df: pd.DataFrame):
            def rename_columns(s: str):
                l = s.lower()
                return self.parent.map[l] if l in self.parent.map else l

            doing_single_file = self.parent.out_type == Decoder.SINGLE_FILE
            if doing_single_file:
                write_method = 'a'
                include_headers = self.parent.first
                if self.parent.first:
                    self.parent.first = False
            else:
                include_headers = True
                write_method = 'w'
            df.rename(rename_columns, inplace=True, copy=False, axis='columns')
            self.parent.rows_opened += len(df.index)
            df.to_csv(
                '{}/{}'.format(self.parent.dir, self.parent.filename),
                index=False,
                header=include_headers,
                mode=write_method,
                columns=self.parent.map.values()
            )

        def decode_file(self, encoding: str, file: bytes):
            return file.decode(encoding).encode(self.parent.desired_encoding)

    class TarfileDecoder(AbstractDecoder):
        def run(self):
            with tarfile.open(self.path) as th:
                extraction_directory = '/tmp/tar-output-' + self.parent.time
                th.extractall(extraction_directory)
                Decoder.DirectoryDecoder(self.parent, extraction_directory).run()
                shutil.rmtree(extraction_directory)

    class ZipfileDecoder(AbstractDecoder):
        def run(self):
            with zipfile.ZipFile(self.path, 'r') as zh:
                extraction_directory = '/tmp/zip-output-' + self.parent.time
                zh.extractall(extraction_directory)
                Decoder.DirectoryDecoder(
                    self.parent, extraction_directory
                ).run()
                shutil.rmtree(extraction_directory)