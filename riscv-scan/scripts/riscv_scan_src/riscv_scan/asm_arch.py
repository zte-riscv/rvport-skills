# Copyright 2026 ZTE Corporation
# SPDX-License-Identifier: Apache-2.0

"""架构关键字检测。

从 riscv.opcode / aarch64.opcode / x86_64.opcode 数据文件加载指令集，
按「RISC-V 独有指令」判定一段汇编是否已经是 RISC-V 实现。
"""
import os
import re

OPCODE_DIR = os.path.join(os.path.dirname(__file__), 'detect_arch')


def create_0_to_n(prefix, n):
    return [f"{prefix}{i}" for i in range(0, n + 1)]


def _load_opcodes(name):
    path = os.path.join(OPCODE_DIR, name)
    opcodes = []
    if os.path.exists(path):
        with open(path, 'r') as file:
            for line in file:
                line = line.strip()
                if line and not line.startswith('#'):
                    opcodes.append(line.lower())
    return opcodes


# ─── RISC-V───
REG_EX = {"csr", "zero", "ra", "gp", "tp"}
REG_SCR_M = {"mstatus", "mie", "mtvec", "mscratch", "mepc", "mcause", "mtval",
             "mip", "mvendorid", "marchid", "mimpid", "mhartid"}
REG_SCR_S = {"sstatus", "sie", "stvec", "sscratch", "sepc", "scause", "stval", "satp"}
REG_SCR_U = {"cycle", "time", "instret", "fflags", "frm", "fcsr"}


def _create_riscv_registers():
    registers = []
    registers.extend(create_0_to_n("t", 6))
    registers.extend(create_0_to_n("a", 7))
    registers.extend(create_0_to_n("f", 31))
    registers.extend(create_0_to_n("ft", 11))
    registers.extend(create_0_to_n("fs", 11))
    registers.extend(create_0_to_n("fa", 7))
    registers.extend(REG_EX)
    registers.extend(REG_SCR_M)
    registers.extend(REG_SCR_S)
    registers.extend(REG_SCR_U)
    return registers


RISCV_KEYWORDS = set(_create_riscv_registers()) | set(_load_opcodes('riscv.opcode'))

# ─── AArch64───
AARCH64_KEYWORDS = {"svc"}


def _create_aarch64_registers():
    registers = []
    registers.extend(create_0_to_n("x", 30))
    registers.extend(create_0_to_n("w", 30))
    registers.extend(create_0_to_n("b", 31))
    registers.extend(create_0_to_n("h", 31))
    registers.extend(create_0_to_n("s", 31))
    registers.extend(create_0_to_n("d", 31))
    registers.extend(create_0_to_n("q", 31))
    registers.extend(create_0_to_n("v", 31))
    registers.extend(AARCH64_KEYWORDS)
    return registers


AARCH64_OPCODES = set(_load_opcodes('aarch64.opcode')) | set(_create_aarch64_registers())

# ─── x86-64───
X86_64_KEYWORDS = {
    "syscall", "pause", "rdtsc", "rdtscp", "cpuid",
    "rax", "rbx", "rcx", "rdx", "rsi", "rdi", "rbp", "rsp",
    "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15",
    "eax", "ebx", "ecx", "edx", "esi", "edi", "ebp", "esp",
    "r8d", "r9d", "r10d", "r11d", "r12d", "r13d", "r14d", "r15d",
    "ax", "bx", "cx", "dx", "si", "di", "bp", "sp",
    "r8w", "r9w", "r10w", "r11w", "r12w", "r13w", "r14w", "r15w",
    "ah", "al", "bh", "bl", "ch", "cl", "dh", "dl",
    "sil", "bpl", "spl",
    "r8b", "r9b", "r10b", "r11b", "r12b", "r13b", "r14b", "r15b",
}


def _create_x86_registers():
    registers = []
    registers.extend(create_0_to_n("mm", 7))
    registers.extend(create_0_to_n("xmm", 15))
    registers.extend(create_0_to_n("ymm", 15))
    registers.extend(create_0_to_n("zmm", 31))
    registers.extend(X86_64_KEYWORDS)
    return registers


X86_64_OPCODES = set(_load_opcodes('x86_64.opcode')) | set(_create_x86_registers())

UNIQUE_RISCVS = RISCV_KEYWORDS - AARCH64_OPCODES - X86_64_OPCODES


class AsmArch:
    RISCV = "RISC-V"
    X86_64 = "x86_64"
    AARCH64 = "aarch64"
    UNKNOWN = "unknown_arch"

    @staticmethod
    def remove_asm_comments(content):
        """移除汇编代码中的 # // ; 三种单行注释。"""
        if content is None or len(content) == 0:
            return ''
        content = re.sub(r'#.*?$', '', content, flags=re.MULTILINE)
        content = re.sub(r'//.*?$', '', content, flags=re.MULTILINE)
        content = re.sub(r';.*?$', '', content, flags=re.MULTILINE)
        return content

    @staticmethod
    def detect_asm_arch(asm_stmt):
        asm_stmt = AsmArch.remove_asm_comments(asm_stmt)
        for match in re.findall(r'\$?[a-zA-Z][a-zA-Z0-9]*\b', asm_stmt):
            reg = match.lower()
            if reg in UNIQUE_RISCVS:
                return AsmArch.RISCV
        for match in re.findall(r'\$?[a-zA-Z]+(?:\.[a-zA-Z]+){0,3}\b', asm_stmt):
            opcode = match.lower()
            if opcode in UNIQUE_RISCVS:
                return AsmArch.RISCV
        return AsmArch.UNKNOWN
