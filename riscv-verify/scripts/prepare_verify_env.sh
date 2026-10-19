#!/usr/bin/env bash
# Copyright 2026 ZTE Corporation
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

# riscv-verify 验证环境一键准备：
# 工具链/QEMU 组件归属 riscv-migrate（已存在则复用），本脚本委托其部署；
# 另检查本技能增量依赖（gcov/lcov 覆盖率工具）。
#
# 配置读取（优先级：环境变量 > 技能根 config.env > 脚本内置默认）：
# 先加载本技能 config.env（如 RISCV_TOOLCHAIN_URL / QEMU_STATIC_URL 覆盖），
# 再委托 riscv-migrate 脚本（其 lib.sh 会尊重已设置的环境变量，不覆盖）。

VERIFY_SKILL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MIGRATE_SKILL_ROOT="${VERIFY_SKILL_ROOT%/riscv-verify}/riscv-migrate"

# 本技能 config.env（存在则加载；环境变量优先）
CONFIG_FILE="${CONFIG_FILE:-${VERIFY_SKILL_ROOT}/config.env}"
if [[ -f "${CONFIG_FILE}" ]]; then
  while IFS= read -r line || [[ -n "${line}" ]]; do
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]}"}"
    [[ -z "${line}" || "${line}" == \#* || "${line}" != *=* ]] && continue
    key="${line%%=*}"; val="${line#*=}"
    [[ "${key}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    val="${val#\"}"; val="${val%\"}"; val="${val#\'}"; val="${val%\'}"
    [[ -n "${!key:-}" ]] && continue
    export "${key}=${val}"
  done < "${CONFIG_FILE}"
fi

if [[ ! -d "${MIGRATE_SKILL_ROOT}" ]]; then
  echo "错误：未找到 riscv-migrate 技能目录（期望 ${MIGRATE_SKILL_ROOT}）。" >&2
  echo "riscv-verify 的工具链/QEMU 由 riscv-migrate 部署（不重复下载），" >&2
  echo "请保持技能组目录结构完整；单独分发 riscv-verify 时须随附 riscv-migrate。" >&2
  exit 1
fi

# 1) RISC-V 交叉工具链 + QEMU user-static（委托 riscv-migrate，幂等；
#    已导出的 *_TOOLCHAIN_URL 等环境变量会被其脚本尊重）
bash "${MIGRATE_SKILL_ROOT}/resources/riscv_toolchain_env.sh"
bash "${MIGRATE_SKILL_ROOT}/resources/qemu_static_env.sh"

# 2) 覆盖率工具检查（缺失给出安装指引；lcov 缺失时可用 gcov 原始输出兜底）
GCOV_BIN="$(command -v gcov || true)"
LCOV_BIN="$(command -v lcov || true)"

echo
echo "覆盖率工具状态："
if [[ -n "${GCOV_BIN}" ]]; then
  echo "  gcov : ${GCOV_BIN}（ok）"
else
  echo "  gcov : 未找到 —— 请安装（随 gcc 提供，或 'apt install gcovr' 替代），否则无法生成 coverage.txt" >&2
fi
if [[ -n "${LCOV_BIN}" ]]; then
  echo "  lcov : ${LCOV_BIN}（ok）"
else
  echo "  lcov : 未找到（可选；缺失时用 gcov 原始输出兜底，或 'apt install lcov'）"
fi

cat <<EOF

已准备好功能验证环境（含 RISC-V 工具链、QEMU、覆盖率工具检查）。

在当前 shell 执行以下命令加载环境变量：
  source "${MIGRATE_SKILL_ROOT}/resources/env.sh"

EOF
