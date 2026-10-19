#!/usr/bin/env bash
# Copyright 2026 ZTE Corporation
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------- 配置文件 ----------
# 优先级：环境变量 > 本技能根 config.env > 脚本内置默认值
# 模板见本技能目录 config.env.example；config.env 已加入 .gitignore（可能含凭据，不入库）。
# CONFIG_FILE 可经环境变量覆盖为共享配置文件（见 README「配置」）。
CONFIG_FILE="${CONFIG_FILE:-${SCRIPT_DIR}/../config.env}"

load_config() {
  [[ -f "${CONFIG_FILE}" ]] || return 0
  local line key val
  while IFS= read -r line || [[ -n "${line}" ]]; do
    # 去首尾空白；跳过注释与非法行
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "${line}" || "${line}" == \#* ]] && continue
    [[ "${line}" != *=* ]] && continue
    key="${line%%=*}"
    val="${line#*=}"
    [[ "${key}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    # 去成对引号
    val="${val#\"}"; val="${val%\"}"
    val="${val#\'}"; val="${val%\'}"
    # 环境变量已设置（非空）则不覆盖
    [[ -n "${!key:-}" ]] && continue
    export "${key}=${val}"
  done < "${CONFIG_FILE}"
}

load_config

# ---------- 缓存/资产目录 ----------
# 默认落在本技能 resources/ 内（技能自包含）；可用环境变量 RISCV_ASSET_ROOT
# 或 config.env 指向共享目录（如 ~/.cache/riscv-skills），避免多技能重复下载。
# 注意：必须在 load_config 之后派生，使 config.env 也能设置 RISCV_ASSET_ROOT。
RISCV_ASSET_ROOT="${RISCV_ASSET_ROOT:-${SCRIPT_DIR}}"
TOOLCHAIN_DIR="${RISCV_ASSET_ROOT}/toolchains"
QEMU_DIR="${RISCV_ASSET_ROOT}/qemu-static"
ENV_D_DIR="${RISCV_ASSET_ROOT}/env.d"

# curl 包装：配置了 ART_API_KEY 时附加制品仓认证头（公开源无需配置）
curl_with_auth() {
  if [[ -n "${ART_API_KEY:-}" ]]; then
    curl -H "X-JFrog-Art-Api:${ART_API_KEY}" "$@"
  else
    curl "$@"
  fi
}

log() {
  echo "[init] $*"
}

require_cmd() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "ERROR: command not found: ${cmd}" >&2
    exit 1
  fi
}

prepare_download_dirs() {
  mkdir -p "${TOOLCHAIN_DIR}" "${QEMU_DIR}"
}

# 是否已有 aarch64 / riscv64 / x86_64 工具链解压目录
# 目录名约定兼容两种来源：
#   - 内部制品：riscv64_* / aarch64_* / x86_64_*（bin 在顶层 <name>/bin）
#   - 公开源：bootlin 的 riscv64--glibc--*/aarch64--glibc--*/x86-64--glibc--*
#     与 riscv-collab 的 riscv64-*/ 及无前缀顶层目录 riscv/（bin 在 <name>/bin）
has_aarch64_toolchain_dir() {
  [[ -n "$(find "${TOOLCHAIN_DIR}" -maxdepth 1 -mindepth 1 -type d \( -name 'aarch64_*' -o -name 'aarch64--*' \) 2>/dev/null | head -1)" ]]
}

has_riscv64_toolchain_dir() {
  [[ -n "$(find "${TOOLCHAIN_DIR}" -maxdepth 1 -mindepth 1 -type d \( -name 'riscv64_*' -o -name 'riscv64-*' -o -name 'riscv64--*' -o -name 'riscv' \) 2>/dev/null | head -1)" ]]
}

has_x86_64_toolchain_dir() {
  [[ -n "$(find "${TOOLCHAIN_DIR}" -maxdepth 1 -mindepth 1 -type d \( -name 'x86_64_*' -o -name 'x86-64--*' \) 2>/dev/null | head -1)" ]]
}

# QEMU user-static 是否已解压（存在任一 qemu-* 文件，不含压缩包）
has_qemu_user_static_extracted() {
  [[ -n "$(find "${QEMU_DIR}" -maxdepth 1 -type f -name 'qemu-*' 2>/dev/null | head -1)" ]]
}

# 在 toolchains/ 下按目录名约定探测 ARM(aarch64) 与 RISC-V 工具链根目录
# 兼容内部（aarch64_*/riscv64_*）、公开源（aarch64--*/riscv64-*）与
# riscv-collab 无前缀顶层目录（riscv/）三种命名
discover_toolchain_roots() {
  ARM_TOOLCHAIN_ROOT=""
  RISCV_TOOLCHAIN_ROOT=""
  [[ -d "${TOOLCHAIN_DIR}" ]] || return 0
  ARM_TOOLCHAIN_ROOT="$(find "${TOOLCHAIN_DIR}" -maxdepth 1 -mindepth 1 -type d \( -name 'aarch64_*' -o -name 'aarch64--*' \) 2>/dev/null | head -1)"
  RISCV_TOOLCHAIN_ROOT="$(find "${TOOLCHAIN_DIR}" -maxdepth 1 -mindepth 1 -type d \( -name 'riscv64_*' -o -name 'riscv64-*' -o -name 'riscv64--*' -o -name 'riscv' \) 2>/dev/null | head -1)"
}

# 在 toolchains/ 下按目录名约定探测 x86_64 交叉工具链根目录
# 兼容内部（x86_64_*）与公开源（x86-64--*）两种命名
discover_x86_toolchain_root() {
  X86_TOOLCHAIN_ROOT=""
  [[ -d "${TOOLCHAIN_DIR}" ]] || return 0
  X86_TOOLCHAIN_ROOT="$(find "${TOOLCHAIN_DIR}" -maxdepth 1 -mindepth 1 -type d \( -name 'x86_64_*' -o -name 'x86-64--*' \) 2>/dev/null | head -1)"
}

ensure_env_wrapper() {
  mkdir -p "${ENV_D_DIR}"
  local env_file="${SCRIPT_DIR}/env.sh"
  {
    echo "# 自动生成：source 本文件即可加载本技能环境变量"
    echo "# 用法: source \"${env_file}\""
    echo ""
    echo "ENV_D_DIR=\"${ENV_D_DIR}\""
    echo "if [[ -d \"\${ENV_D_DIR}\" ]]; then"
    echo "  for f in \"\${ENV_D_DIR}\"/*.sh; do"
    echo "    [[ -f \"\${f}\" ]] || continue"
    echo "    # shellcheck disable=SC1090"
    echo "    source \"\${f}\""
    echo "  done"
    echo "fi"
  } >"${env_file}"
}

