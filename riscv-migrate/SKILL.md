---
name: riscv-migrate
description: RISC-V 迁移第二步：条目级迁移 + 工程级验证一体闭环。前置=scan_result.json 已由 riscv-scan 产出（缺失时引导先跑 riscv-scan，不代跑）。迁移段：规划 Subagent 先产出互不重叠任务分组 → 迁移 Subagent 先做必要性分析（误报返回 NO_WORK_NEEDED）再迁移 → 汇编/RVV 条目必过 Reviewer 门禁 → 主 Agent 条目级 QEMU 验证 → 写 DONE + marking。全部条目 DONE 后自动进入验证段（3.x）：完整工程交叉编译 + 并行诊断串行修复（FIX_IN_PHASE3 直接修 / REFLOW_TO_PHASE2 回流条目闭环）+ 产物级 QEMU 对比（-cpu max,vlen=目标VLEN）。向量源默认用 RVV 1.0 intrinsic，intrinsic 表达不出或编不过时降级手写汇编。验证段跑通主流程即迁移完成；迁移后功能验证（benchmark/覆盖率/报告）由 riscv-verify 技能收口。
---

# RISC-V 条目迁移与工程验证（riscv-migrate）

> **架构：主 Agent 编排 + 阶段内动态 Subagent**（迁移段与验证段一体）

主 Agent 读取 `scan_result.json` 中所有 `TODO`/`START` 条目，由迁移规划 Subagent 产出任务分组方案并经主 Agent 审核后，对可分发的任务组分派迁移 Subagent 执行。每个条目内部仍严格按 `必要性分析 → 分流 → 迁移 → 知识库 → 验证` 闭环执行。**全部条目 DONE 后不停留在"迁移完成"，自动进入 3.x 工程级验证**（完整工程编译 + QEMU 运行），确保迁移后的功能正确。

## 技能总图（本技能 = 第 2 步：迁移 + 验证一体）

| # | 技能 | 职责 | 门禁 |
| - | ---- | ---- | ---- |
| 1 | riscv-scan | 扫描迁移点，产出 scan_result.json | **JSON 存在可读 → 才能进本技能** |
| **2（本技能）** | **riscv-migrate** | **条目级迁移（2.x）+ 工程级验证（3.x，全条目 DONE 后自动进入）** | **工程完整构建成功并在 QEMU 跑通主流程 → 可进 riscv-verify** |
| 3 | riscv-verify | 迁移后功能验证（4.x）：benchmark 优先 → 兜底对比 → 覆盖率 → report.md + marking 闭环 | 全部验证目标 report.md/coverage.txt 生成、用例全过 → 验证收口 |

> 跨技能协议（状态字段、门禁、回流、令牌）权威：`references/scan_result_protocol.md`。
>
> 路径约定：`${RISCV_SKILLS_ROOT}` 指各技能目录的共同父目录；未设置该环境变量时按相对本技能的目录结构自行解析。

## 入口前置条件

- `<project_root>/scan_result.json` 存在且可读。**不存在时：引导用户先运行 `riscv-scan` 技能，本技能不代跑扫描**。
- 全部条目已 `DONE` 时（如用户对已迁移工程重跑本技能，或迁移段已完成）：**直接从 3.1 工程级验证开始**，不重做迁移。
- 用户明确只要工程级编译验证时：同样直接从 3.1 开始（未完成条目的可编译性风险由用户承担并在摘要中说明）。
- JSON schema 不一致时自主修补（缺 `status`/`marking` 的条目补默认值 `TODO`/`""`，保留缩进）。

## 迁移点进度（必须，权威源在 `scan_result.json`）

每个条目通过 `status`、`marking` 两个结构化字段同步进度：

- `status`（三态互斥）：`TODO` / `START` / `DONE`
- `marking`（备注/异常一句话）：`status=DONE` 时必填；语汇表见协议 4.4 节
- 不向源码写 `MIGRATE-*` 注释，JSON 是唯一权威源
- **只有主 Agent 可以写入 `scan_result.json`**

## 主 Agent 职责（唯一编排者与状态提交者）

主 Agent 不默认亲自完成全部工作，而是负责：探测工程根目录和技能资源；读取并修复 `scan_result.json` schema；审核规划 Subagent 产出的任务分组方案；给每个任务分配唯一 `task_id`；收集并核验 Subagent 结果；合并代码修改；运行条目级最终验证；更新 `status`/`marking`；输出摘要；决定推进或回流。

> **主 Agent 不得把"Subagent 返回成功"直接等同于"条目 DONE"**。Subagent 只完成被分配的工作单元，不拥有推进权和最终完成认定权。

> **任务拆分与分派由迁移规划 Subagent 专职完成**：主 Agent 只提供条目全集和工程上下文，规划 Subagent 输出互不重叠的任务分组方案，主 Agent 审核后按方案分派，从源头保证同一个文件不会被多个迁移 Subagent 同时操作。规划 Subagent 不可用或方案不满足硬性条件时，主 Agent 按同样的硬性条件自行接管规划职责。

### Subagent 通用约束

- **不修改 `scan_result.json`**：所有 Subagent（含 Reviewer、Worker）均不得直接写入状态文件。
- **不直接向用户提问**：缺少信息时先将问题返回主 Agent，由主 Agent 按自主运行原则处理。
- **不超出分配范围**：只处理任务包内指定的文件与行号范围。
- **只返回"待审查/待验证"**：Subagent 内部使用 `READY_FOR_REVIEW`、`READY_FOR_VERIFY`、`BLOCKED` 等状态，这些状态不写入 `scan_result.json`。

## 动态调度

```text
零个 Subagent：主 Agent 直接完成
一个 Subagent：委托一个明确工作单元
多个 Subagent：处理互不依赖且收益明显的工作流
```

**本技能是例外**：任务拆分与分配默认必须先经过迁移规划 Subagent（或主 Agent 按同样硬性条件接管规划），不允许在没有分组方案的情况下直接并行分派迁移 Subagent。

### 并发上限（保守默认）

- 迁移规划：同一时刻最多 1 个规划 Subagent，产出全量分组方案；
- 写入型迁移：最多 4 个并行 Subagent，且必须依据规划方案的分组，保证写入集合互斥或使用隔离工作区；
- 审查：可与其他互不相关条目的迁移并行；
- 用户明确要求不同并发度时，由主 Agent 在安全边界内覆盖默认值。

## 任务输入协议

主 Agent 应给每个 Subagent 提供明确的任务包，避免其重新探索整个工程或扩大范围。

### 规划任务包

```json
{
  "task_id": "phase2-plan-all",
  "phase": "PHASE_2",
  "role": "MIGRATION_PLANNER",
  "project_root": "/abs/path/project",
  "scan_result_path": "/abs/path/project/scan_result.json",
  "entries": "全部 TODO/START 条目（或直接指向 scan_result.json）",
  "requirements": [
    "按依赖分组规则产出任务组",
    "每个任务组显式列出 write_files",
    "任意两个可并行任务组的 write_files 交集为空",
    "同一文件的所有条目必须划入同一任务组",
    "为每个任务组标注 parallel/serial/main_agent 和工作量估计",
    "只读，不修改任何文件"
  ],
  "acceptance": [
    "每个条目恰好属于一个任务组",
    "返回 PLAN_READY + 结构化分组方案"
  ]
}
```

### 迁移任务包

```json
{
  "task_id": "phase2-src-crc-crc32-c-120-200",
  "phase": "PHASE_2",
  "role": "MIGRATION_WORKER",
  "project_root": "/abs/path/project",
  "scan_result_path": "/abs/path/project/scan_result.json",
  "scope": {
    "file_path": "/abs/path/project/src/crc/crc32.c",
    "start_line": 120,
    "end_line": 200,
    "solver_type": 4
  },
  "allowed_write_paths": [
    "/abs/path/project/src/crc/crc32_riscv.c",
    "/abs/path/project/tests/crc32_riscv_test.c"
  ],
  "read_only_paths": [
    "/abs/path/project/scan_result.json"
  ],
  "requirements": [
    "先做必要性分析：确认误报则不改代码，直接返回 NO_WORK_NEEDED 并附依据",
    "RVV 1.0",
    "补充原始实现与 RISC-V 实现对比测试",
    "涉及指令和扩展时查询知识库"
  ],
  "acceptance": [
    "局部交叉编译通过",
    "返回知识库 file_path/header_path",
    "不得修改 scan_result.json"
  ]
}
```

任务包中的路径列表是能力边界。主 Agent 合并结果时必须检查实际修改是否超出 `allowed_write_paths`。

## 统一结构化返回协议

所有 Subagent 应返回统一结果：

```json
{
  "task_id": "phase2-src-crc-crc32-c-120-200",
  "phase": "PHASE_2",
  "status": "READY_FOR_REVIEW",
  "summary": "已将 SSE CRC 内核迁移为 RVV 1.0 intrinsic 实现",
  "changed_files": [
    "/abs/path/project/src/crc/crc32_riscv.c",
    "/abs/path/project/tests/crc32_riscv_test.c"
  ],
  "commands_run": [
    "riscv64-unknown-linux-gnu-gcc ..."
  ],
  "tests": [
    {
      "name": "crc32-local-build",
      "result": "PASS",
      "evidence": "exit code 0"
    }
  ],
  "knowledge_evidence": [
    {
      "claim": "所用 intrinsic 属于 RVV 1.0",
      "file_path": "...",
      "header_path": "..."
    }
  ],
  "risks": [],
  "blocked_reason": ""
}
```

允许的 Subagent 内部 `status`（不得写入 `scan_result.json`；令牌语义与冻结值见协议第 7 节）：`PLAN_READY` / `NO_WORK_NEEDED` / `TRIVIAL_MACRO_DONE` / `READY_FOR_REVIEW` / `READY_FOR_VERIFY` / `PASS` / `NEEDS_FIX` / `BLOCKED` / `FAILED`。

误报返回示例（迁移 Subagent 必要性分析确认误报）：

```json
{
  "task_id": "phase2-src-crc-crc32-c-120-200",
  "phase": "PHASE_2",
  "status": "NO_WORK_NEEDED",
  "summary": "条目指向的 CRC 分支已含 __riscv 条件编译实现，无需迁移",
  "changed_files": [],
  "commands_run": [],
  "tests": [],
  "knowledge_evidence": [],
  "false_positive_justification": {
    "file_path": "/abs/path/project/src/crc/crc32.c",
    "line_range": "120-200",
    "reason": "该函数已有 #ifdef __riscv 分支并使用 RVV intrinsic，x86 分支在 RV 构建下不参与编译",
    "evidence": "crc32.c:118 #ifdef __riscv；crc32.c:121-198 为 RVV 实现"
  },
  "risks": [],
  "blocked_reason": ""
}
```

主 Agent 复核 `false_positive_justification` 后，将条目以"误报"写入 `marking` 并置 `DONE`；对依据存疑时退回补充或二次分析，不得直接采信。

## 并发与写入安全

- **单一状态提交者**：`scan_result.json` 只能由主 Agent 写入（详见协议第 5 节）。
- **文件独占**：任意两个并行任务的写入集合不得相交（`write_set(task_a) ∩ write_set(task_b) = ∅`），由规划方案保证。
- **隔离工作区**：局部测试和编译使用 `<project_root>/.riscv-migrate/tasks/<task_id>/{build,logs}`。
- **结果合并检查**：合并前至少检查 8 项（越界 / 改 JSON / 覆盖用户未提交修改 / 任务冲突 / 代码风格 / 测试可复现 / 知识库证据 / 误报依据），全表见协议 5.5。

## 2.0 任务规划与分派（本技能入口，规划 Subagent 先行）

```text
主 Agent 读取全部 TODO/START 条目
  → 迁移规划 Subagent（riscv-migration-planner）分析文件与依赖，产出任务分组方案
  → 主 Agent 审核方案（分组完整性、写入集合互斥）
  → 按方案将任务组分为可并行组与串行组
  → 主 Agent 将待处理条目写为 START
  → 分派迁移 Subagent
      └─ Subagent 先做必要性分析
          ├─ 误报 → 返回 NO_WORK_NEEDED + 依据
          └─ 确需迁移 → 迁移 → 查库 → 局部编译
  → 收集迁移结果
  → 主 Agent 复核误报依据，通过则以"误报"标记 DONE
  → 汇编/RVV 条目调用 Reviewer
  → 非 trivial 条目：主 Agent 执行条目级 QEMU 验证 → 通过后写 DONE + marking
  → trivial 条目（仅预处理行改动）：跳过验证，直接 DONE（marking 记 trivial 宏适配）
```

**规划硬性条件**（主 Agent 审核时校验，不满足退回重规划）：

1. 每个条目恰好属于一个任务组；
2. 任意两个标记为 `parallel` 的任务组，其 `write_files` 交集为空；
3. 同一文件的所有条目位于同一任务组。

**依赖分组规则**（规划 Subagent 执行；主 Agent 接管时同样适用）：

下列情况必须进入同一串行任务组：修改同一个源文件 / 头文件 / 构建脚本或链接脚本；依赖同一个尚未确定的公共函数接口；一个条目生成的文件是另一个条目的输入；多个条目属于同一套架构实现并需要整体替换。

下列情况通常可以并行：位于不同模块且没有公共修改文件；独立的 missing_class 目录补齐；不同源文件中的独立 intrinsic/asm 条目；只读知识库查询和代码审查；不同条目的局部测试构建不会写同一输出目录。

## 2.1 分流（条目级别——可由 Subagent 执行，主 Agent 裁决）

按 `solver_type` + 源码特征判断每个条目（完整速查含登记字段见 [references/code_migrate.md](references/code_migrate.md)「分流依据（速查）」）。满足以下**任一**即视为**汇编代码**（走完整闭环）：

1. **文件类型**：`.S` / `.s` / `.asm` 等汇编源文件。
2. **内联汇编**：源文件中含 `__asm__` / `__asm` / `asm volatile`，且迁移点落在该段内。
3. **intrinsic**：含 x86 intrinsic（`_mm_*` / `_mm256_*` / `_mm512_*`）或 ARM NEON intrinsic（`vld1q_*` / `vmlaq_*` / `vst1q_*`）。
4. **架构强绑定 built-in**：含 `__builtin_ia32_*` / `__builtin_neon_*` 等。
5. **`solver_type` 为汇编类**：基础扫描器输出整数——`4`（InlineAsmSolver）/ `1`（IntrinsicsSolver）；并行扫描 Subagent 补充的条目用字符串标签（`InlineAsm` / `Builtin`）。**分流判断必须同时容纳整数与字符串两种形态**（完整映射表见 `${RISCV_SKILLS_ROOT}/riscv-scan/references/project_scan.md`）。

- **汇编代码** → 登记后进入 **2.2 迁移 → 2.3 知识库 → 2.4 验证** 完整子闭环（含 Reviewer 门禁）。
- **非汇编代码**（源码/Shell/宏/Toml、纯 C/C++ 逻辑、标准库调用、无架构绑定）→ 走轻量子流程（仅 2.2 迁移中的代码适配 + 2.4 验证，无 Reviewer 门禁）。

**轻量流程再细分（trivial 条目判定）**——非汇编条目在进入 2.4 前，先按下列判据识别 **trivial 条目**：

- **判据（满足任一即 trivial）**：
  1. 迁移动作仅为**架构宏判定/宏分支**改动——`#ifdef __x86_64__`/`__ARM_ARCH` 加 `__riscv` 分支或调整条件编译逻辑，不改任何表达式与函数体（典型：MacrosSolver 条目里"给平台判定宏加 riscv 值"）；
  2. 仅**头文件包含调整**（增删 `#include`）或仅**类型/编译选项**适配，不引入新逻辑；
  3. 已有 `__riscv` 分支的宏——该条目本来就是误报/已适配（应走必要性分析返回 `NO_WORK_NEEDED`，而不是验证）。
- **trivial 条目免 2.4 条目级验证**：**不编译、不跑 QEMU、不写测试**。判断依据是宏展开的静态语义（改的只是预处理分支选择，可编译性由本技能 3.x 工程级编译整体兜底）。直接由主 Agent 置 `DONE`，`marking` 写 `trivial 宏适配：<具体宏/分支>`。
- **判 trivial 的硬约束**：改动**仅在预处理指令行**（`#if*`/`#ifdef`/`#else`/`#elif`/`#endif`/`#define`/`#include`）。凡需要改动任何 C/C++ 语句行（表达式、函数体、类型定义、初始化器），一律不算 trivial，回到普通轻量流程（局部编译 + 2.4 验证）。
- **疑义从重**：无法确定改动是否仅预处理级 → 按普通轻量流程走（多花一次局部编译，好过漏验证）。宏体内嵌架构相关表达式（如宏展开后是 intrinsic/asm）**不是** trivial，按完整闭环处理。
- **正则速查**（辅助判断，非判据本体）：改动行全部匹配 `^\s*#\s*(if|ifdef|ifndef|elif|else|endif|define|include)\b` → 候选 trivial；再人工确认宏体内无 intrinsic/asm/架构相关表达式。

## 2.2 迁移（按分流结果——可由迁移 Subagent 执行）

**前置必要性分析（必须先做）**：迁移 Subagent 动手修改任何代码前，先判断条目是否真的需要迁移。若确认为扫描误报，**不改任何代码**，直接返回 `NO_WORK_NEEDED` 并附可核验依据（文件、行号、判断理由）。判断要点：

- 条目指向的代码是否已通过条件编译天然支持 RISC-V（如已有 `__riscv` 分支）；
- 是否为死代码、注释掉的代码或不可达平台分支；
- 是否为跨平台兼容宏（字节序、对齐处理）在 RV 上语义本就等价；
- 是否为扫描器对普通内置函数或非架构代码的误识别。

误报条目由主 Agent 复核依据后，以"误报"写入 `marking` 并置 `DONE`，不进入迁移和 QEMU 验证流程；主 Agent 对依据存疑时退回补充或另派 Subagent 二次分析，二次分析结论冲突时按"需要迁移"处理并回流。

**通用要求**（测试先行、`_riscv` 命名、实现策略、状态同步）与**汇编/非汇编/missing_class 子闭环**的完整细则见 [references/code_migrate.md](references/code_migrate.md)。核心实现策略：

- 默认 RVV 1.0 intrinsic + 编译参数（`-O3`、`__restrict`、`__builtin_assume_aligned`）；
- intrinsic 表达不出（如部分 `Zvk*` intrinsic 在 GCC 14.2 缺失）或编译不过时，降级为手写汇编，原因记入 `marking`。

**状态字段同步**：**主 Agent** 在分派任务前将该条目的 `status` 从 `TODO` 改为 `START`；Subagent 不得修改 `scan_result.json`。

## 2.2.5 Reviewer 门禁（汇编/RVV 条目必须）

汇编、inline asm、builtin、RVV intrinsic 等条目的迁移 Subagent 返回 `READY_FOR_REVIEW` 后，主 Agent **必须**召唤 `riscv-code-reviewer` 进行独立审查。Reviewer 只读审查，返回 `PASS`、`NEEDS_FIX` 或 `FAIL`：

- `PASS`：主 Agent 进入 2.4 验证。
- `NEEDS_FIX`：主 Agent 将 Reviewer 发现回流给迁移 Subagent 修复，修复后重新审查。
- `FAIL`：存在严重架构问题，主 Agent 判定是否缩小任务范围或接管修复。

非汇编轻量条目可跳过 Reviewer 门禁：trivial 条目免验证直接 DONE；其余由主 Agent 直接进入 2.4 验证。

## 2.3 知识库/手册查询（汇编条目必走；非汇编条目按需）

**触发条件**：迁移过程中出现任一信号：指令名/扩展名（如 `Zba`/`Zvbb`）、intrinsic（如 `__riscv_*`）、CSR 或 ABI 约束不确定时，**必须**主动查询知识库。查询方式、工具选择规则、失败处理与证据链要求见 [references/code_migrate.md](references/code_migrate.md) 2.3 节。

## 2.4 验证（条目级；主 Agent 必须执行最终 QEMU 验证——**trivial 条目除外**）

每个**非 trivial** 条目迁移完成后，**主 Agent 必须执行条目级交叉编译 + QEMU 静态运行验证**。不能只凭 Subagent 自述认定完成。完整步骤、浮点容差口径与 VLEN 对齐细则见 [references/code_migrate.md](references/code_migrate.md) 2.4 节。

**批量验证（重要提速手段）**：同一任务组的条目由迁移 Subagent 产出**一个**组级测试程序（多个条目的测试用例链接进同一 main，按条目分函数/分节输出），主 Agent 一次编译 + 一次 QEMU 运行 + 一次 diff 完成全组验证；输出不一致时按节定位到具体条目，仅失败条目单独回流。

**通过条件**：编译零错误、输出按口径一致（整数/字节流逐字节一致；浮点在容差内一致）。主 Agent 将该条目从 `START` 改为 `DONE`，并填写 `marking`。

## 迁移段出口（进入验证段的门禁）

所有条目（含 `missing_class`）`status=DONE`；每个 `DONE` 条目 `marking` 非空；每个条目动手前完成必要性分析（误报条目有可核验依据并经主 Agent 复核）；汇编条目经过 2.3 知识库证据 + 2.2.5 Reviewer 门禁 + 2.4 条目级验证；missing_class 条目已参照 `existing_arch_paths` 补齐并接入构建系统；非 trivial 条目完成架构宏替换并通过主 Agent QEMU 验证；trivial 条目（`marking` 含 `trivial 宏适配`）确无验证记录但改动行均为预处理指令。

**满足后不停留在"迁移完成"，自动进入 3.x 工程级验证**（用户明确叫停验证段才跳过，风险写入摘要）。

## 3.1 准备环境（工程级验证开始）

- 一键准备（首次从 `${RISCV_SKILLS_ROOT}/riscv-migrate/resources/` 部署工具链与 QEMU，已存在则复用）：`bash ${RISCV_SKILLS_ROOT}/riscv-migrate/scripts/prepare_verify_env.sh`
- 由技能自动加载 RISC-V 交叉工具链：`bash ${RISCV_SKILLS_ROOT}/riscv-migrate/resources/riscv_toolchain_env.sh` + `source ${RISCV_SKILLS_ROOT}/riscv-migrate/resources/env.sh`
- 同时准备 QEMU user-static：`bash ${RISCV_SKILLS_ROOT}/riscv-migrate/resources/qemu_static_env.sh`
- 工具链与 QEMU 由技能自动部署加载，无需用户手动安装。

## 3.2 编译与修复（并行诊断 → 串行修复）

```text
主 Agent 完整编译并保存完整日志
  → 按模块和类型对错误切片
  → 一个或多个诊断 Subagent 并行分析
  → 主 Agent 汇总根因和依赖顺序
  → 主 Agent 或单个写入型 Subagent 实施一组修复
  → 主 Agent 重新完整编译
  → 重复直到成功
```

**关键约束**：

1. 并行只用于错误分析（诊断 Subagent 只读），不默认用于同时修改工程。
2. 在目标工程里用交叉工具链跑完整构建（如 `make` / `cmake --build`），前缀以 `*_TOOLCHAIN_ROOT/bin` 下实际文件为准（如 `riscv64-unknown-linux-gnu-gcc`）。
3. **修编译错误**：
   - 每轮只根据首个根因或一组互不冲突的根因实施修复；
   - 重新编译必须由主 Agent 统一执行，保证日志和环境一致；
   - 如果发现迁移段遗漏，必须回流对应条目（`REFLOW_TO_PHASE2`），不在验证段绕过状态闭环；
   - 缺什么装什么（系统包 + `${RISCV_SKILLS_ROOT}/riscv-migrate/resources/*.sh`）；
   - `__x86_64__` / `__ARM_ARCH` 等宏残留未替换的，回流迁移段补；
   - 头文件路径、链接库路径、ABI（`lp64d`）等，按工程实际调整。
4. **`-march` 覆盖所用扩展**；常见起点：`-march=rv64gcv_zbb_zbc_zbkb_zvbb_zvbc_zvkb_zvksed_zvkned_zvksh_zvknha_zvkt -mabi=lp64d`，不够再补。
5. 若工程要求静态链接，遵守之。
6. 若任务固定产物名（如 `riscv64_test`），遵守任务说明。
7. 连续 3 次同类型错误未修复才询问用户（白名单 #3）。

### 3.2.5 编译错误诊断 Subagent（按需）

主 Agent 在编译失败后，可召唤 `riscv-build-diagnoser` 对完整构建日志做只读分析（并发上限 3）。诊断 Subagent 将错误按根因聚类，识别首个根因与派生错误，判断是环境问题、构建参数问题、ABI/链接问题还是迁移段遗漏，并给出最小修复建议和回流标注：

- `FIX_IN_PHASE3` → 在验证段内直接修复（编译参数、构建脚本接入等）；
- `REFLOW_TO_PHASE2` → 回流本技能迁移段对应条目（状态保持或恢复为 `START`）。

> 两个令牌值为**冻结字面量**（见协议第 7 节），不得改名。

## 3.3 运行验证（产物级 QEMU 对比；主 Agent 必须执行）

- 用 `qemu-riscv64 -cpu max,vlen=<目标VLEN> <bin>` 跑主流程/集成测试，至少确认主程序可启动、无立即崩溃、关键路径输出与 x86/ARM 侧一致。
- 与 2.4 条目级 QEMU 验证互补：条目级验证保证**单个迁移点**正确；工程级验证保证**整体**可运行。
- **对比口径**：整数/字节流/checksum 逐字节 diff 必须一致；浮点输出用容差对比（`rel_err=1e-9`/`abs_err=1e-12` 量级），差异写入 `marking`；位精确语义（哈希输入、序列化格式）条目除外。
- **VLEN 对齐（必须）**：`-cpu max` 默认 VLEN=128，与目标（如 VLEN=256）不一致。`vlen=` 取值必须与 A 节 #6 选定目标 CPU 时确定的目标 VLEN 一致；同时确认向量 crypto 扩展（Zvbc/Zvk*）在 `-cpu max` 下已使能。
- 完整命令模板与浮点容差细则见 [references/build_and_audit.md](references/build_and_audit.md) 3.3 节。

## 出口条件（进度自检）

迁移段 + 验证段全部达成：工程完整构建无错误；RV 可执行程序可在 QEMU 中跑通主流程。完成后向用户输出一次结构化摘要（构建结果 / 产物路径 / 对比结论），并提示下一步可用 `riscv-verify` 技能做迁移后功能验证（benchmark 优先 + 覆盖率 + 验证报告）。

## Subagent

| Subagent | 角色 | 读写属性 |
| -------- | ---- | -------- |
| [`riscv-migration-planner`](agents/riscv-migration-planner.md) | 读取全部 TODO/START 条目，产出互不重叠的任务分组方案（含 `write_files`、执行方式、工作量估计）；定义在本技能 `agents/` | 只读、只规划不执行 |
| [`riscv-migration-worker`](agents/riscv-migration-worker.md) | 执行分配迁移条目（必要性分析 → 分流、迁移、查库）；定义在本技能 `agents/` | 写入（指定文件范围内） |
| [`riscv-code-reviewer`](agents/riscv-code-reviewer.md) | 审查汇编/RVV 迁移代码的向量化正确性、ABI、对齐、指令选择；定义在本技能 `agents/` | 只读 |
| [`riscv-build-diagnoser`](agents/riscv-build-diagnoser.md) | 分析工程级完整构建日志，按根因聚类编译错误，给出 `FIX_IN_PHASE3`/`REFLOW_TO_PHASE2` 标注（3.2.5）；定义在本技能 `agents/` | 只读 |

## 脚本与资源

| 资产 | 路径 | 用途 |
| ---- | ---- | ---- |
| 迁移细则 + 指令映射速查表 | [references/code_migrate.md](references/code_migrate.md) | 2.2/2.3/2.4 实施细则、x86/ARM → RVV/扩展映射 |
| 工程级验证细则 | [references/build_and_audit.md](references/build_and_audit.md) | 3.2-3.3 全细则、浮点容差、VLEN 对齐 |
| 验证环境一键准备 | `${RISCV_SKILLS_ROOT}/riscv-migrate/scripts/prepare_verify_env.sh` | 部署工具链 + QEMU |
| RISC-V 工具链 | `${RISCV_SKILLS_ROOT}/riscv-migrate/resources/riscv_toolchain_env.sh` | 交叉编译器加载 |
| QEMU | `${RISCV_SKILLS_ROOT}/riscv-migrate/resources/qemu_static_env.sh` | user-static 加载 |
| 知识库查询 | `${RISCV_SKILLS_ROOT}/riscv-migrate/scripts/run_query.sh` | MCP 客户端 |

## 失败回流

| 发现位置 | 回流位置 |
| -------- | -------- |
| 规划分组不完整或写入集合相交 | 退回规划 Subagent 重规划；连续不可用时主 Agent 接管 |
| 必要性分析确认误报 | 直接 `NO_WORK_NEEDED`，不进入迁移 |
| 主 Agent 对误报依据存疑 | 退回原 Subagent 补充依据，或另派 Subagent 二次分析 |
| Reviewer 发现 RVV/ABI 高危问题 | 2.2 修复循环 |
| 条目 QEMU 不一致 | 2.2/2.4 修复循环（连续 5 轮不一致才问用户） |
| 3.2 完整编译发现架构迁移遗漏 | 迁移段对应条目（`REFLOW_TO_PHASE2`；状态保持或恢复为 `START`） |
| 3.2 发现 `__x86_64__`/`__ARM_ARCH` 宏残留 | 回流迁移段补 |
| 产物输出不一致 | 回流迁移段修复，修复后回到 3.3 复测 |
| 扫描条目集冲突或遗漏 | 建议用户重跑 `riscv-scan` |

Subagent 失败处理（不直接询问用户）：主 Agent 检查任务输入是否充分 → 缩小或重新拆分任务 → 恢复原 Subagent 上下文或更换角色 → 主 Agent 必要时接管 → 达到白名单阈值后才询问用户。恢复原 Subagent 优先于新建；只有范围划分错误、类型不匹配、连续不可用结果、需要独立审查时才更换。

## 自主运行原则（本技能子集）

以 `references/scan_result_protocol.md` 第 9 节为共同基底，本技能专属决策（A 节核心项）：

| # | 决策点 | 默认值 / 默认行为 |
| - | ------ | ------------------ |
| 4 | 汇编形式（RVV asm vs intrinsic） | 默认 RVV 1.0 intrinsic；intrinsic 表达不出或编不过时降级手写汇编（原因记入 `marking`） |
| 5 | 单元测试缺失 | **agent 自己补**：边界值 + 随机 + checksum 三类各至少一组；向量条目另须覆盖"尾部不足一条向量"用例；不要问"测试怎么写" |
| 6 | 目标 CPU / VLEN（编译与 QEMU 对齐） | 用户指定 > 「VLEN=256 通用目标」（默认）> 目标部署芯片匹配 > sifive-p450/sifive-u74。**不要用 `generic`**。选定后同时确定目标 VLEN（QEMU 侧 `-cpu max,vlen=<目标VLEN>` 显式对齐） |
| 7 | `-march` 起点 | `rv64gcv_zbb_zbc_zbkb_zvbb_zvbc_zvkb_zvksed_zvkned_zvksh_zvknha_zvkt`；编译报错或目标芯片不支持时**自主裁剪/追加**扩展，不询问 |
| 7b | `-mabi` | 含浮点且 `-march` 含 `D` → `lp64d`（默认）；纯整数 → `lp64`；工程已声明 ABI → 跟随工程 |
| 8 | `marking` 内容 | 记录验证结论与差异说明；**禁止跨架构运行时间对比结论** |
| 12 | QEMU 对比失败修复 | 差异行 ≤3：自主改 RISC-V 侧；>3：自主定位修复；循环直到一致（连续 5 轮不一致才问） |
| 12b | trivial 条目裁决 | 非汇编条目先判 trivial（判据见 2.1）；**疑义从重**；批量宏条目可合并裁决 |
| 13 | 知识库查询失败 | 更具体条件重试 2 次 → 降级参考 code_migrate.md 默认映射；都失败再问 |
| 15 | 工具链/QEMU 不存在 | 自主调用 `prepare_verify_env.sh` 部署；不要问"要不要装" |
| 11 | 工程级编译错误处理 | 自主诊断（看错误码）→ 自主修复（装系统包、调 march、追加 include、`-mabi` 切换等）→ 不在中途汇报"修了一个错误要不要继续"（连续 3 次同类型失败才向用户汇报） |

**反模式黑名单（本技能）**："用汇编还是 intrinsic？"（#4）、"测试怎么写？"（#5）、"用什么 -march？"（#7）、"RVV 用什么 LMUL？"（自己按数据宽度算）、"找不到 scan_result.json 怎么办？"（引导先跑 riscv-scan）、"工程里同时有 x86 和 ARM 迁哪个？"（默认都迁）、"编译错了要不要继续修？"（#11）、"工具链没装要不要装？"（#15）、"迁移完了要不要做工程级验证？"（默认自动进入 3.x）。
