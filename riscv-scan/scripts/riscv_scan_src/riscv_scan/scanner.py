# Copyright 2026 ZTE Corporation
# SPDX-License-Identifier: Apache-2.0

"""扫描编排。
"""
import os
from collections import defaultdict

from .source_file import SourceFile
from .solver_macros import MacrosSolver
from .solver_intrinsics import IntrinsicsSolver
from .solver_builtin import BuiltinSolver
from .solver_inline_asm import InlineAsmSolver
from .solver_asm_file import AsmFileSolver
from .solver_makefile import MakefileSolver
from .solver_cmake import CMakeSolver
from .solver_build_script import BuildScriptSolver
from .solver_build_meson import BuildMesonSolver
from .solver_shell import ShellSourceCodeSolver
from .common import matches_c_file

MY_SOLVERS = [
    MakefileSolver,
    IntrinsicsSolver,
    BuiltinSolver,
    MacrosSolver,
    InlineAsmSolver,
    AsmFileSolver,
    BuildScriptSolver,
    BuildMesonSolver,
    CMakeSolver,
    ShellSourceCodeSolver,
]


def advise(solver_type):
    """跨 solver 命中时的附加建议文本。"""
    return '仿照其他架构替换相关实现\n'


def post_process_file(source_file, file_solvers_result):
    """A 的行范围包含 B 的起止行时只报外层，并对内层 solver 追加建议。"""
    if not matches_c_file(source_file.get_file_path()):
        return
    for solver, result in file_solvers_result.items():
        changed_list, found_list = result
        res_found_list = []
        for found in found_list:
            found_start_lineno = found.start_line
            found_end_lineno = found.end_line
            for solver2, result2 in file_solvers_result.items():
                if solver2 == solver:
                    continue
                changed2_list, _ = result2
                indices_to_remove = []
                for i, changed in enumerate(changed2_list):
                    changed_start_lineno = changed[0]
                    changed_end_lineno = changed[1]
                    if found_start_lineno <= changed_start_lineno and \
                            found_end_lineno >= changed_end_lineno:
                        indices_to_remove.append(i)
                for i in sorted(indices_to_remove, reverse=True):
                    if i < len(changed2_list):
                        changed2_list.pop(i)
            res_found_list.append([found_start_lineno, found_end_lineno])
        for changed in changed_list:
            start_lineno = changed[0]
            end_lineno = changed[1]
            for solver2, result2 in file_solvers_result.items():
                if solver2 == solver:
                    continue
                changed2_list, _ = result2
                indices_to_remove_from_changed2 = []
                for i, found in enumerate(changed2_list):
                    found_start_lineno = found[0]
                    found_end_lineno = found[1]
                    if start_lineno <= found_start_lineno and end_lineno >= found_end_lineno:
                        indices_to_remove_from_changed2.append(i)
                if len(indices_to_remove_from_changed2) > 0:
                    changed[2] += advise(solver2.solver_type)
                for i in sorted(indices_to_remove_from_changed2, reverse=True):
                    if i < len(changed2_list):
                        changed2_list.pop(i)
        file_solvers_result[solver] = (changed_list, res_found_list)


def process_file(file_path):
    """单个文件过全部 solver；返回 {solver: (change_list, found_list)}。"""
    file_solvers_result = defaultdict(lambda: ([], []),
                                      {solver: ([], []) for solver in MY_SOLVERS})
    file_name = os.path.basename(file_path)
    source_file = SourceFile(file_path)
    for solver, result_list in file_solvers_result.items():
        change_list, found_list = result_list
        if solver.matches_file(file_name):
            result, found = solver.solve(source_file)
            change_list.extend(result)
            found_list.extend(found)
    post_process_file(source_file, file_solvers_result)
    return file_solvers_result


def walk_project(root_path):
    """遍历工程目录。

    返回:
        (scanned_files, missing_files, missing_dirs)
        scanned_files: 待过 solver 的文件绝对路径列表
        missing_files: {缺失文件绝对路径: [现有架构文件绝对路径]}
        missing_dirs:  {缺失目录绝对路径: [现有架构目录绝对路径]}
    """
    from .arch_missing import group_files, group_dirs

    scanned_files, missing_files, missing_dirs = [], {}, {}
    if os.path.isfile(root_path):
        return [root_path], {}, {}

    for root, dirs, files in os.walk(root_path, topdown=True):
        dirs[:] = [d for d in dirs if d not in ('.git', '.github')]

        for missing, existing in group_dirs(dirs).items():
            missing_dirs[os.path.join(root, missing)] = \
                [os.path.join(root, e) for e in existing]

        for missing, existing in group_files(files).items():
            missing_files[os.path.join(root, missing)] = \
                [os.path.join(root, e) for e in existing]

        for file_name in files:
            scanned_files.append(os.path.join(root, file_name))
    return scanned_files, missing_files, missing_dirs
