# Copyright 2026 ZTE Corporation
# SPDX-License-Identifier: Apache-2.0

"""Makefile 架构参数扫描。"""
import re

from .common import CodeTooLong, SOLVER_TYPE_MAKEFILE, SOLVER_DESCRIPTIONS
from .solver_base import Solver

MARCH_RV64GC = "-march=rv64gc"


class MakefileSolver(Solver):
    solver_type = SOLVER_TYPE_MAKEFILE
    solver_description = SOLVER_DESCRIPTIONS[SOLVER_TYPE_MAKEFILE]

    patterns = [
        (r'\b(FLAGS|CFLAGS|CXXFLAGS)\s*=\s*(.*)', 'flags'),
        (r'-m64\b|-mcpu=[^\s]+|-march=[^\s]+|-mtune=[^\s]+|-mabi=[^\s]+', 'target'),
    ]

    suggestion = "此处参数可能与架构相关，请修改为RISCV支持的参数"
    migration_advice = {
        'flags': suggestion,
        'target': suggestion,
    }
    compiled_patterns = [(re.compile(p[0], re.IGNORECASE), p[1]) for p in patterns]

    @staticmethod
    def matches_file(file_name):
        return "Makefile" in file_name or file_name.endswith(".mk")

    @staticmethod
    def show_suggestion(line) -> bool:
        riscv_params = {
            "-mtune=generic": False,
            "-mabi=lp64d": False,
            "-fsigned-char": False,
        }
        has_march_rv64gc = False
        for param in line.strip().split():
            if MARCH_RV64GC in param or "-march=rv64imafdc" in param:
                has_march_rv64gc = True
            elif param in riscv_params:
                riscv_params[param] = True
        if not has_march_rv64gc:
            return True
        for _, has_value in riscv_params.items():
            if not has_value:
                return True
        return False

    @classmethod
    def create_suggestion_for_file(cls, lines):
        lineno_and_suggestions = []
        for lineno, raw_line in enumerate(lines, start=1):
            line = raw_line.strip()
            for pattern, pattern_type in cls.compiled_patterns:
                match = pattern.search(line)
                if match and MakefileSolver.show_suggestion(line):
                    advice = cls.migration_advice.get(pattern_type, cls.suggestion)
                    lineno_and_suggestions.append(
                        [lineno, lineno, advice, CodeTooLong.HAS_SOURCE_CODE, line])
                    break
        return lineno_and_suggestions, []

    @classmethod
    def solve(cls, source_file):
        lines = source_file.remove_makefile_comments()
        return cls.create_suggestion_for_file(lines)
