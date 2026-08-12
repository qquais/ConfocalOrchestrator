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
from mcp_server import analysis_tools as analysis

mcp = MCPServer("ConfocalOrchestrator")

# ── Acquisition tools (control/read the microscope stage) ───────────────

# Read-only tools (no safety gate)
mcp.add_tool(tools.get_position)
mcp.add_tool(tools.list_saved_positions)
mcp.add_tool(tools.compute_sharpness)
mcp.add_tool(tools.check_focus_drift)
mcp.add_tool(tools.get_live_status)
mcp.add_tool(tools.save_current)
mcp.add_tool(tools.get_pfs_status)

# Move/write tools - backend="mock" by default, backend="sdk" requires confirm=True.
# move_z_absolute/move_z_relative are deliberately NOT registered here - a
# blind absolute Z jump risks crashing the objective into the sample, and
# that action simply shouldn't be reachable from a chat prompt. Use
# nudge_focus_offset instead: it only fine-tunes an already-engaged PFS
# hardware focus lock by a small, range-capped amount. See this file's
# and acquisition_tools.py's top-of-file comments for the full rationale.
mcp.add_tool(tools.move_xy_absolute)
mcp.add_tool(tools.move_xy_relative)
mcp.add_tool(tools.go_to_saved_position)
mcp.add_tool(tools.nudge_focus_offset)
mcp.add_tool(tools.start_protocol_run)
mcp.add_tool(tools.abort_run)

# Write tools with no hardware contact (no safety gate)
mcp.add_tool(tools.define_position)
mcp.add_tool(tools.load_positions_from_yaml)
mcp.add_tool(tools.delete_saved_position)

# Imaging profile tools - SDK/real-hardware only, no mock equivalent.
# list/delete are pure file operations (no gate); save reads hardware
# read-only (no gate, same rationale as save_current); apply physically
# moves the turret/filter wheels and requires confirm=True.
mcp.add_tool(tools.list_imaging_profiles)
mcp.add_tool(tools.save_imaging_profile)
mcp.add_tool(tools.apply_imaging_profile)
mcp.add_tool(tools.delete_imaging_profile)

# ── Analysis tools (post-acquisition image processing, no hardware) ─────

# Read-only
mcp.add_tool(analysis.inspect_nd2_metadata)

# Conversion / extraction
mcp.add_tool(analysis.convert_nd2_to_ometiff)
mcp.add_tool(analysis.extract_nd2_frames)

# Preprocessing / segmentation
mcp.add_tool(analysis.preprocess_frame)
mcp.add_tool(analysis.segment_nuclei_image)

# Shape-metrics / tracking pipelines
mcp.add_tool(analysis.compute_shape_metrics)
mcp.add_tool(analysis.track_nuclei_sequence)

# Cross-sequence analysis
mcp.add_tool(analysis.analyze_synchronization)
mcp.add_tool(analysis.compare_trajectory_sequences)

# Validation / inspection (compare pipeline output against reference data)
mcp.add_tool(analysis.check_preprocessing_quality)
mcp.add_tool(analysis.compare_trackmate)


if __name__ == "__main__":
    mcp.run(transport="stdio")
