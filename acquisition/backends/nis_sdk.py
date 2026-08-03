# nis_sdk.py
# ------------------------------------------------------------
# Ti2 ActiveX SDK backend for stage control - real hardware via
# win32com.client.Dispatch(NkTi2Ax.NikonTi2AxAutoConnectMicroscope.CLSID),
# the same connection pattern confirmed working in
# acquisition/calibration/nikon_connection_test.py against the Ti2-E Device Simulator.
#
# ConfocalOrchestrator has two stage-control backends, both exposing the
# same shape of interface so orchestration/stage_positions.py can swap
# between them via its `backend` parameter - see nis_mock.py for the
# other one ("mock").
# This is the "sdk" backend: direct ActiveX bindings, now that Nikon has
# approved SDK access (see docs/microscope-notes.md's "SDK Status") -
# confirmed end-to-end against the Ti2-E Device Simulator, 2026-07-27.
#
# CONFIRMED PROPERTIES (from .venv/Lib/site-packages/NkTi2Ax.py, the
# generated bindings for the SDK's own type library - the same file that
# defines iTURRET1POS/Turret1Pos, confirmed working in calibration/nikon_connection_test.py):
#   iXPOSITION / iYPOSITION / iZPOSITION - direct properties, readable and
#   writable, same shape as iTURRET1POS.
#   XPosition / YPosition / ZPosition - child settings objects (.Value/
#   .Lower/.Higher), same shape as Turret1Pos. Read-verified against the
#   Ti2-E Device Simulator via acquisition/calibration/nikon_stage_test.py -
#   both forms returned identical values.
#
# UNITS (inferred, not stated anywhere explicit - the bindings just
# declare a plain integer VARIANT, no unit metadata): cross-referencing

# the simulator's reported Lower/Higher travel limits against
# docs/microscope-notes.md's documented hardware spec ("Stroke X:
# +/-57mm, Y: +/-36.5mm ... Focusing: min increment 0.01um, 10mm stroke"):
#   X: Lower/Higher = +/-570000  -> 0.1um/count exactly reproduces +/-57mm
#   Z: Lower/Higher = 0..1000000 -> 0.01um/count exactly reproduces the
#      10mm stroke, and matches the doc's stated 0.01um min focus increment
#   Y: Lower/Higher = +/-375000  -> 0.1um/count gives +/-37.5mm, close to
#      but not exactly the documented +/-36.5mm - most likely the
#      simulator's configured soft limit isn't identical to the real
#      hardware's exact stroke, not a different unit (X and Z both match
#      their spec exactly at these scales). Re-confirm against the real
#      microscope if Y positions come out visibly wrong.
# So: X/Y properties are in units of 0.1um ("decimicrons"), Z is in units
# of 0.01um ("centimicrons"). XY_GetPosition/XY_Move/Z_GetPosition/Z_Move
# below convert to/from plain microns at their boundary so callers
# (StagePositionManager, run_protocol.py) never see raw counts.
# ------------------------------------------------------------

import win32com.client
import NkTi2Ax

# Raw-count-per-micron scale factors confirmed above.
XY_COUNTS_PER_UM = 10.0
Z_COUNTS_PER_UM = 100.0


def to_plain_float(value) -> float:
    """Convert a numpy scalar (or anything float-like) to a plain Python float.

    Matches the same convention used in calibration/nis_jobs_connection_test.py/orchestration/stage_positions.py -
    values passed to a COM property setter must be plain Python numbers,
    not numpy types.
    """
    return float(value)


class NISSdk:
    """Ti2 SDK (ActiveX) backend: real stage control via NkTi2Ax's
    iXPOSITION/iYPOSITION/iZPOSITION properties, matching the
    XY_GetPosition/XY_Move/Z_GetPosition/Z_Move shape used by MockNIS so
    StagePositionManager can use this backend interchangeably with 'mock'.
    """

    def __init__(self):
        self._microscope = win32com.client.Dispatch(
            NkTi2Ax.NikonTi2AxAutoConnectMicroscope.CLSID
        )

    def XY_GetPosition(self) -> tuple[float, float]:
        """Return the current stage (x, y) position in microns."""
        x = self._microscope.iXPOSITION / XY_COUNTS_PER_UM
        y = self._microscope.iYPOSITION / XY_COUNTS_PER_UM
        return to_plain_float(x), to_plain_float(y)

    def XY_Move(self, x: float, y: float) -> None:
        """Move the stage to an absolute (x, y) position, in microns."""
        before = self.XY_GetPosition()
        x_counts = round(to_plain_float(x) * XY_COUNTS_PER_UM)
        y_counts = round(to_plain_float(y) * XY_COUNTS_PER_UM)
        self._microscope.iXPOSITION = x_counts
        self._microscope.iYPOSITION = y_counts
        after = self.XY_GetPosition()
        print(
            f"[NISSdk] XY_Move: requested ({x:.2f}, {y:.2f}) um "
            f"[counts ({x_counts}, {y_counts})] - before {before} - after {after} um"
        )
        if round(after[0] * XY_COUNTS_PER_UM) != x_counts or round(after[1] * XY_COUNTS_PER_UM) != y_counts:
            print(f"[NISSdk] WARNING: XY_Move readback does not match requested counts!")

    def Z_GetPosition(self) -> float:
        """Return the current focus (z) position in microns."""
        z = self._microscope.iZPOSITION / Z_COUNTS_PER_UM
        return to_plain_float(z)

    def Z_Move(self, z: float) -> None:
        """Move focus to an absolute z position in microns."""
        before = self.Z_GetPosition()
        z_counts = round(to_plain_float(z) * Z_COUNTS_PER_UM)
        self._microscope.iZPOSITION = z_counts
        after = self.Z_GetPosition()
        print(
            f"[NISSdk] Z_Move: requested {z:.2f} um [counts {z_counts}] - "
            f"before {before} um - after {after} um"
        )
        if round(after * Z_COUNTS_PER_UM) != z_counts:
            print(f"[NISSdk] WARNING: Z_Move readback does not match requested counts!")


if __name__ == "__main__":
    sdk = NISSdk()
    print("Current position:", sdk.XY_GetPosition(), sdk.Z_GetPosition())
