# Copyright 2026 ZTE Corporation
# SPDX-License-Identifier: Apache-2.0

"""__builtin_* 内置函数扫描。"""
import os
import re

from .common import matches_c_file, CodeTooLong, SOLVER_TYPE_BUILTIN, SOLVER_DESCRIPTIONS, \
    load_list_from_file
from .solver_base import Solver

CONF_PATH = os.path.join(os.path.dirname(__file__), 'solver')

X86_BUILDIN_SET = load_list_from_file(os.path.join(CONF_PATH, 'x86.builtin'))
ARM_BUILDIN_SET = load_list_from_file(os.path.join(CONF_PATH, 'aarch64.builtin'))
BUILTIN_FUNC_SET = set(X86_BUILDIN_SET + ARM_BUILDIN_SET)


class BuiltinSolver(Solver):
    solver_type = SOLVER_TYPE_BUILTIN
    solver_description = SOLVER_DESCRIPTIONS[SOLVER_TYPE_BUILTIN]

    builtin_not_supported_suggestion = "// Line {}, built-in {} {} not supported.\n"
    builtin_pattern = re.compile(r"__builtin_\w+(?=\s*)")

    @staticmethod
    def find_matched_positions(line, matches):
        matched_positions = []
        match_find_start = 0
        for match in matches:
            matched_position = line.find(match, match_find_start)
            matched_positions.append([match, matched_position])
            match_find_start = matched_position + len(match)
        return matched_positions

    @staticmethod
    def join_matches(matches):
        values = []
        for i, match in enumerate(matches):
            if i == 0:
                pass
            elif i == len(matches) - 1:
                values.append(" and ")
            else:
                values.append(", ")
            values.append(match[0])
            values.append("(offset: ")
            values.append(str(match[1]))
            values.append(")")
        return "".join(values)

    @staticmethod
    def create_is_or_are(length):
        if length == 1:
            return "is"
        return "are"

    @classmethod
    def create_x86_builtins_suggestion(cls, lines, line_number_and_matches):
        line_number_and_suggestions = []
        for line_number, matches in line_number_and_matches:
            suggestion = cls.builtin_not_supported_suggestion.format(
                line_number,
                BuiltinSolver.join_matches(matches),
                BuiltinSolver.create_is_or_are(len(matches)))
            line_number_and_suggestions.append(
                [line_number, line_number, suggestion, CodeTooLong.HAS_SOURCE_CODE,
                 lines[line_number - 1]])
        return line_number_and_suggestions, []

    @classmethod
    def find_matches_for_file(cls, lines):
        line_number_and_matches = []
        for line_number, line in enumerate(lines, start=1):
            matches = cls.builtin_pattern.findall(line)
            filtered = [m for m in matches if m in BUILTIN_FUNC_SET]
            matched_positions = cls.find_matched_positions(line, filtered)
            if matched_positions:
                line_number_and_matches.append([line_number, matched_positions])
        return line_number_and_matches

    @classmethod
    def solve(cls, source_file):
        lines = source_file.remove_c_comments_lines()
        line_number_and_matches = cls.find_matches_for_file(lines)
        return cls.create_x86_builtins_suggestion(lines, line_number_and_matches)

    @staticmethod
    def matches_file(file_name):
        return matches_c_file(file_name)
