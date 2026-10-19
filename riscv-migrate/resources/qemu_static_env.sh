#!/usr/bin/env bash
# Copyright 2026 ZTE Corporation
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

# amd64/arm64 及其它架构：统一从 GitHub 公开源下载（tonistiigi/binfmt 发布包）
# https://github.com/tonistiigi/binfmt/releases
qemu_linux_suffix_from_uname() {
  case "$(uname -m)" in
    x86_64 | amd64)
      printf '%s' 'amd64'
      ;;
    aarch64 | arm64)
      printf '%s' 'arm64'
      ;;
    armv7l | armv7a | armv7*)
      printf '%s' 'arm-v7'
      ;;
    armv6l | armv6*)
      printf '%s' 'arm-v6'
      ;;
    i386 | i686)
      printf '%s' '386'
      ;;
    ppc64le)
      printf '%s' 'ppc64le'
      ;;
    riscv64)
      printf '%s' 'riscv64'
      ;;
    s390x)
      printf '%s' 's390x'
      ;;
    *)
      log "WARN: 未识别 CPU 型号 $(uname -m)，回退使用 amd64 的 QEMU 包"
      printf '%s' 'amd64'
      ;;
  esac
}

ensure_env_wrapper
prepare_download_dirs
log "QEMU user-static (binfmt bundle)"
require_cmd curl

qemu_suffix="$(qemu_linux_suffix_from_uname)"
QEMU_VER="v10.0.4"
QEMU_FILE="qemu_${QEMU_VER}_linux-${qemu_suffix}.tar.gz"
QEMU_BINFMT_TAG="deploy%2Fv10.0.4-56"

# 公开源（可用 QEMU_STATIC_URL 环境变量 / config.env 覆盖为私有镜像）
QEMU_STATIC_URL="${QEMU_STATIC_URL:-"https://github.com/tonistiigi/binfmt/releases/download/${QEMU_BINFMT_TAG}/${QEMU_FILE}"}"

log "本机 CPU 对应 QEMU 包: ${QEMU_FILE}"

tarball="${QEMU_DIR}/${QEMU_FILE}"

if [[ -f "${tarball}" ]]; then
  log "已存在，跳过下载: ${tarball}"
else
  curl_with_auth -fsSL "${QEMU_STATIC_URL}" -o "${tarball}"
fi

if ! has_qemu_user_static_extracted; then
  if [[ ! -f "${tarball}" ]]; then
    log "ERROR: 缺少 ${tarball} 且本地无 qemu-* 文件，无法解压" >&2
    exit 1
  fi
  log "解压: ${tarball}"
  tar -xzvf "${tarball}" -C "${QEMU_DIR}"
fi

export QEMU_USER_STATIC_DIR="${QEMU_DIR}"
export PATH="${QEMU_DIR}:${PATH}"

mkdir -p "${ENV_D_DIR}"
qemu_env="${ENV_D_DIR}/30-qemu.sh"
{
  echo "# QEMU user-static env"
  echo "export QEMU_USER_STATIC_DIR=\"${QEMU_DIR}\""
  echo "export PATH=\"${QEMU_DIR}:\${PATH}\""
} >"${qemu_env}"

log "QEMU env written: ${qemu_env}"
