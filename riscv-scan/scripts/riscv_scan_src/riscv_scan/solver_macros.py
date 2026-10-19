# Copyright 2026 ZTE Corporation
# SPDX-License-Identifier: Apache-2.0

"""C/C++ 宏条件分支扫描。"""
import os
import re

from treelib import Tree

from .common import matches_c_file, SOLVER_TYPE_MACROS, SOLVER_DESCRIPTIONS
from .solver_base import Solver, create_automaton

MACROS_SUGGESTION = "  // Suggestion: Add macros for the RISC-V architecture."

CONF_PATH = os.path.join(os.path.dirname(__file__), 'solver')


def load_macros_from_file(file_path: str) -> list:
    macros = []
    with open(file_path, 'r') as file:
        macros = [line.strip() for line in file if line.strip()]
    return macros


RISCV_MACROS_SET = load_macros_from_file(os.path.join(CONF_PATH, 'riscv.macro'))
AARCH64_SET = load_macros_from_file(os.path.join(CONF_PATH, 'aarch64.macro'))
X86_SET = load_macros_from_file(os.path.join(CONF_PATH, 'x86.macro'))
MACROS_SET = set(AARCH64_SET + X86_SET)


def create_upper_and_lower_automaton(macros):
    upper_macros = [m.strip().upper() for m in macros]
    lower_macros = [m.strip().lower() for m in macros]
    macros = [m.strip() for m in macros]
    combined_macros = list(dict.fromkeys(upper_macros + lower_macros + macros))
    return create_automaton(combined_macros)


def automaton_match(automaton, line):
    for _, (_, _) in automaton.iter(line):
        return True
    return False


class TreeData:
    def __init__(self, depth, start_line, end_line, has_other, has_riscv, defines: []):
        self.depth = depth
        self.start_line = start_line
        self.end_line = end_line
        self.has_other = has_other
        self.has_riscv = has_riscv
        self.defines = defines
        self.multi_condition = False
        self.multi_if = False


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


def combine_node(condition_list, lines):
    new_condition_list = []
    for tree in condition_list:
        root_node = tree.get_node(tree.root)
        if root_node.data.has_other or root_node.data.has_riscv:
            data = TreeData(root_node.data.depth, root_node.data.start_line,
                            root_node.data.end_line, root_node.data.has_other,
                            root_node.data.has_riscv, root_node.data.defines)
            data.multi_condition = root_node.data.multi_condition
            data.multi_if = root_node.data.multi_if
            new_condition_list.append(data)
        else:
            child_llist = [tree.subtree(child.identifier) for child in
                           tree.children(root_node.identifier)]
            child_condition_list = combine_node(child_llist, lines)
            new_condition_list.extend(child_condition_list)
    return new_condition_list


def process_list(condition_list, found, leak):
    for data in condition_list:
        if data.has_other and data.has_riscv:
            found.append(data)
        elif data.has_other and not data.has_riscv:
            leak.append(data)
        else:
            continue


class MacrosSolver(Solver):
    solver_type = SOLVER_TYPE_MACROS
    solver_description = SOLVER_DESCRIPTIONS[SOLVER_TYPE_MACROS]

    macros_automaton = create_upper_and_lower_automaton(MACROS_SET)
    riscv_automaton = create_upper_and_lower_automaton(RISCV_MACROS_SET)
    if_pattern = re.compile(r'^\s*#\s*if(def)?\s+')
    elif_pattern = re.compile(r'^\s*#\s*elif\s+')
    else_pattern = re.compile(r'^\s*#\s*else\s*')
    endif_pattern = re.compile(r'^\s*#\s*endif\s*$')

    @staticmethod
    def create_suggestion(indentno, defines, multi_if):
        indent = " " * indentno
        value = MACROS_SUGGESTION
        suggestion_lines = [
            f"{indent}#elif defined(__riscv) && __riscv_xlen == 64" if not multi_if else
            f"{indent}#if defined(__riscv) && __riscv_xlen == 64",
            f"{indent}  {value}",
        ]
        return "\n".join(suggestion_lines) + "\n"

    @staticmethod
    def preprocess_backslash(lines):
        lineno_and_lines = []
        string_builder = []
        for lineno, line in enumerate(lines, 1):
            if not string_builder:
                start_lineno = lineno
            stripped = line.rstrip()
            if stripped.endswith("\\"):
                string_builder.append(stripped[:-1])
                string_builder.append(" ")
            else:
                string_builder.append(stripped)
                lineno_and_lines.append((start_lineno, "".join(string_builder)))
                string_builder.clear()
        return lineno_and_lines

    @classmethod
    def match_other_arch(cls, line):
        return automaton_match(cls.macros_automaton, line)

    @classmethod
    def match_riscv_arch(cls, line):
        return automaton_match(cls.riscv_automaton, line)

    @classmethod
    def solve_lines(cls, lines, lineno_and_lines):
        suggestions = []
        in_if_block = False
        if_depth = 0
        tree_identifier = 0
        tree = None
        parent = None
        node = None
        condition_list = []
        found = []
        leak = []
        for lineno, line in lineno_and_lines:
            if line.strip() == '':
                continue
            if not in_if_block:
                if cls.if_pattern.search(line):
                    tree = Tree()
                    condition_list.append(tree)
                    tree_identifier = 0
                    if_depth = 1
                    node = tree.create_node(identifier=str(tree_identifier), parent=None,
                                            data=TreeData(1, lineno, lineno,
                                                          cls.match_other_arch(line),
                                                          cls.match_riscv_arch(line), []))
                    in_if_block = True
                    parent = str(tree_identifier)
            else:
                if cls.if_pattern.search(line):
                    if_depth += 1
                    tree_identifier += 1
                    node = tree.create_node(identifier=str(tree_identifier), parent=parent,
                                            data=TreeData(if_depth, lineno, lineno,
                                                          cls.match_other_arch(line),
                                                          cls.match_riscv_arch(line), []))
                    parent = str(tree_identifier)
                elif cls.elif_pattern.search(line):
                    node.data.has_other |= cls.match_other_arch(line)
                    node.data.has_riscv |= cls.match_riscv_arch(line)
                    node.data.multi_condition = True
                elif cls.else_pattern.search(line):
                    node.data.multi_condition = True
                elif cls.endif_pattern.search(line):
                    node.data.end_line = lineno
                    if_depth -= 1
                    parent_node = tree.parent(node.identifier)
                    if parent_node:
                        parent = parent_node.identifier
                        node = parent_node
                    if if_depth == 0:
                        in_if_block = False
                        prune_tree(tree, tree.root)
        combined_list = combine_node(condition_list, lineno_and_lines)
        process_list(combined_list, found, leak)

        for no, line in lineno_and_lines:
            for leak_node in leak:
                end_lineno = leak_node.end_line
                if end_lineno == no:
                    indentno = line.find("#endif")
                    suggestion = MacrosSolver.create_suggestion(indentno, leak_node.defines,
                                                                leak_node.multi_if)
                    code_too_long, code = Solver.extract_code(lines, leak_node.start_line,
                                                              end_lineno)
                    suggestions.append(
                        [leak_node.start_line, end_lineno, suggestion, code_too_long, code])
                    break

        return suggestions, found

    @classmethod
    def solve(cls, source_file):
        lines = source_file.remove_c_comments_lines()
        lineno_and_lines = MacrosSolver.preprocess_backslash(lines)
        raw_lines = source_file.get_code_lines()
        return cls.solve_lines(raw_lines, lineno_and_lines)

    @staticmethod
    def matches_file(file_name):
        return matches_c_file(file_name)
