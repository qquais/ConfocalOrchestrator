import win32com.client
import NkTi2Ax
import time

# the auto-connect object connects either to the real microscope or the simulator
microscope: NkTi2Ax.NikonTi2AxAutoConnectMicroscope = win32com.client.Dispatch(NkTi2Ax.NikonTi2AxAutoConnectMicroscope.CLSID)

# for development, make the simulation GUI visible
microscope.DedicatedCommand(r"SHOW_SIMULATION_WINDOW", r"0,1")

# all microscope settings can be addressed directly with the properties starting with a 'i':
for i in range(1, 6):
    microscope.iTURRET1POS = i
    time.sleep(1)

# each setting also has a child-object without a 'i' that holds information such as the lowest and highest value
turret1: NkTi2Ax.INikonTi2AxSetting = microscope.Turret1Pos
for i in range(turret1.Lower, turret1.Higher):
    print(r"moving to filter: " + turret1.LongName(i))
    turret1.Value = i
    time.sleep(1)
