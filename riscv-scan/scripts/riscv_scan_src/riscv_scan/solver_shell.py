# Copyright 2026 ZTE Corporation
# SPDX-License-Identifier: Apache-2.0

"""shell 脚本架构 case 块扫描。"""
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
        """处理文本行，识别特定 case 块；无 riscv 分支的 case 报建议。"""
        results = []
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
                    matched = True
                    if not cls._has_riscv_branch(block_lines):
                        advice = ("架构分支缺少RISC-V支持！需要添加类似分支："
                                  "riscv64\\|riscv) ARCH=\"riscv64\" ;;")
                        code_too_long, mycode = Solver.extract_code(
                            lines, start_line + 1, end_line + 1)
                        results.append([start_line + 1, end_line + 1, advice,
                                        code_too_long, mycode])
                    i = end_line + 1
                    continue
            except ValueError:
                pass
            if not matched:
                i += 1
        return results

    @staticmethod
    def _find_case_block_end(lines, start_idx):
        for j in range(start_idx, len(lines)):
            if lines[j].strip().startswith('esac'):
                return j
        return None

    @staticmethod
    def _has_riscv_branch(block_lines):
        return any(CaseBlockProcessor.riscv_pattern.search(line) for line in block_lines)


class ShellSourceCodeSolver(Solver):
    solver_type = SOLVER_TYPE_BUILD_SCRIPT
    solver_description = SOLVER_DESCRIPTIONS[SOLVER_TYPE_BUILD_SCRIPT]

    @staticmethod
    def matches_file(file_name):
        return file_name.endswith('.sh')

    @classmethod
    def solve(cls, source_file):
        lines = source_file.remove_multiple_comments_lines()
        results = CaseBlockProcessor.process_lines(lines)
        return results, []
