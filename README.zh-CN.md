# RISC-V Skills —— x86/ARM 工程迁移 RISC-V 技能组

[English](README.md) | **简体中文**

一组 agent 技能，用于把 x86 / ARM 工程（C/C++，含内联汇编、intrinsic、架构宏）迁移到 RISC-V（含 RVV 1.0 向量扩展），并验证迁移后的**功能正确性**。

> **宿主兼容性**：技能体（流程、门禁、协议）平台无关，任何能加载「SKILL.md + 脚本 + Subagent 定义」的 agent 框架均可移植使用；但 `agents/*.md` 的 frontmatter（`name` / `description` / `tools:` 字段）与任务包/返回令牌协议按 **Claude Code subagent 约定**书写，其他框架需按各自 Subagent 机制做等价映射。

> 本技能组只关注**正确性**（构建通过 + QEMU 运行输出一致 + 用例/覆盖率验证），不做性能度量与优化。

## 组成与职责

| # | 技能 | 目录 | 职责 | 产出 / 门禁 |
| - | ---- | ---- | ---- | ---------- |
| 1 | **riscv-scan** | [`riscv-scan/`](riscv-scan/) | 扫描 x86/ARM 工程全部架构相关待迁移点（汇编、intrinsic、架构宏、架构分支源码、缺失架构目录） | `<project_root>/scan_result.json`；JSON 存在、可读、条目盘点清楚 → 可进 migrate |
| 2 | **riscv-migrate** | [`riscv-migrate/`](riscv-migrate/) | 条目级迁移（2.x）：规划分组 → 必要性分析 → 分流 → 迁移 → 知识库查证 → 条目级 QEMU 验证；**全条目 DONE 后自动进入工程级验证段（3.x）**：完整交叉编译修复 + 产物级 QEMU 对比 | `*_riscv` 源码 + 条目 `TODO→START→DONE` + 可执行产物；产物构建跑通、QEMU 输出一致 → 迁移完成，可进 verify |
| 3 | **riscv-verify** | [`riscv-verify/`](riscv-verify/) | **迁移后功能验证（4.x）**：探测工程自带 benchmark/测试套件（命中即复用，`BENCHMARK_HIT`）；未命中（`BENCHMARK_MISS`）兜底自建原架构 vs RISC-V 对比测试；两条路径都做 gcov 覆盖率分析（行覆盖 ≥70%）并生成验证报告 | `<project_root>/test/<验证目标名>/{report.md,coverage.txt,run.log}` + 用例统计 + `marking` 验证结论；用例全过（失败已闭环或说明环境理由）→ 验证收口 |

三技能**串行衔接、也可独立调用**（用户只要其中一步时，仍须满足对应入口前置条件）：

```text
riscv-scan ──scan_result.json──▶ riscv-migrate ──全条目 DONE + QEMU 跑通──▶ riscv-verify
（无前置）                        （前置：scan_result.json 已产出）           （前置：迁移已完成）
```

技能间的**唯一**状态衔接载体是 `<project_root>/scan_result.json`：状态字段语义、门禁链、回流路径、Subagent 返回令牌（冻结值）、共用自主运行条款，一律以 [`riscv-scan/references/scan_result_protocol.md`](riscv-scan/references/scan_result_protocol.md)（三技能内副本字节一致）为跨技能协议权威。

## 目录结构

```text
riscv-skills/
├── README.md                     # 英文版（默认展示）
├── README.zh-CN.md               # 本文件（中文版）
├── LICENSE                       # Apache-2.0
├── riscv-scan/                   # 技能 1：工程扫描
│   ├── SKILL.md                  # 技能入口（流程、门禁、自主运行原则）
│   ├── agents/                   # Subagent 定义（riscv-scan-worker）
│   ├── scripts/                  # run_scan.sh + riscv_scan_src/（Python 源码扫描器）
│   ├── tests/                    # expected_scan_result.sample.json（输出格式参考）
│   └── references/               # project_scan.md（条目 Schema 唯一权威）等
├── riscv-migrate/                # 技能 2：条目迁移 + 工程级验证
│   ├── SKILL.md
│   ├── agents/                   # planner / worker / reviewer / build-diagnoser
│   ├── scripts/                  # 知识库查询(query.py)、验证环境准备
│   ├── references/               # code_migrate.md、build_and_audit.md 等
│   └── resources/                # 工具链/QEMU 环境脚本
└── riscv-verify/                 # 技能 3：迁移后功能验证
    ├── SKILL.md
    ├── agents/                   # verify-runner
    ├── scripts/                  # benchmark 探测、验证环境准备（委托 migrate 部署）
    ├── references/               # verify_functional.md（探测清单、兜底模板、报告规范）
    └── config.env.example
```

每个技能目录**自包含**（脚本用自相对路径解析，不依赖外部安装位置）。`${RISCV_SKILLS_ROOT}` 在文档中指技能目录的共同父目录，未设置时按相对目录结构自行解析。

> **一个例外**：`riscv-verify` 的工具链/QEMU **复用 riscv-migrate 的部署**（避免重复下载大体积组件），其 `prepare_verify_env.sh` 需要同级 `riscv-migrate/` 目录存在，缺失时报错退出。单独分发 `riscv-verify` 时须随附 `riscv-migrate`；扫描与迁移两技能可各自独立分发。

## 环境要求

### 宿主机基础环境（三技能共用）

- Linux x86_64 或 ARM64
- `bash`（脚本入口与工具链加载脚本）
- `python3` ≥ 3.10 + `pip`（扫描引擎依赖安装、MCP 知识库客户端）
- 网络可达（首次运行按需下载运行时组件；内网环境见下文「配置」覆盖为私有镜像源）

### 各技能前置工具与版本

| 技能 | 前置工具 | 版本 | 用途 / 来源 | 是否需预装 |
| ---- | -------- | ---- | ----------- | ---------- |
| **riscv-scan** | `bash` | — | 脚本入口 | 是 |
| | `python3` + `pip` | ≥ 3.10 | 安装扫描器 Python 依赖 | 是 |
| | `pyahocorasick` / `treelib` / `chardet` | requirements.txt | 扫描引擎（`riscv_scan_src/` Python 源码，平台无关）依赖，`run_scan.sh` 自动安装 | 否（自动装） |
| | 交叉工具链 / QEMU | — | **扫描阶段不需要** | — |
| **riscv-migrate** | `bash` | — | 脚本入口与环境加载 | 是 |
| | `python3` + `pip` | ≥ 3.10 | MCP 知识库客户端（`query.py`，需 `mcp>=1.0.0`、`httpx>=0.27.0`；未配置 MCP 端点时可不用） | 是 |
| | RISC-V 交叉工具链 | riscv-collab/riscv-gnu-toolchain **gcc 14.2 nightly（2024.09.03，glibc，ubuntu-22.04 构建）**，前缀 `riscv64-unknown-linux-gnu-` | 交叉编译迁移代码与测试 | 否（`prepare_verify_env.sh` 自动下载） |
| | QEMU user-static | **v10.0.4**（tonistiigi/binfmt `deploy/v10.0.4-56`），含 `qemu-riscv64` / `qemu-aarch64` 等 | 运行 RISC-V / ARM 二进制做输出对比（`-cpu max,vlen=<目标VLEN>`） | 否（自动下载） |
| | x86 交叉工具链（可选） | bootlin x86-64 glibc stable **2025.08-1** | 编译/运行 x86 参考侧对比测试（x86_64 宿主机可直接用系统 gcc） | 否（按需自动下载） |
| | ARM 交叉工具链（可选） | bootlin aarch64 glibc stable **2025.08-1**，前缀 `aarch64-buildroot-linux-gnu-` | 编译 ARM 原生参考侧测试 | 否（按需自动下载） |
| | 构建工具 | `make` / `cmake` 等按目标工程要求 | 工程级完整构建（3.x） | 是（随工程） |
| **riscv-verify** | `bash` | — | 脚本入口与环境加载 | 是 |
| | RISC-V 工具链 / QEMU | 同 riscv-migrate（**复用其部署**，`riscv-verify/scripts/prepare_verify_env.sh` 委托） | 交叉编译测试套件 + QEMU 全量运行（参数与 migrate 对齐） | 否（复用 migrate 部署） |
| | 覆盖率工具 | `gcov`（必要）+ `lcov`（可选） | 生成行/分支覆盖率报告 `coverage.txt`（lcov 缺失时 gcov 原始输出兜底） | gcov 建议预装（随 gcc）；lcov 否（缺失给安装指引） |
| | 构建工具 | `make` / `cmake` / `ctest` 等按目标工程自带测试要求 | 编译并运行自带 benchmark/测试套件（4.3 基准路径） | 是（随工程） |

> 工具链与 QEMU 由技能的 `prepare_verify_env.sh` / 各 `*_env.sh` 脚本按需下载并配置 `PATH`，**无需用户手动预装**；已存在时自动复用（riscv-verify 直接复用 riscv-migrate 的部署，不重复下载）。版本可通过 `config.env` 的 `RISCV_TOOLCHAIN_URL` / `QEMU_STATIC_URL` / `ARM_TOOLCHAIN_URL` / `X86_TOOLCHAIN_URL` 覆盖为私有镜像。

## 快速开始

以迁移一个 x86 工程 `<project_root>` 为例（由 agent 依次加载三个技能执行）：

1. **扫描** —— 让 agent 加载 `riscv-scan/SKILL.md`，对目标工程产出 `scan_result.json`（若已存在则直接复用，不重扫）。等价的脚本入口：
   ```bash
   bash riscv-scan/scripts/run_scan.sh <project_root> -o <project_root>/scan_result.json
   ```
2. **迁移 + 工程级验证** —— 加载 `riscv-migrate/SKILL.md`。agent 按条目闭环迁移（误报返回 `NO_WORK_NEEDED`，汇编/RVV 条目过 Reviewer 门禁），全条目 DONE 后自动进入 3.x 工程级验证（完整交叉编译 + QEMU 运行对比）。
3. **迁移后功能验证** —— 加载 `riscv-verify/SKILL.md`。agent 探测工程自带 benchmark（命中即复用全量用例），未命中则自建原架构 vs RISC-V 对比测试；统一做覆盖率分析（行覆盖 ≥70%），产出 `test/<验证目标名>/{report.md,coverage.txt,run.log}`，并把验证结论写回 `scan_result.json` 的 `marking`。benchmark 探测的等价脚本入口：
   ```bash
   bash riscv-verify/scripts/probe_benchmark.sh <project_root>
   ```

只跑其中一步也可以：如对已迁移工程单独重跑功能验证——满足对应入口前置条件即可（见各 SKILL.md「入口前置条件」）。

## 配置

三技能基本零配置即可运行（组件从公网开源源下载）。两个可选项需知晓：① **知识库查询是可选能力**——`RISCV_DOC_MCP_URL` 无默认值，未配置时 migrate 的知识库环节自动降级为速查表映射，不影响主流程；② 下载源 URL 钉死了具体版本（保证可复现），远端失效时按下列可覆盖项换源。需要覆盖时，在 `riscv-migrate` / `riscv-verify` 目录（riscv-scan 无配置项）：

```bash
cp config.env.example config.env   # 按需取消注释并填写
```

- **优先级**：环境变量 > 技能根 `config.env` > 脚本内置公网默认源
- **可覆盖项**（详见 `riscv-migrate`/`riscv-verify` 的 `config.env.example` 注释）：私有制品仓认证 `ART_API_KEY`、工具链/QEMU 下载地址、RISC-V 文档知识库 MCP 端点 `RISCV_DOC_MCP_URL`（未配置时知识库查询降级）、共享缓存目录 `RISCV_ASSET_ROOT`。**riscv-scan 无配置项**（源码扫描零配置）
- **技能间共用配置**：凭据建议放 shell 环境变量，或设 `CONFIG_FILE` 环境变量指向一份共享配置文件
- `config.env` 已加入 `.gitignore`，不会被提交

## 核心约定（跨技能，agent 实现者必读）

- **单一写入者**：`scan_result.json` 只能由主 Agent 写入；Subagent 一律只读并返回结果令牌。
- **条目状态机**：`TODO → START → DONE` 三态互斥；`DONE` 必填 `marking`。verify 技能只追加 `marking` 验证结论；定位出迁移缺陷时把条目 `DONE` 恢复 `START` 回流 migrate 修复。
- **返回令牌冻结**：`PLAN_READY` / `NO_WORK_NEEDED` / `READY_FOR_REVIEW` / `PASS` / `NEEDS_FIX` / `FIX_IN_PHASE3` / `REFLOW_TO_PHASE2` / `FIX_IN_PHASE4` / `BENCHMARK_HIT` / `BENCHMARK_MISS` 等为字面匹配的冻结值，禁止改名（语义映射见协议第 7 节）。
- **正确性验证口径**：整数/字节流/checksum 逐字节一致；浮点输出按容差对比（`rel_err=1e-9`/`abs_err=1e-12` 量级）；位精确语义（哈希输入、序列化格式）条目必须逐位一致。
- **验证产物落位**（verify）：所有功能验证产物统一落 `<project_root>/test/<验证目标名>/`；不写 `/tmp`、不在仓库根留构建目录；覆盖率报告生成后清理中间产物。
- **自主运行原则**：各技能 SKILL.md 的自主运行条款以协议第 9 节为共同基底——可恢复的问题一律自助修复，只在白名单场景（如根目录探测失败、修复循环超阈值）才询问用户。

## 文档索引

| 文档 | 位置 | 内容 |
| ---- | ---- | ---- |
| 跨技能协议权威 | `riscv-scan/references/scan_result_protocol.md`（三技能副本一致） | 状态机、门禁链、回流路径、令牌总表、自主运行条款 |
| 条目 Schema 权威 | `riscv-scan/references/project_scan.md` | `scan_result.json` 全字段、solver_type 枚举 |
| 扫描流程 | `riscv-scan/SKILL.md` | 扫描、合并去重 |
| 迁移流程 | `riscv-migrate/SKILL.md` + `riscv-migrate/references/code_migrate.md` | 条目闭环、分流、指令映射速查表 |
| 工程级验证 | `riscv-migrate/references/build_and_audit.md` | 交叉编译修复、QEMU 对比、浮点容差 |
| 功能验证 | `riscv-verify/SKILL.md` + `riscv-verify/references/verify_functional.md` | benchmark 探测、基准/兜底路径、覆盖率、报告规范 |
