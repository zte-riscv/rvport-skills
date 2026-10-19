# Copyright 2026 ZTE Corporation
# SPDX-License-Identifier: Apache-2.0

"""Solver 基类。"""
import os
from abc import ABC, abstractmethod

import ahocorasick

from .common import CodeTooLong, NUMBER_LINES_TOO_LONG

# 各 solver 对应的 solver_type 整数枚举（与 solvers_mapping.py 一致）
SOLVER_TYPES = {}


def create_automaton(words):
    automaton = ahocorasick.Automaton()
    for idx, word in enumerate(words):
        automaton.add_word(word, (idx, word))
    automaton.make_automaton()
    return automaton


class Solver(ABC):
    solver_type = None       # int，子类必填
    solver_description = ""  # 中文描述，子类必填

    @staticmethod
    @abstractmethod
    def matches_file(file_name):
        pass

    @classmethod
    @abstractmethod
    def solve(cls, source_file):
        """返回 (change_list, found_list)；change_list 元素为
        [start_line, end_line, suggestion, code_too_long, code]"""
        pass

    @classmethod
    def get_solver_type(cls):
        return cls.solver_type

    @staticmethod
    def extract_code(lines, start_lineno, end_lineno):
        number_lines = end_lineno - start_lineno + 1
        code_too_long = number_lines > NUMBER_LINES_TOO_LONG
        if code_too_long:
            return CodeTooLong.CODE_TOO_LONG, None
        mycode = "\n".join(lines[start_lineno - 1:end_lineno])
        return CodeTooLong.HAS_SOURCE_CODE, mycode
