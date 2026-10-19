# Copyright 2026 ZTE Corporation
# SPDX-License-Identifier: Apache-2.0

"""缺失 RISC-V 架构实现检测。

规则（经黑盒用例校准，与服务端旧版 arch_missing_process.py 有差异）：

目录级：
  - 同一父目录下，若存在 ≥1 个名字含其他架构关键字的子目录
    （x86/arm/aarch64/amd64，大小写不敏感），且没有任何名字含 riscv
    关键字的子目录，则报告缺失目录 <parent>/riscv64，
    existing_arch_paths 为全部架构子目录（ppc64le 等不计入）。

文件级（按扩展名 splitext 分组）：
  - 名字含架构关键字的文件为架构变体文件；名字含 riscv 关键字
    （riscv/riscv64/risc-v，rv64 不算）的文件视为已有 RISC-V 实现。
  - 架构关键字与 ISA 关键字（avx/sse/neon/sve/...）都替换为占位符后
    余量相同的文件为一组；组内有架构变体且无 riscv 文件时报告缺失。
  - 缺失文件名 = 组内字典序首个架构文件 stem 删除架构 token
    （区分大小写字面替换：aarch64/amd64/x86/arm）、去尾部分隔符后拼
    _riscv64；stem 删空则直接命名 riscv64。例：
      foo_arm64.c      -> foo_64_riscv64.c
      cflags-x86.cmake -> cflags_riscv64.cmake   （尾部 '-' 被去掉）
      arm.h            -> riscv64.h
      impl_arm_sve.cpp -> impl__sve_riscv64.cpp  （ISA token 保留）
      foo_X86.c        -> foo_X86_riscv64.c      （检测不区分大小写，
                                                    替换区分）
"""
import os
import re
from collections import defaultdict

# 字面替换 token（区分大小写，长前缀优先）
ARCH_STRIP_TOKENS = ('aarch64', 'amd64', 'x86', 'arm')

# 架构变体检测（不区分大小写，无词边界 —— alarm.c/harmony.c 也命中）
ARCH_DETECT_RE = re.compile(r'aarch64|amd64|x86|arm', re.IGNORECASE)

# riscv 已有实现检测（rv64 不算，与编译版一致）
RISCV_DETECT_RE = re.compile(r'riscv64|risc-v|riscv(?!32)', re.IGNORECASE)

# ISA 关键字（与服务端 isa_others 一致，用于分组 key）
ISA_OTHER = (
    r"(?<![a-zA-Z0-9])("
    r"avx5124fmaps|avx5124vnniw|avx512vp2intersect|avx512vpopcntdq|"
    r"avx512bitalg|avx512vbmi|avx512vnni|avx512ifma|avx512dq|avx512pf|"
    r"avx512er|avx512cd|avx512bw|avx512vl|avx512f|avx512|avxifma|avxvnni|"
    r"avx2|avx|"
    r"ssse3|sse4\.1|sse4\.2|sse4_1|sse4_2|sse41|sse42|sse4a|sse2|sse3|sse|"
    r"neon_fp16|neon_vfpv4|neon-fp16|neon-vfpv4|neonfp16|neon\.fp16|"
    r"neonvfpv4|neon\.vfpv4|neon|"
    r"sve|mmx|aesni"
    r")(?![a-zA-Z0-9])"
)
ISA_OTHER_RE = re.compile(ISA_OTHER, re.IGNORECASE)

SEPARATORS = '_-.#'


def _merge_star_sequences(text):
    """*arch*/*isa* 之间仅隔分隔符时合并占位符（与服务端一致）。"""
    pattern = r'\*(?:arch|isa)\*[_\-.#]+\*(?:arch|isa)\*'
    while True:
        if re.search(pattern, text):
            text = re.sub(pattern, '*isa*', text)
        else:
            break
    return text


def _group_key(stem):
    """架构/ISA 关键字替换为占位符后的分组 key（不区分大小写）。"""
    key = ARCH_DETECT_RE.sub('*arch*', stem)
    key = ISA_OTHER_RE.sub('*isa*', key)
    return _merge_star_sequences(key)


def _missing_file_name(arch_file_name):
    stem, ext = os.path.splitext(arch_file_name)
    stripped = stem
    for token in ARCH_STRIP_TOKENS:
        stripped = stripped.replace(token, '')
    stripped = stripped.rstrip(SEPARATORS)
    if not stripped:
        return 'riscv64' + ext
    return stripped + '_riscv64' + ext


def group_files(names):
    """一个目录内的文件名列表 -> {缺失文件名: [现有架构文件名列表]}。"""
    missing = {}
    by_ext = defaultdict(list)
    for name in names:
        stem, ext = os.path.splitext(name)
        by_ext[ext].append(name)

    for ext, files in by_ext.items():
        groups = defaultdict(list)
        for file_name in files:
            stem = os.path.splitext(file_name)[0]
            if not (ARCH_DETECT_RE.search(stem) or ISA_OTHER_RE.search(stem)):
                continue
            groups[_group_key(stem)].append(file_name)
        for members in groups.values():
            arch_members = sorted(
                m for m in members if ARCH_DETECT_RE.search(os.path.splitext(m)[0]))
            has_riscv = any(RISCV_DETECT_RE.search(os.path.splitext(m)[0])
                            for m in members)
            if has_riscv or not arch_members:
                continue
            missing[_missing_file_name(arch_members[0])] = arch_members
    return missing


def group_dirs(names):
    """一个目录内的子目录名列表 -> {缺失目录名: [现有架构目录名列表]}。"""
    arch_dirs = sorted(n for n in names if ARCH_DETECT_RE.search(n))
    if not arch_dirs:
        return {}
    if any(RISCV_DETECT_RE.search(n) for n in names):
        return {}
    return {'riscv64': arch_dirs}
