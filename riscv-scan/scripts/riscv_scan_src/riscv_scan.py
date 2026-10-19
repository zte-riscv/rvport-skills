#!/usr/bin/env python3
# Copyright 2026 ZTE Corporation
# SPDX-License-Identifier: Apache-2.0
"""riscv_scan — 最小可运行的 RISC-V 迁移扫描工程入口。

独立维护的基础扫描链路


用法:
    python3 riscv_scan.py <target_path> [-o <output.json>]
    # -o 缺省时输出 <target_path>/scan_result.json

输出 scan_result.json 结构与 scan/scan_result.json 参考格式一致
（大写 TODO、tier/perf/arch_source 字段、顶层 warnings 数组）；
内容为基础扫描器结果——参考文件中由 AI Subagent 追加/合并的条目
（更详细的 migration_suggestion 文本与 warnings 条目）不在基础扫描
范围内，warnings 中会注明。
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from riscv_scan.arch_missing import ARCH_DETECT_RE
from riscv_scan.scanner import process_file, walk_project
from riscv_scan.solver_asm_file import arch_file_pattern


def derive_arch_source(file_path):
    """按文件所在路径推导 arch_source（x86_64/arm/aarch64/none）。"""
    rel = file_path.replace('\\', '/')
    if re.search(r'(?i)aarch64', rel):
        return 'aarch64'
    if re.search(r'(?i)x86', rel):
        return 'x86_64'
    if re.search(r'(?i)arm', rel):
        return 'arm'
    return 'none'


def scan_target(target_path):
    """扫描文件或目录，返回 (suggestion_entries, missing_entries)。"""
    scanned_files, missing_files, missing_dirs = walk_project(target_path)

    suggestion_entries = []
    for file_path in scanned_files:
        file_name = os.path.basename(file_path)
        # 纯架构后缀文件（如 foo_arm64.s）由 missing 检测负责，跳过
        if arch_file_pattern.search(file_name):
            continue
        file_solvers_result = process_file(file_path)
        for solver, (change_list, _) in file_solvers_result.items():
            solver_name = solver.__name__
            for start_line, end_line, suggestion, _ctl, _code in change_list:
                suggestion_entries.append({
                    "class_type": "suggestion_class",
                    "file_name": file_name,
                    "file_path": os.path.abspath(file_path),
                    "solver_name": solver_name,
                    "solver_type": solver.solver_type,
                    "solver_description": solver.solver_description,
                    "start_line": start_line,
                    "end_line": end_line,
                    "migration_suggestion": suggestion,
                    # schema：intrinsic 热点建议标 hot，其余默认 warm
                    "tier": "hot" if solver.solver_type == 1 else "warm",
                    "status": "TODO",
                    "marking": "",
                    "perf": None,
                    "arch_source": derive_arch_source(file_path),
                })
    suggestion_entries.sort(key=lambda s: (s["file_path"], s["solver_name"],
                                           s["start_line"], s["end_line"]))

    missing_entries = []
    for missing_path, arch_paths in {**missing_files, **missing_dirs}.items():
        missing_entries.append({
            "class_type": "missing_class",
            "missing_path": os.path.abspath(missing_path),
            "is_file": missing_path in missing_files,
            "existing_arch_paths": [os.path.abspath(p) for p in arch_paths],
            "migration_suggestion": "补充对应的 RISC-V 架构文件/目录实现。",
            "status": "TODO",
            "marking": "",
        })
    missing_entries.sort(key=lambda m: m["missing_path"])
    return suggestion_entries, missing_entries


def main():
    parser = argparse.ArgumentParser(
        description="Scan file or directory. Output scan_result.json.")
    parser.add_argument('target', help="Path to a single file or a directory.")
    parser.add_argument('-o', '--output', default=None,
                        help="Output JSON path. Default: <target>/scan_result.json")
    args = parser.parse_args()

    if not os.path.exists(args.target):
        print(f"Error: target not found: {args.target}", file=sys.stderr)
        sys.exit(1)

    target_abs = os.path.abspath(args.target)
    output = args.output or os.path.join(
        target_abs if os.path.isdir(target_abs) else os.path.dirname(target_abs),
        'scan_result.json')

    suggestions, missing = scan_target(target_abs)

    result = {
        "target": target_abs,
        "suggestion_class_count": len(suggestions),
        "missing_class_count": len(missing),
        "suggestion_class": suggestions,
        "missing_class": missing,
        "warnings": [
            "基础扫描器输出：参考格式中的 AI Subagent 增强条目"
            "（更详细 migration_suggestion / warnings 明细）不在此范围"
        ],
    }
    with open(output, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=1)

    print(f"scan done: {target_abs}")
    print(f"suggestion class items: {len(suggestions)}")
    print(f"missing class items: {len(missing)}")
    print(f"json written to: {os.path.abspath(output)}")


if __name__ == '__main__':
    main()
