# Copyright 2026 ZTE Corporation
# SPDX-License-Identifier: Apache-2.0

"""Cython .pyx 扫描（对齐 server/plugin/codemig/solver/cython_source_code_solver.py）。"""
import re

from .common import CodeTooLong, SOLVER_TYPE_PYTHON, SOLVER_DESCRIPTIONS
from .solver_base import Solver


class CythonSourceCodeSolver(Solver):
    solver_type = SOLVER_TYPE_PYTHON
    solver_description = SOLVER_DESCRIPTIONS[SOLVER_TYPE_PYTHON]

    patterns = [
        (r'\b(?:ctypes\.CDLL|ctypes\.cdll\.LoadLibrary|cdll\.LoadLibrary|cffi\.FFI\(\)\.dlopen)\s*',
         'ctypes_dynamic_loading'),
        (r'\bfrom\s+ctypes\s+import\s+\w*[dD][lL][lL]\b', 'ctypes_import'),
    ]

    migration_advice = {
        'ctypes_dynamic_loading':
            "检测到动态加载C库的调用。请确保目标库有RISC-V版本， 使用.so扩展名而非.dll， 并考虑使用跨平台加载方式",
        'ctypes_import':
            "检测到ctypes导入。确保ctypes调用的函数在RISC-V上行为一致，并检查结构体对齐和字节序",
    }

    compiled_patterns = [(re.compile(p[0]), p[1]) for p in patterns]

    @staticmethod
    def matches_file(file_name):
        return file_name.endswith(".pyx")

    @classmethod
    def solve(cls, source_file):
        return CythonSourceCodeSolver.find_pattern(source_file.get_code_lines(),
                                                   cls.compiled_patterns,
                                                   cls.migration_advice)

    @staticmethod
    def find_pattern(lines, compiled_patterns, migration_advice):
        results = []
        for line_number, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            for pattern, pattern_type in compiled_patterns:
                match = pattern.search(line)
                if match:
                    advice = migration_advice.get(pattern_type, "需要进一步检查RISC-V兼容性")
                    results.append((line_number, line_number, f'匹配到{match.group()}代码，{advice}',
                                    CodeTooLong.HAS_SOURCE_CODE, line))
                    break
        return results, []
