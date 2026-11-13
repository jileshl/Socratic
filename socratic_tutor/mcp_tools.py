"""The app's MCP client: agents call their tools through the MCP protocol, not as plain Python functions.

Team review (13 Nov): the three MCP servers existed and were tested, but the graph called the same Python
functions directly. Now every tool call the agents make goes through an MCP client session:

- inside Docker, over streamable HTTP to each server's own service (MCP_<SERVER>_URL, for example
  MCP_TEXTBOOK_KB_URL=http://mcp-textbook:8101/mcp), as the guide asks ("HTTP inside Docker");
- elsewhere (development, tests, the evaluation harness), over the SDK's in-memory transport to the same
  server object: the same tools/list and tools/call messages, without a network.

If an HTTP server can't be reached, the call falls back to the in-memory server, and the fallback is counted
(socratic_errors_total{where="mcp_http_fallback"}) so it shows up in Grafana instead of hiding.

    call("textbook-kb", "search_textbook", {"query": "...", "top_k": 4})  ->  the tool's structured result
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import importlib
import logging
import os
from typing import Any

from mcp import Client

logger = logging.getLogger("mcp-client")

# server name -> (environment variable with its HTTP URL, module holding the server object `mcp`)
SERVERS: dict[str, tuple[str, str]] = {
    "textbook-kb": ("MCP_TEXTBOOK_KB_URL", "socratic_tutor.tools.textbook_kb_server"),
    "math-tools": ("MCP_MATH_TOOLS_URL", "socratic_tutor.tools.math_tools_server"),
    "question-bank": ("MCP_QUESTION_BANK_URL", "socratic_tutor.tools.question_bank_server"),
    "learner-store": ("MCP_LEARNER_STORE_URL", "socratic_tutor.tools.learner_store_server"),
}
_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="mcp")


def transport(server: str) -> str:
    """"http" when the server has a URL in the environment, else "in-memory"."""
    return "http" if os.getenv(SERVERS[server][0], "").strip() else "in-memory"


def _target(server: str, use_http: bool) -> Any:
    env, module = SERVERS[server]
    url = os.getenv(env, "").strip()
    if use_http and url:
        return url
    return importlib.import_module(module).mcp


async def _call(target: Any, tool: str, arguments: dict[str, Any]) -> Any:
    async with Client(target, raise_exceptions=True) as client:
        result = await client.call_tool(tool, arguments)
        if result.structured_content is not None:
            content = result.structured_content
            # FastMCP wraps a non-object return as {"result": ...}
            return content.get("result", content) if isinstance(content, dict) and set(content) == {"result"} else content
        texts = [getattr(c, "text", "") for c in (result.content or [])]
        return {"ok": not result.is_error, "text": "\n".join(t for t in texts if t)}


def _run(coro: Any) -> Any:
    # The graph runs in a worker thread with no event loop; a fresh loop in a helper thread is always safe.
    return _pool.submit(asyncio.run, coro).result(timeout=float(os.getenv("MCP_TIMEOUT_S", "30")))


def call(server: str, tool: str, arguments: dict[str, Any]) -> Any:
    """Call one tool on one MCP server and return its structured result."""
    if server not in SERVERS:
        raise ValueError(f"unknown MCP server: {server}")
    if transport(server) == "http":
        try:
            return _run(_call(_target(server, True), tool, arguments))
        except Exception as error:  # the HTTP service is down or slow: say so, then use the same server in-process
            logger.warning("mcp_http_fallback server=%s tool=%s error=%s", server, tool, type(error).__name__)
            try:
                from socratic_tutor.web import metrics

                metrics.ERRORS.labels("mcp_http_fallback").inc()
            except Exception:
                pass
    return _run(_call(_target(server, False), tool, arguments))


# ---------------------------------------------------------------------------
# The textbook tools as the graph uses them, with the same names R4's permission map knows.
# ---------------------------------------------------------------------------


def search_textbook(query: str, chapter: str | None = None, top_k: int = 4) -> list[dict[str, Any]]:
    """textbook-kb.search_textbook over MCP, as passages: [{section_id, section_title, content, citation}]."""
    args: dict[str, Any] = {"query": query, "top_k": max(1, min(int(top_k), 8))}
    if chapter:
        args["chapter"] = str(chapter)
    out = call("textbook-kb", "search_textbook", args)
    if not isinstance(out, dict) or not out.get("ok"):
        return []
    return [{"section_id": h.get("section_id"), "section_title": h.get("section_title", ""),
             "content": h.get("excerpt", ""), "citation": h.get("citation", ""),
             "chapter_num": h.get("chapter_num")} for h in out.get("hits") or []]


def get_section(section_id: str) -> dict[str, Any]:
    """textbook-kb.get_section over MCP: the whole section, or {"ok": False, "error": ...}."""
    return call("textbook-kb", "get_section", {"section_id": section_id})


def get_exemplar(exemplar_id: str) -> dict[str, Any]:
    """textbook-kb.get_exemplar over MCP: an NCERT Exemplar problem, never its solution."""
    return call("textbook-kb", "get_exemplar", {"exemplar_id": exemplar_id})
