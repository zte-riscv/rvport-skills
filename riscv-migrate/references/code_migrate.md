# 迁移点迁移（code_migrate）

本文对应 `riscv-migrate` 技能 **2.2 / 2.3 / 2.4**（迁移段）的实施细则。条目 Schema 见 `${RISCV_SKILLS_ROOT}/riscv-scan/references/project_scan.md`，跨技能协议（状态/门禁/回流/令牌）见 `references/scan_result_protocol.md`。工程级编译验证（3.x，全条目 DONE 后自动进入）见同技能 [build_and_audit.md](build_and_audit.md)。

## 在技能组中的位置

```
riscv-scan(扫描) → riscv-migrate(本文档核心)
                      ├─ 2.1 分流（含 trivial 判定）
                      ├─ 2.2 迁移(主 Agent 将 status: TODO → START)
                      ├─ 2.3 知识库查询
                      └─ 2.4 验证 (主 Agent 将 status: START → DONE + 填 marking；trivial 条目免)
                  → 同技能 3.x 验证段(工程级交叉编译 + 运行验证, 全条目 DONE 后自动进入)
```

每个条目的状态以 `scan_result.json` 中的 `status`、`marking` 两个结构化字段同步（**权威源在 JSON，不在源码注释**）。详见 `references/scan_result_protocol.md` 第 4 节。

---

## 分流依据（速查）

满足以下**任一**即视为汇编代码，走完整子闭环 `2.2 迁移 → 2.3 知识库 → 2.4 验证`；其余（源码/Shell/宏/Toml、纯 C/C++ 逻辑、标准库调用、无架构绑定）走轻量子流程——其中**改动仅在预处理指令行的 trivial 条目免 2.4 验证**（判据见 SKILL.md 2.1「轻量流程再细分」：仅 `#if*`/`#define`/`#include` 行、宏体内无 intrinsic/asm → 不编译不跑 QEMU，直接 DONE；可编译性由同技能 3.x 工程级编译兜底）。

> **`solver_type` 取值形态**：基础扫描器输出**整数**（`1`=IntrinsicsSolver、`3`=MacrosSolver、`4`=InlineAsmSolver，见 project_scan.md 映射表）；并行扫描 Subagent 补充的条目用**字符串标签**。分流代码对两种形态都要能匹配——`solver_type in (4, "InlineAsm")` 这类**混合判断**，不要写成只认字符串或只认整数。

1. **文件类型**：`.S` / `.s` / `.asm` 等汇编源文件。
2. **内联汇编**：源文件中含 `__asm__` / `__asm` / `asm volatile`，且迁移点落在该段内。
3. **intrinsic**：含 x86 intrinsic（`_mm_*` / `_mm256_*` / `_mm512_*`）或 ARM NEON intrinsic（`vld1q_*` / `vmlaq_*` / `vst1q_*`）。
4. **架构强绑定 built-in**：含 `__builtin_ia32_*` / `__builtin_neon_*` 等。
5. **`solver_type` 为汇编类**：整数 `4`（InlineAsmSolver）/ `1`（IntrinsicsSolver），或字符串 `InlineAsm` / `Builtin`（补充扫描条目）。

登记字段：`file_path`、`start_line`/`end_line`、`asm_type`（`inline_asm`/`standalone_asm`/`intrinsic`/`builtin`）、`arch_source`（`x86`/`x86_64`/`arm`/`aarch64`/`none`）、`brief`（一句话描述，用于条目 `marking` 文本）、`status`、`marking`。

---

## x86/ARM → RISC-V 指令映射速查表（迁移时先查这里）

> **用法**：迁移 intrinsic/asm 条目时先在下表找对应行；表内没有的模式再查知识库（2.3）。"-march 起点"已含下表全部扩展（见 SKILL.md A 节 #7）。

### 位操作 / 标量

| x86 / ARM | 语义 | RISC-V 落点 | 扩展 |
| --------- | ---- | ----------- | ---- |
| `_mm_popcnt_u32/64` / ARM `vcnt` | 位计数 | `cpop`（或 RVV `vcpop`） | Zbb |
| `__builtin_clz` / `_lzcnt_u32/64` | 前导零 | `clz`（RVV `vclz`） | Zbb |
| `__builtin_ctz` / `_tzcnt_u32/64` | 尾随零 | `ctz`（RVV `vctz`） | Zbb |
| `_bswap_32/64` | 字节反转 | `rev8`（RVV `vrev8`） | Zbb / Zbkb |
| `_rotl64` / `_rotr64` / ARM `ror` | 循环移位 | `rol` / `ror`（RVV `vrolnor`→`vror`） | Zbb |
| `_andn_u64`（BMI） | 与非 | `andn` | Zbb |
| PCLMULQDQ / ARM `vmull_p64`（标量） | 无进位乘法 | `clmul` / `clmulh` / `clmulr` | Zbc |
| `_blsi`/`_blsmsk`/`_blsr`（BMI） | 位隔离 | `min`/`and` 组合 或查库 | Zbb（部分需组合） |

### 向量（SIMD → RVV）

| x86 / ARM NEON | 语义 | RISC-V 落点 | 扩展 |
| -------------- | ---- | ----------- | ---- |
| `_mm_loadu_si128` / `vld1q_s8` | 向量加载 | `vle8/16/32/64.v`（`__riscv_vle...`） | V |
| `_mm_storeu_si128` / `vst1q_s32` | 向量存储 | `vse8/16/32/64.v` | V |
| `_mm_add_epi32` / `vaddq_s32` | 向量加 | `vadd.vv/vx` | V |
| `_mm_madd_epi16` / `vmlal_s16` | 乘加 | `vmacc.vx/vv` / `vmadd` | V |
| `_mm_max_epi8` / `vmaxq_s8` | 向量最值 | `vmax/vmin.vv/vx` | V |
| `_mm_shuffle_epi8`（SSSE3） | 字节查表重排 | `vperm.vv`（或 `vrgather`） | Zvbb / V |
| `_mm_slli_epi32` / `vshlq_n_s32` | 向量移位 | `vsll/vsrl/vsra.vi/vx/vv` | V |
| `_mm_cmpeq_epi32` / `vceqq_s32` | 比较→mask | `vmseq/vmslt...` + mask 操作 | V |
| `_mm_blendv_epi8` / `vbslq_u8` | 按 mask 混合 | `vmerge.vvm/vxm` | V |
| `_mm_extract_epi8` / ARM lane 提取 | lane 提取 | `vmv.x.s` / `vslide1down` | V |
| AVX gather / `vld1q_gather` | 收集访存 | `vluxei/vloxei` | V |
| `_mm512_*`（AVX-512 mask 语义） | 掩码操作 | mask 寄存器 `v0.t` 尾部语义（`ta`/`ma`） | V |

### 加密（高收益区）

| x86 / ARM | 语义 | RISC-V 落点 | 扩展 |
| --------- | ---- | ----------- | ---- |
| `_mm_crc32_u8/16/32/64`（SSE4.2） | CRC32 | `vclmul.vv` 多系数并行 | Zvbc（`vclmul`）/ Zbc（标量 `clmul`） |
| `_mm_aesenc_si128` 等 AES-NI 全家 | AES 轮函数 | `vaesef/vaesdf/vaesem/vaesdm.vs/vv` + `vaesz.vs` | **Zvkned** |
| ARM `vaeseq_u8` / `vaesmcq_u8` | AES | 同上 | Zvkned |
| SHA-NI（`_mm_sha256rnds2_epu32`）/ ARM `vsha256hq_u32` | SHA-256 | `vsha2cl/vsha2ch.vs` + `vshatri` | **Zvksh** |
| ARM `vsha1*`（SHA-1 四件套） | SHA-1 | 同 Zvksh（`vsha2*` 支持 SHA-1/2 双模式） | Zvksh |
| ARM `vsm3tt1q`/`vsm3tt2q`（SM3） | SM3 | `vsm3c/vsm3me.vv/x` | **Zvksh**（SM3 子集） |
| ARM `vsm4ekeyq_u8`（SM4） | SM4 | `vsm4k.vi` / `vsm4r.vs/vv` | **Zvksed** |
| SHA-384/512（ARM `vsha512*`） | SHA-512 | `vsha2cl/vsha2ch`（SEW=64 模式） | **Zvknha/zvknhb**（zbkb+zvksh 组合） |
| 通用 GF 乘 / GCM 域乘 | GF(2^128) | `vclmul` + `vgmul` 组合（查库确认目标扩展集） | Zvkg（若目标支持） |

> **注意**：SHA-512 需要 **SEW=64 模式**，即 `zvknhb`（`zvknha` 只支持 SEW=32 的 SHA-256 轮函数）。A 节 #7 的 `-march` 起点只含 `zvknha`，迁移 SHA-384/512 条目时须手工追加 `zvknhb`。

> **注意**：向量 crypto 的 intrinsic 覆盖在 GCC 14.2 上不全（部分 `__riscv_vaes*/vsha2*` 缺失或需更高版本）。intrinsic 编不过时按 SKILL.md「实现策略」**降级手写汇编**（`vaesef.vv` 等指令本身汇编器完整支持），并在 `marking` 记录"intrinsic 不可用"原因。

---

## 工具与知识

- 指令/扩展不熟：**先查上文映射速查表**；表内没有再 **优先知识库 MCP（`RISCV_DOC_MCP_URL` 端点，经 `run_query.sh`/`query.py` 访问）**；无 MCP 时用 **`${RISCV_SKILLS_ROOT}/riscv-migrate/scripts/query.py`**（需先 `python3 -m pip install -r ${RISCV_SKILLS_ROOT}/riscv-migrate/scripts/requirements-mcp.txt`）。**禁止凭感觉编指令**。
- 列工具：MCP 客户端工具列表，或 `python3 ${RISCV_SKILLS_ROOT}/riscv-migrate/scripts/query.py --list-tools`。常用四组知识库：`search_core_isa_manuals` / `search_rvv_vector_extensions` / `search_special_instructions` / `search_docs_tools`。
- 任务开始前可简述：清单、算法要点、拟用指令或内建函数。

```bash
python3 ${RISCV_SKILLS_ROOT}/riscv-migrate/scripts/query.py --list-tools
python3 ${RISCV_SKILLS_ROOT}/riscv-migrate/scripts/query.py -t search_core_isa_manuals -q "vadd.vv"
python3 ${RISCV_SKILLS_ROOT}/riscv-migrate/scripts/query.py -t search_rvv_vector_extensions -q "__riscv_vsetvl"
```

---

## 2.2：迁移（按分流结果）

### 通用要求

- **测试先行**：为**原始 x86/ARM 实现**与**即将编写的 RISC-V 实现**补齐或编写可运行的单元测试（同一行为、可对比输出或 checksum）。无测试不得宣称迁移完成。
- **新增源文件命名带 `_riscv` 后缀**（与工程约定冲突时在说明里写清）。
- **算法一致、语义一致**；向量源必须用 **RVV**（汇编或 intrinsic，RVV 1.0），不得把汇编问题退化成纯 C 替代。
- **实现策略**：默认 RVV 1.0 intrinsic + 编译参数（`-O3`、`__restrict`、`__builtin_assume_aligned`）；intrinsic 表达不出或编不过时降级手写汇编，原因记入 `marking`。
- **状态字段同步**：**主 Agent** 在分派任务前把 `scan_result.json` 中该条目的 `status` 从 `TODO` 改为 `START`；迁移 Subagent 不写 JSON。完成并验证后由主 Agent改为 `DONE` 并填 `marking`。**不要**在源码里写 `// [MIGRATE-*]` 注释。

### 汇编代码（完整子闭环）

1. 读懂 x86/ARM 语义与边界；设计 RISC-V 寄存器分配、RVV `vl` / mask。
2. 先查上文**指令映射速查表**，按实现策略编写 `*_riscv` 后缀的汇编或 intrinsic 实现。
3. **遇到指令/扩展/SEW&LMUL/intrinsic 对应/ABI 约束不确定时**：立即进入 2.3 查库，再继续编码。

### 非汇编代码（轻量子流程）

1. **代码适配**：改架构宏/头文件/编译选项使 C/C++ 在 RISC-V 可编译——`#ifdef __x86_64__`/`__ARM_ARCH` 换 `__riscv`；移除 `<immintrin.h>`/`<arm_neon.h>` 等专有头文件；确认字节序/对齐/类型宽度在 RV64（小端、`long`=64-bit）下成立。
2. 一般不需要进入 2.3 知识库查询（除非出现指令/intrinsic 信号）。
3. **先做 trivial 判定**（判据见 SKILL.md 2.1）：改动仅在预处理指令行（`#if*`/`#define`/`#include`）且宏体内无 intrinsic/asm → **免 2.4 验证**（不编译、不跑 QEMU、不写测试），主 Agent 直接置 `DONE`，`marking` 记 `trivial 宏适配：<宏/分支>`；可编译性由同技能 3.x 工程级编译兜底。疑义从重——不确定就照常走 2.4。
4. 非 trivial 条目进入 2.4 验证。

### 单元测试细节

- **按需准备环境**：要跑扫描类脚本时，执行 `python3 -m pip install -r ${RISCV_SKILLS_ROOT}/riscv-scan/scripts/requirements.txt`（归属 riscv-scan 技能）。要编译/运行 **x86_64 或 ARM 原生** 测试时，执行 `bash ${RISCV_SKILLS_ROOT}/riscv-migrate/resources/x86_toolchain_env.sh` 或 `bash ${RISCV_SKILLS_ROOT}/riscv-migrate/resources/arm_toolchain_env.sh`，再 **`source ${RISCV_SKILLS_ROOT}/riscv-migrate/resources/env.sh`**（新终端需重做）。若缺系统级依赖（头文件、动态库等），用发行版包管理器补齐。
- 为迁移点编写或补全 **单元测试**：同一套测试既能编 **原始 x86/ARM**，也能在后续用于 **RISC-V**。
- 断言可比对结果（返回值、缓冲区、checksum 等）。**无可用测试则不应结束迁移。**
- **测试充分性下限**：边界值（n=0 / n=1 / 极值）、随机（固定种子、可复现）、checksum 三类各至少一组；asm/RVV 条目另须覆盖**尾部不足一条向量**的规模（`n = k×VL + r`，`0 < r < VL`）与整倍数对照——strip-mining 尾部处理是向量迁移最高频出错点（详见 agent 定义 `riscv-migration-worker` 第 3 节）。

---

## 2.3：知识库/手册查询（汇编条目必走；非汇编条目按需）

**触发条件**：迁移过程中出现任一信号：指令名/扩展名（如 `Zba`/`Zvbb`）、intrinsic（如 `__riscv_*`）、ABI/CSR/特权字段（如 `mstatus`）。

### 选工具的规则

- **`search_core_isa_manuals`**：核心 ISA/汇编/Profile（合并知识库，Milvus spec=`core-isa-manuals`）
  - 覆盖：`riscv/riscv-isa-manual`、`riscv-non-isa/riscv-asm-manual`、`riscv/riscv-profiles`
- **`search_rvv_vector_extensions`**：RVV/向量相关扩展与 vector crypto（合并知识库，Milvus spec=`rvv-vector-extensions`）
  - 覆盖：`riscv-non-isa/riscv-rvv-intrinsic-doc`、`riscv/riscv-crypto`
- **`search_special_instructions`**：真正的指令扩展（合并知识库，Milvus spec=`special-instructions`）
  - 覆盖：`riscv-zabha`、`riscv-zalasr`、`riscv-zaamo-zalrsc`、`riscv-bitmanip`、`riscv-bfloat16`
- **`search_docs_tools`**：工具/指南（合并知识库，Milvus spec=`docs-tools`）

### 调用方式

- 列工具确认服务端暴露的工具名：`${RISCV_SKILLS_ROOT}/riscv-migrate/scripts/run_query.sh --list-tools`
- 示例：
  - `${RISCV_SKILLS_ROOT}/riscv-migrate/scripts/run_query.sh -t search_core_isa_manuals -q "mstatus MPP"`
  - `${RISCV_SKILLS_ROOT}/riscv-migrate/scripts/run_query.sh -t search_rvv_vector_extensions -q "__riscv_vsetvl"`
  - `${RISCV_SKILLS_ROOT}/riscv-migrate/scripts/run_query.sh -t search_special_instructions -q "Zba 有哪些指令"`

### 输出要求（证据链）

- **必须**在结论里保留 MCP 返回中的 `file_path` 与 `header_path`（或等价的标题路径信息），作为证据链。
- 如果返回未包含上述字段：优先让问题更具体（指令名/扩展名/操作数形态/SEW/LMUL），再重查；不要猜。

---

## 2.4：执行对比与修复（非 trivial 条目）

**范围**：完整闭环条目（asm/RVV）+ 改动涉及 C/C++ 语句行的普通轻量条目。trivial 条目（改动仅在预处理指令行）**免本节全部步骤**，主 Agent 直接置 `DONE`（`marking` 记 `trivial 宏适配`），判据见 SKILL.md 2.1。

1. **按需准备环境**：用 **`qemu-riscv64`** 等 user-static 跑 RISC-V 二进制前，执行 `bash ${RISCV_SKILLS_ROOT}/riscv-migrate/resources/qemu_static_env.sh`，并 **`source ${RISCV_SKILLS_ROOT}/riscv-migrate/resources/env.sh`**。
2. 分别构建并运行原生与 RISC-V 测试；RISC-V 侧常用 `qemu-riscv64 -cpu max,vlen=<目标VLEN> <bin>`（VLEN 与 A 节 #6 选定的目标 CPU 对应，「VLEN=256 通用目标」为 256；默认 `-cpu max` 的 VLEN=128 与目标不一致，须显式覆盖）。ARM 侧对比可用 `qemu-aarch64 -cpu max <bin>`。
3. 对比输出；不一致则优先改 RISC-V 侧（或测试/构建脚本）直到一致。浮点输出用容差对比（`rel_err=1e-9`/`abs_err=1e-12` 量级），禁止盲目逐字节 diff——详规见同技能 [build_and_audit.md](build_and_audit.md) 3.3 的浮点对比口径。
4. **验证通过后必须更新 JSON 字段**（**主 Agent** 执行）：
   - 把 `scan_result.json` 中该条目的 `status` 从 `START` 改为 `DONE`
   - 同时填写 `marking`（语汇表见 `references/scan_result_protocol.md` 4.4 节）：
     - 正常：`无异常`
     - 有异常：`语义差异：<具体点>，已通过测试规避` 或 `TODO(后续)：<具体项>`
     - trivial：`trivial 宏适配：<具体宏/分支>`（免验证直接 DONE 时）

---

## 衔接技能

- **工程级交叉编译验证**：全部条目 DONE 后**自动进入**同技能 3.x 验证段（细则见 [build_and_audit.md](build_and_audit.md)）。

---

## 完成说明

向用户简短总结：处理了哪些条目、改了哪些文件、测试与对比命令及结果。除非用户要固定模板，否则不必单独写 `output.md`。
