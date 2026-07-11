# nis_connection.py
# ------------------------------------------------------------
# First acquisition module: connects to the NIS-Elements Python API and
# tests basic stage control on the Nikon Eclipse Ti2-E.
#
# >>> Run this script ON the microscope PC, with NIS-Elements AR 6.20.02
# >>> already open. The `nis` module is provided by NIS-Elements itself
# >>> (via its embedded Python / Jobs API) and does not exist anywhere else,
# >>> so this script cannot run standalone on a dev laptop (Mac/Linux/plain
# >>> Windows Python) - it will only import successfully inside that
# >>> environment.
#
# Hardware path: this PC -> Ti2-CTRE controller (USB/LAN) -> Ti2-E stage.
#
# Run (on the microscope PC, from the NIS-Elements Python console or a
# terminal with the NIS-Elements Python environment active):
#   python nis_connection.py
# ------------------------------------------------------------

# ── 1. Connect to the NIS-Elements Python API ────────────────────────────────
try:
    import nis  # NIS-Elements' own Python API module (only available on the microscope PC)
except ImportError as e:
    raise SystemExit(
        "Could not import the 'nis' module.\n"
        "This script must be run ON the microscope PC, with NIS-Elements "
        "AR 6.20.02 already open, so its Python API is available.\n"
        f"Original error: {e}"
    )


def to_plain_float(value) -> float:
    """Convert a numpy scalar (or anything float-like) to a plain Python float.

    NIS-Elements functions expect plain Python numbers. Values read back from
    the API (or computed with numpy) can come back as numpy.float64 etc.,
    which NIS-Elements may not accept - so every value gets converted before
    being passed to a NIS function.
    """
    return float(value)


def get_stage_position():
    """Read and return the current stage position as (x, y, z) in microns.

    XY_GetPosition() -> current stage X, Y in microns.
    Z_GetPosition()  -> current focus (Z) position in microns.
    """
    x, y = nis.XY_GetPosition()
    z = nis.Z_GetPosition()
    return to_plain_float(x), to_plain_float(y), to_plain_float(z)


def main():
    print("Connecting to NIS-Elements...")

    try:
        # ── 2. Read and print the current stage position ─────────────────────
        x, y, z = get_stage_position()
        print(f"Current XY position: X={x:.2f} um, Y={y:.2f} um")
        print(f"Current Z position:  Z={z:.2f} um")

        # ── 3. SAFETY CHECK: never move the stage without explicit confirmation ──
        # A small relative offset from the CURRENT position, rather than a
        # hardcoded absolute coordinate, so the test move stays safe no matter
        # where the stage currently is.
        offset_um = 50.0
        target_x = to_plain_float(x + offset_um)
        target_y = to_plain_float(y + offset_um)

        print("\nSAFETY CHECK")
        print(f"  About to move the stage from ({x:.2f}, {y:.2f}) to ({target_x:.2f}, {target_y:.2f}) um.")
        confirm = input("  Type 'yes' to proceed with this test move, anything else to cancel: ").strip().lower()

        if confirm != "yes":
            print("Move cancelled by user. No stage motion performed.")
            return

        # ── 4. Move the stage to the confirmed test position ─────────────────
        # XY_Move(x, y) -> moves the stage to an ABSOLUTE position in microns.
        print(f"Moving stage to ({target_x:.2f}, {target_y:.2f}) um...")
        nis.XY_Move(target_x, target_y)

        # ── 5. Confirm the new position by reading it back ───────────────────
        new_x, new_y, new_z = get_stage_position()
        print(f"Stage now reports: X={new_x:.2f} um, Y={new_y:.2f} um, Z={new_z:.2f} um")

        # ── 6. Success ─────────────────────────────────────────────────────
        print("\nStage control test PASSED: connected to NIS-Elements and moved the stage successfully.")

    except Exception as e:
        # Broad catch on purpose: this is a connection/hardware smoke test,
        # and any failure here (lost connection, controller offline, stage
        # fault, etc.) should be reported clearly rather than crash with a
        # raw traceback.
        print(f"\nStage control test FAILED: {e}")


if __name__ == "__main__":
    main()
