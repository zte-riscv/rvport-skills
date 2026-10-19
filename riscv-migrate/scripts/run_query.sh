#!/usr/bin/env bash
# Copyright 2026 ZTE Corporation
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

SKILL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# 加载配置（环境变量 > 本技能根 config.env > 空）
source "${SKILL_ROOT}/resources/lib.sh"

# 幂等：缺啥装啥。用于让“查询知识库”默认可用。
# 只装 MCP 查询所需依赖（与扫描脚本依赖分离，见 requirements-mcp.txt）。
python3 -m pip install -r "${SKILL_ROOT}/scripts/requirements-mcp.txt" >/dev/null

exec python3 "${SKILL_ROOT}/scripts/query.py" "$@"

