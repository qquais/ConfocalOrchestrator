# loop_tools.py
# ------------------------------------------------------------
# Minimal MCP surface for the normal agent control loop:
#   get_image()         - capture + the stage position that goes with it
#   get_pos()            - a lightweight, on-demand position sync primitive
#   move()               - move XY, return the ACTUAL resulting position
#   get_move_history()   - every point move() has visited this session
#
# NOT wired into server.py yet - deliberately kept separate so it can be
# tried/registered independently of the existing acquisition_tools.py
# tool set. See mcp.add_tool(...) calls in server.py for the pattern to
# follow when ready.
#
# NO NIS-ELEMENTS ANYWHERE IN THIS FILE (2026-08-17, explicit team
# decision - manager does not want capture going through NIS): get_image()
# captures via acquisition.backends.baumer_genicam.BaumerGenICam - a
# GenICam/GenTL camera reached directly through the `harvesters` library,
# no NIS-Elements process, no Jobs, no nis_ar.exe. get_pos()/move() were
# already NIS-Elements-independent for real hardware (backend="sdk" talks
# to the Ti2 ActiveX SDK directly - Nikon-approved, does not require
# NIS-Elements to be running); backend="mock" falls back to nis_mock.
# MockNIS for offline dev, which also has no NIS-Elements dependency (see
# stage_positions.py - `import nis` only ever succeeds inside NIS-
# Elements' own bundled Python, never from this repo's .venv). So nothing
# in this file's real-hardware path touches NIS-Elements software at all.
#
# WHY get_move_history(): move() already returns the resulting position
# of ONE move - this answers "where has the stage actually been", e.g.
# "did I already image this area" or "what path did I take to get here"
# without the model needing to remember/re-derive it turn over turn.
# Every move() call appends one record (requested target, actual
# resulting position, timestamps, backend) to logs/move_history.jsonl -
# append-only, one JSON object per line, so concurrent/repeated runs
# never need a read-modify-write of the whole file (unlike
# stage_positions.py's saved-positions file, which IS fully rewritten
# per change - that's fine there because it's small/keyed by label, not
# an ever-growing log). This is a plain history log, not the same thing
# as StagePositionManager's saved/named positions - nothing here is
# deduplicated or labeled, it's every move, in order.
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
# WHY get_image() REQUIRES confirm=True: unlike get_pos()/move(), it
# fires a real camera - same safety-gate pattern used elsewhere in this
# repo for anything that touches real hardware, even when (as here)
# there's no backend="mock" equivalent to fall back to.
# ------------------------------------------------------------

import json
import threading
from datetime import datetime
from pathlib import Path
from time import monotonic

from acquisition.backends.baumer_genicam import BaumerGenICam
from acquisition.orchestration.stage_positions import to_plain_float
from mcp_server import acquisition_tools as _acq

REPO_ROOT = Path(__file__).resolve().parent.parent
MOVE_HISTORY_PATH = REPO_ROOT / "logs" / "move_history.jsonl"

# Persistent camera connection, opened lazily on the first get_image()
# call and reused after that - matches nis_sdk.py's pattern for the
# stage connection (constructing BaumerGenICam() is not cheap: it opens
# the GenTL producer, enumerates devices, and starts continuous
# acquisition - see that class's __init__). A camera can only be held
# open by one process at a time, so this also means: close any other
# GenICam consumer (Baumer Camera Explorer, etc.) before the first call.
_camera: "BaumerGenICam | None" = None
_camera_lock = threading.Lock()


def _get_camera() -> BaumerGenICam:
    global _camera
    with _camera_lock:
        if _camera is None:
            _camera = BaumerGenICam()
        return _camera


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _append_move_history(record: dict) -> None:
    """Append one move record as a single JSON line to MOVE_HISTORY_PATH.

    Append-only by design (see this file's header) - never reads or
    rewrites prior entries, so this stays cheap regardless of how long
    the history grows.
    """
    MOVE_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MOVE_HISTORY_PATH, "a") as f:
        f.write(json.dumps(record) + "\n")


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

    result = {
        "position": {"x": to_plain_float(new_x), "y": to_plain_float(new_y), "z": to_plain_float(z)},
        "started_at": started_at,
        "completed_at": completed_at,
        "backend": backend,
    }
    _append_move_history({
        "requested": {"x": to_plain_float(x), "y": to_plain_float(y)},
        **result,
    })
    return result


def get_image(
    confirm: bool = False,
    exposure_time_us: float | None = None,
    gain: float | None = None,
) -> dict:
    """Grab one frame from the Baumer GenICam camera (see
    acquisition.backends.baumer_genicam.BaumerGenICam) and return it
    together with the exact stage position associated with it - read
    immediately after the frame is captured, so the two stay coupled
    without the model needing a separate get_pos() call.

    No NIS-Elements involved - connects directly to the camera via its
    GenTL producer (see BaumerGenICam/find_cti_files), independent of any
    NIS-Elements process. Real hardware only (no mock equivalent - there's
    nothing to simulate a camera trigger against) - requires confirm=True,
    same safety-gate pattern as every other real-hardware-touching tool in
    this repo. Position is read via backend="sdk" (Ti2 ActiveX SDK), the
    same NIS-Elements-independent hardware path move()/get_pos() use.

    exposure_time_us, gain: optional - if given, applied via
    BaumerGenICam.set_settings() before capturing (raises ValueError if
    outside the camera's own reported valid range - see that method's
    docstring for confirmed ranges/units, notably that "gain" is the
    camera's own unit-less scale, not dB). Omit either to leave it at
    whatever the camera is already set to (persists across calls, since
    the camera connection - and therefore its settings - is reused, not
    reopened, between get_image() calls).

    The saved image is real RGB (demosaiced from the sensor's raw
    BayerRG8 via BaumerGenICam.capture()) - see that method's docstring
    for the one unconfirmed detail (which Bayer color code is actually
    correct for this camera).
    """
    if not confirm:
        raise PermissionError(
            "get_image fires a real camera and requires confirm=True. "
            "Refusing to proceed without explicit confirmation."
        )

    camera = _get_camera()
    if exposure_time_us is not None or gain is not None:
        camera.set_settings(exposure_time_us=exposure_time_us, gain=gain)
    image_path = camera.capture()
    pos = get_pos(backend="sdk")

    return {
        "image": str(image_path),
        "position": pos["position"],
        "captured_at": pos["measured_at"],
        "monotonic_ms": pos["monotonic_ms"],
    }


def get_move_history(limit: int = 50) -> dict:
    """Return the most recent points move() has actually moved the stage
    to, oldest-first, each with its requested target, actual resulting
    position, and timestamps - so "where has this session already been"
    doesn't need to be remembered/re-derived turn over turn.

    limit: max number of most-recent records to return (default 50) -
    the log file itself is never truncated, only what's returned here.

    Returns {"history": [...], "returned": N, "total_moves": M} - total_moves
    lets the caller tell "you're seeing the last 50 of 300" apart from
    "you're seeing everything there is".
    """
    if not MOVE_HISTORY_PATH.exists():
        return {"history": [], "returned": 0, "total_moves": 0}

    with open(MOVE_HISTORY_PATH, "r") as f:
        lines = [line for line in f if line.strip()]

    records = [json.loads(line) for line in lines[-limit:]]
    return {"history": records, "returned": len(records), "total_moves": len(lines)}
