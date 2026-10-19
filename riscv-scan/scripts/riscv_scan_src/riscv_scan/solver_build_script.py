# Copyright 2026 ZTE Corporation
# SPDX-License-Identifier: Apache-2.0

"""configure.ac / .m4 构建脚本扫描。"""
import re

from .common import CodeTooLong, SOLVER_TYPE_BUILD_SCRIPT, SOLVER_DESCRIPTIONS
from .solver_base import Solver


class BuildScriptSolver(Solver):
    solver_type = SOLVER_TYPE_BUILD_SCRIPT
    solver_description = SOLVER_DESCRIPTIONS[SOLVER_TYPE_BUILD_SCRIPT]

    arch_pattern = (
        r"x86_64|amd64|amd64p32|i386|i486|i586|i686|x32|"
        r"arm|arm64|arm64be|armbe|aarch64|aarch64_be|armv8-a|armv9-a|"
        r"ppc|ppc64|ppc64le|powerpc|powerpc64|powerpc64le|"
        r"mips|mips64|mips64le|mips64p32|mips64p32le|mipsle|"
        r"sparc|sparc64|sparcv9|"
        r"s390|s390x|"
        r"loongarch64|loongarch32|loong64|"
        r"wasm|wasm32|wasm64|"
        r"alpha|hppa|ia64|m68k|sh|tilegx|xtensa"
    )

    patterns = [
        (r'case\s*["\']?\$host\b', 'arch_case'),
        (r'case\s*["\']?\$host_cpu\b', 'arch_case'),
        (r'case\s*["\']?\$target\b', 'arch_case'),
        (r'case\s*["\']?\$target_cpu\b', 'arch_case'),
        (r'(-m(avx|sse|neon|fpu|float-abi|arch=[^ \n]*?(arm|x86)))', 'arch_flag'),
        (r'AC_DEFINE\s*\(\s*\[([\w]+_BIGENDIAN|ENDIANNESS)\]\s*,\s*\[?([01])\]?\s*'
         r'(?:,\s*\[[^\]]*\]\s*)?\)', 'arch_endian'),
        (rf'\.(set|arch|cpu)\b.*?\b({arch_pattern})\b', 'arch_pseudo_inst'),
        (rf'\.(ifdef|ifndef)\b.*?(__{arch_pattern}__)', 'arch_conditional_asm'),
        (r'__asm__', 'arch_inline_asm'),
        (rf'\b(CC|CXX|LD|AS)\b.*?\b({arch_pattern})\b', 'arch_env_var'),
        (rf'AC_TRY_(RUN|COMPILE|LINK).*?\b({arch_pattern})\b', 'arch_config_test'),
    ]

    migration_advice = {
        'arch_case': "架构分支缺少RISC-V支持！需要添加类似分支：riscv*) "
                     "ARCH_FLAGS=\"-mabi=lp64d\" ;;",
        'arch_flag': "特定架构编译器标志，需替换为RISC-V等效标志",
        'arch_endian': "字节序硬编码，RISC-V支持大端(be)和小端(le)配置",
        'arch_pseudo_inst': "汇编伪指令需添加RISC-V支持",
        'arch_conditional_asm': "汇编条件编译需添加RISC-V分支",
        'arch_inline_asm': "检测到架构特定的内联汇编，需替换为RISC-V兼容版本或抽象层",
        'arch_env_var': "检测到架构特定的环境变量，需确保支持riscv*目标",
        'arch_config_test': "配置测试中包含架构特定逻辑，需添加RISC-V分支",
    }

    compiled_patterns = [(re.compile(p[0], re.IGNORECASE), p[1]) for p in patterns]

    @staticmethod
    def matches_file(file_name):
        ends = ['configure.ac', '.m4']
        return any(file_name.endswith(ext) for ext in ends)

    @classmethod
    def solve(cls, source_file):
        lines = source_file.get_code_lines()
        return BuildScriptSolver.find_pattern(lines, cls.compiled_patterns,
                                              cls.migration_advice)

    @staticmethod
    def find_pattern(lines, compiled_patterns, migration_advice):
        results = []
        in_arch_case = False
        case_start_line = 0
        case_lines = []
        has_riscv_branch = False

        for line_number, line in enumerate(lines, 1):
            stripped_line = line.strip()
            if stripped_line.startswith(('#', 'dnl')) or not stripped_line:
                continue
            next_line = lines[line_number] if line_number < len(lines) else ""

            if not in_arch_case:
                for pattern, pattern_type in compiled_patterns:
                    if pattern_type == 'arch_case' and pattern.search(
                            stripped_line + " " + next_line[:20]):
                        in_arch_case = True
                        case_start_line = line_number
                        case_lines = [stripped_line]
                        has_riscv_branch = False
                        break

            if in_arch_case:
                case_lines.append(stripped_line)
                if re.search(r'risc[_-]?v|rv(?:32|64)', stripped_line, re.IGNORECASE):
                    has_riscv_branch = True
                if stripped_line.startswith('esac') and 'esac' in stripped_line:
                    in_arch_case = False
                    if not has_riscv_branch:
                        advice = migration_advice.get('arch_case')
                        code_too_long, mycode = Solver.extract_code(lines, case_start_line,
                                                                    line_number)
                        results.append(
                            (case_start_line, line_number, advice, code_too_long, mycode))

            if not in_arch_case:
                for pattern, pattern_type in compiled_patterns:
                    if pattern_type == 'arch_case':
                        continue
                    match = pattern.search(stripped_line)
                    if match:
                        advice = migration_advice.get(pattern_type, "需要RISC-V兼容性检查")
                        results.append((line_number, line_number,
                                        f"{pattern_type}: {match.group()} - {advice}",
                                        CodeTooLong.HAS_SOURCE_CODE, stripped_line))
                        break

        if in_arch_case and not has_riscv_branch:
            advice = migration_advice.get('arch_case')
            end_lineno = len(lines)
            code_too_long, mycode = Solver.extract_code(lines, case_start_line, end_lineno)
            results.append((case_start_line, end_lineno, advice, code_too_long, mycode))

        return results, []
