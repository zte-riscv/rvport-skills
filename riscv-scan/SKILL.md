---
name: riscv-scan
description: RISC-V 迁移第一步：扫描工程迁移点。盘点 x86/ARM 工程中全部架构相关待迁移点（汇编、intrinsic、架构宏、架构分支源码、缺失架构目录），产出 scan_result.json。无前置条件，是 riscv-migrate 技能的入口。基础扫描器 + 可选并行扫描 Subagent → 主 Agent 合并去重统一写入。
---

# RISC-V 工程扫描（riscv-scan）

> **架构：主 Agent 编排 + 阶段内动态 Subagent**

面向 **x86 或 ARM** 工程，扫描**全部**架构相关待迁移点（汇编、intrinsic、架构宏、架构分支源码等），产出 `<project_root>/scan_result.json`。

## 技能组总图（本技能 = 第 1 步）

| # | 技能 | 职责 | 门禁 |
| - | ---- | ---- | ---- |
| **1（本技能）** | **riscv-scan** | **扫描迁移点，产出 scan_result.json** | **JSON 存在、可读、条目盘点清楚 → 可进 riscv-migrate** |
| 2 | riscv-migrate | 条目级迁移（2.x）+ 工程级验证（3.x，全条目 DONE 后自动进入） | 产物构建跑通、QEMU 跑通主流程 → 可进 riscv-verify |
| 3 | riscv-verify | 迁移后功能验证（4.x）：benchmark 优先 → 兜底对比 → 覆盖率 → report.md + marking 闭环 | 全部验证目标 report.md/coverage.txt 生成、用例全过 → 验证收口 |

> 跨技能协议（状态字段、门禁、回流、令牌）权威：[`references/scan_result_protocol.md`](references/scan_result_protocol.md)。**只有主 Agent 可以写入 `scan_result.json`**。

## 入口前置条件

- 无（本技能是流程起点）。目标工程根目录探测失败时按「自主运行原则」处理。

## 扫描执行（1.1）

1. 在**目标工程根目录**（用户指定或当前仓库根）固定输出 `<project_root>/scan_result.json`。
2. **若 `scan_result.json` 已存在**：视为已完成，**不要**重跑脚本，直接读该文件（除非用户明确要求重新扫描——先备份或删除再扫）。
3. **若不存在**：

   **第一步：运行基础扫描**

   > 路径约定：`${RISCV_SKILLS_ROOT}` 指各技能目录的共同父目录；未设置该环境变量时按相对本技能的目录结构自行解析。

   - 推荐（自动装依赖）：`${RISCV_SKILLS_ROOT}/riscv-scan/scripts/run_scan.sh <project_root> -o <project_root>/scan_result.json`
   - 兜底（手动）：`python3 -m pip install -r ${RISCV_SKILLS_ROOT}/riscv-scan/scripts/requirements.txt && python3 ${RISCV_SKILLS_ROOT}/riscv-scan/scripts/riscv_scan_src/riscv_scan.py <project_root> -o <project_root>/scan_result.json`

   扫描引擎为仓库自带 **Python 源码**（`riscv_scan_src/`，平台无关、可审计；无预编译二进制依赖），依赖缺失时 run_scan.sh 自动安装。

   **第二步：评估是否需要补充并行扫描**

   主 Agent 在基础扫描完成后，根据工程规模和架构复杂度判断是否需要补充扫描 Subagent（并发上限 4，只读）：

   - 工程文件较少或扫描器覆盖明确 → 无需 Subagent，直接进入合并步骤。
   - 存在多个架构（x86 + ARM 并存）或多个独立目录 → 可派发以下只读扫描 Subagent：
     - x86/intrinsic 扫描 Subagent；
     - ARM/NEON 扫描 Subagent；
     - 架构宏扫描 Subagent；
     - 构建与缺失目录扫描 Subagent。

   **第三步：合并与去重**

   主 Agent 合并基础扫描结果与各 Subagent 返回的候选条目，按以下键去重：

   ```text
   class_type + file_path/missing_path + start_line + end_line + solver_type
   ```

   **重叠裁决**（去重键不同但行区间相交的条目）：

   - **同类型条目区间相交**（如两个 Subagent 对同一循环返回略有出入的行号）：保留区间**更完整**（覆盖行数更多）的条目，丢弃较窄的；行号差异写入 `warnings`。
   - 所有因重叠被丢弃的条目**必须**记入 `warnings`（文件 + 行区间 + 保留哪条 + 原因），保证裁决可追溯、可人工复核。
   - 基础扫描器条目与 Subagent 条目重叠时，以 Subagent 条目信息更全（含 `brief`/`arch_source`）为准合并，`solver_type` 冲突时按 project_scan.md 映射表归并。

4. 扫描覆盖**全部**架构相关待迁移点；类型由条目的 `solver_type` 标识（参见 [references/project_scan.md](references/project_scan.md)）。
5. **归一化与写入**：对每个条目补充 `status="TODO"`、`marking=""`，扫描器小写 `"todo"` 归一化为大写（详见 project_scan.md「扫描器原始输出 vs 主 Agent 归一化」）。然后**由主 Agent 统一写入最终 `scan_result.json`**。扫描 Subagent 不直接写 JSON。
6. 若扫描引擎执行失败：确认依赖已装（`python3 -m pip install -r ${RISCV_SKILLS_ROOT}/riscv-scan/scripts/requirements.txt`）后重试；仍失败则按 [references/project_scan.md](references/project_scan.md) 的 JSON schema 手工/静态分析填写 `scan_result.json`（静态分析兜底：grep 架构宏/intrinsic/asm 特征，按 schema 手工构造条目）。

## 出口条件（进度自检）

`scan_result.json` 存在、可读；`suggestion_class` / `missing_class` 覆盖当前要处理的迁移范围；条目总数已盘点清楚。完成后向用户输出一次结构化摘要（条目数 / 类型分布 / 产物路径），并提示下一步可用 `riscv-migrate` 技能开始条目级迁移 + 工程级验证一体闭环，迁移完成后再用 `riscv-verify` 技能做迁移后功能验证。

## Subagent

| Subagent | 角色 | 读写属性 |
| -------- | ---- | -------- |
| [`riscv-scan-worker`](agents/riscv-scan-worker.md) | 按目录/扫描维度返回候选迁移点；定义在本技能 `agents/` | 只读 |

## 脚本与资源

| 资产 | 路径 | 用途 |
| ---- | ---- | ---- |
| 扫描入口 | `${RISCV_SKILLS_ROOT}/riscv-scan/scripts/run_scan.sh` | 基础扫描（自动装依赖） |
| 扫描引擎 | `${RISCV_SKILLS_ROOT}/riscv-scan/scripts/riscv_scan_src/` | Python 源码扫描器（10 个 solver + 缺失架构检测；输出 `scan_result.json`） |
| 参考输出样例 | `${RISCV_SKILLS_ROOT}/riscv-scan/tests/expected_scan_result.sample.json` | 输出格式参考（基础扫描 + Subagent 增强合并后的完整形态） |
| 条目 Schema | [references/project_scan.md](references/project_scan.md) | JSON 全字段、solver_type 枚举、归一化规则 |
| 跨技能协议 | `references/scan_result_protocol.md` | 状态字段、门禁、令牌 |

## 失败回流

| 发现位置 | 回流位置 |
| -------- | -------- |
| 扫描候选冲突或遗漏 | 本技能合并步骤重做 |
| 后续技能发现条目集不完整 | 建议用户重跑本技能（用户明确要求才覆盖旧 JSON） |

## 自主运行原则（本技能子集）

以 `references/scan_result_protocol.md` 第 9 节为共同基底，本技能专属决策：

| 决策点 | 默认行为 |
| ------ | -------- |
| 是否重新扫描 | 存在 → 不重扫，直接读；不存在 → 跑扫描。不要问"要不要重扫" |
| 是否补充并行扫描 Subagent | 主 Agent 按工程规模与架构复杂度自主决策（≤4 个只读） |
| 扫描器执行失败 | 换 Python 重试 → 仍失败走静态分析兜底（按 schema 手工填写） |
| 源码依赖装不上 | 手动安装指引已给出；仍失败按静态分析兜底（按 schema 手工填写），**不**阻断流程 |
| Subagent 条目与基础扫描条目重叠 | 以信息更全者为准合并，裁决记入 `warnings` |
