# acquisition_tools.py
# ------------------------------------------------------------
# Tool implementations for the ConfocalOrchestrator MCP server. Each
# function below is registered as an MCP tool in server.py.
#
# SAFETY GATE (non-negotiable - this controls real hardware):
# Every tool that can move the stage defaults to backend="mock" and
# raises a clear PermissionError if backend="sdk" is requested without
# confirm=True. There is no silent fallback - see _require_confirm_for_sdk().
# Read-only tools (get_position, list_saved_positions, compute_sharpness,
# check_focus_drift, get_live_status) and save_current (reads hardware but
# never moves it) are ungated.
#
# Z FOCUS: move_z_absolute/move_z_relative exist below for internal/
# scripted use (e.g. run_protocol.py) but are deliberately NOT registered
# as MCP tools in server.py - a blind absolute Z jump risks crashing the
# objective into the sample, and that action simply isn't reachable from
# a chat prompt. nudge_focus_offset() is the MCP-exposed alternative: it
# only fine-tunes an already-engaged PFS hardware focus lock by a small,
# range-capped amount (see nis_sdk.PFS_MAX_OFFSET_STEP_FRACTION), so it
# can't blindly jump focus from an arbitrary starting position.
#
# Image capture is intentionally NOT exposed here - acquisition/planned/
# nis_jobs_capture.py is unconfirmed/non-functional prep material.
# ------------------------------------------------------------

import json
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

from acquisition.monitoring.focus_check import compute_sharpness as _compute_sharpness
from acquisition.orchestration.stage_positions import StagePositionManager

DASHBOARD_STATUS_URL = "http://localhost:8000/status"


def _get_backend(backend: str):
    """Instantiate the stage backend named by `backend` ("mock" or "sdk").

    No safety gate here - only for use by read-only callers. Move/write
    tools must call _require_confirm_for_sdk() first.
    """
    if backend == "mock":
        from acquisition.backends.nis_mock import MockNIS
        return MockNIS()
    elif backend == "sdk":
        from acquisition.backends.nis_sdk import NISSdk
        return NISSdk()
    raise ValueError(f"Unknown backend '{backend}'. Expected 'mock' or 'sdk'.")


def _require_confirm_for_sdk(backend: str, confirm: bool) -> None:
    """Raise PermissionError if `backend` is "sdk" and `confirm` is not True.

    This is the safety gate for every tool that can move real hardware -
    it must be called before any stage motion, never bypassed with a
    silent fallback to mock.
    """
    if backend not in ("mock", "sdk"):
        raise ValueError(f"Unknown backend '{backend}'. Expected 'mock' or 'sdk'.")
    if backend == "sdk" and not confirm:
        raise PermissionError(
            "backend='sdk' controls real microscope hardware and requires "
            "confirm=True. Refusing to proceed without explicit confirmation."
        )


# ── Read-only tools ──────────────────────────────────────────────────────


def get_position(backend: str = "mock") -> dict:
    """Return the current stage (x, y, z) position, in microns.

    backend: "mock" (default, safe) or "sdk" (real hardware). Read-only -
    no confirmation required for either backend.
    """
    nis = _get_backend(backend)
    x, y = nis.XY_GetPosition()
    z = nis.Z_GetPosition()
    return {"x": x, "y": y, "z": z, "backend": backend}


def list_saved_positions() -> dict:
    """Return all saved stage positions as {label: {"x", "y", "z"}}.

    Reads only from the saved-positions file - never touches hardware.
    """
    manager = StagePositionManager(backend="mock")
    return manager.list_positions()


def compute_sharpness(image_path: str) -> float:
    """Return the Laplacian-variance sharpness score of an already-captured
    image file. Higher = sharper / more in focus.
    """
    image = np.array(Image.open(image_path).convert("RGB"))
    return _compute_sharpness(image)


def check_focus_drift(image_path: str, baseline_sharpness: float, drop_threshold: float = 0.4) -> dict:
    """Compare an already-captured frame's sharpness against a baseline value.

    This is a single-frame check (unlike focus_check.FocusMonitor, it does
    not track consecutive low-sharpness frames across calls - baseline_sharpness
    is supplied by the caller each time, since MCP tool calls are stateless).

    drop_threshold: fraction below baseline that counts as drift, e.g. 0.4
        flags a frame that's 40% less sharp than baseline.
    """
    sharpness = compute_sharpness(image_path)
    percent_drop = (
        max(0.0, (baseline_sharpness - sharpness) / baseline_sharpness)
        if baseline_sharpness > 0
        else 0.0
    )
    return {
        "sharpness": sharpness,
        "baseline_sharpness": baseline_sharpness,
        "percent_drop": percent_drop,
        "drift_detected": percent_drop >= drop_threshold,
    }


def get_live_status() -> dict:
    """Return the current acquisition status from the running dashboard
    (acquisition/monitoring/dashboard.py's GET /status), e.g. timepoint
    progress, position, images captured.

    Requires a dashboard server to already be running (started today by
    acquisition/orchestration/run_protocol.py) - raises ConnectionError with
    a clear message if it isn't reachable.
    """
    try:
        with urllib.request.urlopen(DASHBOARD_STATUS_URL, timeout=5) as response:
            return json.loads(response.read())
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise ConnectionError(
            f"Could not reach the acquisition dashboard at {DASHBOARD_STATUS_URL} - "
            "is run_protocol.py running? "
            f"Underlying error: {e}"
        ) from e


def save_current(label: str, backend: str = "mock") -> dict:
    """Read the stage's current position and save it under `label`.

    backend: "mock" (default) or "sdk" (real hardware). No confirmation
    required - this only reads the current position, it never moves the
    stage.
    """
    manager = StagePositionManager(backend=backend)
    return manager.save_current(label)


def get_pfs_status() -> dict:
    """Return Nikon PFS (Perfect Focus System) hardware focus-lock status:
    whether it's currently enabled/locked, its raw status code, current
    offset, and the offset's valid range. Real hardware only - no mock
    PFS. Read-only - no confirmation required.
    """
    from acquisition.backends.nis_sdk import NISSdk

    return NISSdk().pfs_status()


# ── Move/write tools (gated - see _require_confirm_for_sdk) ─────────────


def move_xy_absolute(x: float, y: float, backend: str = "mock", confirm: bool = False) -> dict:
    """Move the XY stage to an absolute (x, y) position, in microns.

    backend: "mock" (default, safe) or "sdk" (real hardware - requires
    confirm=True).
    """
    _require_confirm_for_sdk(backend, confirm)
    nis = _get_backend(backend)
    nis.XY_Move(x, y)
    new_x, new_y = nis.XY_GetPosition()
    return {"x": new_x, "y": new_y, "backend": backend}


def move_z_absolute(z: float, backend: str = "mock", confirm: bool = False) -> dict:
    """Move focus to an absolute Z position, in microns.

    backend: "mock" (default, safe) or "sdk" (real hardware - requires
    confirm=True).
    """
    _require_confirm_for_sdk(backend, confirm)
    nis = _get_backend(backend)
    nis.Z_Move(z)
    new_z = nis.Z_GetPosition()
    return {"z": new_z, "backend": backend}


def move_xy_relative(dx: float, dy: float, backend: str = "mock", confirm: bool = False) -> dict:
    """Move the XY stage by (dx, dy) microns relative to its current position.

    backend: "mock" (default, safe) only - the real SDK backend
    (acquisition/backends/nis_sdk.py) has no relative-move method, so
    backend="sdk" raises NotImplementedError. Use move_xy_absolute with an
    explicit target position on real hardware instead.
    """
    if backend == "sdk":
        raise NotImplementedError(
            "Relative XY moves are not available on backend='sdk' - "
            "nis_sdk.NISSdk has no XY_MoveRelative method. Use "
            "move_xy_absolute with an explicit target position instead."
        )
    _require_confirm_for_sdk(backend, confirm)
    nis = _get_backend(backend)
    nis.XY_MoveRelative(dx, dy)
    new_x, new_y = nis.XY_GetPosition()
    return {"x": new_x, "y": new_y, "backend": backend}


def move_z_relative(dz: float, backend: str = "mock", confirm: bool = False) -> dict:
    """Move focus by dz microns relative to its current position.

    backend: "mock" (default, safe) only - the real SDK backend
    (acquisition/backends/nis_sdk.py) has no relative-move method, so
    backend="sdk" raises NotImplementedError. Use move_z_absolute with an
    explicit target position on real hardware instead.
    """
    if backend == "sdk":
        raise NotImplementedError(
            "Relative Z moves are not available on backend='sdk' - "
            "nis_sdk.NISSdk has no Z_MoveRelative method. Use "
            "move_z_absolute with an explicit target position instead."
        )
    _require_confirm_for_sdk(backend, confirm)
    nis = _get_backend(backend)
    nis.Z_MoveRelative(dz)
    new_z = nis.Z_GetPosition()
    return {"z": new_z, "backend": backend}


def go_to_saved_position(label: str, backend: str = "mock", confirm: bool = False) -> dict:
    """Move the stage (XY and Z) to a previously saved position by label.

    backend: "mock" (default, safe) or "sdk" (real hardware - requires
    confirm=True).
    """
    _require_confirm_for_sdk(backend, confirm)
    manager = StagePositionManager(backend=backend)
    return manager.go_to(label)


def nudge_focus_offset(delta_counts: float, confirm: bool = False) -> dict:
    """Fine-tune focus by a small amount via Nikon's PFS hardware focus
    lock - NOT by moving Z to an absolute position.

    Requires PFS to already be enabled/locked (check with get_pfs_status
    first) - this only nudges the existing lock's offset, it can never
    move focus from an arbitrary/unknown starting position the way
    move_z_absolute could. Each call is capped to a small fraction of the
    SDK's own reported valid offset range (see
    nis_sdk.PFS_MAX_OFFSET_STEP_FRACTION) - this is the safe, MCP-exposed
    way to adjust focus; move_z_absolute/move_z_relative are intentionally
    not available as tools here (see this module's top-of-file comment).

    Real hardware only (no mock PFS) - requires confirm=True, same gate
    as the other real-hardware write tools.

    KNOWN LIMITATION (unconfirmed as of 2026-08-10): writes have been
    observed to silently no-op on real hardware while PFS is locked - see
    the TODO on NISSdk.nudge_pfs_offset for details. The call itself is
    still safe (worst case it does nothing), but don't assume a returned
    offset_before/offset_after pair means the physical focus moved -
    check they actually differ.
    """
    if not confirm:
        raise PermissionError(
            "nudge_focus_offset controls real microscope hardware and "
            "requires confirm=True. Refusing to proceed without explicit "
            "confirmation."
        )
    from acquisition.backends.nis_sdk import NISSdk

    return NISSdk().nudge_pfs_offset(delta_counts)


# ── Write tools with no hardware contact (ungated) ───────────────────────


def define_position(label: str, x: float, y: float, z: float) -> dict:
    """Manually define a named position from explicit (x, y, z) coordinates
    in microns, without moving the stage. Writes only to the saved-positions
    file - never touches hardware.
    """
    manager = StagePositionManager(backend="mock")
    return manager.define_position(label, x, y, z)


def load_positions_from_yaml(protocol_path: str) -> dict:
    """Load the `positions:` list from a protocol YAML file (see
    protocols/example_protocol.yaml) and save each one by its label.
    Writes only to the saved-positions file - never touches hardware.
    """
    manager = StagePositionManager(backend="mock")
    return manager.load_positions_from_yaml(Path(protocol_path))


def delete_saved_position(label: str) -> dict:
    """Delete a saved stage position by label. Writes only to the
    saved-positions file - never touches hardware.
    """
    manager = StagePositionManager(backend="mock")
    manager.delete(label)
    return {"deleted": label}
