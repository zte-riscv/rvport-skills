# Copyright 2026 ZTE Corporation
# SPDX-License-Identifier: Apache-2.0

"""shell 脚本扫描（对齐 server/plugin/codemig/solver/shell_source_code_solver.py）。

两步：
1. CaseBlockProcessor：`case "$(uname -m)"` / `case "$ARCH"` 块——含 riscv
   关键字的块整块替换为空行（不产条目），不含 riscv 的块原样保留。
2. find_pattern：保留行按 arch_detect 正则逐行命中（x86/amd64/arm64/...）。
"""
import re

from .common import CodeTooLong, SOLVER_TYPE_BUILD_SCRIPT, SOLVER_DESCRIPTIONS
from .solver_base import Solver


class CaseBlockProcessor:
    case_pattern = re.compile(
        r'case\s+"\$'
        r'(?:'
        r'\(uname\s+-m\)'
        r'|'
        r'ARCH'
        r')'
        r'"'
    )
    riscv_pattern = re.compile(r'riscv(?:64|32)?')

    @classmethod
    def process_lines(cls, lines):
        """识别 case 块；含 riscv 的块替换为等量空行，其余原样保留。"""
        processed_lines = []
        i = 0
        total_lines = len(lines)

        while i < total_lines:
            line = lines[i]
            matched = False
            try:
                if cls.case_pattern.search(line):
                    start_line = i
                    end_line = cls._find_case_block_end(lines, i)
                    if not end_line:
                        raise ValueError("文件不完整")
                    block_lines = lines[start_line:end_line + 1]

                    if cls._contains_riscv(block_lines):
                        processed_lines.extend(['\n'] * (end_line - start_line + 1))
                        i = end_line + 1
                        matched = True

                if not matched:
                    processed_lines.append(line)
                    i += 1
            except ValueError:
                return processed_lines

        return processed_lines

    @staticmethod
    def _find_case_block_end(lines, start_idx):
        """找 case 块的结束行（配平的 esac 所在行）。"""
        indent_level = 0
        for i in range(start_idx, len(lines)):
            line = lines[i]
            if line.strip().startswith('case'):
                indent_level += 1
            elif line.strip() == 'esac':
                indent_level -= 1
                if indent_level == 0:
                    return i
        return False

    @classmethod
    def _contains_riscv(cls, block_lines):
        for line in block_lines:
            if cls.riscv_pattern.search(line):
                return True
        return False


class ShellSourceCodeSolver(Solver):
    solver_type = SOLVER_TYPE_BUILD_SCRIPT
    solver_description = SOLVER_DESCRIPTIONS[SOLVER_TYPE_BUILD_SCRIPT]

    patterns = [
        (r'case\s+"\$((?:\(uname\s+-m\)|ARCH))"', 'arch_case'),
        (r'(?i)(?<![a-z0-9])(x86|x86_64|amd64|amd64p32|arm64|arm64be|aarch64|aarch_64|'
         r'aarch64_be|armbe|arm|loong64|386|ppc|ppc64|ppc64le|s390|s390x|mips|'
         r'mips64|mips64le|mips64p32|mips64p32le|mipsle|sparc|sparc64|wasm)(?![a-z0-9])',
         'arch_detect'),
    ]

    migration_advice = {
        'arch_case': "架构分支缺少RISC-V支持！",
        'arch_detect': '检测到非riscv架构，建议检查',
    }

    compiled_patterns = [(re.compile(p[0], re.IGNORECASE), p[1]) for p in patterns]

    @staticmethod
    def matches_file(file_name):
        return file_name.endswith(".sh")

    @classmethod
    def solve(cls, source_file):
        lines = source_file.remove_multiple_comments_lines()
        remove_case_lines = CaseBlockProcessor.process_lines(lines)
        return ShellSourceCodeSolver.find_pattern(remove_case_lines, cls.compiled_patterns,
                                                  cls.migration_advice)

    @staticmethod
    def find_pattern(lines, compiled_patterns, migration_advice):
        results = []
        for line_number, line in enumerate(lines, 1):
            stripped_line = line.strip()
            for pattern, pattern_type in compiled_patterns:
                if pattern_type == 'arch_case':
                    continue
                match = pattern.search(stripped_line)
                if match:
                    advice = migration_advice.get(pattern_type, "需要RISC-V兼容性检查")
                    results.append(
                        (line_number, line_number,
                         f"{pattern_type}: {match.group()} - {advice}",
                         CodeTooLong.HAS_SOURCE_CODE, stripped_line))
                    break
        return results, []
