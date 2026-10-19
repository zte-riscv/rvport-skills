# Copyright 2026 ZTE Corporation
# SPDX-License-Identifier: Apache-2.0

"""内联汇编扫描。"""
import re

from .asm_arch import AsmArch
from .common import matches_c_file, CodeTooLong, SOLVER_TYPE_INLINE_ASM, SOLVER_DESCRIPTIONS
from .solver_base import Solver


def get_line_offsets(code):
    line_offsets = []
    offset = 0
    for line in code.splitlines(keepends=True):
        line_offsets.append(offset)
        offset += len(line)
    return line_offsets


def get_line_number(start_pos, end_pos, line_offsets):
    start_lineno = None
    for i, start in enumerate(line_offsets):
        if start_lineno is None and start_pos < start:
            start_lineno = i
        if end_pos < start:
            return start_lineno, i
    end_lineno = len(line_offsets)
    if start_lineno is None:
        return end_lineno, end_lineno
    return start_lineno, end_lineno


def find_end_pos(start_pos, code):
    """提取完整 asm 表达式：查找括号配对直到配平。"""
    i = start_pos
    n = len(code)
    paren_count = 0
    in_string = False
    escaped = False
    while i < n:
        c = code[i]
        if in_string:
            if escaped:
                escaped = False
            elif c == '\\':
                escaped = True
            elif c == '"':
                in_string = False
        else:
            if c == '"':
                in_string = True
            elif c == '(':
                paren_count += 1
            elif c == ')':
                if paren_count == 1:
                    return i
                paren_count -= 1
        i += 1
    return None


class InlineAsmSolver(Solver):
    solver_type = SOLVER_TYPE_INLINE_ASM
    solver_description = SOLVER_DESCRIPTIONS[SOLVER_TYPE_INLINE_ASM]

    asm_start_pattern = re.compile(
        r'''
        (?:
            \b__asm__|\b__asm|\basm|\basm!|\bglobal_asm!|\bnaked_asm!
        )
        (?:\s+\w+)*
        \s*\(
        ''', re.VERBOSE | re.MULTILINE)

    @staticmethod
    def matches_file(file_name):
        return matches_c_file(file_name)

    @classmethod
    def find_asm_for_file(cls, code):
        lineno_and_asm_stmt = []
        for match in cls.asm_start_pattern.finditer(code):
            start_pos = match.start()
            end_pos = find_end_pos(start_pos, code)
            if end_pos is not None:
                asm_stmt = code[start_pos:end_pos + 1]
                asm_stmt = cls.remove_variable(asm_stmt)
                start_lineno, end_lineno = get_line_number(start_pos, end_pos,
                                                           get_line_offsets(code))
                lineno_and_asm_stmt.append((start_lineno, end_lineno, asm_stmt))
        return lineno_and_asm_stmt

    @staticmethod
    def create_suggestion_for_arch(arch):
        return "此处汇编与架构相关，请转换为适用于 RISC-V 架构的实现。"

    @staticmethod
    def extract_code(asm_stmt, start_lineno, end_lineno):
        number_lines = end_lineno - start_lineno + 1
        code_too_long = number_lines > 50
        if code_too_long:
            return CodeTooLong.CODE_TOO_LONG, None
        return CodeTooLong.HAS_SOURCE_CODE, asm_stmt

    @staticmethod
    def create_suggestion(lineno_and_asm_stmt):
        suggestions = []
        for start_lineno, end_lineno, asm_stmt in lineno_and_asm_stmt:
            arch = AsmArch.detect_asm_arch(asm_stmt)
            if arch != AsmArch.RISCV:
                code_too_long, code = InlineAsmSolver.extract_code(asm_stmt, start_lineno,
                                                                   end_lineno)
                suggestions.append([
                    start_lineno, end_lineno,
                    InlineAsmSolver.create_suggestion_for_arch(arch),
                    code_too_long, code
                ])
        return suggestions, []

    @classmethod
    def solve(cls, source_file):
        code = source_file.remove_c_comments()
        lineno_and_asm_stmt = cls.find_asm_for_file(code)
        return InlineAsmSolver.create_suggestion(lineno_and_asm_stmt)

    @classmethod
    def remove_variable(cls, asm_stmt):
        """从 asm 语句的 input/output 列表中移除变量名，保留约束条件。"""
        if asm_stmt is None or len(asm_stmt) == 0 or ":" not in asm_stmt:
            return asm_stmt

        colon_positions = []
        in_string = False
        escape_next = False
        for i, char in enumerate(asm_stmt):
            if escape_next:
                escape_next = False
                continue
            if char == '\\':
                escape_next = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if char == ':' and not in_string:
                colon_positions.append(i)

        if len(colon_positions) == 0:
            return asm_stmt

        result = asm_stmt
        processed_ranges = []
        for i in range(min(2, len(colon_positions))):
            colon_pos = colon_positions[i]
            if i + 1 < len(colon_positions):
                list_end = colon_positions[i + 1]
            else:
                list_end = len(asm_stmt)
            list_content = result[colon_pos:list_end]
            pattern1 = re.compile(r'(\[[^\]]+\]\s*"[^"]*"\s*)\([^)]+\)',
                                  re.MULTILINE | re.DOTALL)
            pattern2 = re.compile(r'("[^"]*"\s*)\([^)]+\)', re.MULTILINE | re.DOTALL)
            pattern3 = re.compile(r'(\[[^\]]+\]\s*)\([^)]+\)', re.MULTILINE | re.DOTALL)
            processed_content = pattern1.sub(r'\1()', list_content)
            processed_content = pattern2.sub(r'\1()', processed_content)
            processed_content = pattern3.sub(r'\1()', processed_content)
            processed_ranges.append((colon_pos, list_end, processed_content))

        for colon_pos, list_end, processed_content in reversed(processed_ranges):
            result = result[:colon_pos] + processed_content + result[list_end:]
        return result
