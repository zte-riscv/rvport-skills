# Copyright 2026 ZTE Corporation
# SPDX-License-Identifier: Apache-2.0

"""Python 源码扫描（对齐 server/plugin/codemig/solver/python_source_code_solver.py）。

tree-sitter 解析 .py 文件：
- 检测 ctypes/cffi 动态加载 C 库调用（CDLL/LoadLibrary/dlopen）
- 提取 cffi cdef/set_source 内嵌的 C 代码字符串，复用 MacrosSolver /
  IntrinsicsSolver / BuiltinSolver / InlineAsmSolver 扫描（行号偏移回 Python 行）
"""
import tree_sitter_python as tspython
from tree_sitter import Language, Parser, TreeCursor

from .common import CodeTooLong, SOLVER_TYPE_PYTHON, SOLVER_DESCRIPTIONS
from .solver_base import Solver
from .solver_intrinsics import IntrinsicsSolver
from .solver_builtin import BuiltinSolver
from .solver_macros import MacrosSolver
from .solver_inline_asm import InlineAsmSolver
from .source_file import SourceFile

LOAD_FUNC = [b'LoadLibrary', b'CDLL', b'dlopen']
FFI_FUNC = b'FFI'
VERIFY_FUNC = b'verify'
CODE_FUNC = [b'cdef', b'set_source', VERIFY_FUNC]
C_FUNC = LOAD_FUNC + CODE_FUNC + [FFI_FUNC]
CFFI_FUNC = CODE_FUNC + [b'dlopen']

PY_LANGUAGE = Language(tspython.language())


class PythonCodeParser:
    def __init__(self, source_code, file_name=None):
        self.source_code = source_code
        self.file_name = file_name
        self.load_so = []
        self.c_source_code = []
        self.maybe_code = []
        self.verify_code = []
        self.c_code_result = []

        self.ctypes_import = []
        self.cl_import = []
        self.dl_import = []
        self.cffi_import = []
        self.ffi_import = []
        self.ffi_instants = []

    def parse(self, code):
        try:
            parser = Parser(PY_LANGUAGE)
            tree = parser.parse(bytes(code, 'utf-8'))
            return tree
        except (UnicodeError, ValueError, RuntimeError, TimeoutError, NotImplementedError,
                MemoryError):
            return None

    def _in_ffi_instant(self, name):
        name = '.'.join(name)
        if '()' in name:
            name = name.split('()', maxsplit=1)[0]
            return name.encode('utf-8') in self.ffi_import
        for inst in self.ffi_instants:
            if inst == name.encode('utf-8'):
                return True
        return False

    def _process_ctypes_import(self, attr, func_step, node, param, load_so):
        """处理 ctypes 导入相关的动态库加载"""
        if attr == b'CDLL':
            if param and param.child_count > 2 and param.children[1].type != 'none':
                load_so.append((node.start_point.row, node.end_point.row))
            return True

        if len(func_step) == 2 and func_step[1] == 'cdll' and attr == b'LoadLibrary':
            load_so.append((node.start_point.row, node.end_point.row))
            return True
        return False

    def _process_cl_import(self, attr, node, load_so, param):
        """处理 ctypes 从 cdll 导入的情况"""
        if attr == b'LoadLibrary':
            if param and param.child_count > 2 and param.type != 'none':
                load_so.append((node.start_point.row, node.end_point.row))
            return True
        return False

    def _process_cdef(self, node, param):
        """处理 cffi cdef 调用"""
        if param and param.child_count > 2:
            if param.children[1].type in ('string', 'concatenated_string'):
                self.c_source_code.append(
                    (param.children[1].start_point.row, param.children[1].end_point.row,
                     param.children[1].text.decode('utf-8')))
            elif param.children[1].type != 'none':
                self.maybe_code.append((node.start_point.row, node.end_point.row))
        return True

    def _process_set_source(self, node, param):
        """处理 cffi set_source 调用"""
        if param and param.child_count >= 4 and param.children[3].type == 'string':
            self.c_source_code.append(
                (param.children[3].start_point.row, param.children[3].end_point.row,
                 param.children[3].text.decode('utf-8')))
        else:
            self.verify_code.append((node.start_point.row, node.end_point.row))

    def _process_cffi_import(self, attr, node, var, param):
        """处理 cffi 相关调用"""
        if attr == FFI_FUNC and var:
            self.ffi_instants.append(var)
            return True
        if attr == b'dlopen':
            if param and param.child_count > 2 and param.children[1].type != 'none':
                self.load_so.append((node.start_point.row, node.end_point.row))
            return True
        if attr == b'cdef':
            return self._process_cdef(node, param)
        if attr == b'set_source':
            self._process_set_source(node, param)
            return True
        if attr == VERIFY_FUNC:
            if param and param.child_count > 2 and param.children[1].type != 'none':
                self.verify_code.append((node.start_point.row, node.end_point.row))
            return True
        return False

    def _process_ffi_instance(self, attr, node, param, load_so):
        """处理 FFI 动态加载调用"""
        if attr == b'dlopen':
            if param and param.child_count >= 3 and param.children[1].type != 'none':
                load_so.append((node.start_point.row, node.end_point.row))
            return True
        if attr == b'cdef':
            if param and param.child_count >= 3 and (
                    param.children[1].type in ('string', 'concatenated_string')):
                self.c_source_code.append(
                    (param.children[1].start_point.row, param.children[1].end_point.row,
                     param.children[1].text.decode('utf-8')))
            else:
                self.maybe_code.append((node.start_point.row, node.end_point.row))
            return True

        if attr == b'set_source':
            if param and param.child_count >= 4:
                if param.children[3].type in ('string', 'concatenated_string'):
                    self.c_source_code.append(
                        (param.children[3].start_point.row,
                         param.children[3].end_point.row,
                         param.children[3].text.decode('utf-8')))
                elif param.children[3].type != 'none':
                    self.maybe_code.append((node.start_point.row, node.end_point.row))
            else:
                self.maybe_code.append((node.start_point.row, node.end_point.row))
            return True
        if attr == VERIFY_FUNC:
            if param and param.child_count >= 3 and param.children[1].type != 'none':
                self.verify_code.append((node.start_point.row, node.end_point.row))
            return True
        return False

    def _add_to_imports(self, import_list, alias):
        import_list.append(alias)

    def traverse_import(self, cursor: TreeCursor):
        current_id = cursor.node.id
        cursor.goto_first_child()
        import_name, alias_name = [], []
        while True:
            if cursor.node.id == current_id:
                break
            node = cursor.node
            if node.type == 'dotted_name':
                import_name.append(node.text)
            elif node.type == 'aliased_import':
                for child in node.children:
                    if child.type == 'dotted_name':
                        import_name.append(child.text)
                    elif child.type == 'identifier':
                        alias_name.append(child.text)
            if cursor.goto_next_sibling():
                continue
            if not cursor.goto_parent():
                break
        for i, im in enumerate(import_name):
            if im == b'ctypes':
                self._add_to_imports(self.ctypes_import,
                                     alias_name[i] if len(alias_name) > 0 and alias_name[i]
                                     else im)
            elif im == b'cffi':
                self._add_to_imports(self.cffi_import,
                                     alias_name[i] if len(alias_name) > 0 and alias_name[i]
                                     else im)

    def traverse_import_from(self, cursor: TreeCursor):
        current_id = cursor.node.id
        cursor.goto_first_child()
        model = False
        model_name = ''
        import_name = []
        alias_name = []
        while True:
            if cursor.node.id == current_id:
                break
            node = cursor.node
            if node.type == 'dotted_name':
                if not model:
                    model_name = node.text
                else:
                    import_name.append(node.text)
            elif node.type == 'import':
                model = True
            elif node.type == 'aliased_import':
                for child in node.children:
                    if child.type == 'dotted_name':
                        import_name.append(child.text)
                    elif child.type == 'identifier':
                        alias_name.append(child.text)
            if cursor.goto_next_sibling():
                continue
            if not cursor.goto_parent():
                break
        if model_name == b'ctypes':
            for i, im in enumerate(import_name):
                if im == b'cdll':
                    self._add_to_imports(self.cl_import,
                                         alias_name[i] if len(alias_name) > 0 and alias_name[i]
                                         else im)
                elif im == b'CDLL':
                    self._add_to_imports(self.dl_import,
                                         alias_name[i] if len(alias_name) > 0 and alias_name[i]
                                         else im)
        elif model_name == b'cffi':
            for i, im in enumerate(import_name):
                if im == b'FFI':
                    self._add_to_imports(self.ffi_import,
                                         alias_name[i] if len(alias_name) > 0 and alias_name[i]
                                         else im)

    def traverse_full_func(self, node):
        func_name = bytes()
        sliced = False
        for child in node.children:
            if sliced:
                if child.type == ']':
                    func_name += child.text
                    sliced = False
                continue
            if child.type == 'identifier':
                func_name += child.text
            elif child.type == 'call':
                func_name += self.traverse_full_func(child) + bytes("()", 'utf-8')
            elif child.type == 'attribute':
                func_name += self.traverse_full_func(child)
            elif child.type == '.':
                func_name += child.text
            elif child.type == 'subscript':
                func_name += self.traverse_full_func(child)
            elif child.type == '[':
                func_name += child.text
                sliced = True
        return func_name

    def traverse_check_func_attribute(self, func_full_name, param, node, variale, load_so):
        if not func_full_name:
            return False
        func_step = func_full_name.decode('utf-8').split('.')
        attr = func_step.pop().encode('utf-8')
        if attr in self.ffi_import and variale and not func_step:
            self.ffi_instants.append(variale)
            return True
        if attr in self.dl_import and param and param.child_count > 2 and param.type != 'none':
            self.load_so.append((node.start_point.row, node.end_point.row))
            return True
        if func_step:
            if func_step[0].encode('utf-8') in self.ctypes_import:
                return self._process_ctypes_import(attr, func_step, node, param, load_so)
            if func_step[0].encode('utf-8') in self.cl_import:
                return self._process_cl_import(attr, node, load_so, param)
            if func_step[0].encode('utf-8') in self.cffi_import:
                return self._process_cffi_import(attr, node, variale, param)
            if func_step[0].encode('utf-8') in self.ffi_import:
                if attr == b'FFI':
                    self.ffi_instants.append(variale)
                    return True
            elif self._in_ffi_instant(func_step):
                return self._process_ffi_instance(attr, node, param, load_so)
            elif attr in CFFI_FUNC and (len(self.ffi_import) > 0 or len(self.cffi_import) > 0):
                self.maybe_code.append((node.start_point.row, node.end_point.row))
                return True
        return False

    def traverse_assignment(self, cursor: TreeCursor):
        current_id = cursor.node.id
        cursor.goto_first_child()
        variable_name = ''
        func_name = ''
        para_node = None
        while True:
            if cursor.node.id == current_id:
                break
            node = cursor.node
            if node.type == 'identifier':
                variable_name = node.text
            elif node.type == 'call':
                func_name = self.traverse_full_func(node)
                for child in node.children:
                    if child.type == 'argument_list':
                        para_node = child
            if cursor.goto_next_sibling():
                continue
            if not cursor.goto_parent():
                break
        return self.traverse_check_func_attribute(func_name, para_node, cursor.node,
                                                  variable_name, self.load_so)

    def traverse_call(self, cursor: TreeCursor):
        node = cursor.node
        func_name = self.traverse_full_func(node)
        para_node = None
        for child in node.children:
            if child.type == 'argument_list':
                para_node = child
        return self.traverse_check_func_attribute(func_name, para_node, cursor.node, None,
                                                  self.load_so)

    def traverse_tree(self, tree):
        cursor = tree.walk()
        visited_children = False
        while True:
            if not visited_children:
                node = cursor.node
                found = False
                if node.type == 'import_statement':
                    self.traverse_import(cursor)
                    found = True
                elif node.type == 'import_from_statement':
                    self.traverse_import_from(cursor)
                    found = True
                elif node.type == 'assignment':
                    found = self.traverse_assignment(cursor)
                elif node.type == 'call':
                    found = self.traverse_call(cursor)
                if found:
                    if cursor.goto_next_sibling():
                        visited_children = False
                    elif not cursor.goto_parent():
                        break
                    else:
                        visited_children = True
                elif not cursor.goto_first_child():
                    visited_children = True
            elif cursor.goto_next_sibling():
                visited_children = False
            elif not cursor.goto_parent():
                break

    def read_source(self):
        tree = self.parse(self.source_code)
        if not tree:
            return
        self.traverse_tree(tree)
        if self.c_source_code:
            solvers = [
                IntrinsicsSolver.solve,
                BuiltinSolver.solve,
                MacrosSolver.solve,
                InlineAsmSolver.solve
            ]
            for start, _, code in self.c_source_code:
                if code is None:
                    continue
                source_file = SourceFile("")
                source_file.code = code
                for solver in solvers:
                    solver_results, _ = solver(source_file)
                    if solver_results:
                        for result in solver_results:
                            result[0] = result[0] + start
                            result[1] = result[1] + start
                        self.c_code_result.extend(solver_results)


class PythonSourceCodeSolver(Solver):
    solver_type = SOLVER_TYPE_PYTHON
    solver_description = SOLVER_DESCRIPTIONS[SOLVER_TYPE_PYTHON]

    migration_advice = {
        'ctypes_dynamic_loading': (
            "检测到动态加载C库的调用。请确保目标库有RISC-V版本， 使用.so扩展名而非.dll， "
            "并考虑使用跨平台加载方式"),
        'cffi_used': "检测到使用cffi动态加载C代码。请确保加载的库或者代码支持RISC-V",
        'verify_used': (
            "检测到使用cffi的verify动态加载C代码。该函数已弃用，请更新代码，并确保加载的代码支持RISC-V"),
    }

    @staticmethod
    def matches_file(file_name):
        return file_name.endswith(".py")

    @classmethod
    def solve(cls, source_file):
        try:
            parser = PythonCodeParser(source_file.get_code(), source_file.get_file_path())
            parser.read_source()
            advise = []
            for start, end in parser.load_so:
                advise.append(
                    (start + 1, end + 1, cls.migration_advice.get('ctypes_dynamic_loading'),
                     CodeTooLong.HAS_SOURCE_CODE,
                     "\n".join(source_file.get_code_lines()[start:end + 1])))
            for start, end in parser.maybe_code:
                advise.append(
                    (start + 1, end + 1, cls.migration_advice.get('cffi_used'),
                     CodeTooLong.HAS_SOURCE_CODE,
                     "\n".join(source_file.get_code_lines()[start:end + 1])))
            for start, end in parser.verify_code:
                advise.append(
                    (start + 1, end + 1, cls.migration_advice.get('verify_used'),
                     CodeTooLong.HAS_SOURCE_CODE,
                     "\n".join(source_file.get_code_lines()[start:end + 1])))
            advise.extend(parser.c_code_result)
            sorted_data = sorted(advise, key=lambda x: (x[0], x[1]))
            return sorted_data, []
        except (AttributeError, ValueError, TypeError, RuntimeError):
            return [], []
