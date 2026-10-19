# scan_result.json 跨技能协议（scan_result_protocol）

> **本文档的定位**：`scan_result.json` 是技能组（`riscv-scan` / `riscv-migrate` / `riscv-verify`）之间**唯一**的状态衔接载体。本文档是它的**跨技能协议权威**：状态字段语义、单一写入者约束、跨技能门禁与回流路径、Subagent 返回令牌、共用自主运行条款，一律以本文档为准。
>
> - 条目完整 Schema（`suggestion_class[]` / `missing_class[]` 全字段）：`${RISCV_SKILLS_ROOT}/riscv-scan/references/project_scan.md`
> - 各技能自己的流程细则：各自 `SKILL.md` 与技能内 references

**令牌与阶段编号约定**：返回令牌与 `marking` 语汇中的 `PHASE_*` / `阶段N` 字样为**冻结值**（见第 7 节），命名与技能步骤一一对应：`PHASE_1` = riscv-scan、`PHASE_2` = riscv-migrate 迁移段（2.x）、`PHASE_3` = riscv-migrate 验证段（3.x）、`PHASE_4` = riscv-verify（4.x）。语义按此映射读作对应技能/阶段段。

---

## 1. 技能组总图与门禁

| # | 技能 | 职责 | 产出 / 状态动作 | 门禁（满足才能进入下一技能） |
| - | ---- | ---- | -------------- | --------------------------- |
| 1 | `riscv-scan` | 扫描 x86/ARM 工程全部待迁移点 | `<project_root>/scan_result.json`（全部条目 `status=TODO`） | `scan_result.json` 存在、可读、条目盘点清楚 |
| 2 | `riscv-migrate` | 条目级迁移（2.x）：规划分组 → 必要性分析 → 分流 → 迁移 → 知识库 → QEMU 验证；**全条目 DONE 后自动进入工程级验证段（3.x）**：交叉编译修复 + QEMU 运行验证 | `*_riscv` 源码 + 条目 `TODO→START→DONE`（`marking` 填写）+ RV 可执行程序 | **产物完整构建成功并在 QEMU 中跑通主流程** |
| 3 | `riscv-verify` | 迁移后功能验证（4.x）：benchmark 优先探测 → 自带测试套件 QEMU 全量运行 / 兜底自建对比测试 → 覆盖率分析 → 验证报告 | `<project_root>/test/<验证目标名>/{report.md,coverage.txt}` + 用例统计 + `marking` 验证结论更新 | 全部验证目标 report.md 与 coverage.txt 生成、用例全过（失败已闭环或已说明环境理由） |

```text
门禁链（严格串行，不得越级）：
scan 产 JSON → 才能进 migrate
migrate 全条目 DONE → 自动进入 migrate 验证段（3.x，不停留不问询）
migrate 验证段跑通主流程 → 才能进 verify（迁移后功能验证）
```

技能内可并行，不代表技能之间可越级并行。每个技能也**可以独立调用**（用户只要其中一步时），此时仍必须满足对应入口前置条件（见各技能 SKILL.md「入口前置条件」）。

---

## 2. 文件与顶层结构

- **路径固定**：`<project_root>/scan_result.json`（`project_root` 为被迁移工程根目录）。
- **顶层字段**：`target` / `suggestion_class_count` / `missing_class_count` / `suggestion_class[]` / `missing_class[]`——完整 Schema 见 `${RISCV_SKILLS_ROOT}/riscv-scan/references/project_scan.md`（唯一 schema 权威）。
- **运行时隔离目录**（写路径约定，目录名冻结）：`<project_root>/.riscv-migrate/tasks/<task_id>/{build,logs}`——任务独立的局部编译与日志输出，避免并行任务互相覆盖。
- **验证产物目录**（riscv-verify 写路径约定，目录名冻结）：`<project_root>/test/<验证目标名>/`——功能验证产物（`report.md` / `coverage.txt` / 运行日志 / 兜底驱动源）统一落位，构建子目录（`build/`、`build-cov/`）也在其中；规范见 `${RISCV_SKILLS_ROOT}/riscv-verify/SKILL.md`「验证产物落位总则」。

---

## 3. 条目字段（跨技能共用部分）

每个条目（`suggestion_class[]` 与 `missing_class[]`）除定位字段外，跨技能共用的关键字段：

| 字段 | 取值 | 语义 |
| ---- | ---- | ---- |
| `solver_type` | 整数 `1`（IntrinsicsSolver）/ `3`（MacrosSolver）/ `4`（InlineAsmSolver），或字符串标签（`InlineAsm` / `Builtin`，来自并行扫描 Subagent 补充） | migrate 技能 2.1 分流依据。**读取代码必须同时容纳整数与字符串两种形态**；未知值回退源码特征分流 |
| `status` | `TODO` / `START` / `DONE` | 见第 4 节 |
| `marking` | string | 跨技能信号语汇，见第 4 节 |

**归一化约定**（scan 产出时主 Agent 负责，后续技能读取时容错）：扫描器原始输出 `status` 为小写 `"todo"`；主 Agent 写入前归一化为大写。读取旧文件时状态匹配**大小写不敏感**。

---

## 4. 状态字段规范（status / marking）

迁移进度由 `scan_result.json` 中每个条目的 `status`、`marking` 两个结构化字段维护，**权威源在 JSON，不在源码**。三态**互斥**（同一时刻只能有一个）；`status=DONE` 时 `marking` 必填。

### 4.1 status 三态与写入者

| `status` | 含义 | 何时设置 | 谁设置 | `marking` |
| -------- | ---- | -------- | ------ | --------- |
| `TODO` | 未处理 | scan 技能产出（默认值） | 主 Agent | 否 |
| `START` | 开始迁移 | migrate 技能分派任务前 | 主 Agent | 否 |
| `DONE` | 迁移完成 | migrate 技能 QEMU 验证通过后；或误报/trivial 复核后；verify 技能回流重验通过后更新 `marking` | 主 Agent | **是** |

migrate 验证段与 verify 技能回流时可把条目从 `DONE` 恢复为 `START`（见第 6 节）。

### 4.2 状态写入唯一路径

```text
主 Agent：TODO → START         （migrate 分派任务前）
规划 Subagent：返回 PLAN_READY + 分组方案（主 Agent 审核后才分派）
迁移 Subagent：返回 NO_WORK_NEEDED / READY_FOR_REVIEW / READY_FOR_VERIFY
Reviewer：返回 PASS / NEEDS_FIX / FAIL（asm/RVV 条目）
主 Agent：复核误报依据，或运行 QEMU 验证
主 Agent：START → DONE + marking（验证通过后；误报条目 marking 记"误报 + 依据"）
verify 主 Agent：功能验证失败且定位为迁移缺陷 → DONE 恢复为 START（回流 migrate 修复）
verify 主 Agent：重验通过 → START → DONE + 更新 marking（验证结论语汇见 4.4）
```

### 4.3 jsonc 示例

```jsonc
// scan 产出（主 Agent 归一化后）：
{
  "suggestion_class": [
    {
      "file_path": "/abs/path/src/crc/crc32.c",
      "start_line": 120,
      "end_line": 200,
      "solver_type": 4,         // ← 扫描器输出整数枚举（映射表见 project_scan.md）
      "status": "TODO",
      "marking": ""
    }
  ]
}

// migrate 分派前：{ "status": "START", "marking": "" }

// migrate QEMU 验证通过后：
{
  "status": "DONE",
  "marking": "无异常"
}

// verify 功能验证后（追加验证结论）：
{
  "status": "DONE",
  "marking": "无异常；验证通过（benchmark）：crc32 自带单测，共 24 条用例，通过 24 条，行覆盖 87%"
}
```

### 4.4 `marking` 跨技能信号语汇

`marking` 是**技能间传递信号**的通道，下游技能按下列固定语汇识别：

| 语汇（固定短语） | 写入者 | 读者 / 触发的动作 |
| ---------------- | ------ | ----------------- |
| `无异常` | migrate 主 Agent | 汇总统计 |
| `语义差异：<具体点>，已通过测试规避` | migrate 主 Agent | migrate 验证段 / verify 运行时关注对应用例 |
| `trivial 宏适配：<具体宏/分支>` | migrate 主 Agent | migrate 验证段编译兜底，不再验证 |
| `误报：<依据>` | migrate 主 Agent | 条目关闭 |
| `TODO(后续)：<具体项>` | migrate / verify 主 Agent | 遗留项清单 |
| `验证通过（benchmark）：<名称/目标>，共 N 条用例，通过 M 条` | verify 主 Agent | 功能验证结论留痕；汇总统计 |
| `验证通过（对比）：<目标> 输出一致，行覆盖 X%` | verify 主 Agent | 功能验证结论留痕；汇总统计 |
| `验证回流：<原因>，已修复重验通过` | verify 主 Agent | 回流过程留痕（与上面两条按条目实际情形组合） |

> **不要**在源码里写 `// [MIGRATE-*]` 注释——所有状态信息以 `scan_result.json` 为唯一权威源。

---

## 5. 单一写入者与并发安全

### 5.1 单一状态提交者

`scan_result.json` **只能由主 Agent 写入**（每个技能的主 Agent 会话各自唯一；同一时刻同一工程只应有一个技能会话在写）。

- `riscv-code-reviewer`：返回建议的状态回流内容，不直接编辑 JSON；
- 所有 Worker 类 Subagent（含 verify-runner）：不接触 JSON；
- Subagent 内部状态（`READY_FOR_REVIEW` 等）**不得写入** `scan_result.json`。

### 5.2 Subagent 通用约束

- **不直接向用户提问**：缺少信息时先将问题返回主 Agent，由主 Agent 按自主运行原则处理。
- **不超出分配范围**：只处理任务包内指定的文件与行号范围。

### 5.3 文件独占（migrate 技能写入型任务）

写入型任务执行前必须声明 `allowed_write_paths`。任意两个并行任务的写入集合不得相交：

```text
write_set(task_a) ∩ write_set(task_b) = ∅
```

migrate 技能的写入互斥由迁移规划 Subagent 的分组方案保证，主 Agent 审核时校验三条硬性条件：

1. 每个条目恰好属于一个任务组；
2. 任意两个标记为 `parallel` 的任务组，其 `write_files` 交集为空；
3. 同一文件的所有条目位于同一任务组。

公共头文件、构建脚本、链接脚本和统一测试入口默认视为共享资源，必须串行修改。

### 5.4 隔离工作区

局部测试和编译使用任务独立输出目录（目录名冻结）：

```text
<project_root>/.riscv-migrate/tasks/<task_id>/build/
<project_root>/.riscv-migrate/tasks/<task_id>/logs/
```

verify 技能的验证产物与构建隔离目录统一在其验证产物目录内：`<project_root>/test/<验证目标名>/{build,build-cov}/`。多个 verify-runner 并行时，各自只写自己的 `<验证目标名>/` 目录。

### 5.5 结果合并检查（主 Agent 合并前至少检查）

1. 实际修改路径是否越界（超出 `allowed_write_paths`）；
2. 是否修改了 `scan_result.json`；
3. 是否覆盖用户原有未提交修改；
4. 是否与已合并任务冲突；
5. 是否保留现有代码风格和构建约定；
6. 测试结果是否可复现；
7. 知识库证据是否覆盖关键架构结论；
8. `NO_WORK_NEEDED` 的误报依据是否足以支撑结论。

---

## 6. 跨技能回流表

| 发现位置 | 回流位置 | 动作 |
| -------- | -------- | ---- |
| migrate：扫描候选冲突或遗漏 | scan 合并步骤（或建议重扫） | 条目集不完整时建议用户重跑 `riscv-scan` |
| migrate：规划分组不完整或写入集合相交 | 退回规划 Subagent 重规划 | 连续不可用时主 Agent 按硬性条件接管 |
| migrate：必要性分析确认误报 | 直接 `NO_WORK_NEEDED`，不进入迁移 | 主 Agent 复核后 DONE（`marking` 记误报） |
| migrate：Reviewer 发现 RVV/ABI 高危问题 | 回 2.2 修复循环 | `NEEDS_FIX` 回流原迁移 Subagent |
| migrate：条目 QEMU 不一致 | 2.2/2.4 修复循环 | 连续 5 轮不一致才问用户 |
| **migrate 验证段**：完整编译发现架构迁移遗漏 | **迁移段对应条目** | 状态保持或恢复为 `START`，诊断标注 `REFLOW_TO_PHASE2`；不得在验证段绕过状态闭环 |
| **verify**：benchmark/用例失败，定位为**迁移缺陷** | riscv-migrate 迁移段对应条目（2.x） | 状态恢复 `START`，修复后重跑直至全过；标注 `REFLOW_TO_PHASE2` |
| **verify**：用例失败，定位为**测试环境/构建参数问题** | verify 段内自修 | `FIX_IN_PHASE4`，说明理由，不回流 |

---

## 7. Subagent 返回令牌总表（**值冻结，禁止改名**）

所有令牌值均为**冻结值**（调整语义描述时不得改值），agent 定义与既有会话数据都按字面匹配：

| 令牌 | 返回者 | 含义（按技能语义） |
| ---- | ------ | ------------------ |
| `PLAN_READY` | 迁移规划 Subagent | 产出任务分组方案，等待主 Agent 审核（migrate） |
| `NO_WORK_NEEDED` | 迁移 Subagent | 必要性分析确认误报，无需迁移（附可核验依据；migrate） |
| `TRIVIAL_MACRO_DONE` | 迁移 Subagent | 轻量条目确认为 trivial 宏适配（仅预处理指令行改动），免验证；主 Agent 复核改动行清单后直接 DONE（migrate） |
| `READY_FOR_REVIEW` | 迁移 Subagent | 修改完成，等待 Reviewer 独立审查（migrate） |
| `READY_FOR_VERIFY` | 迁移/诊断 Subagent | 修改和局部检查完成，等待主 Agent 最终验证（migrate） |
| `PASS` | Reviewer / verify-runner | 审查任务通过（migrate）；单验证目标用例全过（verify） |
| `NEEDS_FIX` | Reviewer | 存在明确可修复问题，回流原任务（migrate） |
| `FAIL` | Reviewer | 严重架构问题，主 Agent 缩小范围或接管（migrate） |
| `BLOCKED` | 任意 Subagent | 当前范围内无法继续，需主 Agent 补充上下文或调整任务 |
| `FAILED` | 任意 Subagent | 执行失败，无可合并结果 |
| `FIX_IN_PHASE3` | 构建 diagnoser | 该错误在 migrate 验证段（3.x）内直接修复，不回流 |
| `REFLOW_TO_PHASE2` | 构建 diagnoser / verify 诊断 | 需修改原始迁移代码，回流 migrate 迁移段（2.x）对应条目 |
| `BENCHMARK_HIT` | verify 探测执行者（主 Agent 或 runner） | 工程自带 benchmark/测试套件命中，走 verify 基准路径（4.3） |
| `BENCHMARK_MISS` | verify 探测执行者（主 Agent 或 runner） | 未命中，走 verify 兜底自建对比测试路径（4.4） |
| `FIX_IN_PHASE4` | verify 诊断 / 主 Agent | 该问题在 riscv-verify 段（4.x）内直接修复（测试驱动、构建参数、报告类），不回流 |

> `FIX_IN_PHASE3` / `REFLOW_TO_PHASE2` / `FIX_IN_PHASE4` 中的 "PHASE3"/"PHASE2"/"PHASE4" 按命名约定分别读作「migrate 技能验证段（3.x）」/「migrate 技能迁移段（2.x）」/「riscv-verify 技能（4.x）」。**不要**"顺手"改名——agent 定义（`agents/riscv-build-diagnoser.md` 等）与既有会话数据都按字面匹配。

---

## 8. 主流程状态机（按技能标注）

```text
resolve_project_root
  ↓
【riscv-scan】PHASE_1_SCAN
  ├─ direct_scan (${RISCV_SKILLS_ROOT}/riscv-scan/scripts/run_scan.sh)
  └─ optional_parallel_scan_workers
  ↓
merge_and_write_scan_result (主 Agent)
  ↓
【riscv-migrate】PHASE_2_MIGRATE
  ↓
migration planner: build task groups (write_files 互斥, riscv-migration-planner)
  ↓
主 Agent: review plan (三条硬性条件)
  ↓
for each runnable group:
  主 Agent: TODO → START
  dispatch migration worker(s)
  worker: 必要性分析
    ├─ false positive → NO_WORK_NEEDED → 主 Agent 复核 → DONE (marking=误报)
    └─ need migration → collect results
  review if required (riscv-code-reviewer)
  main-agent QEMU verify
  主 Agent: START → DONE + marking
  ↓
all entries DONE?
  ├─ no → continue migrate
  └─ yes
       ↓
【riscv-migrate 验证段】PHASE_3_BUILD
  ↓
full build (主 Agent)
  ├─ failed → parallel diagnose (build-diagnoser) → serial fix → rebuild
  │            （FIX_IN_PHASE3 直接修 / REFLOW_TO_PHASE2 回 migrate 条目）
  └─ passed
       ↓
full QEMU/integration verify (主 Agent, vlen 对齐)
  ↓
【riscv-verify】PHASE_4_FUNCTIONAL_VERIFY
  ↓
主 Agent: 校验全条目 DONE + 盘点验证目标 (test/<验证目标名>/)
  ↓
benchmark 探测 → BENCHMARK_HIT（4.3 基准路径）/ BENCHMARK_MISS（4.4 兜底路径）
  ↓
per target（可派 verify-runner Subagent）:
  交叉编译（-march/-mabi/VLEN 沿用 migrate 选定值）
  → QEMU 全量运行 + 用例统计
  → 失败分流：迁移缺陷 REFLOW_TO_PHASE2（条目恢复 START，修复重跑）/ 其他 FIX_IN_PHASE4
  → --coverage 重编 + gcov/lcov → coverage.txt（行覆盖 ≥ 70%）
  → report.md
  ↓
主 Agent: status/marking 闭环校验 + 验证结论写入 marking
  ↓
final summary
```

---

## 9. 共用自主运行条款（技能组通用）

> 各技能 SKILL.md 的「自主运行原则」以本节为共同基底，另附各自技能专属决策项。**Subagent 不得直接向用户提问。**

### 9.1 共用自主默认

| 决策点 | 默认行为 |
| ------ | -------- |
| 目标工程根目录 | 当前工作目录；无源码则向上找最近的 `CMakeLists.txt` / `Makefile` / `meson.build` / 含 `.c`/`.cpp` 的目录；用户显式指定则用指定值 |
| `scan_result.json` 路径 | `<目标工程根>/scan_result.json`，不另选路径 |
| 已存在 `scan_result.json` | 不重扫、不覆盖，直接读取；用户明确要求重扫才覆盖（scan 技能）。**其余技能读不到该文件时，引导用户先运行 `riscv-scan`，不代跑** |
| JSON schema 不一致 | 自主修补：缺 `status`/`marking` 的条目补默认值 `TODO`/`""`，写回时保留缩进 |
| 报告时机 | 只在**每个技能流程结束时**输出一次结构化摘要（条目数 / 变更文件 / 产物路径 / 阻塞项；并行阶段增加 Subagent 调度统计）；用户要求"详细日志"才细化；用户主动问进度时直接汇报（不属于询问许可） |
| 错误汇报时机 | 真正不可恢复的错误（制品源不可达 / 所有编译器都不支持 / JSON schema 无法修补 / 用户输入来源空）才向用户汇报；可恢复的一律自助修复 |
| 并发上限 | 只读扫描 ≤4；迁移规划同一时刻 1 个；写入型迁移 ≤4；诊断 ≤3；写入修复同一时刻 1 个；verify-runner ≤4（各占一个验证目标目录）。用户明确要求时在安全边界内覆盖 |
| 配置读取 | 环境变量 > 技能根 `config.env` > 脚本内置默认（模板 `config.env.example`） |
| 验证产物目录（verify） | `<project_root>/test/<验证目标名>/`；不写 `/tmp`，不在仓库根留构建目录 |

### 9.2 共用白名单（真正可以问用户的场景）

只有以下场景**可以**问用户一次，且应给出明确推荐选项：

1. 用户 prompt 完全没指明目标工程，**且**当前目录无任何源码文件（根目录探测失败）；
2. migrate：某条目 5 轮 QEMU 对比仍不一致（修复循环超出阈值）；
3. migrate 验证段：编译连续 3 个同类错误未能修复；
4. 制品源不可达 **且** 无离线制品包（`prepare_verify_env.sh` 失败）；
5. verify：某验证目标连续 5 轮修复后用例仍失败（对齐条目级阈值）。

### 9.3 反模式黑名单（共用）

- ❌ "找不到 `scan_result.json`，怎么办？" → 非 scan 技能：引导先跑 `riscv-scan`；scan 技能：自己跑扫描
- ❌ "要不要重扫？" → 默认不重扫
- ❌ "用几个 Subagent 并行？" → 主 Agent 按工作量与依赖关系自主决策
- ❌ "工程里同时有 x86 和 ARM 实现，迁哪个？" → 默认两个都迁，按文件路径一一处理
- ❌ 不可逆操作（删除/覆盖/重扫）前不自检——先核对对象，避免误删用户未纳入迁移的源码
- ❌ "自带 benchmark 要不要复用？"（verify）→ 探测命中即复用（`BENCHMARK_HIT`），未命中才自建
- ❌ "覆盖率报告要不要生成？"（verify）→ 必做，两条路径都做

---

## 10. 文档与脚本索引

| 资产 | 路径（`${RISCV_SKILLS_ROOT}` 为技能目录的共同父目录） | 用途 |
| ---- | ---------------------------------------- | ---- |
| 条目 Schema 权威 | `${RISCV_SKILLS_ROOT}/riscv-scan/references/project_scan.md` | `scan_result.json` 全字段、solver_type 枚举、扫描器约定 |
| 跨技能协议（本文档） | 各技能内 `references/scan_result_protocol.md`（主本在 riscv-scan） | 状态机/门禁/令牌/回流；技能组副本字节一致 |
| 扫描技能 | `${RISCV_SKILLS_ROOT}/riscv-scan/SKILL.md` + `${RISCV_SKILLS_ROOT}/riscv-scan/references/project_scan.md` | 扫描流程、条目 Schema 约定 |
| 迁移技能 | `${RISCV_SKILLS_ROOT}/riscv-migrate/SKILL.md` + `${RISCV_SKILLS_ROOT}/riscv-migrate/references/code_migrate.md` | 迁移段流程、指令映射速查表 |
| 迁移技能验证段 | `${RISCV_SKILLS_ROOT}/riscv-migrate/SKILL.md` 3.x + `${RISCV_SKILLS_ROOT}/riscv-migrate/references/build_and_audit.md` | 工程级编译修复细则 |
| 功能验证技能 | `${RISCV_SKILLS_ROOT}/riscv-verify/SKILL.md` + `${RISCV_SKILLS_ROOT}/riscv-verify/references/verify_functional.md` | benchmark 探测、基准/兜底路径、覆盖率、报告规范 |
| 扫描入口 | `${RISCV_SKILLS_ROOT}/riscv-scan/scripts/run_scan.sh` | 基础扫描（Python 源码引擎，自动装依赖；归属 riscv-scan） |
| 知识库查询 | `${RISCV_SKILLS_ROOT}/riscv-migrate/scripts/run_query.sh` / `query.py` | MCP 知识库客户端（归属 riscv-migrate） |
| 验证环境准备（migrate） | `${RISCV_SKILLS_ROOT}/riscv-migrate/scripts/prepare_verify_env.sh` | 部署 RISC-V 工具链与 QEMU user-static（归属 riscv-migrate） |
| 验证环境准备（verify） | `${RISCV_SKILLS_ROOT}/riscv-verify/scripts/prepare_verify_env.sh` | 委托 riscv-migrate 部署工具链/QEMU + 检查 gcov/lcov（归属 riscv-verify） |
| benchmark 探测辅助 | `${RISCV_SKILLS_ROOT}/riscv-verify/scripts/probe_benchmark.sh` | 只读探测工程自带测试/benchmark（归属 riscv-verify） |
| 配置 | 各技能根 `config.env`（模板 `config.env.example`） | 凭据 / 制品源覆盖；`CONFIG_FILE` 环境变量可指向共享文件 |
| Subagent 定义 | 各技能内 `agents/`（scan-worker→riscv-scan；planner/worker/reviewer/diagnoser→riscv-migrate；verify-runner→riscv-verify） | Subagent 定义随技能分发 |
