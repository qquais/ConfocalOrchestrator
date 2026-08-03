# nikon_connection_test.py
# ------------------------------------------------------------
# First test of the Nikon Ti2 connection: confirms we can connect to the
# microscope and read/write a setting (here, the turret) two different
# ways. Not part of the regular acquisition workflow - just the initial
# check that this connection approach works at all.
# ------------------------------------------------------------

import win32com.client
import NkTi2Ax
import time

# connects to the real microscope, or the simulator if that's not available
# the auto-connect object connects either to the real microscope or the simulator
microscope: NkTi2Ax.NikonTi2AxAutoConnectMicroscope = win32com.client.Dispatch(NkTi2Ax.NikonTi2AxAutoConnectMicroscope.CLSID)

# for development, make the simulation GUI visible
microscope.DedicatedCommand(r"SHOW_SIMULATION_WINDOW", r"0,1")

# all microscope settings can be addressed directly with the properties starting with a 'i':
# Moves the turret through positions 1-5, guessed/hardcoded, without
# knowing what's actually mounted at each one.
# WARNING: this physically moves the turret, no confirmation asked.
for i in range(1, 6):
    microscope.iTURRET1POS = i
    time.sleep(1)

# each setting also has a child-object without a 'i' that holds information such as the lowest and highest value
turret1: NkTi2Ax.INikonTi2AxSetting = microscope.Turret1Pos
# Moves the turret through its real valid range (asked from the hardware
# itself, not guessed), printing what's mounted at each position first.
# WARNING: same as above, this also physically moves the turret.
for i in range(turret1.Lower, turret1.Higher):
    print(r"moving to filter: " + turret1.LongName(i))
    turret1.Value = i
    time.sleep(1)
