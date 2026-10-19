---
name: riscv-verify
description: RISC-V 迁移第三步（功能验证收口）。前置=riscv-migrate 已完成迁移（全条目 DONE 且工程级验证段在 QEMU 跑通主流程；缺失 scan_result.json 时引导先跑 riscv-scan）。基准路径优先：探测工程自带 benchmark/测试套件（BENCHMARK_HIT）→ 只换工具链为 RISC-V 交叉链复用全量用例，QEMU 全量运行统计通过率；未命中（BENCHMARK_MISS）则兜底自建原架构 vs RISC-V 对比测试（expected.out/actual.out diff）。两条路径都必须做 gcov 覆盖率分析（行覆盖 ≥70%）并生成 test/<验证目标名>/{report.md,coverage.txt}；用例失败按迁移缺陷（REFLOW_TO_PHASE2）/环境问题（FIX_IN_PHASE4）分流；验证结论按固定语汇写回 scan_result.json 的 marking。只关注功能正确性，不做性能度量。
---

# RISC-V 迁移后功能验证（riscv-verify）

> **架构：主 Agent 编排 + 阶段内动态 Subagent**

面向已由 `riscv-migrate` 完成迁移的工程，对**全部 RISC-V 迁移产物**执行功能验证：优先复用工程自带 benchmark/测试套件，未命中时自建对比测试兜底；统一做覆盖率分析；产出规范化验证报告 `report.md` 与 `coverage.txt`；并把验证结论按固定语汇写回 `scan_result.json` 的 `marking`。

## 技能组总图（本技能 = 第 3 步）

| # | 技能 | 职责 | 门禁 |
| - | ---- | ---- | ---- |
| 1 | riscv-scan | 扫描迁移点，产出 scan_result.json | JSON 存在可读 → 才能进 migrate |
| 2 | riscv-migrate | 条目级迁移（2.x）+ 工程级验证（3.x，全条目 DONE 后自动进入） | 产物构建跑通、QEMU 跑通主流程 → 才能进本技能 |
| **3（本技能）** | **riscv-verify** | **迁移后功能验证（4.x）：benchmark 优先 → 兜底对比 → 覆盖率 → report.md + marking 闭环** | 全部验证目标 report.md/coverage.txt 生成、用例全过（失败已闭环或说明环境理由） |

> 跨技能协议（状态字段、门禁、回流、令牌）权威：[`references/scan_result_protocol.md`](references/scan_result_protocol.md)。**只有主 Agent 可以写入 `scan_result.json`**。
>
> 路径约定：`${RISCV_SKILLS_ROOT}` 指各技能目录的共同父目录；未设置该环境变量时按相对本技能的目录结构自行解析。

## 入口前置条件

- `<project_root>/scan_result.json` 存在且可读。**不存在时：引导用户先运行 `riscv-scan` 技能，本技能不代跑扫描**。
- **全条目 `DONE` 且每个 `DONE` 条目 `marking` 非空**（即 riscv-migrate 已完成迁移段）。
- 工程已在 QEMU 中跑通主流程（migrate 验证段 3.3 达成）。**未达成时：引导用户先完成 riscv-migrate 工程级验证，本技能不代跑**；用户明确要求只做部分目标的验证时，可对已达成目标执行并在摘要中说明限制。
- JSON schema 不一致时自主修补（缺 `status`/`marking` 的条目补默认值 `TODO`/`""`，保留缩进）。
- 存在未完成条目（`TODO`/`START`）而用户仍要求验证时：视为部分验证，受限范围写入最终摘要。

## 验证产物落位总则（基准路径与兜底路径都必须遵守）

所有验证产物必须统一落在 `<project_root>/test/<验证目标名>/` 下：

- **验证目标名** = benchmark/测试套件名，或兜底路径的源文件 basename；
- **禁止**在仓库根目录新留构建目录（如 `build/`、`build-riscv64/`）；**不要写 `/tmp`**（跨会话稳定保留的关键就是落地在仓库内）；
- 每个验证目标目录的最终形态（清理中间产物后）至少包含：

| 文件 | 必/荐 | 内容 |
| ---- | ----- | ---- |
| `report.md` | 必 | 验证报告（规范见下） |
| `coverage.txt` | 必 | 覆盖率报告（行/分支覆盖率，与 gcov/lcov 输出对应） |
| `expected.out` / `actual.out` 或 `run.log` | 必 | 运行输出与基线（基准路径通常只有 `run.log`） |
| `build.log` / `run.log` | 荐 | 编译与运行日志 |
| 驱动源文件（`main.c` / `Makefile` / `run.sh` / qemu 包装脚本等） | 兜底路径必 | 自建测试驱动 |

- **`report.md` 内容规范**（六节）：
  1. 工程与验证目标概况（benchmark 名称或被测源文件）；
  2. 实际使用的工具链与完整编译命令（CC/CXX、`-march`/`-mabi`、构建目录）；
  3. 用例统计（总数 / 通过 / 失败 / 跳过）；
  4. 失败用例分析（迁移缺陷须修复后重跑；环境问题说明理由）；
  5. 覆盖率摘要（行/分支覆盖率数字，与 `coverage.txt` 对应）；
  6. 结论与遗留 `TODO(后续)`。
- **清理规则**：覆盖率报告生成之后，统一清理编译中间产物（`build/`、`build-cov/` 子目录、`*.o` / `*.gcda` / `*.gcno` / 可执行文件等；原地构建的工程用 `make clean` 或按扩展名删除本次新增中间文件），只保留上表文件，避免污染仓库与前端文件树。清理前核对对象，避免误删用户原有文件。

## 迁移点进度（权威源在 `scan_result.json`）

- 本技能**只更新 `marking`**（追加验证结论语汇，见协议 4.4），不回退已达成状态；功能验证定位出**迁移缺陷**时把对应条目 `DONE` 恢复为 `START` 回流 riscv-migrate 修复（见「失败回流」）。
- **只有主 Agent 可以写入 `scan_result.json`**。

## 主 Agent 职责（唯一编排者与状态提交者）

主 Agent 不默认亲自完成全部工作，而是：确认入口前置条件（全条目 DONE）；盘点验证目标；组织 benchmark 探测并裁决 `BENCHMARK_HIT`/`BENCHMARK_MISS`；生成验证任务包并分派 verify-runner Subagent（或规模小时自己执行）；收集核验 Subagent 结果；执行/复核失败用例的分流裁决（`REFLOW_TO_PHASE2` vs `FIX_IN_PHASE4`）；生成覆盖率报告与 `report.md` 的最终审核；更新 `marking`；清理构建中间产物；输出摘要；决定推进或回流。

> **主 Agent 不得把"Subagent 返回 PASS"直接等同于"验证通过"**——必须核对用例统计、输出基线（`diff` 结果或 benchmark 判定输出）与 `coverage.txt` 三类证据后才认定。

### Subagent 通用约束

- **不修改 `scan_result.json`**：所有 Subagent 均不得直接写入状态文件。
- **不直接向用户提问**：缺少信息时先将问题返回主 Agent，由主 Agent 按自主运行原则处理。
- **不超出分配范围**：只处理任务包内指定的验证目标目录。
- **只返回"待审核"状态**：Subagent 内部使用 `READY_FOR_VERIFY`、`PASS`、`BLOCKED` 等状态，这些状态不写入 `scan_result.json`。

## 动态调度

```text
零个 Subagent：主 Agent 直接完成（验证目标数 ≤ 2 时默认）
一个 Subagent：委托一个明确工作单元
多个 Subagent：处理互不依赖的验证目标（并发 ≤ 4，各自只写自己的 test/<验证目标名>/ 目录）
```

## 任务输入协议

### 验证任务包（主 Agent → verify-runner）

```json
{
  "task_id": "phase4-verify-crc32",
  "phase": "PHASE_4",
  "role": "VERIFY_RUNNER",
  "project_root": "/abs/path/project",
  "scan_result_path": "/abs/path/project/scan_result.json",
  "scope": {
    "verify_target": "crc32",
    "target_dir": "/abs/path/project/test/crc32",
    "path_mode": "BENCHMARK_HIT",
    "benchmark": {
      "name": "crc32 unit tests",
      "build_system": "cmake",
      "run_command": "ctest",
      "source": "探测依据（命中目录/目标/README 段落）"
    }
  },
  "context": {
    "march": "rv64gcv_zbb_zbc_zbkb_zvbb_zvbc_zvkb_zvksed_zvkned_zvksh_zvknha_zvkt",
    "mabi": "lp64d",
    "target_vlen": 256,
    "toolchain_env": "${RISCV_SKILLS_ROOT}/riscv-migrate/resources/riscv_toolchain_env.sh"
  },
  "allowed_write_paths": ["/abs/path/project/test/crc32"],
  "requirements": [
    "构建目录必须指向 /abs/path/project/test/crc32/build/",
    "benchmark 按原工程构建方式，只把工具链/编译参数换成 RISC-V 交叉链",
    "QEMU 全量运行并逐条记录用例通过情况，完整重定向到 run.log",
    "失败用例标注分流建议（迁移缺陷/环境问题）供主 Agent 裁决",
    "覆盖率构建在 build-cov/，报告输出 coverage.txt",
    "不得修改 scan_result.json 与工程源码"
  ],
  "acceptance": [
    "全部用例通过（或失败项已给出分流建议）",
    "report.md + coverage.txt + run.log 生成",
    "构建中间产物已清理"
  ]
}
```

## 统一结构化返回协议

```json
{
  "task_id": "phase4-verify-crc32",
  "phase": "PHASE_4",
  "status": "PASS",
  "summary": "crc32 自带单测 24 条全部通过，行覆盖 87%",
  "path_mode": "BENCHMARK_HIT",
  "case_stats": { "total": 24, "passed": 24, "failed": 0, "skipped": 0 },
  "coverage": { "line": 87.2, "branch": 71.5 },
  "artifacts": [
    "/abs/path/project/test/crc32/report.md",
    "/abs/path/project/test/crc32/coverage.txt",
    "/abs/path/project/test/crc32/run.log"
  ],
  "failure_triage": [],
  "risks": [],
  "blocked_reason": ""
}
```

允许的 Subagent 内部 `status`（不得写入 `scan_result.json`；令牌语义与冻结值见协议第 7 节）：`READY_FOR_VERIFY` / `PASS` / `BLOCKED` / `FAILED` / `BENCHMARK_HIT` / `BENCHMARK_MISS`。

## 4.1 盘点验证目标（本技能入口）

主 Agent 读取 `scan_result.json`，把每个含 RISC-V 迁移产物的条目映射为验证目标：

- 逐条目确定「验证目标名」：该条目对应的 benchmark/测试套件名，或迁移产物源文件 basename（如 `crc32` → `test/crc32/`）；
- 多个条目共享同一 benchmark/目录（如同一 test 套件覆盖多个迁移文件）→ 合并为**一个**验证目标，在 `report.md` 用例统计中按源文件分节；
- 条目 `marking` 含 `误报` 的 → 跳过（无迁移产物可验证），摘要中单列；
- 条目 `marking` 含 `trivial 宏适配` 的 → 纳入（可编译性已在 migrate 3.x 兜底，本技能关注其功能行为）；
- 产出验证目标清单（名称、覆盖条目、初判 benchmark 候选），作为 4.2 输入。

## 4.2 验证环境与工具链（沿用 migrate 部署，自动加载）

- 一键准备（工具链 + QEMU + 覆盖率工具检查；组件归属 riscv-migrate，已存在则复用）：`bash ${RISCV_SKILLS_ROOT}/riscv-verify/scripts/prepare_verify_env.sh`
- RISC-V 工具链加载：`bash ${RISCV_SKILLS_ROOT}/riscv-migrate/resources/riscv_toolchain_env.sh` + `source ${RISCV_SKILLS_ROOT}/riscv-migrate/resources/env.sh`
- QEMU user-static：`bash ${RISCV_SKILLS_ROOT}/riscv-migrate/resources/qemu_static_env.sh`
- **编译参数对齐（必须）**：`-march` / `-mabi` / 目标 VLEN 沿用 riscv-migrate 为本工程选定的值（见各条目 `marking` 或 migrate 3.x 构建日志），不要在本技能另起一套；QEMU 侧 `-cpu max,vlen=<目标VLEN>` 与 migrate 3.3 对齐。

## 4.3 基准路径：工程自带 benchmark/测试套件（★ 首选）

**第一步：探测**（主 Agent 执行，可用辅助脚本）：

- 只读探测入口：`bash ${RISCV_SKILLS_ROOT}/riscv-verify/scripts/probe_benchmark.sh <project_root>`（输出命中清单与判据）；脚本失败时按下列清单手工探测：
  - `test` / `tests` / `benchmark` / `benchmarks` / `bench` / `unit_test` / `unittest` 等目录；
  - `CMakeLists.txt` / `Makefile` 中的 test/check/benchmark 目标（`grep -rn -E '(add_test|enable_testing|benchmark|gtest|catch2|ctest|check:)' --include='CMakeLists.txt' --include='Makefile*' <project_root>`）；
  - 第三方基准套件特征：CTest、Google Test（libgtest）、Catch2、google/benchmark、nbench、SPEC 子目录等；
  - README / docs 里声明的测试运行方式（`grep -rn -iE '(make (test|check)|ctest|run.?tests?|benchmark)' <project_root>/README* <project_root>/docs 2>/dev/null`）。

**裁决**：任一维度命中 → `BENCHMARK_HIT`，走本节基准路径；全部未命中 → `BENCHMARK_MISS`，走 4.4 兜底路径。裁决与探测依据记入各目标 `report.md` 第 1 节。

**第二步：执行**（主 Agent 或 verify-runner，按任务包）：

1. **构建**：按原工程自带构建方式（CMake：`cmake -S . -B <target_dir>/build`；Makefile：`make test` / `make check` / 对应目标），只把工具链/编译参数换成 RISC-V 交叉链（`-march`/`-mabi`/`-static` 取值与 4.2 对齐；CTest 场景给 ctest 传 qemu 包装）。
   - **构建目录必须指向 `<target_dir>/build/`**，不要在仓库根目录留 `build/`；
   - benchmark 自身强制源内构建（CMakeLists 限制或源内生成文件）时：构建后把测试可执行文件与日志复制到 `<target_dir>/` 留档，并 `make clean` 清掉源内构建目录。
2. **运行**：在 `qemu-riscv64 -cpu max,vlen=<目标VLEN>` 下全量运行，逐条记录用例通过情况（CTest 场景：先写 qemu 包装脚本 `<target_dir>/qemu_wrapper.sh` —— `#!/bin/sh` + `exec qemu-riscv64 "$@"`，再 `ctest` 逐个运行）；运行输出完整重定向到 `<target_dir>/run.log`。
3. **失败分流（主 Agent 裁决）**：
   - **迁移缺陷**（输出错误/语义不一致/崩溃，根因在迁移代码）→ `REFLOW_TO_PHASE2`：对应条目 `DONE` 恢复 `START`，回 riscv-migrate 修复，修复后重跑本目标直至全过；
   - **环境/工具链问题**（缺库、模拟器限制、参考侧无法构建等）→ `FIX_IN_PHASE4`：段内自修（装包、调包装脚本、改报告说明），理由记入 `report.md` 第 4 节；跳过的用例计入 skipped 并说明。
4. **覆盖率（必须）**：benchmark 跑通后用 `--coverage` 重编一份（构建目录 `<target_dir>/build-cov/`），跑同套用例后用 gcov / lcov 生成行/分支覆盖率，输出 `<target_dir>/coverage.txt`；**行覆盖 ≥ 70%**（低于阈值在 `report.md` 说明原因并列入 `TODO(后续)`）。
5. **报告**：按产物落位总则的六节规范写 `<target_dir>/report.md`，并在最终摘要写明「使用了原工程自带 benchmark：<名称/目标>，共 N 条用例，通过 M 条」。

## 4.4 兜底路径：自建对比测试（仅当 BENCHMARK_MISS）

为每个验证目标在 `<target_dir>/` 下生成三件套驱动：

- **`main.c`**：用同一份输入驱动原始 x86/ARM 实现与 RISC-V 实现对拍，输出对齐到 stdout 或固定文件；
- **`Makefile`**：
  - **工具链探测（必做，避免硬编码失败）**：按部署形态分两路——技能部署的工具链（已 `source` migrate 的 `env.sh`）探测 `riscv64-unknown-linux-gnu-gcc` / `aarch64-buildroot-linux-gnu-gcc`；系统/容器发行版包探测 `riscv64-linux-gnu-gcc-14` → `riscv64-linux-gnu-gcc`、`aarch64-linux-gnu-gcc-14` → `aarch64-linux-gnu-gcc`（只装不带版本后缀包时常见）；**探测结果直接写进 Makefile 的 CC/CXX 变量**，不在文本里硬编码后缀。
  - **原始版本探测**：`command -v gcc`（x86_64 宿主）或技能部署的 x86 交叉链；ARM 侧 `aarch64-buildroot-linux-gnu-gcc` → `aarch64-linux-gnu-gcc-14` → `aarch64-linux-gnu-gcc`；**哪个找不到就跳过对应参考侧**，不强行编；至少把 RISC-V 版本编出来跑 qemu（仅 RISC-V 侧时改用固定期望值或 migrate 2.4 已验证的基线）。
  - **找不到 cmake 时**：直接在本目录写最小 Makefile 串编目标源文件 + RISC-V 实现；这是验证产物，不回改工程构建系统。
  - RISC-V 编译参数与 4.2 对齐（`-march`/`-mabi`/`-static`）。
- **`run.sh`**：先跑原实现输出 `expected.out`，再跑 RISC-V 版本（qemu）输出 `actual.out`，`diff` 二者；浮点按容差口径（`rel_err=1e-9`/`abs_err=1e-12` 量级，细则见 [references/verify_functional.md](references/verify_functional.md)）。

**执行**：`cd <target_dir> && make 2>&1 | tee build.log && bash run.sh 2>&1 | tee run.log`；`diff` 有差异时按 4.3 第 3 步同口径分流：语义不一致 → `REFLOW_TO_PHASE2` 修复重跑；驱动自身问题 → `FIX_IN_PHASE4` 段内自修。循环直至完全一致。覆盖率与 `report.md` 同 4.3 第 4-5 步（`--coverage` 重编在 `build-cov/`）。

> 兜底路径的 `main.c`/`Makefile`/`run.sh` 是**验证驱动**，不是对工程源码的修改；不因兜底路径回改工程构建系统。

## 4.5 status/marking 闭环更新（必做）

每个验证目标通过后，主 Agent **直接编辑 `scan_result.json`**：

- 对应条目的 `marking` **追加**验证结论语汇（固定短语，完整表见协议 4.4）：
  - 基准路径：`验证通过（benchmark）：<名称/目标>，共 N 条用例，通过 M 条`（可附覆盖率：`，行覆盖 X%`）
  - 兜底路径：`验证通过（对比）：<目标> 输出一致，行覆盖 X%`
  - 验证过程发生回流：`验证回流：<原因>，已修复重验通过`（与上两条组合）
  - 遗留项：`TODO(后续)：<具体项>`
- 写回时保持 schema 与缩进一致；不改 `target` / `suggestion_class_count` / `missing_class_count` 三个顶层字段；`status` 保持 `DONE`（回流修复期间除外）。

## 4.6 进度自检（出口条件）

- 所有含迁移产物的条目：验证目标 `report.md` 与 `coverage.txt` 生成；行覆盖 ≥ 70%（低于者已说明并列入 `TODO(后续)`）；
- 每个验证目标用例全过；失败用例要么已按 `REFLOW_TO_PHASE2` 闭环重跑全过，要么已按 `FIX_IN_PHASE4` 说明环境理由（计入 skipped）；
- 自带 benchmark 的工程在摘要中写明 benchmark 名称与用例通过数；
- 汇编类条目在 migrate 已有知识库查证证据（本技能抽查即可，不重查）；
- `marking` 已按 4.5 追加验证结论；
- 仓库根目录没有遗留本次验证产生的构建目录（`build/` 等已清理）。

完成后向用户输出一次结构化摘要：验证目标数 / 基准 vs 兜底路径分布 / 用例统计（总/过/败/跳过）/ 覆盖率分布 / `marking` 更新数 / 产物路径 / 遗留 `TODO(后续)` 清单。

## Subagent

| Subagent | 角色 | 读写属性 |
| -------- | ---- | -------- |
| [`riscv-verify-runner`](agents/riscv-verify-runner.md) | 按验证目标执行基准/兜底路径全流程（构建、QEMU 运行、用例统计、覆盖率、report.md 初稿、失败分流建议），返回结构化结果；定义在本技能 `agents/` | 写入（仅限本目标 `test/<验证目标名>/` 目录） |

## 脚本与资源

| 资产 | 路径 | 用途 |
| ---- | ---- | ---- |
| 功能验证细则 | [references/verify_functional.md](references/verify_functional.md) | benchmark 探测清单、兜底驱动模板、浮点容差、report.md 六节模板 |
| 验证环境一键准备 | `${RISCV_SKILLS_ROOT}/riscv-verify/scripts/prepare_verify_env.sh` | 委托 riscv-migrate 部署工具链/QEMU + 检查 gcov/lcov 可用性 |
| benchmark 探测辅助 | `${RISCV_SKILLS_ROOT}/riscv-verify/scripts/probe_benchmark.sh` | 只读探测工程自带测试/benchmark，输出命中清单 |
| RISC-V 工具链 | `${RISCV_SKILLS_ROOT}/riscv-migrate/resources/riscv_toolchain_env.sh` | 交叉编译器加载（复用 migrate 部署） |
| QEMU | `${RISCV_SKILLS_ROOT}/riscv-migrate/resources/qemu_static_env.sh` | user-static 加载（复用 migrate 部署） |

## 失败回流

| 发现位置 | 回流位置 |
| -------- | -------- |
| 用例失败，定位为迁移缺陷 | `REFLOW_TO_PHASE2` → riscv-migrate 迁移段对应条目（`DONE` 恢复 `START`），修复后重跑本目标直至全过 |
| 用例失败，定位为环境/工具链/驱动问题 | `FIX_IN_PHASE4` → 本技能段内自修（理由写入 report.md 第 4 节） |
| 对比输出不一致（兜底路径） | 同上分流：语义问题回 migrate；驱动/环境问题段内修，修后复测 |
| 覆盖率 < 70% | 不回流；原因与补充计划写入 report.md + `TODO(后续)` |
| 条目集与迁移产物对不上（有条目无产物/有产物无条目） | 建议用户重跑 `riscv-scan`（+ migrate 对应段） |
| verify-runner 返回 `BLOCKED`/`FAILED` | 主 Agent 补充上下文重派；连续 2 次失败则接管亲自执行 |
| 同一目标连续 5 轮修复仍失败 | 协议 9.2 白名单 #5：问用户一次（附推荐选项） |

Subagent 失败处理（不直接询问用户）：主 Agent 检查任务输入是否充分 → 缩小或重新拆分任务 → 恢复原 Subagent 上下文或更换角色 → 主 Agent 必要时接管 → 达到白名单阈值后才询问用户。

## 自主运行原则（本技能子集）

以 `references/scan_result_protocol.md` 第 9 节为共同基底，本技能专属决策：

| 决策点 | 默认行为 |
| ------ | -------- |
| 是否复用自带 benchmark | 探测命中即复用（`BENCHMARK_HIT`），不问"要不要复用"；未命中才自建兜底 |
| 兜底参考侧选 x86 还是 ARM | 都探测，能编哪个用哪个；都不可用时仅跑 RISC-V 侧 + 固定期望值基线 |
| 编译参数另起一套？ | 否：`-march`/`-mabi`/VLEN 沿用 migrate 选定值，保证验证口径与迁移一致 |
| 覆盖率报告要不要做 | 必做，基准/兜底两条路径都做；行覆盖 ≥70% 为达标线 |
| 构建目录落哪 | `<target_dir>/build/` 与 `build-cov/`；不写 `/tmp`、不留仓库根 |
| 失败用例的分流 | 主 Agent 按根因裁决：迁移缺陷 → `REFLOW_TO_PHASE2`；环境/驱动 → `FIX_IN_PHASE4`；不问"要不要回流" |
| gcov/lcov 缺失 | 自主安装（系统包）；装不上时用 gcov 原始输出兜底生成 coverage.txt |
| 工具链/QEMU 不存在 | 自主调用 `prepare_verify_env.sh`（委托 migrate 部署）部署；不问"要不要装" |
| 中间产物清理 | 覆盖率生成后统一清理；清理前核对对象清单，避免误删用户文件 |

**反模式黑名单（本技能）**："自带 benchmark 要不要复用？"（命中即复用）、"覆盖率要不要生成？"（必做）、"用例失败要不要回流？"（按根因分流，不问）、"验证参数和 migrate 不一致行不行？"（必须对齐）、"-march 用什么？"（沿用 migrate 值）、"报告写不写？"（必生成 report.md）。
