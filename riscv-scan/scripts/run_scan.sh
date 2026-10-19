#!/usr/bin/env bash
# Copyright 2026 ZTE Corporation
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

# riscv-scan 扫描入口：直接运行仓库自带 Python 源码扫描器
# （scripts/riscv_scan_src/，平台无关；不使用预编译二进制）。

SKILL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCAN_SRC_ENTRY="${SKILL_ROOT}/scripts/riscv_scan_src/riscv_scan.py"

if [[ ! -f "${SCAN_SRC_ENTRY}" ]]; then
  echo "[scan] ERROR: 扫描器源码缺失: ${SCAN_SRC_ENTRY}" >&2
  exit 1
fi

# 依赖检查：缺失时自动安装（幂等；失败时给出手动指引并中止）
if ! python3 -c "import ahocorasick, treelib, chardet" >/dev/null 2>&1; then
  echo "[scan] 安装扫描器 Python 依赖 ..."
  python3 -m pip install -r "${SKILL_ROOT}/scripts/requirements.txt" || {
    echo "[scan] ERROR: 依赖自动安装失败，请手动执行:" >&2
    echo "[scan]   python3 -m pip install -r ${SKILL_ROOT}/scripts/requirements.txt" >&2
    echo "[scan] 依赖就绪后重跑本脚本，或按 riscv-scan 技能 SKILL.md 的静态分析兜底流程产出 scan_result.json" >&2
    exit 1
  }
fi

exec python3 "${SCAN_SRC_ENTRY}" "$@"
