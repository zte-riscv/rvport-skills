# Copyright 2026 ZTE Corporation
# SPDX-License-Identifier: Apache-2.0

"""meson.build 构建脚本扫描。"""
import re

from .common import SOLVER_TYPE_BUILD_SCRIPT, SOLVER_DESCRIPTIONS
from .solver_base import Solver

ARCH_OTHERS = (
    r"(?<![a-zA-Z0-9])("
    r"x86|x86_64|amd64|amd64p32|i386|i486|i586|i686|x32|"
    r"arm|arm64|arm64be|armbe|aarch64|aarch64_be|armv8-a|armv7|armv8|armv8a"
    r"ppc|ppc64|ppc64le|powerpc|powerpc64|powerpc64le|"
    r"mips|mips64|mips64le|mips64p32|mips64p32le|mipsle|"
    r"sparc|sparc64|sparcv9|"
    r"s390|s390x|"
    r"loongarch64|loong64|"
    r"wasm|wasm32|wasm64|"
    r"alpha|hppa|ia64|m68k|tilegx|xtensa"
    r")(?![a-zA-Z0-9])"
)

ARCH_RISCV = (
    r"(?<![a-zA-Z0-9])("
    r"riscv|risc-v|rvv|riscv64"
    r")(?![a-zA-Z0-9])"
)


class BuildMesonSolver(Solver):
    solver_type = SOLVER_TYPE_BUILD_SCRIPT
    solver_description = SOLVER_DESCRIPTIONS[SOLVER_TYPE_BUILD_SCRIPT]

    patterns = [
        (r'host_machine.cpu_family\(\)', 'arch_case'),
        (ARCH_OTHERS, 'arch_detect')
    ]

    migration_advice = {
        'arch_case': "架构分支缺少RISC-V支持！需要添加类似分支：arch_subdir = 'riscv'",
        'arch_detect': "检测到非RISC架构，需要进一步检查"
    }

    compiled_patterns = [
        (re.compile(p[0], re.IGNORECASE), p[1]) for p in patterns
    ]

    @staticmethod
    def matches_file(file_name):
        ends = ['meson.build', 'meson_options.txt']
        return any(file_name.endswith(ext) for ext in ends)

    @classmethod
    def solve(cls, source_file):
        lines = source_file.get_code_lines()
        return BuildMesonSolver.find_pattern(lines, cls.compiled_patterns,
                                             cls.migration_advice)

    @staticmethod
    def find_pattern(lines, compiled_patterns, migration_advice):
        results = []
        in_arch_case = False
        case_start_line = 0
        case_lines = []
        has_riscv_branch = False

        for line_number, line in enumerate(lines, 1):
            stripped_line = line.strip()
            if stripped_line.startswith('#') or not stripped_line:
                continue
            next_line = lines[line_number] if line_number < len(lines) else ""

            if not in_arch_case:
                for pattern, pattern_type in compiled_patterns:
                    if pattern_type == 'arch_case' and pattern.search(
                            stripped_line + " " + next_line[:20]):
                        in_arch_case = True
                        case_start_line = line_number
                        case_lines = [stripped_line]
                        has_riscv_branch = False
                        break

            if in_arch_case:
                case_lines.append(stripped_line)
                if re.search(ARCH_RISCV, stripped_line, re.IGNORECASE):
                    has_riscv_branch = True
                # meson 用 elif / endif 结束 if 块
                if re.match(r'^(elif|else|endif)\b', stripped_line):
                    if stripped_line.startswith('endif'):
                        in_arch_case = False
                        if not has_riscv_branch:
                            advice = migration_advice.get('arch_case')
                            code_too_long, mycode = Solver.extract_code(
                                lines, case_start_line, line_number)
                            results.append(
                                (case_start_line, line_number, advice, code_too_long,
                                 mycode))
                        continue
                    # elif/else 分支继续留在块内判断 riscv 分支
                    continue

            if not in_arch_case:
                for pattern, pattern_type in compiled_patterns:
                    match = pattern.search(stripped_line)
                    if match:
                        advice = migration_advice.get(pattern_type, "需要RISC-V兼容性检查")
                        code_too_long, mycode = Solver.extract_code(
                            lines, line_number, line_number)
                        results.append((line_number, line_number, advice, code_too_long,
                                        mycode))
                        break

        return results, []
