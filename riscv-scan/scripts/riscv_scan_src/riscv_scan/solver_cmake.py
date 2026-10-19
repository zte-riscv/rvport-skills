# Copyright 2026 ZTE Corporation
# SPDX-License-Identifier: Apache-2.0

"""CMake 构建脚本架构分支扫描。"""
import re

from treelib import Tree

from .common import SOLVER_TYPE_BUILD_SCRIPT, SOLVER_DESCRIPTIONS
from .solver_base import Solver

ARCH_OTHER = (
    r"(?<![a-zA-Z0-9])("
    r"x86|x86_64|amd64|amd64p32|i386|i486|i586|i686|x32|"
    r"arm|arm64|arm64be|armbe|aarch64|aarch64_be|armv8-a|armv9-a|"
    r"ppc|ppc64|ppc64le|powerpc|powerpc64|powerpc64le|"
    r"mips|mips64|mips64le|mips64p32|mips64p32le|mipsle|"
    r"sparc|sparc64|sparcv9|"
    r"s390|s390x|"
    r"loongarch64|loongarch32|loong64|"
    r"wasm|wasm32|wasm64|"
    r"alpha|hppa|ia64|m68k|tilegx|xtensa"
    r")(?![a-zA-Z0-9])"
)

ACH_RISCV = (
    r"(?<![a-zA-Z0-9])("
    r"riscv|risc-v|rvv|riscv64"
    r")(?![a-zA-Z0-9])"
)

ARC_KEYWORDS = [
    'CMAKE_SYSTEM_PROCESSOR',
    'CMAKE_HOST_SYSTEM_PROCESSOR',
    'CMAKE_OSX_ARCHITECTURES'
]

migration_advice = {
    'arch_case': "架构分支缺少RISC-V支持！需要添加类似分支;",
}


def contains_architecture_others(condition):
    return any(keyword in condition for keyword in ARC_KEYWORDS) or bool(
        re.search(ARCH_OTHER, condition, flags=re.IGNORECASE))


def contains_architecture_riscv(condition):
    return bool(re.search(ACH_RISCV, condition, flags=re.IGNORECASE))


def count_brackets_outside_strings(line):
    left_count = 0
    right_count = 0
    in_string = False
    string_char = None
    escape_next = False
    for char in line:
        if escape_next:
            escape_next = False
            continue
        if char == '\\':
            escape_next = True
            continue
        if char in ('"', "'") and not in_string:
            in_string = True
            string_char = char
            continue
        if char == string_char and in_string:
            in_string = False
            string_char = None
            continue
        if not in_string:
            if char == '(':
                left_count += 1
            elif char == ')':
                right_count += 1
    return left_count, right_count


def remove_comments(line):
    """移除行内注释，但保留字符串中的 # 字符"""
    if '#' not in line:
        return line
    in_string = False
    string_char = None
    result = []
    for char in line:
        if char in ('"', "'") and not in_string:
            in_string = True
            string_char = char
            result.append(char)
        elif char == string_char and in_string:
            in_string = False
            string_char = None
            result.append(char)
        elif char == '#' and not in_string:
            break
        else:
            result.append(char)
    return ''.join(result).rstrip()


class TreeData:
    def __init__(self, depth, start_line, end_line, has_other, has_riscv):
        self.depth = depth
        self.start_line = start_line
        self.end_line = end_line
        self.has_other = has_other
        self.has_riscv = has_riscv


def prune_tree(tree, node_id):
    node = tree.get_node(node_id)
    if not tree.is_branch(node_id):
        return
    if node.data.has_riscv or node.data.has_other:
        for child in list(tree.children(node_id)):
            tree.remove_node(child.identifier)
    else:
        for child in tree.children(node_id):
            prune_tree(tree, child.identifier)


def find_architecture_conditions(cmake_content):
    if_pattern = r'^\s*if\s*\((.*)$'
    elseif_pattern = r'^\s*elseif\s*\((.*)$'
    else_pattern = r'^\s*else\s*\(\)\s*$'
    endif_pattern = r'^\s*endif\s*\(.*\)\s*$'

    lines = cmake_content.split('\n')
    in_multiline_block_comment = False
    bracket_stack = 0
    in_if_block = False
    if_depth = 0
    condition_list = []
    for i, line in enumerate(lines):
        if re.match(r'^\s*#\[\[.*$', line):
            in_multiline_block_comment = True
            continue
        if re.match(r'^.*\]\]\s*$', line):
            in_multiline_block_comment = False
            continue
        if in_multiline_block_comment:
            continue

        line_without_comments = remove_comments(line.strip())

        if not in_if_block:
            if_match = re.match(if_pattern, line_without_comments, re.IGNORECASE)
            if if_match:
                tree = Tree()
                condition_list.append(tree)
                condition = if_match.group(1)
                condition_has_others = contains_architecture_others(condition)
                condition_has_riscv = contains_architecture_riscv(condition)
                tree_identifier = 0
                if_depth = 1
                node = tree.create_node(identifier=str(tree_identifier), parent=None,
                                        data=TreeData(1, i, i, condition_has_others,
                                                      condition_has_riscv))
                left_count, right_count = count_brackets_outside_strings(
                    line_without_comments)
                bracket_stack = left_count - right_count
                in_if_block = True
                parent = str(tree_identifier)
        else:
            if re.match(if_pattern, line_without_comments, re.IGNORECASE):
                if_depth += 1
                tree_identifier += 1
                condition_has_others = contains_architecture_others(line_without_comments)
                condition_has_riscv = contains_architecture_riscv(line_without_comments)
                node = tree.create_node(identifier=str(tree_identifier), parent=parent,
                                        data=TreeData(if_depth, i, i, condition_has_others,
                                                      condition_has_riscv))
                left_count, right_count = count_brackets_outside_strings(
                    line_without_comments)
                bracket_stack = left_count - right_count
                parent = str(tree_identifier)
            elif re.match(elseif_pattern, line_without_comments, re.IGNORECASE):
                node.data.has_other |= contains_architecture_others(line_without_comments)
                node.data.has_riscv |= contains_architecture_riscv(line_without_comments)
                left_count, right_count = count_brackets_outside_strings(
                    line_without_comments)
                bracket_stack = left_count - right_count
            elif re.match(endif_pattern, line_without_comments, re.IGNORECASE):
                bracket_stack = 0
                node.data.end_line = i
                if_depth -= 1
                parent_node = tree.parent(node.identifier)
                if parent_node:
                    parent = parent_node.identifier
                    node = parent_node
                if if_depth == 0:
                    in_if_block = False
                    prune_tree(tree, tree.root)
            elif re.match(else_pattern, line_without_comments, re.IGNORECASE):
                bracket_stack = 0
            elif bracket_stack > 0:
                node.data.has_other |= contains_architecture_others(line_without_comments)
                node.data.has_riscv |= contains_architecture_riscv(line_without_comments)
                left_count, right_count = count_brackets_outside_strings(
                    line_without_comments)
                bracket_stack += left_count - right_count

    return condition_list


def extract_if_blocks_with_arch(if_tree_list, leak, found):
    for tree in if_tree_list:
        root_node = tree.get_node(tree.root)
        if root_node.data.has_riscv:
            found.append(root_node.data)
        elif root_node.data.has_other:
            leak.append(root_node.data)
        else:
            child_llist = [tree.subtree(child.identifier) for child in
                           tree.children(root_node.identifier)]
            extract_if_blocks_with_arch(child_llist, leak, found)


def analyze_cmake_file(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except UnicodeDecodeError:
        with open(file_path, 'r', encoding='latin-1') as f:
            content = f.read()
    except FileNotFoundError:
        return [], []
    if_blocks = find_architecture_conditions(content)
    leak = []
    found = []
    extract_if_blocks_with_arch(if_blocks, leak, found)
    suggestions = []
    for node in leak:
        code_too_long, code = Solver.extract_code(content.splitlines(), node.start_line + 1,
                                                  node.end_line + 1)
        suggestions.append(
            [node.start_line + 1, node.end_line + 1, migration_advice['arch_case'],
             code_too_long, code])
    exist_code = []
    for node in found:
        code_too_long, code = Solver.extract_code(content.splitlines(), node.start_line + 1,
                                                  node.end_line + 1)
        exist_code = [node.start_line + 1, node.end_line + 1, code_too_long, code]
    return suggestions, exist_code


class CMakeSolver(Solver):
    solver_type = SOLVER_TYPE_BUILD_SCRIPT
    solver_description = SOLVER_DESCRIPTIONS[SOLVER_TYPE_BUILD_SCRIPT]

    @staticmethod
    def matches_file(file_name):
        return file_name.endswith('.cmake') or file_name == 'CMakeLists.txt'

    @classmethod
    def solve(cls, source_file):
        return analyze_cmake_file(source_file.file_path)
