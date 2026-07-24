# nikon_stage_test.py
# ------------------------------------------------------------
# Confirmation script for XY/Z stage property names on the Ti2 ActiveX SDK.
#
# nikon_test.py already confirmed the connection pattern (win32com.client.
# Dispatch against NkTi2Ax.NikonTi2AxAutoConnectMicroscope.CLSID) and the
# iTURRET1POS / Turret1Pos property shape. This script applies the same
# pattern to the stage-position candidates found in the generated bindings
# (.venv/Lib/site-packages/NkTi2Ax.py): iXPOSITION / iYPOSITION / iZPOSITION
# (direct properties) and XPosition / YPosition / ZPosition (child setting
# objects, same shape as Turret1Pos - .Value / .Lower / .Higher).
#
# These names are real (pulled from the SDK's own type library, not
# guessed), but have never been run live and their unit/scale is unknown -
# that's what this script is for.
#
# HOW TO USE:
#   1. Run this script. It shows the simulation window and prints the
#      current iXPOSITION/iYPOSITION/iZPOSITION and XPosition/YPosition/
#      ZPosition.Value readings.
#   2. In the simulator's own GUI, move the stage by a KNOWN amount (note
#      exactly what the simulator's own display says, in whatever units it
#      shows - usually microns).
#   3. Press Enter here to take a second reading.
#   4. Compare: does the iXPOSITION/iYPOSITION delta match the distance you
#      moved in the simulator's display? That tells us the unit/scale.
#      Repeat for Z.
# ------------------------------------------------------------

import sys

import win32com.client
import NkTi2Ax

# --read: take a single snapshot and exit - no pause, no re-prompt. Lets this
# script be invoked twice as two separate processes (once before a manual
# move in the simulator GUI, once after), which works because
# AutoConnectMicroscope reconnects to the SAME running simulator instance/
# state each time rather than spinning up a fresh one.
READ_ONLY = "--read" in sys.argv

microscope: NkTi2Ax.NikonTi2AxAutoConnectMicroscope = win32com.client.Dispatch(
    NkTi2Ax.NikonTi2AxAutoConnectMicroscope.CLSID
)

microscope.DedicatedCommand(r"SHOW_SIMULATION_WINDOW", r"0,1")


def read_direct_properties() -> None:
    print(f"  iXPOSITION = {microscope.iXPOSITION}")
    print(f"  iYPOSITION = {microscope.iYPOSITION}")
    print(f"  iZPOSITION = {microscope.iZPOSITION}")


def read_child_objects() -> None:
    for name in ("XPosition", "YPosition", "ZPosition"):
        child = getattr(microscope, name)
        print(f"  {name}.Value = {child.Value}   (Lower={child.Lower}, Higher={child.Higher})")


print("=" * 60)
print("Stage property confirmation test" + (" (--read snapshot)" if READ_ONLY else ""))
print("=" * 60)

print("\nDirect properties:")
read_direct_properties()
print("Child settings objects:")
read_child_objects()

if not READ_ONLY:
    print(
        "\nNow, in the simulator window: move the stage by a KNOWN distance "
        "using its own controls, and note what the simulator's own display "
        "reports for that move (in whatever unit it shows)."
    )
    input("Press Enter here once you've made the move and noted the simulator's own reading...")

    print("\n--- Reading AFTER manual move ---")
    print("Direct properties:")
    read_direct_properties()
    print("Child settings objects:")
    read_child_objects()

    print(
        "\nCompare the delta above (reading after minus reading before) against "
        "the distance you moved per the simulator's own display. If they match "
        "1:1, the property is already in the simulator's displayed unit "
        "(most likely microns). If not, note the ratio - that's the scale "
        "factor needed in nis_sdk.py."
    )
