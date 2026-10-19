# Copyright 2026 ZTE Corporation
# SPDX-License-Identifier: Apache-2.0

"""共享常量与工具。

只保留扫描链路用到的部分，剔除数据库 / 路径配置等 Web 服务依赖。
"""
import re
from enum import Enum

NUMBER_LINES_TOO_LONG = 50

# solver_type 整数枚举（与 solvers_mapping.SolverType 一致）
SOLVER_TYPE_MAKEFILE = 0
SOLVER_TYPE_INTRINSICS = 1
SOLVER_TYPE_BUILTIN = 2
SOLVER_TYPE_MACROS = 3
SOLVER_TYPE_INLINE_ASM = 4
SOLVER_TYPE_ASM_FILE = 5
SOLVER_TYPE_BUILD_SCRIPT = 10

SOLVER_DESCRIPTIONS = {
    SOLVER_TYPE_MAKEFILE: "Makefile",
    SOLVER_TYPE_INTRINSICS: "内联函数",
    SOLVER_TYPE_BUILTIN: "内置函数",
    SOLVER_TYPE_MACROS: "宏定义",
    SOLVER_TYPE_INLINE_ASM: "内联汇编",
    SOLVER_TYPE_ASM_FILE: "汇编文件",
    SOLVER_TYPE_BUILD_SCRIPT: "构建脚本",
}


class CodeTooLong(Enum):
    HAS_SOURCE_CODE = 0
    CODE_TOO_LONG = 1


class ChangeType(Enum):
    APPEND = 0
    REPLACE = 1
    OTHER = 2


C_EXTENSIONS = (".h", ".c", ".cc", ".cpp", ".h.in", ".c.in", ".hpp", ".cc.in",
                ".cpp.in", ".hpp.in")


def matches_c_file(file_name):
    return any(file_name.endswith(ext) for ext in C_EXTENSIONS)


def load_list_from_file(file_path: str) -> list:
    res = []
    with open(file_path, 'r') as file:
        res = [line.strip() for line in file if line.strip()]
    return res


def regex_arch(text):
    """路径/文本中是否出现 x86/arm 等其他架构关键字。"""
    architectures = (
        r'(?<![a-zA-Z0-9])(x86(?:_64)?|amd(?:_64)?|arm(?:_64|64)?|armv8(?:_64)?|armv9(?:_64)?|'
        r'aarch64)(?![a-zA-Z0-9])')
    return bool(re.search(architectures, text, flags=re.IGNORECASE))
