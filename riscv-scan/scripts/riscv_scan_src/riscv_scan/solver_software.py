# Copyright 2026 ZTE Corporation
# SPDX-License-Identifier: Apache-2.0

"""二进制库文件扫描（对齐 server/plugin/codemig/solver/software_solver.py）。

调用 file 命令检查 .so/.dll 的目标架构，非 riscv64 报条目。
"""
import subprocess

from .common import SOLVER_TYPE_LIB, SOLVER_DESCRIPTIONS
from .solver_base import Solver

TARGET_ARCHITECTURE = 'riscv64'


def get_file_architecture(file_path):
    try:
        result = subprocess.run(
            ['file', '--brief', file_path],
            capture_output=True, text=True
        )
        output = result.stdout
        if 'ELF 64-bit' in output:
            if 'x86-64' in output:
                return 'x86_64'
            if 'aarch64' in output or 'ARM' in output:
                return 'arm64'
            if 'riscv64' in output or 'RISCV64' in output or 'RISC-V' in output:
                return 'riscv64'
            return 'unknown_64bit'
        if 'ELF 32-bit' in output:
            if 'ARM' in output:
                return 'arm'
            if 'Intel 80386' in output:
                return 'x86'
            return 'unknown_32bit'
        if 'Mach-O' in output:
            if 'x86_64' in output:
                return 'x86_64'
            if 'arm64' in output:
                return 'arm64'
            return 'unknown_macho'
        if 'PE32+' in output:
            return 'x86_64'
        if 'PE32' in output:
            return 'x86'
        return 'unknown'
    except (OSError, FileNotFoundError, PermissionError, AttributeError,
            subprocess.TimeoutExpired, UnicodeDecodeError):
        return 'error'


def is_architecture_supported(arch_info):
    return arch_info.lower() == TARGET_ARCHITECTURE.lower()


class SoftwareSolver(Solver):
    """扫 .so/.dll 的目标架构（migration_class 为 DYNAMIC_LINK_LIBRARY）。"""

    solver_type = SOLVER_TYPE_LIB
    solver_description = SOLVER_DESCRIPTIONS[SOLVER_TYPE_LIB]

    @staticmethod
    def matches_file(file_name):
        return file_name.endswith(".so") or file_name.endswith(".dll")

    @classmethod
    def solve(cls, source_file):
        file_path = source_file.get_file_path()
        scan_results = []
        arch_info = get_file_architecture(file_path)
        if not is_architecture_supported(arch_info):
            scan_results.append([arch_info, None])
        return scan_results, []
