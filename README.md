# RISC-V Skills — Agent Skills for Porting x86/ARM Projects to RISC-V

**[简体中文](README.zh-CN.md)** | English

A set of agent skills that port x86/ARM projects (C/C++, including inline
assembly, intrinsics, and architecture macros) to RISC-V (including the RVV 1.0
vector extension) and verify the **functional correctness** of the ported code.

> **Host compatibility**: The skill bodies (workflows, gates, protocols) are
> platform-agnostic and can be adapted to any agent framework that can load
> "SKILL.md + scripts + subagent definitions". However, the frontmatter of
> `agents/*.md` (the `name` / `description` / `tools:` fields) and the task
> package / return token protocol follow the **Claude Code subagent
> conventions**; other frameworks need an equivalent mapping to their own
> subagent mechanisms.

> This skill set focuses solely on **correctness** (builds pass + QEMU output
> matches + test/coverage verification). It does not measure or optimize
> performance.

## Composition and Responsibilities

| # | Skill | Directory | Responsibility | Output / Gate |
| - | ----- | --------- | -------------- | ------------- |
| 1 | **riscv-scan** | [`riscv-scan/`](riscv-scan/) | Scan an x86/ARM project for all architecture-specific migration points (assembly, intrinsics, architecture macros, architecture-branched source, missing architecture directories) | `<project_root>/scan_result.json`; JSON exists, is readable, entries fully inventoried → ready for migrate |
| 2 | **riscv-migrate** | [`riscv-migrate/`](riscv-migrate/) | Entry-level migration (2.x): plan grouping → necessity analysis → triage → migrate → knowledge-base verification → entry-level QEMU verification; **after all entries are DONE, automatically enters the project-level verification phase (3.x)**: full cross-compilation fixes + artifact-level QEMU comparison | `*_riscv` sources + entry states `TODO→START→DONE` + executable artifacts; artifacts build and QEMU output matches → migration complete, ready for verify |
| 3 | **riscv-verify** | [`riscv-verify/`](riscv-verify/) | **Post-migration functional verification (4.x)**: probe the project's own benchmarks/test suites (reuse on hit, `BENCHMARK_HIT`); on miss (`BENCHMARK_MISS`), fall back to self-built original-arch vs RISC-V comparison tests; both paths run gcov coverage analysis (line coverage ≥70%) and produce a verification report | `<project_root>/test/<target>/{report.md,coverage.txt,run.log}` + test statistics + `marking` verdicts; all tests pass (failures closed-loop or explained as environmental) → verification concluded |

The three skills **run in sequence but can also be invoked standalone** (when
you only need one step, its entry prerequisites still apply):

```text
riscv-scan ──scan_result.json──▶ riscv-migrate ──all entries DONE + QEMU passes──▶ riscv-verify
(no prerequisite)                (prerequisite: scan_result.json produced)        (prerequisite: migration complete)
```

The **sole** state carrier between skills is `<project_root>/scan_result.json`:
state-field semantics, gate chains, reflow paths, subagent return tokens
(frozen values), and the shared autonomy clauses are all defined
authoritatively in
[`riscv-scan/references/scan_result_protocol.md`](riscv-scan/references/scan_result_protocol.md)
(byte-identical copies in all three skills).

## Directory Layout

```text
riscv-skills/
├── README.md                     # this file (English, default)
├── README.zh-CN.md               # Chinese translation
├── LICENSE                       # Apache-2.0
├── riscv-scan/                   # skill 1: project scanning
│   ├── SKILL.md                  # skill entry (workflow, gates, autonomy principles)
│   ├── agents/                   # subagent definitions (riscv-scan-worker)
│   ├── scripts/                  # run_scan.sh + riscv_scan_src/ (Python source scanner)
│   ├── tests/                    # expected_scan_result.sample.json (output format reference)
│   └── references/               # project_scan.md (sole authority for the entry schema), etc.
├── riscv-migrate/                # skill 2: entry migration + project-level verification
│   ├── SKILL.md
│   ├── agents/                   # planner / worker / reviewer / build-diagnoser
│   ├── scripts/                  # knowledge-base query (query.py), verify env setup
│   ├── references/               # code_migrate.md, build_and_audit.md, etc.
│   └── resources/                # toolchain/QEMU environment scripts
└── riscv-verify/                 # skill 3: post-migration functional verification
    ├── SKILL.md
    ├── agents/                   # verify-runner
    ├── scripts/                  # benchmark probing, verify env setup (delegates to migrate)
    ├── references/               # verify_functional.md (probe checklist, fallback templates, report spec)
    └── config.env.example
```

Each skill directory is **self-contained** (scripts resolve paths relative to
themselves, independent of install location). `${RISCV_SKILLS_ROOT}` in the
docs refers to the common parent of the skill directories; when unset, it is
derived from the relative directory layout.

> **One exception**: `riscv-verify` **reuses the toolchain/QEMU deployment of
> `riscv-migrate`** (to avoid downloading large components twice). Its
> `prepare_verify_env.sh` requires a sibling `riscv-migrate/` directory and
> exits with an error if missing. When distributing `riscv-verify` alone,
> ship `riscv-migrate` alongside it; the scan and migrate skills can each be
> distributed independently.

## Environment Requirements

### Host basics (shared by all three skills)

- Linux x86_64 or ARM64
- `bash` (script entry points and toolchain loader scripts)
- `python3` ≥ 3.10 + `pip` (scanner dependency installation, MCP
  knowledge-base client)
- Network access (runtime components are downloaded on demand at first run;
  see [Configuration](#configuration) below to override with private mirrors
  for intranet environments)

### Per-skill prerequisites and versions

| Skill | Prerequisite | Version | Purpose / Source | Preinstall? |
| ----- | ------------ | ------- | ---------------- | ----------- |
| **riscv-scan** | `bash` | — | script entry | yes |
| | `python3` + `pip` | ≥ 3.10 | install scanner Python dependencies | yes |
| | `pyahocorasick` / `treelib` / `chardet` | requirements.txt | scanner engine (`riscv_scan_src/` Python source, platform-agnostic) dependencies; auto-installed by `run_scan.sh` | no (auto) |
| | cross toolchains / QEMU | — | **not needed for scanning** | — |
| **riscv-migrate** | `bash` | — | script entry and environment loading | yes |
| | `python3` + `pip` | ≥ 3.10 | MCP knowledge-base client (`query.py`, needs `mcp>=1.0.0`, `httpx>=0.27.0`; optional if no MCP endpoint configured) | yes |
| | RISC-V cross toolchain | riscv-collab/riscv-gnu-toolchain **gcc 14.2 nightly (2024.09.03, glibc, built on ubuntu-22.04)**, prefix `riscv64-unknown-linux-gnu-` | cross-compile migrated code and tests | no (auto-downloaded by `prepare_verify_env.sh`) |
| | QEMU user-static | **v10.0.4** (tonistiigi/binfmt `deploy/v10.0.4-56`), includes `qemu-riscv64` / `qemu-aarch64`, etc. | run RISC-V / ARM binaries for output comparison (`-cpu max,vlen=<target VLEN>`) | no (auto-downloaded) |
| | x86 cross toolchain (optional) | bootlin x86-64 glibc stable **2025.08-1** | compile/run x86 reference-side comparison tests (x86_64 hosts can use the system gcc directly) | no (auto-downloaded on demand) |
| | ARM cross toolchain (optional) | bootlin aarch64 glibc stable **2025.08-1**, prefix `aarch64-buildroot-linux-gnu-` | compile ARM native reference-side tests | no (auto-downloaded on demand) |
| | build tools | `make` / `cmake`, etc. as required by the target project | full project-level build (3.x) | yes (per project) |
| **riscv-verify** | `bash` | — | script entry and environment loading | yes |
| | RISC-V toolchain / QEMU | same as riscv-migrate (**reuses its deployment**; `riscv-verify/scripts/prepare_verify_env.sh` delegates) | cross-compile test suites + full QEMU runs (parameters aligned with migrate) | no (reuses migrate deployment) |
| | coverage tools | `gcov` (required) + `lcov` (optional) | generate line/branch coverage report `coverage.txt` (falls back to raw gcov output if lcov is missing) | gcov recommended (ships with gcc); lcov no (install guidance given if missing) |
| | build tools | `make` / `cmake` / `ctest`, etc. as required by the project's own tests | compile and run the project's benchmarks/test suites (4.3 baseline path) | yes (per project) |

> Toolchains and QEMU are downloaded on demand and added to `PATH` by the
> skills' `prepare_verify_env.sh` / `*_env.sh` scripts — **no manual
> preinstallation required**. Existing downloads are reused automatically
> (riscv-verify reuses riscv-migrate's deployment without downloading again).
> Versions can be overridden with private mirrors via `RISCV_TOOLCHAIN_URL` /
> `QEMU_STATIC_URL` / `ARM_TOOLCHAIN_URL` / `X86_TOOLCHAIN_URL` in
> `config.env`.

## Quick Start

Porting an x86 project `<project_root>` (the agent loads the three skills in
sequence):

1. **Scan** — Have the agent load `riscv-scan/SKILL.md` and produce
   `scan_result.json` for the target project (an existing JSON is reused
   as-is, no rescan). Equivalent script entry point:
   ```bash
   bash riscv-scan/scripts/run_scan.sh <project_root> -o <project_root>/scan_result.json
   ```
2. **Migrate + project-level verification** — Load `riscv-migrate/SKILL.md`.
   The agent migrates entry by entry in a closed loop (false positives return
   `NO_WORK_NEEDED`; assembly/RVV entries pass the Reviewer gate), then
   automatically enters 3.x project-level verification after all entries are
   DONE (full cross-compilation + QEMU run comparison).
3. **Post-migration functional verification** — Load `riscv-verify/SKILL.md`.
   The agent probes the project's own benchmarks (reusing the full test set on
   a hit) or, on a miss, builds original-arch vs RISC-V comparison tests; runs
   coverage analysis either way (line coverage ≥70%), produces
   `test/<target>/{report.md,coverage.txt,run.log}`, and writes verdicts back to the
   `marking` fields of `scan_result.json`. Equivalent script entry point for
   benchmark probing:
   ```bash
   bash riscv-verify/scripts/probe_benchmark.sh <project_root>
   ```

Running just one step is also fine — e.g. re-running functional verification
alone on an already-migrated project — as long as that step's entry
prerequisites are met (see "Entry Prerequisites" in each SKILL.md).

## Configuration

All three skills run with essentially zero configuration (components download
from public open-source mirrors). Two optional items to know about:
① **knowledge-base querying is an optional capability** — `RISCV_DOC_MCP_URL`
has no default; when unset, the migrate skill's knowledge-base step degrades
to quick-reference table mapping without affecting the main workflow;
② download URLs are pinned to specific versions (for reproducibility) — if a
remote goes away, switch sources via the overrides below. To override, in the
`riscv-migrate` / `riscv-verify` directories (riscv-scan has no config):

```bash
cp config.env.example config.env   # uncomment and fill in as needed
```

- **Priority**: environment variables > skill-root `config.env` > built-in
  public defaults in the scripts
- **Overridable items** (see the comments in each `config.env.example`):
  private artifact-repo authentication `ART_API_KEY`, toolchain/QEMU download
  URLs, RISC-V documentation knowledge-base MCP endpoint `RISCV_DOC_MCP_URL`
  (querying degrades when unset), shared cache directory `RISCV_ASSET_ROOT`.
  **riscv-scan has no configuration** (source scanning is zero-config)
- **Shared configuration across skills**: put credentials in shell environment
  variables, or point `CONFIG_FILE` at one shared configuration file
- `config.env` is listed in `.gitignore` and never committed

## Core Conventions (cross-skill, required reading for agent implementers)

- **Single writer**: `scan_result.json` is written only by the main agent;
  subagents are read-only and return result tokens.
- **Entry state machine**: `TODO → START → DONE`, three mutually exclusive
  states; `DONE` requires a non-empty `marking`. The verify skill only appends
  `marking` verdicts; when a migration defect is identified, the entry's
  `DONE` is reverted to `START` and reflowed to migrate for fixing.
- **Frozen return tokens**: `PLAN_READY` / `NO_WORK_NEEDED` /
  `READY_FOR_REVIEW` / `PASS` / `NEEDS_FIX` / `FIX_IN_PHASE3` /
  `REFLOW_TO_PHASE2` / `FIX_IN_PHASE4` / `BENCHMARK_HIT` / `BENCHMARK_MISS`,
  etc. are frozen values matched literally; do not rename them (semantic
  mapping in protocol section 7).
- **Correctness criteria**: integers/byte streams/checksums must match byte
  for byte; floating-point output is compared within tolerance (on the order
  of `rel_err=1e-9` / `abs_err=1e-12`); bit-exact semantics (hash inputs,
  serialization formats) must match bit for bit.
- **Verification artifact placement** (verify): all functional verification
  artifacts go under `<project_root>/test/<target>/`; nothing in `/tmp`, no
  build directories left in the repo root; intermediate artifacts are cleaned
  up after the coverage report is generated.
- **Autonomy principles**: the autonomy clauses of each SKILL.md share
  protocol section 9 as their common base — recoverable problems are always
  self-served; the user is asked only in whitelisted scenarios (e.g. project
  root probing failed, fix-loop threshold exceeded).

## Documentation Index

| Document | Location | Content |
| -------- | -------- | ------- |
| Cross-skill protocol authority | `riscv-scan/references/scan_result_protocol.md` (identical copies in all three skills) | state machine, gate chains, reflow paths, token table, autonomy clauses |
| Entry schema authority | `riscv-scan/references/project_scan.md` | all `scan_result.json` fields, solver_type enums |
| Scanning workflow | `riscv-scan/SKILL.md` | scanning, merge and dedup |
| Migration workflow | `riscv-migrate/SKILL.md` + `riscv-migrate/references/code_migrate.md` | entry closed-loop, triage, instruction mapping quick reference |
| Project-level verification | `riscv-migrate/references/build_and_audit.md` | cross-compilation fixes, QEMU comparison, floating-point tolerance |
| Functional verification | `riscv-verify/SKILL.md` + `riscv-verify/references/verify_functional.md` | benchmark probing, baseline/fallback paths, coverage, report spec |
