"""MCP server exposing the ledger tools over stdio.

Nothing is redefined here. The server iterates ``tools.ALL_TOOLS`` and hands MCP the
same names, descriptions and JSON schemas the agent loop uses, so a change to a tool
reaches both surfaces at once. Point any MCP client at this module and the accounting
tools become available to it:

    uv run python -m ledger_agent.mcp_server
"""

from __future__ import annotations

import asyncio
from typing import Any

import mcp.types as types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server

from ledger_agent.tools import ALL_TOOLS, get_tool

SERVER_NAME = "ledger-agent"
SERVER_VERSION = "0.1.0"


async def on_list_tools(
    context: Any,
    params: types.PaginatedRequestParams | None,
) -> types.ListToolsResult:
    """Advertise every registered tool, schema included."""
    return types.ListToolsResult(
        tools=[
            types.Tool(
                name=tool.name,
                description=tool.description,
                input_schema=tool.input_schema,
            )
            for tool in ALL_TOOLS
        ]
    )


async def on_call_tool(
    context: Any,
    params: types.CallToolRequestParams,
) -> types.CallToolResult:
    """Dispatch to the handler.

    A handler that raises would surface to the client as a transport error, which reads
    as "the server is broken" rather than "your arguments were wrong". Everything comes
    back as text the caller can act on instead, with ``is_error`` distinguishing the two.
    """
    tool = get_tool(params.name)
    if tool is None:
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=f"ERROR: unknown tool '{params.name}'.")],
            is_error=True,
        )

    try:
        output = tool.handler(dict(params.arguments or {}))
        is_error = False
    except Exception as exc:  # reported to the caller, not the transport
        output = f"ERROR: {type(exc).__name__}: {exc}"
        is_error = True

    return types.CallToolResult(
        content=[types.TextContent(type="text", text=output)],
        is_error=is_error,
    )


def build_server() -> Server[None]:
    """Construct the server with both handlers wired in."""
    return Server(
        SERVER_NAME,
        version=SERVER_VERSION,
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )


async def main() -> None:
    """Serve over stdio until the client disconnects."""
    server = build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name=SERVER_NAME,
                server_version=SERVER_VERSION,
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
