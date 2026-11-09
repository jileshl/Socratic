"""Write docs/mcp_tool_list.json: every MCP tool with its read/write mark, description and schemas.

This is the evidence the capstone guide asks for at the final review: "a tool list with schemas
and one test per tool" (capstone guide p.3, minimum bar, row L7). The tests are in tests/.
Add each new server to SERVERS below as it is built.

The file goes into config.DOCS_DIR, which is docs/ unless DOCS_DIR is set in .env. A relative
DOCS_DIR is read relative to the repository, the same way as DATA_DIR.

Run from the repository root, like the other scripts:
    PowerShell:  $env:PYTHONPATH = "."; python scripts/export_tool_list.py
    bash:        PYTHONPATH=. python scripts/export_tool_list.py
"""

# [X0] Every import is at the top. The script doesn't change Python's import path itself:
# PYTHONPATH=. (see above) is what lets Python find the socratic_tutor package.
import asyncio
import json
from pathlib import Path
from typing import Any

from mcp import Client

from socratic_tutor import config
from socratic_tutor.tools import math_tools_server

# Every MCP server in the project: name -> server object.
SERVERS: dict[str, Any] = {
    "math-tools": math_tools_server.mcp,
}

# [X2] The output folder comes from config.py, so all paths are set in one place.
OUTPUT_FILE: Path = config.DOCS_DIR / "mcp_tool_list.json"


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


def shown_path(path: Path) -> str:
    """Show a path relative to the repository when it is inside it (docs/...), and in full otherwise."""
    # A DOCS_DIR set in .env may point outside the repository, where relative_to() would raise an error.
    if path.is_relative_to(config.BASE_DIR):
        return str(path.relative_to(config.BASE_DIR))
    return str(path)


def main() -> None:
    """Collect the tools of every server and write them to mcp_tool_list.json in config.DOCS_DIR."""
    # Flowchart (each [box] matches a comment in the code):
    #
    #   [X0] imports at the top (module level)
    #          |
    #          v
    #   [X1] ask every server in SERVERS for its tools
    #          |
    #          v
    #   [X2] output file = config.DOCS_DIR / "mcp_tool_list.json" (module level)
    #          |
    #          v
    #   [X3] create the folder if needed, write the file, print where it went

    # [X1] ask every server for its tools, one server after another.
    all_tools: list[dict[str, Any]] = []
    for server_name in SERVERS:
        all_tools.extend(asyncio.run(list_server_tools(server_name, SERVERS[server_name])))

    # [X3] parents=True also creates a configured folder whose parent folders don't exist yet.
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(all_tools, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Wrote " + str(len(all_tools)) + " tools to " + shown_path(OUTPUT_FILE))


if __name__ == "__main__":
    main()
