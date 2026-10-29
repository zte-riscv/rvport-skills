# Copyright 2026 ZTE Corporation
# SPDX-License-Identifier: Apache-2.0

"""GoReleaser yml 扫描（对齐 server/plugin/codemig/solver/go_releaser_yml_solver.py）。

检查 goarch: 架构列表块是否包含 riscv64/riscv。
"""
import re

from .common import SOLVER_TYPE_GO_RELEASER, SOLVER_DESCRIPTIONS
from .solver_base import Solver


class GoReleaserYmlSolver(Solver):
    solver_type = SOLVER_TYPE_GO_RELEASER
    solver_description = SOLVER_DESCRIPTIONS[SOLVER_TYPE_GO_RELEASER]

    patterns = [(r'^\s*goarch:\s*$', 'goarch_declaration')]

    migration_advice = {'goarch_declaration': '架构列表缺少RISC-V支持'}

    compiled_patterns = [
        (re.compile(p[0], re.IGNORECASE), p[1]) for p in patterns
    ]

    @staticmethod
    def matches_file(file_name):
        # 兼容 .goreleaser.yaml / .goreleaser.yml / goreleaser.yml 等生态常见命名
        return file_name.endswith(("goreleaser.yml", "goreleaser.yaml"))

    @classmethod
    def solve(cls, source_file):
        lines = source_file.get_code_lines()
        return GoReleaserYmlSolver.find_arch_blocks(lines, cls.compiled_patterns,
                                                    cls.migration_advice)

    @staticmethod
    def find_arch_blocks(lines, compiled_patterns, migration_advice):
        results = []
        in_arch_block = False
        arch_block_start = 0
        arch_list = []
        current_indent = 0

        for line_number, line in enumerate(lines, 1):
            stripped_line = line.strip()

            if not in_arch_block:
                for pattern, _ in compiled_patterns:
                    if pattern.search(line):
                        in_arch_block = True
                        arch_block_start = line_number
                        current_indent = len(line) - len(line.lstrip())
                        break
                continue

            if in_arch_block:
                line_indent = len(line) - len(line.lstrip())
                if line_indent <= current_indent and stripped_line:
                    in_arch_block = False

                    if arch_list and not {'riscv64', 'riscv'}.intersection(arch_list):
                        advice = migration_advice.get('goarch_declaration',
                                                      "需要进一步检查RISC-V兼容性")
                        code_too_long, mycode = Solver.extract_code(
                            lines, arch_block_start, line_number - 1)
                        results.append((
                            arch_block_start, line_number - 1,
                            f'发现架构定义块(行{arch_block_start}-{line_number - 1})，{advice}',
                            code_too_long, mycode))

                    arch_list = []
                    continue

                if line_indent > current_indent and stripped_line.startswith('- '):
                    arch = stripped_line[2:].strip()
                    arch_list.append(arch)

        if arch_list and not {'riscv64', 'riscv'}.intersection(arch_list):
            advice = migration_advice.get('goarch_declaration', "需要进一步检查RISC-V兼容性")
            end_lineno = len(lines)
            code_too_long, mycode = Solver.extract_code(lines, arch_block_start, end_lineno)
            results.append(
                (arch_block_start, end_lineno,
                 f'发现架构定义块(行{arch_block_start}-{len(lines)})，{advice}',
                 code_too_long, mycode))

        return results, []
