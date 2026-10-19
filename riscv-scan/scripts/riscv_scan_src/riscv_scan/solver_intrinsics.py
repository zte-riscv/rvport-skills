# Copyright 2026 ZTE Corporation
# SPDX-License-Identifier: Apache-2.0

"""intrinsic 头文件引用扫描。"""
import os
import re

from .common import matches_c_file, CodeTooLong, SOLVER_TYPE_INTRINSICS, SOLVER_DESCRIPTIONS
from .solver_base import Solver, create_automaton

REPLACEMENT = "建议使用riscv的intrinsics进行替换、优化文件中{arch}的intrinsic函数"

ARCH_X86 = "__x86_64__"
ARCH_ARM = "__aarch64__"
ARCH_UNKNOWN = "unknown_arch"

CONF_PATH = os.path.join(os.path.dirname(__file__), 'solver')


def load_head_from_file(file_path: str) -> list:
    head = []
    with open(file_path, 'r') as file:
        head = [line.strip() for line in file if line.strip()]
    return head


X86_HEAD_SET = {head: ARCH_X86 for head in
                load_head_from_file(os.path.join(CONF_PATH, 'x86.intrinsics'))}
ARM_HEAD_SET = {head: ARCH_ARM for head in
                load_head_from_file(os.path.join(CONF_PATH, 'aarch64.intrinsics'))}

INTRINSICS = {}
INTRINSICS.update(ARM_HEAD_SET)
INTRINSICS.update(X86_HEAD_SET)


class IntrinsicsSolver(Solver):
    solver_type = SOLVER_TYPE_INTRINSICS
    solver_description = SOLVER_DESCRIPTIONS[SOLVER_TYPE_INTRINSICS]

    automaton = create_automaton(INTRINSICS)

    @staticmethod
    def solve_intrinsics(lines, line_number_and_matches):
        suggestions = []
        for line_number, matches in line_number_and_matches:
            arch = INTRINSICS.get(matches[0], ARCH_UNKNOWN)
            suggestion = REPLACEMENT.format(arch=arch, file_name=matches[0])
            suggestions.append([line_number, line_number, suggestion, CodeTooLong.HAS_SOURCE_CODE,
                                lines[line_number - 1]])
        return suggestions, []

    @staticmethod
    def matches_file(file_name):
        return matches_c_file(file_name)

    @classmethod
    def find_matches(cls, lines):
        line_number_and_matches = []
        for line_number, line in enumerate(lines, start=1):
            matches = []
            for _, (_, match) in cls.automaton.iter(line):
                pattern = rf'\b{re.escape(match)}\b'
                if re.search(pattern, line):
                    matches.append(match)
            if matches:
                line_number_and_matches.append((line_number, matches))
        return line_number_and_matches

    @classmethod
    def solve(cls, source_file):
        lines = source_file.remove_c_comments_lines()
        line_number_and_matches = cls.find_matches(lines)
        return IntrinsicsSolver.solve_intrinsics(lines, line_number_and_matches)
