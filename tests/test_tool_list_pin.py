"""Pin test for the MCP tool list (threat model, row T3: a poisoned tool description or result).

The lecture's defence against a poisoned tool is "pin and review" (AAI-15-2.pdf p.15, p.17). We keep a saved
copy of every tool's name, description, read/write mark and schemas (docs/mcp_tool_list.json), and this test
fails when the live servers differ from it. So any change to a tool must be re-exported, and then it shows up
as a diff of that file in the PR, where a person reviews it. The test can't tell a good change from a bad one:
the reviewer does that. The pin covers only what the export saves: it doesn't cover a server's instructions,
a tool's title, or annotations other than the read-only mark.

The live list comes from scripts/export_tool_list.py, so the servers are listed in one place only. Like
tests/test_math_tools_server.py, it talks to each server in-process with the SDK's Client (the MCP "tools/list"
call of the Lecture 7 hands-on client) and uses asyncio.run inside ordinary test functions.

Flowchart (each [box] matches a comment in the code):

    test_the_tool_list_matches_the_saved_file
      [T0] load scripts/export_tool_list.py by its path (scripts/ isn't a package)
      [T1] ask every server in its SERVERS for its tools
      [T2] read the saved docs/mcp_tool_list.json
      [T3] same tools, same order, same description, read/write mark and schemas?
             yes -> pass;  no -> fail, naming each "server/tool (field)" that differs

    test_every_server_file_is_in_the_export_list
      [S1] find socratic_tutor/tools/*_server.py
      [S2] is each file's server object one of SERVERS' values?   no -> fail, naming the file
"""

import asyncio
import importlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

from socratic_tutor import config

# The export script that writes docs/mcp_tool_list.json, and the folder that holds every MCP server file.
EXPORT_SCRIPT: Path = config.BASE_DIR / "scripts" / "export_tool_list.py"
TOOLS_FOLDER: Path = config.BASE_DIR / "socratic_tutor" / "tools"
# The pinned copy is the file in the repository. The export writes to config.DOCS_DIR, which a local .env can
# move elsewhere, so the test never reads that setting: a moved DOCS_DIR must not hide a changed pinned file.
PINNED_FILE: Path = config.BASE_DIR / "docs" / "mcp_tool_list.json"
# The fields of one saved entry, in the order the export script writes them.
ENTRY_FIELDS: list[str] = ["server", "tool", "access", "description", "input_schema", "output_schema"]
# What to do when the test fails: the same advice in every failure message.
HOW_TO_FIX: str = ("Re-run scripts/export_tool_list.py (with DOCS_DIR unset, so it writes docs/) and review the diff "
                   "of docs/mcp_tool_list.json in the PR.")


def load_export_script() -> ModuleType:
    """[T0] Load scripts/export_tool_list.py by its path: scripts/ isn't a package, so it can't be imported by name."""
    # Describe where the module's file is; the name is only used inside this test.
    spec = importlib.util.spec_from_file_location("export_tool_list", EXPORT_SCRIPT)
    # A missing file gives no spec (or no loader), and then nothing below could run.
    assert spec is not None and spec.loader is not None, "Cannot load " + str(EXPORT_SCRIPT)
    # Make an empty module from the description, then run the script's top level into it.
    module: ModuleType = importlib.util.module_from_spec(spec)
    # Running it defines SERVERS, list_server_tools and OUTPUT_FILE. main() doesn't run, so nothing is written.
    spec.loader.exec_module(module)
    return module


def live_tool_list(export: ModuleType) -> list[dict[str, Any]]:
    """[T1] Ask every server in the script's SERVERS for its tools, exactly the way the export does."""
    entries: list[dict[str, Any]] = []
    # One server after another, in the order of SERVERS (the order the saved file has).
    for server_name in export.SERVERS:
        # The script's own "tools/list" helper is asynchronous, so run it to the end here.
        server_entries: list[dict[str, Any]] = asyncio.run(
            export.list_server_tools(server_name, export.SERVERS[server_name])
        )
        # Keep this server's tools after the ones already collected.
        entries.extend(server_entries)
    return entries


def saved_tool_list() -> list[dict[str, Any]]:
    """[T2] The tool list pinned in the repository's docs/mcp_tool_list.json."""
    # Always the repository's copy, whatever DOCS_DIR says (see PINNED_FILE).
    text: str = PINNED_FILE.read_text(encoding="utf-8")
    # The file is one JSON list with one entry per tool.
    saved: list[dict[str, Any]] = json.loads(text)
    return saved


def label(entry: dict[str, Any]) -> str:
    """'server/tool' for a failure message, e.g. 'question-bank/propose_question'."""
    # str() keeps the message readable even if a saved entry lacks one of the two keys.
    return str(entry.get("server")) + "/" + str(entry.get("tool"))


def differences(live: list[dict[str, Any]], saved: list[dict[str, Any]]) -> list[str]:
    """[T3] Every difference between the two lists as 'server/tool (field)', plus tools found on one side only."""
    found: list[str] = []
    # Look up each saved entry by its "server/tool" label.
    saved_by_label: dict[str, dict[str, Any]] = {}
    for entry in saved:
        saved_by_label[label(entry)] = entry
    # The labels of the live tools, for the "saved but gone" check at the end.
    live_labels: list[str] = []
    for entry in live:
        entry_label: str = label(entry)
        live_labels.append(entry_label)
        # A tool that the saved file doesn't have: it was added without re-exporting.
        if entry_label not in saved_by_label:
            found.append(entry_label + " (new tool, not in the saved file)")
            continue
        # The same tool on both sides: compare it field by field, so the message says what changed.
        for field in ENTRY_FIELDS:
            if entry.get(field) != saved_by_label[entry_label].get(field):
                found.append(entry_label + " (" + field + ")")
    # A tool that the saved file has but no server lists any more: it was removed without re-exporting.
    for saved_label in saved_by_label:
        if saved_label not in live_labels:
            found.append(saved_label + " (in the saved file, but no server lists it)")
    return found


def test_the_tool_list_matches_the_saved_file() -> None:
    """[T0]-[T3] The live tools equal docs/mcp_tool_list.json: names, descriptions, read/write marks and schemas."""
    # [T0] the export script, with its list of servers
    export: ModuleType = load_export_script()
    # [T1] what the servers say about their tools right now
    live: list[dict[str, Any]] = live_tool_list(export)
    # [T2] what the pinned file in the repository says
    saved: list[dict[str, Any]] = saved_tool_list()
    # An empty live list would make the comparison meaningless, so there must be tools to compare.
    assert live != [], "No server listed any tools; is SERVERS empty?"
    # [T3] first name each tool and field that differs, so a failure says exactly what changed ...
    found: list[str] = differences(live, saved)
    assert found == [], "These tools differ from docs/mcp_tool_list.json: " + "; ".join(found) + ". " + HOW_TO_FIX
    # ... then compare the whole lists: this also catches a changed order, or an extra field in a saved entry.
    assert live == saved, "Same tools, but the order or the saved fields differ. " + HOW_TO_FIX


def test_every_server_file_is_in_the_export_list() -> None:
    """[S1]-[S2] A server that the export doesn't list isn't pinned either, so every *_server.py must be in SERVERS."""
    export: ModuleType = load_export_script()
    # [S1] every MCP server file in the tools folder, in a fixed order
    server_files: list[Path] = sorted(TOOLS_FOLDER.glob("*_server.py"))
    # A wrong folder would find nothing and pass without checking anything.
    assert server_files != [], "No *_server.py files found in " + str(TOOLS_FOLDER)
    missing: list[str] = []
    for path in server_files:
        # [S2] import the file the normal way (the same module object the export script imported) ...
        module: ModuleType = importlib.import_module("socratic_tutor.tools." + path.stem)
        # ... take its server object (None when the file has no `mcp`) ...
        server: Any = getattr(module, "mcp", None)
        # ... and look for that very object among SERVERS' values.
        listed: bool = False
        for server_name in export.SERVERS:
            if export.SERVERS[server_name] is server:
                listed = True
        # Not listed: its tools never reach the saved file, so nobody would see them change.
        if not listed:
            missing.append(path.name)
    assert missing == [], ("These server files are not in SERVERS in scripts/export_tool_list.py, so their tools are "
                           "not pinned: " + ", ".join(missing) + ". Add them to SERVERS. " + HOW_TO_FIX)
