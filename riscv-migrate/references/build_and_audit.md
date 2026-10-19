# 工程级编译验证（build_and_audit）

本文对应 `riscv-migrate` 技能 **3.1–3.3**（验证段）的实施细则：工程级交叉编译修复 + 产物级 QEMU 验证。条目级（2.4）QEMU 对比在同技能迁移段执行，本段做**整体**兜底。跨技能协议见 `references/scan_result_protocol.md`。

## 在技能组中的位置

```
riscv-scan(扫描) → riscv-migrate(条目级迁移 + 条目级 QEMU 验证
                                → 全条目 DONE 后自动进入本段：
                                  工程级交叉编译 + 3.3 运行验证)
```

**条目级 + 产物级互补**：条目级保证单个迁移点正确；产物级保证整体可运行。trivial 宏条目（迁移段免验证直接 DONE）的可编译性由本段工程级编译兜底。

## 3.1 准备环境

- 由技能自动加载 RISC-V 交叉工具链：`bash ${RISCV_SKILLS_ROOT}/riscv-migrate/resources/riscv_toolchain_env.sh` + `source ${RISCV_SKILLS_ROOT}/riscv-migrate/resources/env.sh`。
- 同时准备 QEMU user-static：`bash ${RISCV_SKILLS_ROOT}/riscv-migrate/resources/qemu_static_env.sh`。
- 一键准备（工具链 + QEMU，已存在则复用）：`bash ${RISCV_SKILLS_ROOT}/riscv-migrate/scripts/prepare_verify_env.sh`。技能会在当前会话**自动加载**所需环境（工具链与 `qemu-*` 写入 `PATH`），无需手动 `source`。

## 3.2 编译与修复（并行诊断 → 串行修复）

目标流程：

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
2. 在目标工程里用交叉工具链跑完整构建（如 `make` / `cmake --build`），前缀以 `*_TOOLCHAIN_ROOT/bin` 下实际文件为准（如 `riscv64-unknown-linux-gnu-gcc`、`aarch64-buildroot-linux-gnu-gcc`、x86 交叉前缀等）。
3. **修编译错误**：
   - 每轮只根据首个根因或一组互不冲突的根因实施修复。
   - 重新编译必须由主 Agent 统一执行，保证日志和环境一致。
   - 如果发现迁移段遗漏，必须回流对应条目（`REFLOW_TO_PHASE2`），不在验证段绕过状态闭环。
   - 缺什么装什么（系统包 + `${RISCV_SKILLS_ROOT}/riscv-migrate/resources/*.sh`）。
   - `__x86_64__` / `__ARM_ARCH` 等宏残留未替换的，回流 migrate 补。
   - 头文件路径、链接库路径、ABI（`lp64d`）等，按工程实际调整。
4. **`-march` 覆盖所用扩展**；常见起点：`-march=rv64gcv_zbb_zbc_zbkb_zvbb_zvbc_zvkb_zvksed_zvkned_zvksh_zvknha_zvkt -mabi=lp64d`，不够再补。
5. 若工程要求静态链接，遵守之。
6. 若任务固定产物名（如 `riscv64_test`），遵守任务说明。
7. "连续 3 次同类型错误才询问用户"的规则保持不变（见协议 9.2 白名单 #3）。

### 3.2.5 编译错误诊断 Subagent（按需）

主 Agent 在编译失败后，可召唤 `riscv-build-diagnoser` 对完整构建日志做只读分析。诊断 Subagent 将错误按根因聚类，识别首个根因与派生错误，判断是环境问题、构建参数问题、ABI/链接问题还是 migrate 遗漏，并给出最小修复建议和回流标注：

- `FIX_IN_PHASE3` → 在验证段内直接修复（编译参数、构建脚本接入等）；
- `REFLOW_TO_PHASE2` → 需要修改原始迁移代码，回流 `riscv-migrate` 对应条目（状态保持或恢复为 `START`）。

> 两个令牌值为**冻结字面量**，见 `references/scan_result_protocol.md` 第 7 节。

## 3.3 运行验证（产物级 QEMU 对比）

- 用 `qemu-riscv64 -cpu max,vlen=<目标VLEN> <bin>` 跑主流程/集成测试，至少确认主程序可启动、无立即崩溃、关键路径输出与 x86/ARM 侧一致。
- 与条目级 QEMU 验证互补：条目级验证保证**单个迁移点**正确；工程级验证保证**整体**可运行。

### 对比口径按输出类型区分

- **整数 / 字节流 / 枚举 / checksum**：逐字节 `diff`，必须完全一致。
- **浮点输出**：禁止盲目逐字节 diff——x86（SSE，80-bit 精度中间值）与 RV（lp64d，IEEE 双精度）的 FPU 收敛路径不同，逐位一致既不可达也不必要。改用**容差对比**：
  - 优先比较 checksum/归一化摘要（如求和误差按 ULP 计）；
  - 逐值对比时用相对误差 `|a-b| ≤ max(abs_err, rel_err×|b|)`，默认 `rel_err=1e-9`（双精度）、`abs_err=1e-12`；
  - 容差内不一致**不算失败**，但差异模式（如系统性偏移、仅尾数位不同）要写入该条目 `marking` 备查；
  - 若原始实现的语义本身要求位精确（如序列化格式、哈希输入），必须逐位一致——此时在 RISC-V 侧实现时就要选用保证位精确的算法，而不是靠容差放行。

### VLEN 对齐（必须）

`-cpu max` 默认 VLEN=128，与目标（如 「VLEN=256 通用目标」）不一致；手写 asm 按 VLEN≥256 选 LMUL 时可能假失败/假通过。验证命令的 `vlen=` 取值必须与本技能 SKILL.md A 节 #6 选定目标 CPU 时确定的目标 VLEN 一致。同时确认所用向量 crypto 扩展（Zvbc/Zvk*）在 QEMU `-cpu max` 下已使能。

```bash
# 参考侧（x86 侧只看正确性，优化级别不要求一致）
gcc -O2 -msse4.2 -o ref.out ref.c
# RISC-V 侧
riscv64-unknown-linux-gnu-gcc -O3 -march=rv64gcv_zbb_zbc_zbkb_zvbb_zvbc_zvkb_zvksed_zvkned_zvksh_zvknha_zvkt -mabi=lp64d -static -o riscv.out riscv.c
./ref.out > ref.txt
qemu-riscv64 -cpu max,vlen=<目标VLEN> ./riscv.out > riscv.txt
diff ref.txt riscv.txt   # 浮点输出按上文容差口径
```

### 验证后分析

1. 对第一处不一致的输出，定位首差行，逆向追溯到 RISC-V 实现的代码差异；
2. 将定位结果回流本技能迁移段（2.2）修复，修复后回到本步骤复测；
3. 闭环至全部用例输出一致。

## 进度自检

工程完整构建无错误；RV 可执行程序可在 QEMU 中跑通主流程。

## 衔接技能

- 验证段保证**正确性**（整数/字节流逐字节一致、浮点容差内一致）；性能优化不在本技能组范围内。
- 验证段跑通主流程后，迁移后功能验证（benchmark 优先复用 / 兜底对比测试、覆盖率、`report.md`）由 `riscv-verify` 技能（4.x）收口，详见 `${RISCV_SKILLS_ROOT}/riscv-verify/SKILL.md`。
