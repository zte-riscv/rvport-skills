# 迁移后功能验证细则（verify_functional）

本文对应 `riscv-verify` 技能 **4.1–4.6** 的实施细则：benchmark 探测与基准/兜底两条路径、浮点容差口径、覆盖率分析与 `report.md` 规范。跨技能协议见 `references/scan_result_protocol.md`。

## 在技能组中的位置

```
riscv-scan(扫描) → riscv-migrate(条目级迁移 + 工程级 QEMU 验证)
                                ↓ 门禁：全条目 DONE + QEMU 跑通主流程
                   riscv-verify(本技能：迁移后功能验证)
                     4.1 盘点验证目标 → 4.2 环境/参数对齐
                     → benchmark 探测：BENCHMARK_HIT → 4.3 基准路径
                                       BENCHMARK_MISS → 4.4 兜底路径
                     → 覆盖率(两路径都做) → 4.5 marking 闭环 → 4.6 自检
```

**与 migrate 验证段（3.x）的分工**：migrate 3.x 保证工程**可构建、可运行**（编译零错误 + 主流程跑通）；本技能保证迁移产物的**功能行为**与原实现一致（全量用例 + 覆盖率 + 报告留痕）。

## 编译参数与运行环境对齐（所有路径的前提）

| 项 | 取值 | 来源 |
| -- | ---- | ---- |
| `-march` / `-mabi` | riscv-migrate 为本工程选定的值（常见起点 `rv64gcv_zbb_zbc_zbkb_zvbb_zvbc_zvkb_zvksed_zvkned_zvksh_zvknha_zvkt` + `lp64d`） | 各条目 `marking` 或 migrate 3.x 构建日志 |
| 目标 VLEN | migrate A 节 #6 选定 CPU 时确定的目标 VLEN（默认 「VLEN=256 通用目标」） | 同上 |
| QEMU 运行 | `qemu-riscv64 -cpu max,vlen=<目标VLEN>` | 与 migrate 3.3 对齐 |
| 静态链接 | 工程要求则 `-static` | 工程实际 |

> 不在本技能另起一套参数：验证口径必须与迁移口径一致，否则失败无法归因。

## 4.3 基准路径细则（BENCHMARK_HIT）

### 探测清单（主 Agent 执行，脚本或手工）

```bash
# 辅助脚本（推荐）：
bash ${RISCV_SKILLS_ROOT}/riscv-verify/scripts/probe_benchmark.sh <project_root>

# 手工兜底（脚本失败时逐项执行）：
# 1) 测试目录
ls -d <project_root>/{test,tests,benchmark,benchmarks,bench,unit_test,unittest} 2>/dev/null
# 2) 构建目标
grep -rn -E '(add_test|enable_testing|benchmark|gtest|catch2|ctest|check:)' \
  --include='CMakeLists.txt' --include='Makefile*' <project_root>
# 3) README/docs 声明的运行方式
grep -rn -iE '(make (test|check)|ctest|run.?tests?|benchmark)' \
  <project_root>/README* <project_root>/docs 2>/dev/null
```

**命中判据**（任一即 `BENCHMARK_HIT`）：存在测试目录 / 构建系统含 test 目标 / 套件特征文件（gtest、catch2、CTestConfig.cmake、SPEC 子目录）/ README 声明运行方式。探测依据（哪个维度命中、路径）记入 `report.md` 第 1 节。

### CTest 场景 qemu 包装

```sh
#!/bin/sh
# <target_dir>/qemu_wrapper.sh —— CTest 逐用例经 QEMU 运行
exec qemu-riscv64 -cpu max,vlen=<目标VLEN> "$@"
```

配 `ctest` 的方式（按工程实际择一）：

```bash
# 方式 A：覆盖测试命令属性（推荐）
ctest --test-dir <target_dir>/build -T test \
  --overwrite TestCommand="<target_dir>/qemu_wrapper.sh" 2>&1 | tee <target_dir>/run.log
# 方式 B：逐个二进制运行（TestCommand 覆盖不被工程支持时）
for t in <target_dir>/build/test_*; do
  echo "=== $t ==="; <target_dir>/qemu_wrapper.sh "$t"
done 2>&1 | tee <target_dir>/run.log
```

### 用例计数口径

- 以测试框架自身判定为准（ctest 的 `tests passed` 行、gtest 的 `[  PASSED  ]` 行等），不靠 grep 源码估算；
- 框架无判定输出时，以「每个测试函数一段、退出码 0」计一条用例，口径写入 `report.md` 第 3 节；
- 因环境跳过的用例计 `skipped` 并逐条写理由（`report.md` 第 4 节），不计入失败。

## 4.4 兜底路径细则（BENCHMARK_MISS）

### 驱动三件套模板

`main.c`（对拍驱动骨架）：

```c
/* 用同一份输入驱动原始实现与 RISC-V 实现，输出必须对齐到 stdout */
#include <stdio.h>
#include <string.h>
#include "crc32_orig.h"   /* 原始 x86/ARM 实现（参考侧编译时启用） */
#include "crc32_riscv.h"  /* 迁移后 RISC-V 实现（被测侧） */

int main(void) {
    /* 1) 固定边界用例 + 2) 随机用例（固定种子，保证两侧输入一致）+ 3) checksum 汇总 */
    static const unsigned char cases[][16] = { {0}, {0xff,0xff,0xff,0xff}, /* ... */ };
    for (size_t i = 0; i < sizeof(cases)/sizeof(cases[0]); i++) {
        uint32_t c = crc32_riscv(cases[i], sizeof(cases[0]));
        printf("case%zu=0x%08x\n", i, c);
    }
    /* 逐用例打印 + 末尾总 checksum；两侧二进制各自编译运行后 diff 输出 */
    return 0;
}
```

> 用例设计三类至少各一组（对齐 migrate A 节 #5）：边界值、随机（固定种子）、checksum 汇总；向量条目另须覆盖「尾部不足一条向量」用例。参考侧与被测侧可用同一份 `main.c`（用宏或链接不同实现文件区分），保证输入完全一致。

`Makefile`（工具链探测写进变量，不硬编码）：

```makefile
# 探测顺序：技能部署的工具链（已 source env，无版本后缀）→ 带版本后缀 → 不带后缀；
# 探测结果写进 CC/CXX，不硬编码
RISCV_CC  := $(shell command -v riscv64-unknown-linux-gnu-gcc 2>/dev/null || command -v riscv64-linux-gnu-gcc-14 2>/dev/null || command -v riscv64-linux-gnu-gcc 2>/dev/null)
X86_CC    := $(shell command -v gcc 2>/dev/null)
ARM_CC    := $(shell command -v aarch64-buildroot-linux-gnu-gcc 2>/dev/null || command -v aarch64-linux-gnu-gcc-14 2>/dev/null || command -v aarch64-linux-gnu-gcc 2>/dev/null)

MARCH := rv64gcv_zbb_zbc_zbkb_zvbb_zvbc_zvkb_zvksed_zvkned_zvksh_zvknha_zvkt  # ← 沿用 migrate 值
MABI  := lp64d
CFLAGS_RISCV := -O2 -march=$(MARCH) -mabi=$(MABI) -static

# 哪个参考侧找不到就跳过对应目标；至少编出 riscv 侧
all: riscv.out $(if $(X86_CC),x86.out,) $(if $(ARM_CC),arm.out,)
```

`run.sh`：

```bash
#!/bin/sh
set -e
# 先跑原实现（参考侧，原生或 qemu-aarch64）→ expected.out
[ -x ./x86.out ]  && ./x86.out  > expected.out
[ -x ./arm.out ]  && qemu-aarch64 ./arm.out > expected.out 2>/dev/null || true
# 再跑 RISC-V 版本（qemu）→ actual.out
qemu-riscv64 -cpu max,vlen=<目标VLEN> ./riscv.out > actual.out
# 整数/字节流逐字节 diff；浮点按容差口径（见下节），由 compare 脚本/工具处理
diff expected.out actual.out && echo "VERIFY PASS"
```

### 浮点容差口径（与 migrate 3.3 一致）

- **整数 / 字节流 / 枚举 / checksum**：逐字节 `diff`，必须完全一致；
- **浮点输出**：禁逐字节 diff，用相对误差 `|a-b| ≤ max(abs_err, rel_err×|b|)`，默认 `rel_err=1e-9`（双精度）、`abs_err=1e-12`；容差内一致不算失败，差异模式写入该目标 `report.md` 第 4 节与条目 `marking`；
- **位精确语义**（哈希输入、序列化格式）：必须逐位一致。

## 覆盖率分析（两条路径都做，行覆盖 ≥ 70%）

```bash
# 1) --coverage 重编（独立构建目录，不污染 build/）
cmake -S . -B <target_dir>/build-cov -DCMAKE_C_FLAGS="--coverage" ...   # 或 Makefile COV=1
# 2) QEMU 跑同套用例（生成 .gcda）
ctest --test-dir <target_dir>/build-cov ...   # 或 qemu-riscv64 <cov_binary>
# 3) 生成报告 → coverage.txt
lcov --capture --directory <target_dir>/build-cov --output-file coverage.info \
  && lcov --remove coverage.info '/usr/*' --output-file coverage.info \
  && lcov --summary coverage.info > <target_dir>/coverage.txt 2>&1
# lcov 不可用时用 gcov 原始输出兜底：
# gcov -b <target_dir>/build-cov/**/*.o > <target_dir>/coverage.txt 2>&1
```

- 覆盖范围 = 被测的迁移产物源文件（排除系统头 / 第三方库）；
- **行覆盖 ≥ 70%** 为达标线：低于阈值不回流，原因（不可达分支、需真机外设等）与补充计划写入 `report.md` 第 5 节并列入 `TODO(后续)`；
- gcda 在 QEMU 下随进程退出落盘；若未生成，检查 `GCOV_PREFIX` 与退出路径（异常退出不落盘，属环境问题按 `FIX_IN_PHASE4` 处理）。

## report.md 六节模板

```markdown
# <验证目标名> 功能验证报告（riscv-verify）

## 1. 工程与验证目标概况
- 工程：<project_root>；路径裁决：BENCHMARK_HIT / BENCHMARK_MISS（探测依据：<命中维度与路径>）
- 验证目标：crc32（覆盖 scan_result.json 条目：src/crc/crc32.c:120-200 等 N 条）

## 2. 工具链与编译命令
- CC/CXX：<探测结果（含探测顺序）>
- -march/-mabi：<沿用 migrate 的值>；QEMU：qemu-riscv64 -cpu max,vlen=<目标VLEN>
- 构建目录：<target_dir>/build（覆盖率：<target_dir>/build-cov）；完整命令：`...`

## 3. 用例统计
- 总数 N / 通过 M / 失败 F / 跳过 S（跳过理由见第 4 节）；计数口径：<框架判定/函数段+退出码>

## 4. 失败用例分析
- <用例>：迁移缺陷 → REFLOW_TO_PHASE2（条目 <file:lines>，已修复重跑通过）/ 环境问题 → FIX_IN_PHASE4（<理由>）

## 5. 覆盖率摘要
- 行覆盖 X%（达标线 70%：<达标/未达标+原因>）；分支覆盖 Y%；详见 coverage.txt

## 6. 结论与遗留 TODO
- 结论：验证通过（benchmark）/ 验证通过（对比）/ 部分通过（受限说明）
- TODO(后续)：<项>
```

## 4.5 marking 写入示例（主 Agent）

```jsonc
// 基准路径通过：
{ "status": "DONE", "marking": "无异常；验证通过（benchmark）：crc32 单测，共 24 条用例，通过 24 条，行覆盖 87%" }
// 兜底路径通过：
{ "status": "DONE", "marking": "语义差异：尾循环掩码处理，已通过测试规避；验证通过（对比）：crc32 输出一致，行覆盖 82%" }
// 发生过回流：
{ "status": "DONE", "marking": "无异常；验证回流：用例 7 输出错位，已修复重验通过；验证通过（benchmark）：... " }
// 遗留：
{ "status": "DONE", "marking": "无异常；验证通过（benchmark）：...；TODO(后续)：vlen=512 场景未覆盖" }
```

## 进度自检（对齐 SKILL.md 4.6）

全部验证目标 `report.md` + `coverage.txt` 生成、用例全过（失败已闭环或说明环境理由）、行覆盖 ≥ 70%（未达标已说明）、`marking` 已追加验证结论、构建中间产物已清理、仓库根无遗留构建目录。
