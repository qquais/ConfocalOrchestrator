# nis_mock.py
# ------------------------------------------------------------
# Mock simulator for the NIS-Elements Python API ('nis' module), so
# acquisition scripts (stage_positions.py, run_protocol.py, etc.) can be
# developed and tested off the microscope PC.
#
# The real `nis` module only exists inside the NIS-Elements Python
# environment on the microscope PC (see nis_connection.py). This mock
# reproduces the small subset of that API used by ConfocalOrchestrator -
# XY/Z stage position, movement, and abort checks - as plain in-memory
# state, so it can run anywhere.
#
# Swap it in for `import nis` during offline development, e.g.:
#   from acquisition.nis_mock import MockNIS
#   nis = MockNIS()
# ------------------------------------------------------------

# Stage travel limits from the Nikon Ti2-E spec (see docs/microscope-notes.md),
# converted from mm to microns to match the units used by the NIS API.
X_LIMIT_UM = 57_000.0
Y_LIMIT_UM = 36_500.0


class MockNIS:
    """Mock of the NIS-Elements Python API's stage control functions.

    Simulates stage state (x, y, z) in microns, matching the method names
    and signatures of the real `nis` module used on the microscope PC.
    No delays, noise, or simulated hardware errors - just state tracking,
    for offline development and testing of ConfocalOrchestrator.
    """

    def __init__(self, x: float = 0.0, y: float = 0.0, z: float = 0.0):
        self._x = float(x)
        self._y = float(y)
        self._z = float(z)

    def _check_xy_limits(self, x: float, y: float) -> None:
        if not -X_LIMIT_UM <= x <= X_LIMIT_UM:
            raise ValueError(
                f"X position {x:.2f} um is outside the stage travel limit "
                f"of +/-{X_LIMIT_UM:.0f} um."
            )
        if not -Y_LIMIT_UM <= y <= Y_LIMIT_UM:
            raise ValueError(
                f"Y position {y:.2f} um is outside the stage travel limit "
                f"of +/-{Y_LIMIT_UM:.0f} um."
            )

    def XY_GetPosition(self) -> tuple[float, float]:
        """Return the current stage (x, y) position in microns."""
        return float(self._x), float(self._y)

    def XY_Move(self, x: float, y: float) -> None:
        """Move the stage to an absolute (x, y) position in microns."""
        x, y = float(x), float(y)
        self._check_xy_limits(x, y)
        self._x, self._y = x, y

    def XY_MoveRelative(self, dx: float, dy: float) -> None:
        """Move the stage by (dx, dy) microns relative to its current position."""
        x, y = self._x + float(dx), self._y + float(dy)
        self._check_xy_limits(x, y)
        self._x, self._y = x, y

    def Z_GetPosition(self) -> float:
        """Return the current focus (z) position in microns."""
        return float(self._z)

    def Z_Move(self, z: float) -> None:
        """Move focus to an absolute z position in microns."""
        self._z = float(z)

    def Z_MoveRelative(self, dz: float) -> None:
        """Move focus by dz microns relative to its current position."""
        self._z += float(dz)

    def shouldAbort(self) -> bool:
        """Return whether the user has clicked abort in the NIS UI.

        Always False in the mock - there is no UI to abort from.
        """
        return False


if __name__ == "__main__":
    nis = MockNIS()

    print("Starting position:", nis.XY_GetPosition(), nis.Z_GetPosition())

    nis.XY_Move(1000.0, -500.0)
    nis.Z_Move(25.0)
    print("After absolute move:", nis.XY_GetPosition(), nis.Z_GetPosition())

    nis.XY_MoveRelative(250.0, 250.0)
    nis.Z_MoveRelative(-5.0)
    print("After relative move:", nis.XY_GetPosition(), nis.Z_GetPosition())

    print("shouldAbort():", nis.shouldAbort())

    try:
        nis.XY_Move(60_000.0, 0.0)
    except ValueError as e:
        print("Expected error on out-of-range move:", e)
