# stage_positions.py
# ------------------------------------------------------------
# Stage position manager: save, list, and move to named XY/Z stage
# positions on the Nikon Eclipse Ti2-E, on top of the NIS-Elements Python
# API - or, off the microscope PC, acquisition/nis_mock.py's MockNIS, so
# this module works for offline development too.
#
# Saved positions persist to protocols/stage_positions.json, so they can
# be reused across sessions (e.g. to build up a protocol's `positions:`
# list - see protocols/example_protocol.yaml).
#
# Run directly for a quick sanity check (works on Mac/Linux/Windows dev
# machines via MockNIS, no NIS-Elements required):
#   python acquisition/stage_positions.py
# ------------------------------------------------------------

import json
from pathlib import Path

# Stage travel limits (see nis_mock.py / docs/microscope-notes.md's hardware
# spec) - imported unconditionally since nis_mock.py has no hardware
# dependency of its own, so these constants are always available regardless
# of whether the real `nis` module or MockNIS ends up being used below.
from nis_mock import X_LIMIT_UM, Y_LIMIT_UM

# ── 1. Connect to the NIS-Elements Python API, or fall back to the mock ─────
# Unlike nis_connection.py / run_protocol.py (which only ever run ON the
# microscope PC and hard-fail without the real API), this module is meant
# to be usable for offline development too, so it falls back to MockNIS
# when the real `nis` module isn't available.
try:
    import nis  # NIS-Elements' own Python API module (only available on the microscope PC)
except ImportError:
    from nis_mock import MockNIS
    nis = MockNIS()
    print(
        "'nis' module not found - using MockNIS (offline/dev mode). "
        "Positions below will not move a real stage."
    )

POSITIONS_FILE = Path(__file__).resolve().parent.parent / "protocols" / "stage_positions.json"

# ── Backend design ────────────────────────────────────────────────────────
# StagePositionManager can drive the stage through any of three backends,
# selected via the `backend` constructor parameter, all kept long-term
# side by side rather than replacing one with another:
#   - "mock"   -> nis_mock.MockNIS (or the real `nis` module, if this
#                 happens to be running on the microscope PC) - unchanged
#                 default, for offline development with no hardware.
#   - "bridge" -> nis_bridge.NISBridge - talks to REAL NIS-Elements stage
#                 hardware today via NIS's native macro language, while
#                 the Ti2 SDK is still awaiting Nikon's approval.
#   - "sdk"    -> reserved for the future Ti2 SDK backend, once approved;
#                 raises NotImplementedError until then.


def to_plain_float(value) -> float:
    """Convert a numpy scalar (or anything float-like) to a plain Python float.

    NIS-Elements functions expect plain Python numbers, not numpy types.
    """
    return float(value)


def validate_position(x: float, y: float) -> None:
    """Raise ValueError if (x, y) - in microns - is outside the Ti2-E's
    stage travel limits (X +/-57mm, Y +/-36.5mm - see nis_mock.X_LIMIT_UM /
    Y_LIMIT_UM, sourced from docs/microscope-notes.md's hardware spec).

    Called before a position is saved (save_current) or moved to (go_to),
    so a bad reading or a hand-edited positions file can't silently send
    the stage past its travel limits.
    """
    x, y = to_plain_float(x), to_plain_float(y)
    if not -X_LIMIT_UM <= x <= X_LIMIT_UM:
        raise ValueError(
            f"X position {x:.2f} um is outside the stage travel limit of +/-{X_LIMIT_UM:.0f} um."
        )
    if not -Y_LIMIT_UM <= y <= Y_LIMIT_UM:
        raise ValueError(
            f"Y position {y:.2f} um is outside the stage travel limit of +/-{Y_LIMIT_UM:.0f} um."
        )


class StagePositionManager:
    """Save, list, and move to named stage (x, y, z) positions, in microns.

    Positions persist as JSON at `positions_file` so they survive between
    runs. Works against either the real NIS-Elements API or MockNIS -
    whichever `nis` this module resolved to on import - since both expose
    the same XY_GetPosition/XY_Move/Z_GetPosition/Z_Move methods.
    """

    def __init__(self, backend: str = "mock", nis_module=None, positions_file: Path = POSITIONS_FILE):
        """
        backend: "mock" (default - unchanged offline-dev behavior via the
            module-level `nis`, which is either the real `nis` module or
            MockNIS depending on what was importable), "bridge" (real
            hardware today via nis_bridge.NISBridge), or "sdk" (reserved,
            not implemented yet).
        nis_module: explicit override, mainly for tests - if given, used
            as-is regardless of `backend`.
        """
        if nis_module is not None:
            self._nis = nis_module
        elif backend == "mock":
            self._nis = nis
        elif backend == "bridge":
            from nis_bridge import NISBridge
            self._nis = NISBridge()
        elif backend == "sdk":
            # Reserved for the future Ti2 SDK backend, once Nikon approves
            # SDK access - see docs/microscope-notes.md's "SDK Status".
            raise NotImplementedError(
                "The 'sdk' backend is reserved for the future Ti2 SDK "
                "integration and isn't implemented yet. Use 'bridge' for "
                "real hardware today, or 'mock' for offline development."
            )
        else:
            raise ValueError(f"Unknown backend '{backend}'. Expected 'mock', 'bridge', or 'sdk'.")

        self._positions_file = positions_file
        self._positions = self._load()

    def _load(self) -> dict:
        if not self._positions_file.exists():
            return {}
        with open(self._positions_file, "r") as f:
            return json.load(f)

    def _save(self) -> None:
        self._positions_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._positions_file, "w") as f:
            json.dump(self._positions, f, indent=2, sort_keys=True)

    def save_current(self, label: str) -> dict:
        """Read the stage's current position and save it under `label`.

        Raises ValueError if the reported position is outside the stage's
        travel limits (see validate_position) - a defensive check, since
        this should never happen for a real, correctly-reporting stage.
        """
        x, y = self._nis.XY_GetPosition()
        z = self._nis.Z_GetPosition()
        validate_position(x, y)
        position = {"x": to_plain_float(x), "y": to_plain_float(y), "z": to_plain_float(z)}
        self._positions[label] = position
        self._save()
        return position

    def list_positions(self) -> dict:
        """Return all saved positions as {label: {"x", "y", "z"}}."""
        return dict(self._positions)

    def go_to(self, label: str) -> dict:
        """Move the stage to the saved position under `label`.

        Raises KeyError if no position with that label has been saved, or
        ValueError if the saved position is outside the stage's travel
        limits (see validate_position) - e.g. from a hand-edited positions
        file. Callers driving real hardware (not MockNIS) should confirm
        with the user before calling this - the same way nis_connection.py
        and run_protocol.py confirm before any stage move.
        """
        if label not in self._positions:
            raise KeyError(f"No saved position named '{label}'. Known positions: {list(self._positions)}")
        position = self._positions[label]
        validate_position(position["x"], position["y"])
        self._nis.XY_Move(position["x"], position["y"])
        self._nis.Z_Move(position["z"])
        return position

    def delete(self, label: str) -> None:
        """Remove a saved position. Raises KeyError if it doesn't exist."""
        del self._positions[label]
        self._save()


if __name__ == "__main__":
    manager = StagePositionManager()

    print("Saving current position as 'start'...")
    print(" ", manager.save_current("start"))

    nis.XY_Move(1500.0, -750.0)
    nis.Z_Move(12.5)
    print("Saving new position as 'sample_edge'...")
    print(" ", manager.save_current("sample_edge"))

    print("\nAll saved positions:")
    for label, pos in manager.list_positions().items():
        print(f"  {label}: {pos}")

    print("\nMoving back to 'start'...")
    manager.go_to("start")
    print("  Stage now at:", nis.XY_GetPosition(), nis.Z_GetPosition())

    print(f"\nPositions saved to: {POSITIONS_FILE}")
