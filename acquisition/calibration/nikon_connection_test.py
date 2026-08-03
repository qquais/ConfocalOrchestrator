# nikon_connection_test.py
# ------------------------------------------------------------
# First test of the Nikon Ti2 connection: confirms we can connect to the
# microscope and read/write a setting (here, the turret).
# Not part of the regular acquisition workflow - just the initial check
# that this connection approach works at all.
#
# SAFETY: moving the turret can physically crash an objective into the
# stage/sample if the wrong one rotates in while Z is close-focused
# (short working distance, especially on the 60x oil objective). This
# script prints what's mounted at each position BEFORE moving anything,
# and requires typing 'yes' before it physically moves the turret.
# ------------------------------------------------------------

import win32com.client
import NkTi2Ax
import time

# connects to the real microscope, or the simulator if that's not available
# the auto-connect object connects either to the real microscope or the simulator
microscope: NkTi2Ax.NikonTi2AxAutoConnectMicroscope = win32com.client.Dispatch(NkTi2Ax.NikonTi2AxAutoConnectMicroscope.CLSID)

# for development, make the simulation GUI visible
microscope.DedicatedCommand(r"SHOW_SIMULATION_WINDOW", r"0,1")

# each setting has a child-object without a leading 'i' that holds
# information such as the lowest/highest valid value and, for the
# turret, a human-readable name per position.
turret1: NkTi2Ax.INikonTi2AxSetting = microscope.Turret1Pos

print(f"Current turret position: {turret1.Value} ({turret1.LongName(turret1.Value)})")
print("Turret positions in range (reading only, nothing moved yet):")
for i in range(turret1.Lower, turret1.Higher):
    print(f"  {i}: {turret1.LongName(i)}")

answer = input(
    "\nType 'yes' to physically step the turret through all positions above, "
    "anything else to cancel: "
).strip().lower()

if answer != "yes":
    print("Cancelled - no turret movement.")
else:
    for i in range(turret1.Lower, turret1.Higher):
        print(r"moving to filter: " + turret1.LongName(i))
        turret1.Value = i
        time.sleep(1)
