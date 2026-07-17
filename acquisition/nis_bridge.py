# nis_bridge.py
# ------------------------------------------------------------
# Native-macro bridge backend for stage control.
#
# ConfocalOrchestrator has three stage-control backends, all exposing the
# same shape of interface so stage_positions.py can swap between them via
# its `backend` parameter:
#   - "mock"   (nis_mock.MockNIS)  -> in-memory simulation, no NIS or
#                                     hardware needed. Used for offline dev.
#   - "bridge" (this file)         -> talks to REAL NIS-Elements stage
#                                     hardware today, via NIS's own native
#                                     macro language (see
#                                     acquisition/macros/bridge_command.mac)
#                                     instead of the (not yet approved)
#                                     Ti2 SDK.
#   - "sdk"    (future, not yet implemented) -> direct Ti2 SDK bindings,
#                                     once Nikon approves SDK access.
#
# How this backend works: NISBridge writes a one-line command (e.g.
# "GET_POS") to bridge_data/command.txt. A NIS-Elements macro
# (acquisition/macros/bridge_command.mac) must already be running INSIDE
# NIS-Elements, polling for that file - see acquisition/macros/README.md
# for how to start it. That macro calls NIS's real Stg_ stage functions
# and writes "<status>,<x>,<y>,<z>" to bridge_data/response.txt. This
# class polls for that file and parses it.
#
# Requires: Python and NIS-Elements running on the SAME machine (this is
# plain local file exchange - no networking, no shared drives), and
# bridge_command.mac already started inside NIS-Elements before any
# NISBridge method is called.
# ------------------------------------------------------------

import time
from pathlib import Path

BRIDGE_DIR = Path(__file__).resolve().parent / "bridge_data"

# Status codes returned by NIS's Stg_ macro functions (confirmed against
# the real NIS-Elements install), and their plain-English meaning.
STATUS_MESSAGES = {
    1: "DR_OK - success",
    2: "DR_PARTIALLYOK - command partially completed",
    -1: "DR_UNKNOWNERROR - unknown error",
    -4: "DR_NOTAVAILABLE - stage not connected/available",
    -6: "DR_NOTCALIBRATED - stage not calibrated",
    -7: "DR_NOTINITIALIZED - stage not initialized",
}


def describe_status(status_code: int) -> str:
    """Translate a Stg_ status code into a human-readable message."""
    return STATUS_MESSAGES.get(status_code, f"Unknown NIS status code: {status_code}")


def to_plain_float(value) -> float:
    """Convert a numpy scalar (or anything float-like) to a plain Python float.

    Matches the same convention used in nis_connection.py / stage_positions.py -
    NIS-Elements functions expect plain Python numbers, not numpy types.
    """
    return float(value)


class NISBridge:
    """Native-macro bridge backend: real NIS-Elements stage control via a
    running bridge_command.mac macro and a pair of hand-off files on disk.

    This is NOT a Python binding to NIS-Elements - it is a small file-based
    request/response protocol, and it only works while bridge_command.mac
    is running inside NIS-Elements on this same machine (see
    acquisition/macros/README.md). It is distinct from nis_mock.MockNIS
    (pure in-memory simulation, no NIS required) and the future Ti2 SDK
    backend (direct bindings, pending Nikon's approval) - this bridge
    exists to get real stage data/control TODAY while that approval is
    pending.
    """

    def __init__(self, bridge_dir: Path = BRIDGE_DIR, poll_interval: float = 0.2):
        self._bridge_dir = bridge_dir
        self._command_file = bridge_dir / "command.txt"
        self._response_file = bridge_dir / "response.txt"
        self._poll_interval = poll_interval
        self._bridge_dir.mkdir(parents=True, exist_ok=True)

    def _write_command(self, *lines: str) -> None:
        """Write a command for bridge_command.mac to pick up on its next poll."""
        with open(self._command_file, "w") as f:
            f.write("\n".join(lines))

    def _wait_for_response(self, timeout: float) -> str:
        """Poll for response.txt every `poll_interval` seconds until it
        appears or `timeout` is hit, then delete it and return its contents.

        Raises TimeoutError if bridge_command.mac isn't running/responding -
        by far the most common cause is simply forgetting to start the
        macro inside NIS-Elements first (Macro -> Run Macro From File...).
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._response_file.exists():
                text = self._response_file.read_text().strip()
                self._response_file.unlink()  # clean up so it can't be re-read stale
                return text
            time.sleep(self._poll_interval)

        raise TimeoutError(
            f"No response from bridge_command.mac within {timeout:.1f}s. "
            "Is the macro running inside NIS-Elements right now? "
            "(Macro -> Run Macro From File... -> bridge_command.mac). "
            "See acquisition/macros/README.md."
        )

    def _parse_response(self, text: str) -> tuple:
        """Parse a 'status,x,y,z' response line into (status_code, x, y, z)."""
        parts = text.split(",")
        status_code = int(parts[0])
        x, y, z = (to_plain_float(v) for v in parts[1:4])
        return status_code, x, y, z

    def get_position(self, timeout: float = 5.0) -> tuple:
        """Read the current stage (x, y, z) position, in microns, from real
        NIS-Elements hardware, via bridge_command.mac and StgGetPos.

        Returns:
            (x, y, z) as plain Python floats.

        Raises:
            TimeoutError: bridge_command.mac isn't running/responding.
            RuntimeError: NIS returned a non-OK status code (e.g. stage not
                connected or not calibrated) - the message names which.
        """
        self._write_command("GET_POS")
        status_code, x, y, z = self._parse_response(self._wait_for_response(timeout))

        if status_code not in (1, 2):  # DR_OK, DR_PARTIALLYOK
            raise RuntimeError(f"NIS stage read failed: {describe_status(status_code)}")

        return x, y, z

    def move_xy(self, x: float, y: float, confirm: bool = False, timeout: float = 5.0) -> tuple:
        """Move the REAL stage to an absolute (x, y) position, in microns,
        via bridge_command.mac and StgMoveXY.

        SAFETY: this moves real hardware. `confirm=True` must be passed
        explicitly - there is no default-on path to motion. This mirrors
        the confirm-before-moving principle used throughout
        ConfocalOrchestrator's acquisition scripts (nis_connection.py,
        run_protocol.py), just as a parameter instead of an input() prompt,
        so this can be called from other code without blocking on stdin.

        Returns:
            (x, y, z) as plain Python floats - the position AFTER the move,
            read back from NIS to confirm it actually happened.

        Raises:
            PermissionError: confirm was not True.
            TimeoutError: bridge_command.mac isn't running/responding.
            RuntimeError: NIS returned a non-OK status code.
        """
        if not confirm:
            raise PermissionError(
                "move_xy() requires confirm=True to move real hardware. "
                "Call move_xy(x, y, confirm=True) only once you've verified "
                "it's safe to move the stage."
            )

        self._write_command("MOVE_XY", f"{to_plain_float(x)},{to_plain_float(y)}")
        status_code, new_x, new_y, new_z = self._parse_response(self._wait_for_response(timeout))

        if status_code not in (1, 2):
            raise RuntimeError(f"NIS stage move failed: {describe_status(status_code)}")

        return new_x, new_y, new_z

    # ── Compatibility wrappers ───────────────────────────────────────────
    # StagePositionManager (stage_positions.py) is written against the same
    # method names/signatures as the real `nis` module and MockNIS -
    # XY_GetPosition() / Z_GetPosition() / XY_Move(x, y) / Z_Move(z) - so it
    # can use whichever backend it was given without caring which one. These
    # wrappers make NISBridge satisfy that same shape.
    #
    # XY_Move() intentionally passes confirm=True straight through: it
    # mirrors the real `nis` module's XY_Move (which also takes no confirm
    # argument), on the assumption that whatever CALLS StagePositionManager
    # has already gated the move behind its own user confirmation - exactly
    # as stage_positions.py's own go_to() docstring already documents for
    # any real-hardware backend. Call move_xy() directly (not this wrapper)
    # if you want the explicit confirm=True gate enforced at this layer too.

    def XY_GetPosition(self) -> tuple:
        """Compatibility wrapper: return (x, y) only, matching the real API."""
        x, y, _z = self.get_position()
        return x, y

    def Z_GetPosition(self) -> float:
        """Compatibility wrapper: return z only, matching the real API."""
        _x, _y, z = self.get_position()
        return z

    def XY_Move(self, x: float, y: float) -> None:
        """Compatibility wrapper over move_xy(confirm=True) - see note above."""
        self.move_xy(x, y, confirm=True)

    def Z_Move(self, z: float) -> None:
        """Not implemented: no Z-axis macro function (e.g. StgMoveZ) has
        been confirmed yet - only StgGetPos and StgMoveXY are confirmed
        against the real NIS-Elements install. Add this once a Z move
        function is confirmed and wired into bridge_command.mac.
        """
        raise NotImplementedError(
            "NISBridge.Z_Move() is not implemented - no Z-axis move macro "
            "function has been confirmed yet (only StgGetPos/StgMoveXY "
            "are). StagePositionManager.go_to() will fail at the Z step "
            "for backend='bridge' until this is added."
        )
