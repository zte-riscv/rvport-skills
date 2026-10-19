# 工程扫描（scan / project_scan）

对应 `riscv-scan` 技能：扫描迁移点。本文是 `scan_result.json` **条目 Schema 的唯一权威**。

> 技能组共用协议（状态字段语义、门禁链、回流路径、冻结令牌）见 `references/scan_result_protocol.md`。

## 输出文件

- **路径**：`<project_root>/scan_result.json`（`project_root` 为被迁移的工程根目录）。
- **语义**：列出待迁移点，供 `riscv-migrate` 技能按条目分流（汇编/非汇编）并按 `分流 → 迁移 → 知识库 → 验证` 串行处理。

## 在技能组中的位置

```
riscv-scan(本文档) → riscv-migrate(按条目分流迁移 → 全条目 DONE 后自动进入工程级验证)
```

- scan 技能产出 `scan_result.json`；
- migrate 技能加载 `scan_result.json` 逐条处理，每个条目通过结构化字段 `status` 与 `marking` 同步进度（**权威源在 JSON 中**，不再向源码写注释）。

## 推荐运行方式

扫描器是 Python 脚本。安装依赖后在任意目录执行扫描（依赖归属 riscv-scan 技能）：

```bash
python3 -m pip install -r ${RISCV_SKILLS_ROOT}/riscv-scan/scripts/requirements.txt

# 在目标工程根目录（或任意目录）执行
python3 "${RISCV_SKILLS_ROOT}/riscv-scan/scripts/riscv_scan_src/riscv_scan.py" "<project_root>" -o "<project_root>/scan_result.json"
```

扫描阶段 **不需要** 交叉工具链或 QEMU。进入迁移与对比阶段时，可按需在 `${RISCV_SKILLS_ROOT}/riscv-migrate/resources/` 下执行各初始化脚本（归属 riscv-migrate 技能；细则见 `${RISCV_SKILLS_ROOT}/riscv-migrate/references/code_migrate.md`），例如：`x86_toolchain_env.sh`、`arm_toolchain_env.sh`、`riscv_toolchain_env.sh`、`qemu_static_env.sh`。

## 是否重新扫描

- **已存在** `scan_result.json`：**默认不执行**扫描（不调用脚本、不覆盖），直接读取。
- **用户明确要求重新扫描**：删除或重命名旧文件后再执行扫描脚本或手工更新。

## `scan_result.json` Schema

顶层对象：

| 字段 | 类型 | 说明 |
|------|------|------|
| `target` | string | 扫描目标路径（文件或目录，绝对路径） |
| `suggestion_class_count` | int | `suggestion_class` 条目数 |
| `missing_class_count` | int | `missing_class` 条目数 |
| `suggestion_class` | array | 迁移建议条目列表 |
| `missing_class` | array | 缺失架构实现（目录/文件）条目列表 |

### `suggestion_class[]` 条目字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `class_type` | string | 固定为 `suggestion_class` |
| `file_name` | string | 文件名 |
| `file_path` | string | 文件绝对路径 |
| `solver_name` | string | 规则/solver 名 |
| `solver_type` | int | solver 类型，**整数枚举**（扫描器实际输出，映射表见下）；migrate 技能 2.1 据此分流（汇编/非汇编） |
| `solver_description` | string | solver 类型说明 |
| `start_line` | int | 起始行（1-based） |
| `end_line` | int | 结束行（含） |
| `migration_suggestion` | string | 迁移建议文本 |
| `status` | string | 迁移状态：`TODO` / `START` / `DONE`（三态之一，互斥；语义与写入者见 `references/scan_result_protocol.md` 第 4 节） |
| `marking` | string | 备注文本：异常说明 / TODO(后续) 等；`status=DONE` 时必填 |

#### `solver_type` 整数枚举映射表（与扫描器实现一致）

**扫描器输出的是整数，不是字符串**。读取 `scan_result.json` 做分流/匹配时必须按下表换算，直接按字符串 `"InlineAsm"` 等匹配会全部失配：

| `solver_type` 值 | 对应 solver | migrate 分流 |
| --- | --- | --- |
| `1` | `IntrinsicsSolver`（内联函数/intrinsic） | **汇编完整闭环** |
| `3` | `MacrosSolver`（宏定义） | 轻量适配（含架构宏时） |
| `4` | `InlineAsmSolver`（内联汇编） | **汇编完整闭环** |
| `2` | `BuiltinSolver`（`__builtin_*` 架构内置函数） | **汇编完整闭环** |
| `5` | `AsmFileSolver`（`.s`/`.S`/`.asm` 汇编文件） | **汇编完整闭环** |
| `0` | `MakefileSolver`（Makefile 架构编译参数） | 轻量适配（构建系统接入） |
| `10` | `CMakeSolver` / `BuildScriptSolver` / `BuildMesonSolver` / `ShellSourceCodeSolver`（构建系统与 shell 架构分支） | 轻量适配（构建系统接入） |

> 枚举定义见扫描器源码 `${RISCV_SKILLS_ROOT}/riscv-scan/scripts/riscv_scan_src/riscv_scan/common.py`。并行扫描 Subagent 补充的条目用字符串标签（`InlineAsm` / `Builtin` 等），同样遵守本 schema。遇到未知整数值时，**回退到源码特征分流**（migrate 技能 SKILL.md 2.1 第 1–4 条），不得因枚举不认识而跳过条目。

#### 扫描器原始输出 vs 主 Agent 归一化

**扫描器直接输出的 JSON 与本 schema 有一处差异**，scan 技能收尾、主 Agent 写入（或合并去重后回写）`scan_result.json` 时必须归一化：

| 字段 | 扫描器原始输出 | 归一化后（schema 要求） |
| ---- | -------------- | ---------------------- |
| `status` | 小写 `"todo"` | 大写 `"TODO"`（后续状态转换统一用大写） |

**状态匹配必须大小写不敏感**：读旧文件或未归一化文件时，`"todo"`/`"Todo"`/`"TODO"` 均视为 `TODO`，避免归一化遗漏导致条目被当成"未知状态"跳过。

### `missing_class[]` 条目字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `class_type` | string | 固定为 `missing_class` |
| `missing_path` | string | 缺失的 riscv64 文件/目录路径（绝对路径） |
| `is_file` | bool | 是否为文件缺失 |
| `existing_arch_paths` | array | 已存在的其他架构文件/目录路径（绝对路径列表） |
| `migration_suggestion` | string | 建议文本 |
| `status` | string | 迁移状态：`TODO` / `START` / `DONE` |
| `marking` | string | 备注文本（与 `suggestion_class` 同义） |

### 示例

以下示例展示**归一化后**的条目（扫描器原始输出的 `"status": "todo"` 已由主 Agent 归一化为大写；`solver_type` 保持扫描器的整数输出）：

```json
{
  "target": "/path/to/project",
  "suggestion_class_count": 1,
  "missing_class_count": 0,
  "suggestion_class": [
    {
      "class_type": "suggestion_class",
      "file_name": "foo.c",
      "file_path": "/path/to/project/src/foo.c",
      "solver_name": "IntrinsicsSolver",
      "solver_type": 1,
      "solver_description": "内联函数",
      "start_line": 40,
      "end_line": 55,
      "migration_suggestion": "NEON 向量加法，需 RVV 等价实现",
      "status": "TODO",
      "marking": ""
    }
  ],
  "missing_class": []
}
```

## 迁移点状态字段（status / marking）

每个条目（`suggestion_class[]` 与 `missing_class[]`）都携带 `status` / `marking` 两个结构化字段，**权威源在 JSON 中，不再向源码写注释**。三态语义、写入者、`marking` 跨技能信号语汇与唯一写入路径的**权威定义在** `references/scan_result_protocol.md`（第 4 节），此处仅列速查：

| `status` | 含义 | 何时设置 | `marking` |
| ------- | ---- | -------- | --------- |
| `TODO` | 未处理 | scan 技能产出（默认值） | 否 |
| `START` | 开始迁移 | migrate 技能主 Agent 分派任务前 | 否 |
| `DONE` | 迁移完成 | migrate 技能 2.4 验证通过 | **是** |

更新方式：直接编辑 JSON 文件（或 agent 用 `jq`/Python 改写条目），写回后必须保持 schema 与缩进一致；不要在源码里写 `MIGRATE-*` 注释。

## 扫描引擎 `riscv_scan_src`（Python 源码）约定

- **入口**：`${RISCV_SKILLS_ROOT}/riscv-scan/scripts/riscv_scan_src/riscv_scan.py`（Python 源码，平台无关；不应在文档里写死安装后的绝对路径）
- **生成输出**：`python3 ${RISCV_SKILLS_ROOT}/riscv-scan/scripts/riscv_scan_src/riscv_scan.py <target> -o <output_path>`（不指定 `-o` 时输出到当前目录 `./scan_result.json`）

## 分流依据（速查）

migrate 技能 2.1 的分流规则速查（判定条件、`solver_type` 双形态匹配、登记字段）见 `${RISCV_SKILLS_ROOT}/riscv-migrate/references/code_migrate.md`「分流依据（速查）」一节。
