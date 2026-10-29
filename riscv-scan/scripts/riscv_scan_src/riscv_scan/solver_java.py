# Copyright 2026 ZTE Corporation
# SPDX-License-Identifier: Apache-2.0

"""Java 源码扫描（对齐 server/plugin/codemig/solver/java_source_code_solver.py）。

正则匹配 JNI 本地库加载：System.load/loadLibrary、Runtime.getRuntime()。
"""
import re

from .common import CodeTooLong, SOLVER_TYPE_JAVA, SOLVER_DESCRIPTIONS
from .solver_base import Solver


class JavaSourceCodeSolver(Solver):
    solver_type = SOLVER_TYPE_JAVA
    solver_description = SOLVER_DESCRIPTIONS[SOLVER_TYPE_JAVA]

    patterns = [
        (r'\b(?:System\s*\.\s*(?:load|loadLibrary)|Native\s*\.\s*loadLibrary)\s*\([^)]*\)',
         'jni_standard_load'),
        (r'\bRuntime\s*\.\s*getRuntime\s*\(\s*\)\s*\.\s*(?:load|loadLibrary)\s*\([^)]*\)',
         'runtime_load'),
        (r'\b(\w+)\s*=\s*(?:java\s*\.\s*lang\s*\.\s*)?\bRuntime\s*\.\s*getRuntime\s*\(\s*\)\s*;',
         'runtime_getruntime_variable_class'),
        (r'(\w+)\.(?:load\b|loadLibrary)\s*\(', 'runtime_getruntime_variable'),
    ]

    migration_advice = {
        'jni_standard_load': (
            "检测到JNI标准库加载调用。确保本地库有RISC-V版本(.so文件),检查库文件名是否遵循RISC-V命名约定,"
            "考虑使用System.mapLibraryName()获取平台相关库名"
        ),
        'runtime_load':
            "检测到通过Runtime加载本地库。确保JVM是RISC-V兼容版本,验证库搜索路径包含RISC-V库目录",
        'runtime_getruntime_variable':
            "检测到通过Runtime加载本地库。确保JVM是RISC-V兼容版本,验证库搜索路径包含RISC-V库目录",
    }

    compiled_patterns = [(re.compile(p[0], re.IGNORECASE), p[1]) for p in patterns]

    @staticmethod
    def matches_file(file_name):
        return file_name.endswith(".java")

    @classmethod
    def solve(cls, source_file):
        lines = source_file.get_code_lines()
        return JavaSourceCodeSolver.find_pattern(lines, cls.compiled_patterns,
                                                 cls.migration_advice)

    @staticmethod
    def find_pattern(lines, compiled_patterns, migration_advice):
        results = []
        tmpclass = []
        in_multiline_comment = False
        for line_number, line in enumerate(lines, 1):
            line = line.strip()
            if '/*' in line and not in_multiline_comment:
                in_multiline_comment = True
                content = line.split('/*', 1)[0]
                if '*/' in line.split('/*', 1)[1]:
                    in_multiline_comment = False
                    content = content + " " + line.split('*/', 1)[1].strip()
                line = content
            elif in_multiline_comment and '*/' in line:
                in_multiline_comment = False
                line = line.split('*/', 1)[1].strip()

            if in_multiline_comment:
                continue

            if "//" in line:
                line = line.split('//', 1)[0].strip()

            for pattern, pattern_type in compiled_patterns:
                match = pattern.search(line)
                if match:
                    if pattern_type == 'runtime_getruntime_variable_class':
                        tmpclass.append(match.group(1))
                        continue
                    if pattern_type == 'runtime_getruntime_variable':
                        if match.group(1) not in tmpclass:
                            continue

                    advice = migration_advice.get(pattern_type, "需要进一步检查RISC-V兼容性")
                    results.append((line_number, line_number,
                                    f'匹配到{match.group()}代码，{advice}',
                                    CodeTooLong.HAS_SOURCE_CODE, line))
                    break
        return results, []
