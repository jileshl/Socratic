"""Write docs/mcp_tool_list.json: every MCP tool with its read/write mark, description and schemas.

This is the evidence the capstone guide asks for at the final review: "a tool list with schemas
and one test per tool" (capstone guide p.3, minimum bar, row L7). The tests are in tests/.
Add each new server to SERVERS below as it is built.

Run from the repository root:
    python scripts/export_tool_list.py
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

# Make the project importable when this file is run as a script from the repository root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from mcp import Client  # noqa: E402  (imported after the path fix above)

from socratic_tutor.tools import math_tools_server  # noqa: E402

# Every MCP server in the project: name -> server object.
SERVERS: dict[str, Any] = {
    "math-tools": math_tools_server.mcp,
}

OUTPUT_FILE = PROJECT_ROOT / "docs" / "mcp_tool_list.json"


async def list_server_tools(server_name: str, server: Any) -> list[dict[str, Any]]:
    """Ask one server for its tools (the MCP "tools/list" call) and describe each one."""
    entries: list[dict[str, Any]] = []
    async with Client(server) as client:
        listing = await client.list_tools()
    for tool in listing.tools:
        # A tool is "read" only if it is marked read-only; anything else counts as "write".
        access = "write"
        if tool.annotations is not None and tool.annotations.read_only_hint is True:
            access = "read"
        entries.append({
            "server": server_name,
            "tool": tool.name,
            "access": access,
            "description": tool.description,
            "input_schema": tool.input_schema,
            "output_schema": tool.output_schema,
        })
    return entries


def main() -> None:
    """Collect the tools of every server and write them to docs/mcp_tool_list.json."""
    all_tools: list[dict[str, Any]] = []
    for server_name in SERVERS:
        all_tools.extend(asyncio.run(list_server_tools(server_name, SERVERS[server_name])))
    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(all_tools, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Wrote " + str(len(all_tools)) + " tools to " + str(OUTPUT_FILE.relative_to(PROJECT_ROOT)))


if __name__ == "__main__":
    main()
