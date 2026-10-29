# Copyright 2026 ZTE Corporation
# SPDX-License-Identifier: Apache-2.0

"""Go 源码扫描（对齐 server/plugin/codemig/solver/go_source_code_solver.py）。

- //go:build / // +build 静态构建标签（含架构、不含 riscv64）
- tree-sitter 分析 runtime.GOARCH 的 if/switch/赋值/常量判断
- import "C" 前置注释块（cgo C 代码）复用 4 个 C solver 扫描
"""
import re

from tree_sitter import Language, Parser
import tree_sitter_go as tsg

GO_LANGUAGE = Language(tsg.language())

from .common import CodeTooLong, SOLVER_TYPE_GO, SOLVER_DESCRIPTIONS
from .solver_base import Solver
from .solver_intrinsics import IntrinsicsSolver
from .solver_builtin import BuiltinSolver
from .solver_macros import MacrosSolver
from .solver_inline_asm import InlineAsmSolver
from .source_file import SourceFile

# 纯架构后缀文件（foo_arm64.go）由 missing 检测负责
go_arch_pattern = re.compile(r'_(x86_64|x86|amd64|arm|arm64|aarch64)(?=\.(go|s)$)')


class GoSourceCodeSolver(Solver):
    solver_type = SOLVER_TYPE_GO
    solver_description = SOLVER_DESCRIPTIONS[SOLVER_TYPE_GO]

    source_patterns = [
        (r'(//\s*go:build\s+(?=.*(?:x86_64|x86|amd64|arm|arm64|aarch64)\b)(?!.*riscv64\b).*$)|'
         r'(//\s*\+build\s+(?=.*(?:x86_64|x86|amd64|arm|arm64|aarch64)\b)(?!.*riscv64\b).*$)',
         'build_tags'),
    ]

    migration_advice = {
        'build_tags': (
            "检测到静态条件编译中特殊注释部分，请判断编译内容中是否支持rv架构，如不支持，请判断在这部分内容中，"
            "是否需要增加新的.go文件，来支持rv架构。"),
        'runtime': (
            "检测到动态条件编译部分，请判断动态条件编译部分中，是否包含rv架构的内容，若不包含，"
            "请判断该部分代码是否需要添加rv架构内容。"),
        'var_runtime': (
            "检测到动态架构检测被赋值给变量，请检查该变量的处理逻辑中，是否包含rv架构的内容，若不包含，"
            "请判断该部分代码是否需要添加rv架构内容。"),
        'C': (
            "检测到C语言依赖部分，请判断C语言依赖部分是否支持rv架构，若不支持，请为目标平台构建C语言库，"
            "或者寻找纯Go的替代方案。"),
    }

    compiled_patterns = [(re.compile(p[0]), p[1]) for p in source_patterns]

    @staticmethod
    def matches_file(file_name):
        return file_name.endswith(".go") and not go_arch_pattern.search(file_name)

    @classmethod
    def solve(cls, source_file):
        results = []
        results_rv = []
        result1, result_rv1 = GoSourceCodeSolver.analyze_code(
            source_file.get_code(), cls.compiled_patterns, cls.migration_advice)
        result2, result_rv2 = GoSourceCodeSolver.find_pattern(
            source_file.get_code_lines(), cls.compiled_patterns, cls.migration_advice)

        results.extend(result1)
        results.extend(result2)
        results_rv.extend(result_rv1)
        results_rv.extend(result_rv2)
        return results, results_rv

    @staticmethod
    def find_pattern(lines, compiled_patterns, migration_advice):
        results = []
        content = ""
        comment_start_line = None
        in_multiline_comment = False
        for line_number, line in enumerate(lines, 1):
            line = line.strip()

            if '/*' in line and not in_multiline_comment:
                in_multiline_comment = True
                comment_start_line = line_number
                comment_content = line.split('/*', 1)[1]
                if '*/' in comment_content:
                    in_multiline_comment = False
                    comment_content = comment_content.split('*/', 1)[0].strip()
                    if comment_content:
                        content = comment_content
                else:
                    content = comment_content.strip()

            elif in_multiline_comment:
                if '*/' in line:
                    in_multiline_comment = False
                    comment_content = line.split('*/', 1)[0].strip()
                    if comment_content:
                        content += "\n" + comment_content
                else:
                    content += "\n" + line

            elif not in_multiline_comment and line.startswith('//'):
                if not content:
                    comment_start_line = line_number
                comment_content = line.split('//', 1)[1].strip()
                if content:
                    content += "\n" + comment_content
                else:
                    content = comment_content

            else:
                if 'import "C"' in line and content:
                    # 关联注释块与 import "C"（cgo C 代码）
                    c_source = SourceFile("")
                    c_source.code = content
                    solvers = [
                        IntrinsicsSolver.solve,
                        BuiltinSolver.solve,
                        MacrosSolver.solve,
                        InlineAsmSolver.solve
                    ]
                    for solver in solvers:
                        solver_results, _ = solver(c_source)
                        if solver_results:
                            for result in solver_results:
                                result[0] = result[0] + comment_start_line - 1
                                result[1] = result[1] + comment_start_line - 1
                            results.extend(solver_results)
                content = ""

            for pattern, pattern_type in compiled_patterns:
                match = pattern.search(line)
                if match and pattern_type == 'build_tags':
                    advice = migration_advice.get(pattern_type, "需要进一步检查RISC-V兼容性")
                    results.append((line_number, line_number, f'匹配到{match.group()}代码，{advice}',
                                    CodeTooLong.HAS_SOURCE_CODE, line))
                    break
        return results, []

    @staticmethod
    def analyze_code(content, compiled_patterns, migration_advice):
        parser = Parser(GO_LANGUAGE)
        tree = parser.parse(bytes(content, 'utf-8'))
        compare_patterns = [
            (r'runtime\s*\.\s*GOARCH\s*==\s*["\']([^"\']+)["\']', 'equal'),
            (r'runtime\s*\.\s*GOARCH\s*!=\s*["\']([^"\']+)["\']', 'not_equal')
        ]
        compiled_compare_patterns = [(re.compile(p[0]), p[1]) for p in compare_patterns]
        goarch_pattern = r'\bruntime\s*\.\s*GOARCH\s*'
        goarch_pattern_compiled = re.compile(goarch_pattern)

        handle_if_binary_list = []

        def handle_if_statement(node):
            """if 无 riscv64 且无 else → 提示；有 riscv64 → 不提示。"""
            ret_list = [0, 0, 0]  # 0: 不支持提示; 1: 支持不提示; 2: 无 GOARCH 不提示
            value_list = [0, 0, 0]
            for child in node.children:
                if child.type == "block":
                    continue
                elif child.type == "if_statement":
                    value_list = handle_if_statement(child)
                elif child.type == "binary_expression":
                    info = (node.start_point.row, node.start_point.column,
                            node.end_point.row, node.end_point.column)
                    if info in handle_if_binary_list:
                        continue
                    handle_if_binary_list.append(info)
                    tmp_content = node.text.decode()
                    for pattern, pattern_type in compiled_compare_patterns:
                        match = pattern.findall(tmp_content)
                        if pattern_type == "equal":
                            if len(match) > 0:
                                if "riscv64" not in match:
                                    ret_list[0] += 1
                                else:
                                    ret_list[1] += 1
                            else:
                                ret_list[2] += 1
                        elif pattern_type == "not_equal":
                            if len(match) > 0:
                                if "riscv64" in match:
                                    ret_list[0] += 1
                                else:
                                    ret_list[1] += 1
                            else:
                                ret_list[2] += 1
            ret_list = [a + b for a, b in zip(ret_list, value_list)]
            return ret_list

        def handle_expression_switch_statement(node):
            """switch runtime.GOARCH 的两种形式：switch GOARCH {case...} / switch {case...==...}。"""
            tmp_content = node.text.decode()
            match = goarch_pattern_compiled.search(tmp_content)
            if match is None:
                return True

            bstart = False
            switch_content = ""
            case_content_list = []
            for child in node.children:
                if child.type == "switch":
                    bstart = True
                    continue
                elif child.type == "{":
                    bstart = False
                    continue
                elif child.type == "expression_case":
                    for tmp_child in child.children:
                        if tmp_child.type == "expression_list":
                            case_content_list.append(tmp_child.text.decode())

                if bstart:
                    switch_content += " " + child.text.decode()

            if len(switch_content) == 0:
                bsupport = True
                for pattern, pattern_type in compiled_compare_patterns:
                    matchs = pattern.findall(tmp_content)
                    for match in matchs:
                        if pattern_type == "equal":
                            if "riscv64" in match:
                                return True
                            else:
                                bsupport = False
                        elif pattern_type == "not_equal":
                            if "riscv64" in match:
                                return False
                            else:
                                bsupport = True

                if not bsupport:
                    return False

            else:
                match = goarch_pattern_compiled.search(switch_content)
                if match is None:
                    return True
                bsupport = False
                for line in case_content_list:
                    if "riscv64" in line:
                        bsupport = True
                        break
                return bsupport

        def handle_assignment_statement(node):
            tmp_content = node.text.decode()
            matched = False
            bsupport = True
            for pattern, pattern_type in compiled_compare_patterns:
                matchs = pattern.findall(tmp_content)
                for match in matchs:
                    matched = True
                    if pattern_type == "equal":
                        if "riscv64" in match:
                            return True
                        else:
                            bsupport = False
                    elif pattern_type == "not_equal":
                        if "riscv64" in match:
                            return False
                        else:
                            bsupport = True

            if not bsupport:
                return False

            if not matched:
                direct_assignment_pattern = re.compile(r'(\w+)\s*=\s*runtime\s*\.\s*GOARCH\b')
                direct_match = direct_assignment_pattern.search(tmp_content)
                if direct_match:
                    return False
            return True

        def handle_const_spec(node):
            tmp_content = node.text.decode()
            for pattern, pattern_type in compiled_compare_patterns:
                match = pattern.findall(tmp_content)
                if len(match) > 0:
                    if pattern_type == "equal" and "riscv64" not in match:
                        return False
                    elif pattern_type == "not_equal" and "riscv64" in match:
                        return False
            return True

        def handle_var_declaration(node):
            tmp_content = node.text.decode()
            pattern = re.compile(r'(\w+)\s*=\s*runtime\s*\.\s*GOARCH')
            match = pattern.search(tmp_content)
            if match:
                return False
            return True

        def handle_short_var_declaration(node):
            pattern = re.compile(r'(\w+)\s*:?=\s*runtime\s*\.\s*GOARCH')
            tmp_content = node.text.decode()
            match = pattern.search(tmp_content)
            if match:
                return False
            return True

        results = []

        def walk(node, depth=0):
            briscv = True
            base_pattern = re.compile(r'runtime\s*\.\s*GOARCH\s*')

            pass_list = ["comment"]
            if node.type in pass_list:
                return

            match = base_pattern.search(node.text.decode())
            if not match:
                return

            if node.type == "if_statement":
                ret_list = handle_if_statement(node)
                if ret_list[0] > 0 and ret_list[1] == 0:
                    briscv = False
                else:
                    briscv = True
            elif node.type == "assignment_statement":
                briscv = handle_assignment_statement(node)
            elif node.type == "const_declaration":
                briscv = handle_const_spec(node)
            elif node.type == "expression_switch_statement":
                briscv = handle_expression_switch_statement(node)
            elif node.type == "var_declaration":
                briscv = handle_var_declaration(node)
            elif node.type == "short_var_declaration":
                briscv = handle_short_var_declaration(node)
            else:
                pass

            if not briscv:
                if node.type == "var_declaration" or node.type == "short_var_declaration":
                    advice = migration_advice.get('var_runtime', "需要进一步检查RISC-V兼容性")
                else:
                    advice = migration_advice.get('runtime', "需要进一步检查RISC-V兼容性")
                info = (node.start_point.row + 1, node.end_point.row + 1,
                        f'匹配到runtime.GOARCH相关代码，{advice}',
                        CodeTooLong.HAS_SOURCE_CODE, node.text.decode())
                results.append(info)
                return

            for child in node.children:
                walk(child, depth + 1)

        walk(tree.root_node)
        return results, []
