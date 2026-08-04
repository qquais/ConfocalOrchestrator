# server.py
# ------------------------------------------------------------
# MCP server entry point: registers acquisition_tools.py's functions as
# MCP tools over stdio, so an MCP client (e.g. Claude Desktop, an LLM
# agent) can call them.
#
# Run (from the repo root, with .venv activated):
#   python -m mcp_server.server
# ------------------------------------------------------------

import sys
from pathlib import Path

# Guarantee the repo root is importable (so `acquisition.*` resolves) even
# if this is launched as a plain script rather than via `-m` from the repo
# root - e.g. by an MCP client that invokes it with an absolute path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.mcpserver import MCPServer

from mcp_server import acquisition_tools as tools

mcp = MCPServer("ConfocalOrchestrator")

# Read-only tools (no safety gate)
mcp.add_tool(tools.get_position)
mcp.add_tool(tools.list_saved_positions)
mcp.add_tool(tools.compute_sharpness)
mcp.add_tool(tools.check_focus_drift)
mcp.add_tool(tools.get_live_status)
mcp.add_tool(tools.save_current)

# Move/write tools - backend="mock" by default, backend="sdk" requires confirm=True
mcp.add_tool(tools.move_xy_absolute)
mcp.add_tool(tools.move_z_absolute)
mcp.add_tool(tools.move_xy_relative)
mcp.add_tool(tools.move_z_relative)
mcp.add_tool(tools.go_to_saved_position)

# Write tools with no hardware contact (no safety gate)
mcp.add_tool(tools.define_position)
mcp.add_tool(tools.load_positions_from_yaml)
mcp.add_tool(tools.delete_saved_position)


if __name__ == "__main__":
    mcp.run(transport="stdio")
