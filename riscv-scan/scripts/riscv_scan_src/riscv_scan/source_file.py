# Copyright 2026 ZTE Corporation
# SPDX-License-Identifier: Apache-2.0

"""源码文件读取与注释剥离。

剔除 python-magic 文件类型探测（扫描入口只处理已知文本扩展名，二进制
文件不会进入 solver），保留编码探测与 C/Makefile/Shell 三类注释剥离。
"""
import re

import chardet


def is_text_file(file_path):
    # 独立版：无 libmagic 依赖，用扩展名 + NUL 字节兜底判断
    try:
        with open(file_path, 'rb') as f:
            head = f.read(8192)
        if b'\x00' in head:
            return False
        return True
    except (OSError, IOError, PermissionError, FileNotFoundError):
        return False


class SourceFile:
    def __init__(self, file_path):
        self.file_path = file_path
        self.code = None
        self.code_lines = None
        self.code_remove_c_comments = None
        self.code_remove_c_comments_lines = None
        self.code_remove_makefile_comments = None
        self.code_remove_multiple_comments = None
        self.code_remove_multiple_comments_lines = None

    def get_file_path(self):
        return self.file_path

    def get_code(self):
        if self.code is not None:
            return self.code
        try:
            with open(self.file_path, "rb") as file:
                raw_data = file.read()
            if not raw_data:
                return ''
            encoding_info = chardet.detect(raw_data)
            encoding = encoding_info['encoding']
            content = ''
            try:
                if encoding.lower() in ['utf-8', 'utf-8-sig']:
                    content = raw_data.decode('utf-8-sig')
                else:
                    content = raw_data.decode(encoding)
                if content.startswith('﻿'):
                    content = content[1:]
            except (UnicodeDecodeError, AttributeError, LookupError, TypeError):
                for enc in ['utf-8', 'latin-1', 'cp1252']:
                    try:
                        content = raw_data.decode(enc)
                        if content.startswith('﻿'):
                            content = content[1:]
                        break
                    except (UnicodeDecodeError, UnicodeError, LookupError):
                        continue
            self.code = content.replace('\x0c', '').replace('\r\n', '\n').replace('\r', '\n')
            return self.code
        except (FileNotFoundError, OSError, PermissionError, UnicodeError):
            return ''

    def get_code_lines(self):
        if self.code_lines is None:
            self.code_lines = self.get_code().splitlines()
        return self.code_lines

    def _compute_remove_c_comments(self):
        """移除 C 语言风格的注释，并保持原始行号"""
        code = self.get_code()
        pattern = r'''
            ("(?:\\.|[^"\\])*")|      # 双引号字符串
            ('(?:\\.|[^'\\])*')|      # 单引号字符
            (/\*[\s\S]*?\*/)|         # 多行注释
            (//[^\n]*)                # 单行注释
        '''

        def replacer(match):
            if match.group(1):
                return match.group(1)
            if match.group(2):
                return match.group(2)
            if match.group(3):
                comment = match.group(3)
                return '\n' * comment.count('\n')
            if match.group(4):
                return ''
            return match.group(0)

        return re.sub(pattern, replacer, code, flags=re.VERBOSE)

    def remove_c_comments(self):
        if self.code_remove_c_comments is None:
            self.code_remove_c_comments = self._compute_remove_c_comments()
        return self.code_remove_c_comments

    def remove_c_comments_lines(self):
        if self.code_remove_c_comments_lines is None:
            self.code_remove_c_comments_lines = self.remove_c_comments().splitlines()
        return self.code_remove_c_comments_lines

    def _compute_remove_multiple_comments(self):
        """移除 shell 文件中单行以及多行注释，并保持原始行号"""
        code = self.get_code()
        code = re.sub(r'^[ \t]*:<<[ \t]*([\'"]?)(\w+)\1[ \t]*\n.*?\n^\2[ \t]*$',
                      lambda m: '\n' * m.group().count('\n'),
                      code,
                      flags=re.DOTALL | re.MULTILINE)
        code = re.sub(r'#.*?$', ' ', code, flags=re.MULTILINE)
        return code

    def remove_multiple_comments_lines(self):
        if self.code_remove_multiple_comments is None:
            self.code_remove_multiple_comments = self._compute_remove_multiple_comments()
        if self.code_remove_multiple_comments_lines is None:
            self.code_remove_multiple_comments_lines = \
                self.code_remove_multiple_comments.splitlines()
        return self.code_remove_multiple_comments_lines

    def _remove_mkfile_comments(self):
        return re.sub(r'#.*?$', '', self.get_code(), flags=re.MULTILINE)

    def remove_makefile_comments(self):
        if self.code_remove_makefile_comments is None:
            self.code_remove_makefile_comments = self._remove_mkfile_comments().splitlines()
        return self.code_remove_makefile_comments
