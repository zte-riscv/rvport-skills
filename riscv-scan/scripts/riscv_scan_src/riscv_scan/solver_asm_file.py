# Copyright 2026 ZTE Corporation
# SPDX-License-Identifier: Apache-2.0

"""汇编文件扫描。"""
import re

from .asm_arch import AsmArch
from .common import SOLVER_TYPE_ASM_FILE, SOLVER_DESCRIPTIONS
from .solver_base import Solver

# 纯架构后缀文件（如 base_arm64.s）由 missing 检测处理，不重复报条目
arch_file_pattern = re.compile(r'_(x86_64|x86|amd64|arm|arm64|aarch64)(?=\.(go|s)$)')


class AsmFileSolver(Solver):
    solver_type = SOLVER_TYPE_ASM_FILE
    solver_description = SOLVER_DESCRIPTIONS[SOLVER_TYPE_ASM_FILE]

    @staticmethod
    def matches_file(file_name):
        return (file_name.endswith(".s") or file_name.endswith(".S") or
                file_name.endswith(".asm")) and not arch_file_pattern.search(file_name)

    @staticmethod
    def extract_code(code, start_lineno, end_lineno):
        number_lines = end_lineno - start_lineno + 1
        code_too_long = number_lines > 50
        if code_too_long:
            return 1, None
        return 0, code

    @classmethod
    def solve(cls, source_file):
        code = source_file.get_code().strip()
        if not code:
            return [], []
        arch = AsmArch.detect_asm_arch(code)
        if arch != AsmArch.RISCV:
            lineno = len(source_file.get_code_lines())
            code_too_long, my_code = AsmFileSolver.extract_code(code, 1, lineno + 1)
            return [[1, lineno, "此处汇编与架构相关，请转换为适用于 RISC-V 架构的实现。",
                     code_too_long, my_code]], []
        return [], []
