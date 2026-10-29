# Copyright 2026 ZTE Corporation
# SPDX-License-Identifier: Apache-2.0

"""Cargo.toml / config.toml 扫描（对齐 server/plugin/codemig/solver/rust_toml_solver.py）。

tomlkit 解析：[target.'cfg(...)'] 架构条件段（复用 Rust 的 cfg 表达式解析）、
build.rustflags 的 target-feature、build.target 列表。
"""
import os

from tomlkit.toml_file import TOMLFile
import tomlkit

from .common import CodeTooLong, SOLVER_TYPE_RUST_TOML, SOLVER_DESCRIPTIONS
from .solver_base import Solver
from .solver_rust import Tokenizer, BaseParser


class RustTomlSolver(Solver):
    solver_type = SOLVER_TYPE_RUST_TOML
    solver_description = SOLVER_DESCRIPTIONS[SOLVER_TYPE_RUST_TOML]

    advices = {
        'target': "此处target配置中, 未包含riscv架构的内容。请判断是否需要添加riscv架构的配置。",
        'arch': "请检查此处配置中, 是否包含riscv架构的内容。若不包含,请判断该部分是否需要添加riscv架构内容。",
        'feature': "请检查此处feature中, 是否包含riscv架构不支持的内容。",
        'riscv64': "此处配置已支持riscv64",
    }

    @staticmethod
    def matches_file(file_name):
        return file_name == "Cargo.toml" or file_name == "config.toml"

    @classmethod
    def solve(cls, source_file):
        return cls.analyze_toml(source_file)

    @classmethod
    def create_block_info(cls, lines):
        block_info = []
        start_line = 0
        end_line = 0
        max_line_num = len(lines)
        for line_number, line in enumerate(lines):
            line = line.strip()
            # 过滤注释
            if line.startswith("#") or len(line) == 0 or line_number < end_line:
                continue

            if line.startswith("["):
                start_line = line_number + 1
                end_line = max_line_num
                space_line = 0
                # 确保 start_line 不会超过 max_line_num
                if start_line < max_line_num:
                    for i in range(max_line_num - start_line):
                        if start_line + i >= max_line_num:
                            break
                        tmpline = lines[start_line + i].strip()
                        if tmpline.startswith("["):
                            end_line = start_line + i - space_line
                            break
                        if tmpline.startswith("#") or len(tmpline) == 0:
                            space_line += 1
                        else:
                            space_line = 0
                # 检查 line 长度，避免越界
                if len(line) < 2:
                    section = line
                elif line[1] != '[':
                    # 普通section: [section_name]
                    section = line[1:-1] if line.endswith(']') and len(line) > 2 else line[1:]
                else:
                    # 数组section: [[section_name]]
                    if len(line) >= 4:
                        section = line[2:-2] if line.endswith(']]') else line[2:]
                    else:
                        section = line[2:] if len(line) > 2 else ""
            elif '=' in line:
                section = line.split('=')[0].strip()
            else:
                section = line

            safe_end_line = min(end_line, max_line_num)
            safe_start_line = min(start_line, max_line_num)
            block_info.append(
                {
                    'section': section,
                    'start_line': safe_start_line,
                    'end_line': safe_end_line,
                    'content': lines[safe_start_line:safe_end_line],
                }
            )
        return block_info

    @classmethod
    def analyze_toml(cls, source_file):
        results = []
        results_rv = []
        block_info = []
        toml_data = None
        file_path = source_file.get_file_path()
        if not os.path.exists(file_path):
            return results, results_rv

        try:
            toml_file = TOMLFile(file_path)
            toml_data = toml_file.read()
        except (tomlkit.exceptions.ParseError, tomlkit.exceptions.KeyAlreadyPresent, OSError):
            return results, results_rv

        block_info = cls.create_block_info(source_file.get_code_lines())

        advice_riscv64 = cls.advices.get('riscv64')
        for key1, value1 in toml_data.items():
            if key1 == 'target' and isinstance(value1, dict):
                for key2, value2 in value1.items():
                    if key2.startswith('cfg'):
                        if 'target_arch' in key2:
                            advice = cls.advices.get('arch')
                        elif 'target_feature' in key2:
                            advice = cls.advices.get('feature')
                        else:
                            continue
                        section = "target.'" + key2
                        tmp_key2 = key2[3:]
                        tmp_key2 = tmp_key2.strip()
                        if tmp_key2.startswith("("):
                            tmp_key2 = tmp_key2[1:]
                        if tmp_key2.endswith(")"):
                            tmp_key2 = tmp_key2[:-1]
                        tokenizer = Tokenizer(tmp_key2)
                        parser = BaseParser(tokenizer)
                        ast = parser.parse()
                        if ast is None:
                            continue
                        bsupport_riscv = parser.check_positive(ast, False)
                        start_line, end_line = cls._get_line_number(block_info, section)
                        if bsupport_riscv:
                            results_rv.append((start_line, end_line,
                                               f'匹配到{key2}, {advice_riscv64}',
                                               CodeTooLong.HAS_SOURCE_CODE, key2))
                        else:
                            results.append((start_line, end_line,
                                            f'匹配到{key2}, {advice}',
                                            CodeTooLong.HAS_SOURCE_CODE, key2))
                    else:
                        section = 'target.' + key2
                        start_line, end_line = cls._get_line_number(block_info, section)
                        if 'riscv64' in key2:
                            results_rv.append((start_line, end_line,
                                               f'匹配到{key2}, {advice_riscv64}',
                                               CodeTooLong.HAS_SOURCE_CODE, key2))
                        else:
                            advice = cls.advices.get('arch')
                            results.append((start_line, end_line,
                                            f'匹配到{key2}, {advice}',
                                            CodeTooLong.HAS_SOURCE_CODE, key2))
            elif key1 == 'build':
                build_list = []
                if isinstance(value1, list):
                    build_list.extend(value1)
                elif isinstance(value1, dict):
                    build_list.append(value1)
                section = 'build'
                start_line, end_line = cls._get_line_number(block_info, section)
                for every in build_list:
                    for key2, value2 in every.items():
                        if key2 == 'rustflags' and isinstance(value2, list):
                            tokenizer = Tokenizer("")
                            parser = BaseParser(tokenizer)
                            for flag in value2:
                                if 'target-feature' in flag:
                                    if not parser.is_feature_support_riscv(flag):
                                        advice = cls.advices.get('feature')
                                        start_line, end_line = cls._get_line_number(
                                            block_info, section, flag)
                                        results.append((start_line, end_line,
                                                        f'匹配到{flag}, {advice}',
                                                        CodeTooLong.HAS_SOURCE_CODE, flag))
                        elif key2 == 'target':
                            advice = cls.advices.get('target')
                            if isinstance(value2, list):
                                briscv = False
                                for target in value2:
                                    if 'riscv64' in target:
                                        briscv = True
                                        start_line, end_line = cls._get_line_number(
                                            block_info, section, target)
                                        break
                                if briscv:
                                    results_rv.append((start_line, end_line,
                                                       f'匹配到{value2}, {advice_riscv64}',
                                                       CodeTooLong.HAS_SOURCE_CODE,
                                                       str(value2)))
                                else:
                                    results.append((start_line, end_line,
                                                    f'匹配到{key2}, {advice}',
                                                    CodeTooLong.HAS_SOURCE_CODE, str(value2)))
                            elif isinstance(value2, str):
                                start_line, end_line = cls._get_line_number(
                                    block_info, section, value2)
                                if 'riscv64' in value2:
                                    results_rv.append((start_line, end_line,
                                                       f'匹配到{value2}, {advice_riscv64}',
                                                       CodeTooLong.HAS_SOURCE_CODE, value2))
                                else:
                                    results.append((start_line, end_line,
                                                    f'匹配到{key2}, {advice}',
                                                    CodeTooLong.HAS_SOURCE_CODE, value2))
        return results, results_rv

    @classmethod
    def _get_line_number(cls, block_info: list, section: str, content: str = None):
        start_line = 0
        end_line = 0
        bfind = False
        for every in block_info:
            if every['section'].startswith(section):
                if content:
                    for line in every['content']:
                        if content in line:
                            start_line = every['start_line']
                            end_line = every['end_line']
                            bfind = True
                            break
                else:
                    start_line = every['start_line']
                    end_line = every['end_line']
                    bfind = True
                if bfind:
                    break
        return start_line, end_line
