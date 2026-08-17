# loop_tools.py
# ------------------------------------------------------------
# Minimal 3-tool MCP surface for the normal agent control loop:
#   get_image()  - capture + the stage position that goes with it
#   get_pos()    - a lightweight, on-demand position sync primitive
#   move()       - move XY, return the ACTUAL resulting position
#
# NOT wired into server.py yet - deliberately kept separate so it can be
# tried/registered independently of the existing acquisition_tools.py
# tool set. See mcp.add_tool(...) calls in server.py for the pattern to
# follow when ready.
#
# WHY THIS SHAPE (design discussion with the team, 2026-08-17):
# Stage position is volatile physical state - if it's pushed into the
# model's context continuously (e.g. injected into the system prompt),
# the model's belief about "where the stage is" can go stale between
# inference and action (a human bumps the joystick, another process
# moves it, etc.), and the model acts on a position that's no longer
# true. The fix is to stop treating position as ambient context and
# instead attach it as a return value on the calls that already touch
# it - get_image() and move() both return the position they observed,
# so the model rarely needs to call get_pos() at all. get_pos() is
# there mainly as an explicit sync primitive: call it when a human/
# other process may have moved the stage, when enough time has passed
# that cached state might be stale, or when you want position without
# paying for a full image capture.
#
# WHY NO get_time(): wall-clock time is something the agent/runtime
# already knows - no reason to ask the microscope for it. What matters
# is DEVICE/EVENT time (when was this physical fact true), so that's
# attached as metadata on every call instead (measured_at/captured_at,
# ISO-8601 wall clock; monotonic_ms, so "218ms after this image" style
# reasoning isn't thrown off by clock corrections).
#
# WHY NO stage_revision (yet): a monotonic counter that increments on
# every physical stage move (from any actor) would let a server detect
# "the agent's cached position is stale" without a full get_pos(), and
# would let move() take an optional expected_revision to reject a move
# if the stage changed since the agent last looked. That mainly earns
# its cost for RELATIVE moves (dx/dy - the operation depends on the
# stage still being where the agent thinks it is) - this move() is
# absolute-only, so it buys little today. Left out until concurrent-
# control/race-condition problems actually show up; see get_pos()'s
# docstring for the intended trigger conditions.
#
# WHY move() IS XY-ONLY (not x/y/z like the original 3-function sketch):
# acquisition_tools.py already establishes - deliberately - that a
# blind absolute Z move must never be reachable from a chat prompt (risk
# of crashing the objective into the sample); move_z_absolute exists
# there for internal/scripted use only and is never registered as an
# MCP tool. This file keeps that same boundary rather than reintroducing
# it via a combined x/y/z move(). Z is out of scope here - use
# acquisition_tools.nudge_focus_offset (PFS-based, range-capped) if a
# tool needs to touch focus.
#
# WHY get_image() REQUIRES confirm=True: unlike the other two tools, it
# fires real hardware (camera/light path via NIS-Elements) with a
# physical side effect - same safety-gate pattern used elsewhere in this
# repo for anything that touches real hardware, even when (as here)
# there's no backend="mock" equivalent to fall back to.
# ------------------------------------------------------------

from datetime import datetime
from time import monotonic

from acquisition.backends.nis_jobs_trigger import TRIGGER_TIMEOUT_SEC, trigger_capture
from acquisition.orchestration.stage_positions import to_plain_float
from mcp_server import acquisition_tools as _acq


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def get_pos(backend: str = "mock") -> dict:
    """Return the current stage (x, y, z) position, in microns - a cheap,
    on-demand sync primitive rather than something to call before every
    move.

    Reach for this when: a human may have moved the stage (joystick),
    another controller/process may have moved it, enough time has passed
    that a previously-observed position might be stale, or you want
    position without paying for a full get_image() capture. During
    normal operation, get_image() and move() already return position as
    part of their result, so most loops don't need this at all.

    backend: "mock" (default, safe) or "sdk" (real hardware). Read-only -
    no confirmation required for either backend.
    """
    nis = _acq._get_backend(backend)
    x, y = nis.XY_GetPosition()
    z = nis.Z_GetPosition()
    return {
        "position": {"x": to_plain_float(x), "y": to_plain_float(y), "z": to_plain_float(z)},
        "measured_at": _now_iso(),
        "monotonic_ms": int(monotonic() * 1000),
        "backend": backend,
    }


def move(x: float, y: float, backend: str = "mock", confirm: bool = False) -> dict:
    """Move the XY stage to an absolute (x, y) position, in microns, and
    return the ACTUAL resulting position - not merely "success". A real
    move commonly lands slightly off the requested target, so callers
    should treat the returned position as ground truth, not an echo of
    the input.

    Z is intentionally not accepted here - see this file's header
    comment for why absolute Z stays out of the chat-reachable surface.

    backend: "mock" (default, safe) or "sdk" (real hardware - requires
    confirm=True, same gate as every other move tool in this repo).
    """
    _acq._require_confirm_for_sdk(backend, confirm)
    nis = _acq._get_backend(backend)

    started_at = _now_iso()
    nis.XY_Move(x, y)
    new_x, new_y = nis.XY_GetPosition()
    z = nis.Z_GetPosition()
    completed_at = _now_iso()

    return {
        "position": {"x": to_plain_float(new_x), "y": to_plain_float(new_y), "z": to_plain_float(z)},
        "started_at": started_at,
        "completed_at": completed_at,
        "backend": backend,
    }


def get_image(project: str, job: str, confirm: bool = False, timeout_sec: float = TRIGGER_TIMEOUT_SEC) -> dict:
    """Trigger a real capture via the NIS-Elements Job named by
    `project`/`job` (see acquisition.backends.nis_jobs_trigger.trigger_capture
    for the underlying mechanism/caveats) and return it together with the
    exact stage position associated with it - read immediately after the
    capture completes, so the two stay coupled without the model needing
    a separate get_pos() call.

    project, job: exact Project/Job names as they exist in NIS's own Jobs
        database (case-sensitive) - no default, so a typo/stale value
        fails loudly instead of silently triggering the wrong Job.

    Real hardware only (no mock equivalent - there's nothing to simulate
    a camera/light path trigger against) - requires confirm=True, same
    safety-gate pattern as every other real-hardware-touching tool in
    this repo. Position is always read via backend="sdk" here, since a
    live capture only ever happens on the real microscope.

    Raises RuntimeError if no fresh capture appears within timeout_sec -
    see trigger_capture's docstring for what that can mean.
    """
    if not confirm:
        raise PermissionError(
            "get_image triggers a real microscope capture (camera/light "
            "path) and requires confirm=True. Refusing to proceed without "
            "explicit confirmation."
        )

    result = trigger_capture(project, job, timeout_sec=timeout_sec)
    pos = get_pos(backend="sdk")

    return {
        "image": {name: str(path) for name, path in result["paths"].items()},
        "shape": result["shape"],
        "dtype": result["dtype"],
        "pixel_size_um_per_px": result["pixel_size_um_per_px"],
        "position": pos["position"],
        "captured_at": pos["measured_at"],
        "monotonic_ms": pos["monotonic_ms"],
    }
