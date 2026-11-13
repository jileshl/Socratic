"""How every MCP server in this project runs: stdio for development, streamable HTTP inside Docker.

The capstone guide (p.5): "Use stdio during development and HTTP inside Docker."

    python -m socratic_tutor.tools.textbook_kb_server               # stdio (an MCP client starts it)
    python -m socratic_tutor.tools.textbook_kb_server --http 8101   # HTTP at http://<host>:8101/mcp

Inside Docker Compose each server is its own service, and the app reaches it at the URL in its environment
(MCP_TEXTBOOK_KB_URL and so on; see socratic_tutor/mcp_tools.py).
"""

from __future__ import annotations

import argparse
import os
from typing import Any

from mcp.server.transport_security import TransportSecuritySettings


def main(mcp: Any) -> None:
    parser = argparse.ArgumentParser(description=f"Run the {getattr(mcp, 'name', 'MCP')} server")
    parser.add_argument("--http", type=int, metavar="PORT", help="serve streamable HTTP on this port instead of stdio")
    parser.add_argument("--host", default=os.getenv("MCP_HOST", "0.0.0.0"))
    args = parser.parse_args()
    if args.http is None:
        mcp.run(transport="stdio")
        return
    # Inside the Compose network the app calls us by service name (for example http://mcp-textbook:8101/mcp).
    # The host check guards a browser on the same machine against DNS rebinding; only the app's names may call.
    allowed = [h.strip() for h in os.getenv("MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=bool(allowed),
        allowed_hosts=[f"{h}:{args.http}" for h in allowed] + allowed,
    )
    mcp.run(transport="streamable-http", host=args.host, port=args.http, stateless_http=True,
            transport_security=security)
