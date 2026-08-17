# server_loop.py
# ------------------------------------------------------------
# Minimal MCP server entry point: registers ONLY loop_tools.py's 3
# functions (get_image, get_pos, move) - none of acquisition_tools.py's
# or analysis_tools.py's tools. Separate from server.py on purpose, so
# the 3-tool agent-loop design (see loop_tools.py's header comment) can
# be tried against a real MCP client in isolation, without touching the
# already-working server.py / its tool set.
#
# Run (from the repo root, with .venv activated):
#   python -m mcp_server.server_loop
# ------------------------------------------------------------

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.mcpserver import MCPServer

from mcp_server import loop_tools as tools

mcp = MCPServer("ConfocalOrchestrator-Loop")

mcp.add_tool(tools.get_image)
mcp.add_tool(tools.get_pos)
mcp.add_tool(tools.move)


if __name__ == "__main__":
    mcp.run(transport="stdio")
