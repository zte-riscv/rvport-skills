# Copyright 2026 ZTE Corporation
# SPDX-License-Identifier: Apache-2.0

"""Rust 源码扫描（对齐 server/plugin/codemig/solver/rust_source_code_solver.py）。

tree-sitter 解析 .rs：
- use core::arch::xxx / std::arch::xxx 架构模块导入
- core::arch::xxx::fn 调用、rust_arch_functions.json 架构函数
- rust_arch_struct.json 架构类型
- #[cfg(target_arch/target_feature)] 条件编译（cfg 表达式递归解析）
- asm!/global_asm!/naked_asm! 宏（复用 InlineAsmSolver）
- cargo:rustc-link-lib 外部库
"""
import json
import os
import re

import tree_sitter_rust as tsrust
from tree_sitter import Language, Parser, Node, Tree

from .common import CodeTooLong, SOLVER_TYPE_RUST, SOLVER_DESCRIPTIONS
from .solver_base import Solver, create_automaton
from .solver_inline_asm import InlineAsmSolver
from .source_file import SourceFile

RUST_CORE_ARCH_LIST = ["aarch64", "arm", "arm_shared", "loongarch32", "loongarch64",
                       "loongarch_shared", "mips", "nvptx", "powerpc", "powerpc64",
                       "riscv32", "riscv64", "riscv_shared", "s390x", "wasm32", "x86",
                       "x86_64"]

CONF_PATH = os.path.join(os.path.dirname(__file__), 'solver')


# ─── cfg 表达式 AST ───
class CfgExpr:
    pass


class Identifier(CfgExpr):
    def __init__(self, name: str):
        self.name = name

    def __repr__(self):
        return f'Identifier("{self.name}")'


class KeyValue(CfgExpr):
    def __init__(self, key: str, value: str):
        self.key = key
        self.value = value

    def __repr__(self):
        return f'KeyValue("{self.key}", "{self.value}")'


class Not(CfgExpr):
    def __init__(self, expr: CfgExpr):
        self.expr = expr

    def __repr__(self):
        return f'Not({self.expr})'


class Any(CfgExpr):
    def __init__(self, exprs: list):
        self.exprs = exprs

    def __repr__(self):
        return f'Any({self.exprs})'


class All(CfgExpr):
    def __init__(self, exprs: list):
        self.exprs = exprs

    def __repr__(self):
        return f'All({self.exprs})'


class Token:
    def __init__(self, type_: str, value: str, pos: int):
        self.type = type_
        self.value = value
        self.pos = pos

    def __repr__(self):
        return f'Token({self.type}, "{self.value}")'


class Tokenizer:
    def __init__(self, text: str):
        self.text = text
        self.pos = 0
        self.tokens = []
        self.tokenize()

    def tokenize(self):
        token_spec = [
            ('STRING', r'"[^"]*"'),
            ('IDENT', r'[a-zA-Z_][a-zA-Z0-9_]*'),
            ('EQUALS', r'='),
            ('COMMA', r','),
            ('LPAREN', r'\('),
            ('RPAREN', r'\)'),
            ('WHITESPACE', r'\s+'),
        ]
        tok_regex = '|'.join(f'(?P<{pair[0]}>{pair[1]})' for pair in token_spec)
        for mo in re.finditer(tok_regex, self.text):
            kind = mo.lastgroup
            value = mo.group()
            if kind == 'WHITESPACE':
                continue
            elif kind == 'STRING':
                value = value[1:-1]
            self.tokens.append(Token(kind, value, mo.start()))

    def peek(self, offset=0):
        if self.pos + offset < len(self.tokens):
            return self.tokens[self.pos + offset]
        return None

    def consume(self, expected_type: str):
        if self.peek() and self.peek().type == expected_type:
            token = self.tokens[self.pos]
            self.pos += 1
            return token
        raise SyntaxError(f"Expected {expected_type}, got {self.peek()} at position {self.pos}")


class BaseParser:
    def __init__(self, tokenizer: Tokenizer):
        self.tok = tokenizer

    def parse_expr(self) -> CfgExpr:
        if (self.tok.peek() and self.tok.peek().type == 'IDENT' and
                self.tok.peek(1) and self.tok.peek(1).type == 'LPAREN'):
            func_name = self.tok.peek().value
            if func_name in ('any', 'all', 'not'):
                self.tok.consume('IDENT')
                self.tok.consume('LPAREN')
                if func_name == 'not':
                    expr = self.parse_expr()
                    self.tok.consume('RPAREN')
                    return Not(expr)
                exprs = []
                if self.tok.peek() and self.tok.peek().type != 'RPAREN':
                    exprs.append(self.parse_expr())
                    while self.tok.peek() and self.tok.peek().type == 'COMMA':
                        self.tok.consume('COMMA')
                        if self.tok.peek() and self.tok.peek().type == 'RPAREN':
                            break
                        exprs.append(self.parse_expr())
                self.tok.consume('RPAREN')
                if func_name == 'any':
                    return Any(exprs)
                else:
                    return All(exprs)

        if (self.tok.peek() and self.tok.peek().type == 'IDENT' and
                self.tok.peek(1) and self.tok.peek(1).type == 'EQUALS'):
            key = self.tok.consume('IDENT').value
            self.tok.consume('EQUALS')
            if self.tok.peek() and self.tok.peek().type == 'STRING':
                value = self.tok.consume('STRING').value
                return KeyValue(key, value)
            raise SyntaxError("Expected string after '='")

        if self.tok.peek() and self.tok.peek().type == 'IDENT':
            name = self.tok.consume('IDENT').value
            return Identifier(name)

        raise SyntaxError(f"Unexpected token: {self.tok.peek()}, text: {self.tok.text}")

    def parse(self) -> CfgExpr:
        expr = None
        try:
            expr = self.parse_expr()
        except SyntaxError:
            expr = None
        return expr

    def check_positive(self, expr: CfgExpr, default: bool = True) -> bool:
        if isinstance(expr, KeyValue):
            if expr.key == "target_arch":
                if expr.value == "riscv64":
                    return True
                return False
            elif expr.key == "target_feature":
                return self.is_feature_support_riscv(expr.value)
            else:
                return default
        elif isinstance(expr, Identifier):
            return default
        elif isinstance(expr, Not):
            return not self.check_positive(expr.expr, not default)
        elif isinstance(expr, Any):
            return any(self.check_positive(e, False) for e in expr.exprs)
        elif isinstance(expr, All):
            return all(self.check_positive(e) for e in expr.exprs)
        else:
            return default

    def is_feature_support_riscv(self, feature: str) -> bool:
        for _, (_, match) in AUTOMATON_FEATURE.iter(feature):
            if match:
                return False
        return True


def _update_function_feature():
    fc_list, ft_list, fc_rv_list, ft_rv_list = [], [], [], []
    json_path = os.path.join(CONF_PATH, 'rust_arch_functions.json')
    if not os.path.exists(json_path):
        return set(), set(), set(), set()
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError, PermissionError):
        return set(), set(), set(), set()

    for arch in json_data:
        if arch == "riscv64" or arch == "riscv_shared":
            for func in json_data[arch]:
                fc_rv_list.append(func)
            for feature in json_data[arch].values():
                if "," in feature:
                    ft_rv_list.extend([i.strip() for i in feature.split(",") if i.strip()])
                else:
                    ft_rv_list.append(feature)
        else:
            for func in json_data[arch]:
                fc_list.append(func)
            for feature in json_data[arch].values():
                if "," in feature:
                    ft_list.extend([i.strip() for i in feature.split(",") if i.strip()])
                else:
                    ft_list.append(feature)

    fc_list = set(fc_list)
    fc_list.discard("")
    ft_list = set(ft_list)
    ft_list.discard("")
    fc_rv_list = set(fc_rv_list)
    fc_rv_list.discard("")
    ft_rv_list = set(ft_rv_list)
    ft_rv_list.discard("")
    return fc_list, ft_list, fc_rv_list, ft_rv_list


FUNCTION_LIST, FEATURE_LIST, FUNCTION_RV_LIST, FEATURE_RV_LIST = _update_function_feature()
AUTOMATON_FEATURE = create_automaton(FEATURE_LIST)


def _update_struct():
    struct_list, struct_rv_list = [], []
    json_path = os.path.join(CONF_PATH, 'rust_arch_struct.json')
    if not os.path.exists(json_path):
        return set(), set()
    try:
        json_data = json.load(open(json_path, encoding='utf-8'))
    except (json.JSONDecodeError, FileNotFoundError, PermissionError):
        return set(), set()

    for arch in json_data:
        if arch == "riscv64" or arch == "riscv_shared":
            struct_rv_list.extend(json_data[arch])
            continue
        struct_list.extend(json_data[arch])
    struct_list = set(struct_list)
    struct_list.discard("")
    struct_rv_list = set(struct_rv_list)
    struct_rv_list.discard("")
    return struct_list, struct_rv_list


STRUCT_LIST, STRUCT_RV_LIST = _update_struct()


PATTERNS_UASM = "use architecture-specific module"
PATTERNS_FUNCTION = "call architecture-specific function"
PATTERNS_TYPE = "call architecture-specific type"
PATTERNS_LINK = "link to external library"
PATTERNS_ARCH = "target arch"
PATTERNS_FEATURE = "target feature"


class RustCodeParser:
    advices = {
        PATTERNS_UASM: "该文件中使用了架构相关的函数, 请添加支持riscv架构的函数。",
        PATTERNS_FUNCTION: "此处调用了架构相关的函数, 请添加对riscv架构的支持。",
        PATTERNS_TYPE: "此处调用了架构相关的类型, 请添加对riscv架构的支持。",
        PATTERNS_LINK: "请确认该外部库是否支持riscv架构, 若不支持, 请替换为支持riscv架构的库。",
        PATTERNS_ARCH: "此处对架构进行判断, 请添加对riscv架构的支持。",
        PATTERNS_FEATURE: "此处使用了架构相关的特性, 请添加支持riscv架构的特性。",
    }

    def __init__(self, source_code):
        self.source_code = source_code
        self.language = Language(tsrust.language())
        self.parser = Parser(self.language)
        self.results = []
        self.results_rv = []
        self.use_no_arch_fn_list = []

    def analyze(self):
        self.results = []
        self.results_rv = []
        self.use_no_arch_fn_list = []
        tree = self.parser.parse(bytes(self.source_code, 'utf-8'))
        self.traverse_tree(tree)
        return self.results, self.results_rv

    def traverse_tree(self, tree: Tree):
        """遍历语法树, 查找 #[cfg()] 结构及其影响范围。"""
        TOKEN_TREE_NON_SPECIAL_PUNCTUATION = [
            '+', '-', '*', '/', '%', '^', '!', '&', '|', '&&', '||', '<<',
            '>>', '+=', '-=', '*=', '/=', '%=', '^=', '&=', '|=', '<<=',
            '>>=', '=', '==', '!=', '>', '<', '>=', '<=', '@', '_', '.',
            '..', '...', '..=', ',', ';', ':', '::', '->', '=>', '#', '?',
        ]
        type_pass_list = ['line_comment', 'string_literal',
                          'function_signature_item', 'let']
        type_pass_list.extend(TOKEN_TREE_NON_SPECIAL_PUNCTUATION)

        cursor = tree.walk()
        visited_children = False
        affected_node_end_line = -1
        while True:
            if not visited_children:
                node = cursor.node
                to_next_sibling = True
                if node.type in type_pass_list or node.end_point.row <= affected_node_end_line:
                    pass
                elif node.type == 'use_declaration':
                    self.traverse_use_declaration(node)
                elif node.type == 'call_expression':
                    to_next_sibling = self.traverse_call_expression(node)
                elif node.type == 'macro_invocation' or node.type == 'macro_definition':
                    self.traverse_macro_invocation(node)
                elif node.type == 'attribute_item':
                    to_next_sibling, affected_node = self.traverse_attribute_item(node)
                    affected_node_end_line = affected_node.end_point.row
                elif node.type == 'type_identifier':
                    self.traverse_type_identifier(node)
                else:
                    to_next_sibling = False

                if to_next_sibling:
                    if cursor.goto_next_sibling():
                        visited_children = False
                    elif not cursor.goto_parent():
                        break
                    else:
                        visited_children = True
                elif not cursor.goto_first_child():
                    visited_children = True
            else:
                if cursor.goto_next_sibling():
                    visited_children = False
                elif not cursor.goto_parent():
                    break
                else:
                    visited_children = True

    def _remove_comments(self, node: Node) -> str:
        if not node:
            return ""
        result_parts = []

        def traverse_node(n: Node):
            if n.type in ('line_comment', 'block_comment'):
                return
            if n.child_count == 0:
                result_parts.append(n.text.decode('utf-8'))
                return
            for child in n.children:
                traverse_node(child)

        traverse_node(node)
        return ''.join(result_parts)

    def traverse_attribute_item(self, node: Node):
        """处理 attribute_item 节点, 识别 #[cfg()] 结构并确定其影响范围。"""
        text = self._remove_comments(node)

        link_match = re.search(r'\[\s*link\s*\(\s*name\s*=\s*"(.*)"', text, re.DOTALL)
        if link_match:
            advice = self.advices.get(PATTERNS_LINK)
            self.results.append((node.start_point.row + 1, node.end_point.row + 1,
                                 f'匹配到{text}, {advice}', CodeTooLong.HAS_SOURCE_CODE, text))
            return True, node

        cfg_match = re.search(r'#\[cfg\((.*?)\)\s*\]', text, re.DOTALL)
        if not cfg_match:
            return True, node

        if "target_arch" in text:
            advice = self.advices.get(PATTERNS_ARCH)
        elif "target_feature" in text:
            advice = self.advices.get(PATTERNS_FEATURE)
        else:
            return True, node

        cfg_expr = cfg_match.group(1).strip()
        cfg_start_line = node.start_point.row + 1
        affected_node = self._find_cfg_affected_node(node)

        tokenizer = Tokenizer(cfg_expr)
        parser = BaseParser(tokenizer)
        ast = parser.parse()
        if ast is None:
            return True, node
        bsupport_riscv = parser.check_positive(ast, False)
        if bsupport_riscv:
            self.results_rv.append((cfg_start_line, affected_node.end_point.row + 1,
                                    f'匹配到{cfg_expr}, 已支持riscv架构',
                                    CodeTooLong.HAS_SOURCE_CODE, text))
        else:
            self.results.append((cfg_start_line, affected_node.end_point.row + 1,
                                 f'匹配到{cfg_expr}, {advice}',
                                 CodeTooLong.HAS_SOURCE_CODE, text))
        return not bsupport_riscv, affected_node

    def _is_cfg_attrbite_item(self, node: Node) -> bool:
        if node.child_count < 1:
            return False
        for child in node.children:
            if child.type == 'attribute' and child.child_count > 0:
                for grandchild in child.children:
                    if grandchild.type == 'identifier':
                        if grandchild.text.decode('utf-8') == 'cfg':
                            return True
        return False

    def _find_cfg_affected_node(self, cfg_node: Node) -> Node:
        """#[cfg()] 可修饰函数/结构体/枚举/impl/mod/trait/类型别名/常量/静态变量等。"""
        valid_item_types = [
            'function_item', 'struct_item', 'enum_item', 'impl_item',
            'mod_item', 'trait_item', 'type_item', 'const_item',
            'static_item', 'union_item', 'use_declaration', 'macro_definition',
            'let_declaration', 'expression_statement'
        ]
        invalid_item_types = ['line_comment', 'block_comment']
        if cfg_node.type != 'attribute_item':
            return cfg_node

        next_node = cfg_node.next_named_sibling
        while next_node:
            if next_node.type == 'attribute_item':
                if self._is_cfg_attrbite_item(next_node):
                    break
                else:
                    next_node = next_node.next_named_sibling
                    continue
            if next_node.type in invalid_item_types:
                next_node = next_node.next_named_sibling
                continue
            return next_node
        return cfg_node

    def _extract_arch_and_functions_from_use(self, node: Node):
        """从 use_declaration 中提取架构类型和函数名（core/std::arch::xxx::fn）。"""
        arch = None
        functions = []
        path_nodes = node.children_by_field_name("path")
        if not path_nodes:
            for child in node.named_children:
                if child.type in ('scoped_identifier', 'path_expression', 'use_list',
                                  'use_wildcard'):
                    path_nodes = [child]
                    break
        if not path_nodes:
            return None, []

        path_node = path_nodes[0]
        path_text = path_node.text.decode('utf-8')
        arch_pattern = r'^(?:core|std)::arch::([^:]+)'
        arch_match = re.match(arch_pattern, path_text)
        if arch_match:
            arch = arch_match.group(1)
            parts = path_text.split('::')
            if len(parts) > 3:
                potential_fn = parts[-1]
                if potential_fn and potential_fn != '*':
                    functions.append(potential_fn)
        else:
            if path_node.type == 'scoped_identifier':
                identifiers = []
                for child in path_node.children:
                    if child.type == 'identifier':
                        identifiers.append(child.text.decode('utf-8'))
                    elif child.type == 'scoped_identifier':
                        sub_arch, sub_functions = self._extract_arch_and_functions_from_use_scoped(child)
                        if sub_arch:
                            arch = sub_arch
                            functions.extend(sub_functions)
                        return arch, functions

                if len(identifiers) >= 3:
                    if identifiers[0] in ('core', 'std') and identifiers[1] == 'arch':
                        arch = identifiers[2]
                        if len(identifiers) > 3:
                            functions.extend(identifiers[3:])

        use_list_nodes = node.children_by_field_name("use_list")
        if use_list_nodes:
            use_list_node = use_list_nodes[0]
            for child in use_list_node.named_children:
                if child.type == 'identifier':
                    functions.append(child.text.decode('utf-8'))
                elif child.type == 'scoped_use_list':
                    for grandchild in child.named_children:
                        if grandchild.type == 'identifier':
                            functions.append(grandchild.text.decode('utf-8'))

        if arch is None:
            text = node.text.decode('utf-8')
            pattern = r'(?:core|std)::arch::([^:\s;{]+)'
            match = re.search(pattern, text)
            if match:
                arch = match.group(1)

        return arch, functions

    def _extract_arch_and_functions_from_use_scoped(self, node: Node):
        identifiers = []
        for child in node.children:
            if child.type == 'identifier':
                identifiers.append(child.text.decode('utf-8'))

        if len(identifiers) >= 3:
            if identifiers[0] in ('core', 'std') and identifiers[1] == 'arch':
                arch = identifiers[2]
                functions = identifiers[3:] if len(identifiers) > 3 else []
                return arch, functions
        return None, []

    def _extract_function_names_from_use(self, node: Node) -> list:
        functions = []
        path_nodes = node.children_by_field_name("path")
        if not path_nodes:
            for child in node.named_children:
                if child.type in ('scoped_identifier', 'path_expression', 'use_list'):
                    path_nodes = [child]
                    break

        if path_nodes:
            path_node = path_nodes[0]
            path_text = path_node.text.decode('utf-8')

            if path_node.type == 'scoped_identifier':
                identifiers = []
                for child in path_node.children:
                    if child.type == 'identifier':
                        identifiers.append(child.text.decode('utf-8'))
                if identifiers:
                    functions.append(identifiers[-1])
            else:
                parts = path_text.split('::')
                if parts:
                    last_part = parts[-1].strip()
                    if last_part and last_part != '*':
                        functions.append(last_part)

        use_list_nodes = node.children_by_field_name("use_list")
        if use_list_nodes:
            use_list_node = use_list_nodes[0]
            for child in use_list_node.named_children:
                if child.type == 'identifier':
                    functions.append(child.text.decode('utf-8'))
                elif child.type == 'scoped_use_list':
                    for grandchild in child.named_children:
                        if grandchild.type == 'identifier':
                            functions.append(grandchild.text.decode('utf-8'))

        if not functions:
            text = node.text.decode('utf-8')
            pattern = r'use\s+(?:[^:]+::)+([a-zA-Z_][a-zA-Z0-9_]*)\s*;'
            match = re.search(pattern, text)
            if match:
                functions.append(match.group(1))

        return functions

    def traverse_use_declaration(self, node: Node) -> bool:
        """处理 use_declaration 节点, 识别 use 语句。"""
        text = node.text.decode('utf-8')
        start_line = node.start_point.row + 1
        end_line = node.end_point.row + 1

        arch, functions = self._extract_arch_and_functions_from_use(node)
        if arch is not None:
            if arch not in RUST_CORE_ARCH_LIST:
                return True
            if arch == "riscv64" or arch == "riscv_shared":
                self.results_rv.append((start_line, end_line,
                                        f'匹配到 {text}, 已支持riscv架构',
                                        CodeTooLong.HAS_SOURCE_CODE, text))
            else:
                advice = self.advices.get(PATTERNS_UASM)
                self.results.append((start_line, end_line,
                                     f'匹配到{text}, {advice}',
                                     CodeTooLong.HAS_SOURCE_CODE, text))
        else:
            all_functions = self._extract_function_names_from_use(node)
            self.use_no_arch_fn_list.extend(all_functions)

        return True

    def traverse_call_expression(self, node: Node) -> bool:
        """处理 call_expression, 识别 std::arch::xxx::fn 调用与架构函数列表命中。"""
        arch = None
        text = node.text.decode('utf-8')
        arch_pattern = r'(?:std|core)::arch::([^:]+)::([a-zA-Z_][a-zA-Z0-9_]*)'
        arch_match = re.search(arch_pattern, text)
        if arch_match:
            arch = arch_match.group(1)
            if arch not in RUST_CORE_ARCH_LIST:
                return False
            elif arch == "riscv64" or arch == "riscv_shared":
                self.results_rv.append((node.start_point.row + 1, node.end_point.row + 1,
                                        f'匹配到{arch_match.group()}, 已支持riscv架构',
                                        CodeTooLong.HAS_SOURCE_CODE, text))
            else:
                advice = self.advices.get(PATTERNS_FUNCTION)
                self.results.append((node.start_point.row + 1, node.end_point.row + 1,
                                     f'匹配到{arch_match.group()}, {advice}',
                                     CodeTooLong.HAS_SOURCE_CODE, text))
            return True

        function_nodes = node.children_by_field_name("function")
        for every_node in function_nodes:
            function_name = every_node.text.decode('utf-8')
            if function_name in self.use_no_arch_fn_list:
                return False
            elif function_name in FUNCTION_LIST:
                advice = self.advices.get(PATTERNS_FUNCTION)
                self.results.append((node.start_point.row + 1, node.end_point.row + 1,
                                     f'匹配到{function_name}, {advice}',
                                     CodeTooLong.HAS_SOURCE_CODE, text))
                return True
            elif function_name in FUNCTION_RV_LIST:
                self.results_rv.append((node.start_point.row + 1, node.end_point.row + 1,
                                        f'匹配到{function_name}, 已支持riscv架构',
                                        CodeTooLong.HAS_SOURCE_CODE, text))
                return True
            return False

    def traverse_macro_invocation(self, node: Node) -> bool:
        """处理 macro_invocation：asm! 宏（复用 InlineAsmSolver）与 link-lib 声明。"""
        text = node.text.decode('utf-8')
        asm_pattern = r'\b(?:asm|global_asm|naked_asm)!\s*\((.*?)\)'
        for match in re.finditer(asm_pattern, text, flags=re.DOTALL):
            source_file = SourceFile("")
            source_file.code = text
            solver_results, solver_results_rv = InlineAsmSolver.solve(source_file)
            for result in solver_results:
                result[0] = result[0] + node.start_point.row
                result[1] = result[1] + node.start_point.row
            self.results.extend(solver_results)
            for result in solver_results_rv:
                result[0] = result[0] + node.start_point.row
                result[1] = result[1] + node.start_point.row
            self.results_rv.extend(solver_results_rv)
            return True

        lib_pattern = r'"cargo:rustc-link-lib=(.*)"'
        for match in re.finditer(lib_pattern, text, flags=re.DOTALL):
            advice = self.advices.get(PATTERNS_LINK)
            self.results.append((node.start_point.row + 1, node.end_point.row + 1,
                                 f'匹配到{match.group()}, {advice}',
                                 CodeTooLong.HAS_SOURCE_CODE, text))
            return True

    def traverse_type_identifier(self, node: Node) -> bool:
        """处理 type_identifier, 识别架构相关类型。"""
        text = node.text.decode('utf-8')
        if text in STRUCT_LIST:
            advice = self.advices.get(PATTERNS_TYPE)
            info = (node.start_point.row + 1, node.end_point.row + 1,
                    f'匹配到{text}, {advice}', CodeTooLong.HAS_SOURCE_CODE, text)
            if info not in self.results:
                self.results.append(info)
        elif text in STRUCT_RV_LIST:
            info = (node.start_point.row + 1, node.end_point.row + 1,
                    f'匹配到{text}, 已支持riscv架构', CodeTooLong.HAS_SOURCE_CODE, text)
            if info not in self.results_rv:
                self.results_rv.append(info)
        return True


class RustSourceCodeSolver(Solver):
    solver_type = SOLVER_TYPE_RUST
    solver_description = SOLVER_DESCRIPTIONS[SOLVER_TYPE_RUST]

    @staticmethod
    def matches_file(file_name):
        return file_name.endswith(".rs")

    @classmethod
    def solve(cls, source_file):
        results = []
        results_rv = []
        try:
            parser = RustCodeParser(source_file.get_code())
            results, results_rv = parser.analyze()
        except (ValueError, RuntimeError):
            results, results_rv = [], []
        return results, results_rv
