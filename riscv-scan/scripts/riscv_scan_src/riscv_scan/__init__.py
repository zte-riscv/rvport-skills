# Copyright 2026 ZTE Corporation
# SPDX-License-Identifier: Apache-2.0

# riscv_scan — 最小可运行的 RISC-V 迁移扫描工程
#
# 独立维护的基础扫描链路，去除 Web 框架、
# 数据库与 AI 相关依赖，只保留「给定工程路径 → 产出 scan_result.json」的
# 核心能力。
#
# 依赖：pip install pyahocorasick treelib chardet
