#!/usr/bin/env bash
# Copyright 2026 ZTE Corporation
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

ensure_env_wrapper
prepare_download_dirs
log "RISC-V cross toolchain"
require_cmd curl

archive="${TOOLCHAIN_DIR}/riscv-toolchain.tar.gz"
# 默认公网源：riscv-collab GNU toolchain（ubuntu-22.04, gcc 14.2 nightly, glibc）
# 可经环境变量 RISCV_TOOLCHAIN_URL 或 config.env 覆盖（如内网镜像）
RISCV_TOOLCHAIN_URL="${RISCV_TOOLCHAIN_URL:-https://github.com/riscv-collab/riscv-gnu-toolchain/releases/download/2024.09.03/riscv64-glibc-ubuntu-22.04-gcc-nightly-2024.09.03-nightly.tar.gz}"

# 按下载 URL 推断压缩格式（公开源为 .tar.gz，内部制品多为 .tar.bz2）
case "${RISCV_TOOLCHAIN_URL}" in
  *.tar.bz2) archive="${TOOLCHAIN_DIR}/riscv-toolchain.tar.bz2" ;;
  *.tar.xz)  archive="${TOOLCHAIN_DIR}/riscv-toolchain.tar.xz" ;;
  *)         archive="${TOOLCHAIN_DIR}/riscv-toolchain.tar.gz" ;;
esac

if [[ -f "${archive}" ]]; then
  log "已存在，跳过下载: ${archive}"
else
  log "下载 RISC-V 工具链（公网源或已覆盖的镜像源）..."
  curl_with_auth -fSL "${RISCV_TOOLCHAIN_URL}" -o "${archive}"
fi

# 解压（本地可能残留其它格式的旧包，一并识别）
extract_riscv_archive() {
  local a
  for a in "${TOOLCHAIN_DIR}/riscv-toolchain.tar.gz" \
           "${TOOLCHAIN_DIR}/riscv-toolchain.tar.bz2" \
           "${TOOLCHAIN_DIR}/riscv-toolchain.tar.xz"; do
    [[ -f "${a}" ]] || continue
    log "解压: ${a}"
    tar -xf "${a}" -C "${TOOLCHAIN_DIR}"
    return 0
  done
  return 1
}

if ! has_riscv64_toolchain_dir; then
  if ! extract_riscv_archive; then
    log "ERROR: 无工具链压缩包且本地无已解压目录: ${TOOLCHAIN_DIR}" >&2
    exit 1
  fi
fi

discover_toolchain_roots
# riscv-collab 包顶层目录形如 riscv64-*/，编译器在其 bin/ 下；
# 若探测到的目录无 bin（罕见布局），退一级找子目录
if [[ -n "${RISCV_TOOLCHAIN_ROOT}" && ! -d "${RISCV_TOOLCHAIN_ROOT}/bin" ]]; then
  sub="$(find "${RISCV_TOOLCHAIN_ROOT}" -maxdepth 2 -type d -name bin 2>/dev/null | head -1)"
  [[ -n "${sub}" ]] && RISCV_TOOLCHAIN_ROOT="$(dirname "${sub}")"
fi
if [[ -z "${RISCV_TOOLCHAIN_ROOT}" || ! -d "${RISCV_TOOLCHAIN_ROOT}/bin" ]]; then
  log "ERROR: 未发现可用的 riscv64 工具链目录（bin/ 缺失）: ${TOOLCHAIN_DIR}" >&2
  exit 1
fi

export RISCV_TOOLCHAIN_ROOT="${RISCV_TOOLCHAIN_ROOT}"
export PATH="${RISCV_TOOLCHAIN_ROOT}/bin:${PATH}"

mkdir -p "${ENV_D_DIR}"
riscv_env="${ENV_D_DIR}/20-riscv.sh"
{
  echo "# RISC-V toolchain env"
  echo "export RISCV_TOOLCHAIN_ROOT=\"${RISCV_TOOLCHAIN_ROOT}\""
  echo "export PATH=\"${RISCV_TOOLCHAIN_ROOT}/bin:\${PATH}\""
} >"${riscv_env}"

log "RISC-V env written: ${riscv_env}"

