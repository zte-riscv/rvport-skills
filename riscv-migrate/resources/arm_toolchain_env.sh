#!/usr/bin/env bash
# Copyright 2026 ZTE Corporation
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

ensure_env_wrapper
prepare_download_dirs
log "ARM cross toolchain"
require_cmd curl

# 默认公网源：bootlin aarch64 glibc stable 工具链
# 可经环境变量 ARM_TOOLCHAIN_URL 或 config.env 覆盖（如内网镜像）
ARM_TOOLCHAIN_URL="${ARM_TOOLCHAIN_URL:-https://toolchains.bootlin.com/downloads/releases/toolchains/aarch64/tarballs/aarch64--glibc--stable-2025.08-1.tar.xz}"

# 按下载 URL 推断压缩格式（bootlin 为 .tar.xz，内部制品多为 .tar.bz2）
case "${ARM_TOOLCHAIN_URL}" in
  *.tar.bz2) archive="${TOOLCHAIN_DIR}/arm-toolchain.tar.bz2" ;;
  *.tar.gz)  archive="${TOOLCHAIN_DIR}/arm-toolchain.tar.gz" ;;
  *)         archive="${TOOLCHAIN_DIR}/arm-toolchain.tar.xz" ;;
esac

# 解压（本地可能残留其它格式的旧包，一并识别）
extract_arm_archive() {
  local a
  for a in "${TOOLCHAIN_DIR}/arm-toolchain.tar.xz" \
           "${TOOLCHAIN_DIR}/arm-toolchain.tar.bz2" \
           "${TOOLCHAIN_DIR}/arm-toolchain.tar.gz"; do
    [[ -f "${a}" ]] || continue
    log "解压: ${a}"
    tar -xf "${a}" -C "${TOOLCHAIN_DIR}"
    return 0
  done
  return 1
}

if [[ -f "${archive}" ]]; then
  log "已存在，跳过下载: ${archive}"
else
  log "下载 ARM 工具链（公网源或已覆盖的镜像源）..."
  curl_with_auth -fSL "${ARM_TOOLCHAIN_URL}" -o "${archive}"
fi

if ! has_aarch64_toolchain_dir; then
  if ! extract_arm_archive; then
    log "ERROR: 无工具链压缩包且本地无已解压目录: ${TOOLCHAIN_DIR}" >&2
    exit 1
  fi
fi

discover_toolchain_roots
# bootlin 包顶层目录形如 aarch64--glibc--*，编译器在其 bin/ 下；
# 若探测到的目录无 bin（罕见布局），退一级找子目录
if [[ -n "${ARM_TOOLCHAIN_ROOT}" && ! -d "${ARM_TOOLCHAIN_ROOT}/bin" ]]; then
  sub="$(find "${ARM_TOOLCHAIN_ROOT}" -maxdepth 2 -type d -name bin 2>/dev/null | head -1)"
  [[ -n "${sub}" ]] && ARM_TOOLCHAIN_ROOT="$(dirname "${sub}")"
fi
if [[ -z "${ARM_TOOLCHAIN_ROOT}" || ! -d "${ARM_TOOLCHAIN_ROOT}/bin" ]]; then
  log "ERROR: 未发现可用的 aarch64 工具链目录（bin/ 缺失）: ${TOOLCHAIN_DIR}" >&2
  exit 1
fi

export ARM_TOOLCHAIN_ROOT="${ARM_TOOLCHAIN_ROOT}"
export PATH="${ARM_TOOLCHAIN_ROOT}/bin:${PATH}"

mkdir -p "${ENV_D_DIR}"
arm_env="${ENV_D_DIR}/10-arm.sh"
{
  echo "# ARM toolchain env"
  echo "export ARM_TOOLCHAIN_ROOT=\"${ARM_TOOLCHAIN_ROOT}\""
  echo "export PATH=\"${ARM_TOOLCHAIN_ROOT}/bin:\${PATH}\""
} >"${arm_env}"

log "ARM env written: ${arm_env}"

