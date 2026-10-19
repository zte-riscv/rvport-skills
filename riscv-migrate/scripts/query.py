#!/usr/bin/env python3
# Copyright 2026 ZTE Corporation
# SPDX-License-Identifier: Apache-2.0
"""
通过 Streamable HTTP 或 SSE 连接远端 MCP 服务并调用工具（如 riscv-doc-mcp）。

依赖：
  python3 -m pip install -r ${RISCV_SKILLS_ROOT}/riscv-migrate/scripts/requirements-mcp.txt  # 相对三技能共同父目录

端点不内置默认值：需通过环境变量 RISCV_DOC_MCP_URL 或
本技能根（${RISCV_SKILLS_ROOT}/riscv-migrate/）config.env 配置（可自建或指向任意兼容 MCP 服务）。
默认传输为 Streamable HTTP（--transport http），URL 指向服务端 /mcp 入口；
该路径下 httpx 不使用系统代理变量，便于直连目标服务。
若服务端仅提供 SSE，使用 `--transport sse` 且 URL 指向 SSE 入口（常见为 `http://<host>:<port>/sse`）；SSE 仍遵循系统代理。

示例：
  python3 ${RISCV_SKILLS_ROOT}/riscv-migrate/scripts/query.py --list-tools --url http://<host>:<port>/mcp
  python3 ${RISCV_SKILLS_ROOT}/riscv-migrate/scripts/query.py --url http://<host>:<port>/mcp -t search_core_isa_manuals -q "CSR mstatus"
  RISCV_DOC_MCP_URL=http://<host>:<port>/mcp python3 ${RISCV_SKILLS_ROOT}/riscv-migrate/scripts/query.py -t search_rvv_vector_extensions -q "__riscv_vsetvl"
  python3 ${RISCV_SKILLS_ROOT}/riscv-migrate/scripts/query.py --transport sse --url http://<host>:<port>/sse --list-tools
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, TextContent

# ---------- 配置加载 ----------
# 优先级：环境变量 > 本技能根 config.env > 空（未配置时拒绝运行并给出指引）

def _load_config_env() -> dict[str, str]:
    """读取技能 config.env（若存在），返回其中定义的键值。

    已存在的环境变量优先，不被 config.env 覆盖。
    """
    cfg = {}
    config_path = (
        Path(__file__).resolve().parent.parent / "config.env"
    )
    if not config_path.is_file():
        return cfg
    for raw in config_path.read_text(errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key.isidentifier():
            cfg[key] = val
    return cfg


_CFG = _load_config_env()


def _cfg_get(name: str) -> str:
    """按 环境变量 > config.env 优先级取值。"""
    return os.environ.get(name, "") or _CFG.get(name, "")


_DEFAULT = ""  # 不内置端点；必须显式配置
# 优先级：RISCV_DOC_MCP_URL（env）> RISCV_DOC_MCP_SSE_URL（env，兼容旧名）> config.env
DEFAULT_MCP_URL = (
    os.environ.get("RISCV_DOC_MCP_URL")
    or os.environ.get("RISCV_DOC_MCP_SSE_URL")
    or _CFG.get("RISCV_DOC_MCP_URL", "")
) or _DEFAULT


def _print_tool_result(result: CallToolResult) -> None:
    if result.isError:
        print("MCP tool error:", file=sys.stderr)
    if result.structuredContent is not None:
        print(json.dumps(result.structuredContent, ensure_ascii=False, indent=2))
        return
    if not result.content:
        print("(empty result)", file=sys.stderr)
        return
    for block in result.content:
        if isinstance(block, TextContent):
            print(block.text)
        else:
            print(block, file=sys.stderr)


async def _session_work(
    session: ClientSession,
    list_tools: bool,
    tool_name: str | None,
    tool_args: dict[str, Any],
) -> int:
    await session.initialize()
    if list_tools:
        listed = await session.list_tools()
        for t in listed.tools:
            print(t.name)
            if t.description:
                for line in t.description.strip().splitlines():
                    print(f"    {line}")
        return 0
    if not tool_name:
        print("请指定 --tool 或使用 --list-tools", file=sys.stderr)
        return 2
    out = await session.call_tool(tool_name, tool_args)
    _print_tool_result(out)
    return 1 if out.isError else 0


async def _run(
    transport: str,
    url: str,
    headers: dict[str, str] | None,
    sse_read_timeout: float,
    list_tools: bool,
    tool_name: str | None,
    tool_args: dict[str, Any],
) -> int:
    try:
        if transport == "sse":
            async with sse_client(
                url,
                headers=headers,
                sse_read_timeout=sse_read_timeout,
            ) as (read, write):
                async with ClientSession(read, write) as session:
                    return await _session_work(
                        session, list_tools, tool_name, tool_args
                    )
        if transport == "http":
            timeout = httpx.Timeout(30.0, read=sse_read_timeout)
            client_kw: dict[str, Any] = {
                "timeout": timeout,
                # 内网 MCP 直连；避免 http_proxy/all_proxy 在 no_proxy 通配不生效时把请求发到企业代理
                "trust_env": False,
            }
            if headers:
                client_kw["headers"] = headers
            async with httpx.AsyncClient(**client_kw) as http_client:
                async with streamable_http_client(
                    url, http_client=http_client
                ) as (read, write, _get_sid):
                    async with ClientSession(read, write) as session:
                        return await _session_work(
                            session, list_tools, tool_name, tool_args
                        )
        print(f"未知 --transport: {transport}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"连接失败 ({url}): {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"请求失败: {e}", file=sys.stderr)
        return 1


def main() -> None:
    p = argparse.ArgumentParser(
        description="查询远端 MCP 工具（默认 Streamable HTTP /mcp），riscv-doc 类服务"
    )
    p.add_argument(
        "--transport",
        choices=("sse", "http"),
        default=os.environ.get("RISCV_DOC_MCP_TRANSPORT", "http"),
        help="传输方式：http（Streamable HTTP，默认）或 sse（Server-Sent Events）",
    )
    p.add_argument(
        "--url",
        default=DEFAULT_MCP_URL,
        help="MCP 端点完整 URL（env RISCV_DOC_MCP_URL 或 config.env 配置；未配置时必须显式传入）",
    )
    p.add_argument(
        "--header",
        action="append",
        default=[],
        metavar="KEY:VALUE",
        help="附加 HTTP 头，可重复（例：--header Authorization:Bearer\\ token）",
    )
    p.add_argument(
        "--sse-read-timeout",
        type=float,
        default=300.0,
        help="SSE 读超时秒数（长查询可调大，默认 300）",
    )
    p.add_argument("--list-tools", action="store_true", help="列出服务端工具后退出")
    p.add_argument(
        "-t",
        "--tool",
        help="工具名，如 search_core_isa_manuals、search_rvv_vector_extensions、search_special_instructions、search_docs_tools",
    )
    p.add_argument("-q", "--query", help="传给工具的 query 参数（ISA/RVV 检索类工具）")
    p.add_argument(
        "--args-json",
        help='工具参数 JSON 对象字符串（与 -q 互斥时优先；例：\'{"query":"add"}\'）',
    )
    args = p.parse_args()

    if not args.url:
        print(
            "未配置 MCP 端点：请通过 --url 参数、RISCV_DOC_MCP_URL 环境变量"
            "或本技能根（${RISCV_SKILLS_ROOT}/riscv-migrate/）config.env 配置后重试",
            file=sys.stderr,
        )
        sys.exit(2)

    headers: dict[str, str] | None = None
    if args.header:
        headers = {}
        for h in args.header:
            if ":" not in h:
                print(f"无效 --header（需 KEY:VALUE）: {h}", file=sys.stderr)
                sys.exit(2)
            k, v = h.split(":", 1)
            headers[k.strip()] = v.strip()

    tool_args: dict[str, Any] = {}
    if args.args_json:
        tool_args = json.loads(args.args_json)
    elif args.query is not None:
        tool_args = {"query": args.query}
    elif args.tool and not args.list_tools:
        print("指定了 --tool 但未提供 -q/--query 或 --args-json", file=sys.stderr)
        sys.exit(2)

    code = asyncio.run(
        _run(
            transport=args.transport,
            url=args.url,
            headers=headers,
            sse_read_timeout=args.sse_read_timeout,
            list_tools=args.list_tools,
            tool_name=args.tool,
            tool_args=tool_args,
        )
    )
    raise SystemExit(code)


if __name__ == "__main__":
    main()
