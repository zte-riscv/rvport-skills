#!/usr/bin/env bash
# Copyright 2026 ZTE Corporation
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

# riscv-verify benchmark 只读探测脚本：
# 探测工程自带的 benchmark / 测试套件，输出命中清单与判据（JSON 摘要 + 人读清单）。
# 只读，不修改工程任何文件。退出码：0=探测完成（是否命中见输出），1=用法/路径错误。

usage() {
  echo "用法: $0 <project_root>" >&2
  exit 1
}

[[ $# -eq 1 ]] || usage
PROJECT_ROOT="$1"
[[ -d "${PROJECT_ROOT}" ]] || { echo "错误：目录不存在：${PROJECT_ROOT}" >&2; exit 1; }

hits=()          # 人读命中行
hit_dirs=0
hit_targets=0
hit_suites=0
hit_docs=0

# ---------- 1) 测试目录 ----------
for d in test tests benchmark benchmarks bench unit_test unittest; do
  if [[ -d "${PROJECT_ROOT}/${d}" ]]; then
    hits+=("DIR\t${PROJECT_ROOT}/${d}")
    hit_dirs=$((hit_dirs + 1))
  fi
done

# ---------- 2) 构建系统 test/check/benchmark 目标 ----------
while IFS=: read -r file line; do
  [[ -n "${file}" ]] || continue
  hits+=("BUILD_TARGET\t${file}:${line}")
  hit_targets=$((hit_targets + 1))
done < <(grep -rn -E '(add_test|enable_testing|benchmark|gtest|catch2|ctest|check:)' \
  --include='CMakeLists.txt' --include='Makefile*' "${PROJECT_ROOT}" 2>/dev/null | head -40 || true)

# ---------- 3) 第三方基准套件特征文件 ----------
for f in CTestConfig.cmake CTestCustom.cmake; do
  if [[ -f "${PROJECT_ROOT}/${f}" ]]; then
    hits+=("SUITE_FEATURE\t${PROJECT_ROOT}/${f}")
    hit_suites=$((hit_suites + 1))
  fi
done
# gtest/catch2 子目录特征（浅层，避免深扫）
for d in googletest third_party/googletest test/third_party catch2 SPEC spec; do
  if [[ -e "${PROJECT_ROOT}/${d}" ]]; then
    hits+=("SUITE_FEATURE\t${PROJECT_ROOT}/${d}")
    hit_suites=$((hit_suites + 1))
  fi
done

# ---------- 4) README/docs 声明的运行方式 ----------
while IFS=: read -r file line; do
  [[ -n "${file}" ]] || continue
  hits+=("DOC\t${file}:${line}")
  hit_docs=$((hit_docs + 1))
done < <(grep -rn -iE '(make (test|check)|ctest|run.?tests?|benchmark)' \
  "${PROJECT_ROOT}"/README* "${PROJECT_ROOT}"/docs 2>/dev/null | head -20 || true)

total=$((hit_dirs + hit_targets + hit_suites + hit_docs))

# ---------- 输出 ----------
echo "benchmark_probe_summary:"
if [[ ${total} -eq 0 ]]; then
  echo "  verdict: BENCHMARK_MISS"
  echo "  hint: 未命中任何维度，走 riscv-verify 兜底路径（自建对比测试，见 SKILL.md 4.4）"
else
  echo "  verdict: BENCHMARK_HIT"
  echo "  hint: 命中 ${total} 条线索，按 riscv-verify SKILL.md 4.3 基准路径复用自带测试套件"
fi
echo "  counts: {dirs: ${hit_dirs}, build_targets: ${hit_targets}, suite_features: ${hit_suites}, docs: ${hit_docs}}"
if [[ ${#hits[@]} -gt 0 ]]; then
  echo "  evidence:"
  printf '    - %b\n' "${hits[@]}"
fi
