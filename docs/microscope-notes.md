# Microscope Notes

> **Living document** — this file is updated as more is learned about the hardware,
> control software, and SDK. Treat anything below as the best current understanding,
> not a final spec.

## Hardware Specs (from Nikon Ti2-E specifications page)

| Component | Spec |
|---|---|
| Stage | Motorized, Stroke X: ±57mm, Y: ±36.5mm, Max speed: 25mm/sec |
| Focusing | Motorized drive, min increment 0.01µm, 10mm stroke |
| Controller | Ti2-CTRE, USB/LAN interface with I/O function |
| Nosepiece | 6 motorized positions (DIC sextuple) |
| Filter wheel | 7 motorized positions, 50ms between positions |
| Shutter | Motorized, 12ms open/close |
| Operating temp | 0-40°C, 60% humidity max |

## Hardware Stack (from lab visit)

- **Microscope body:** Nikon Eclipse Ti2-E (inverted)
- **Confocal scanner:** Nikon AX
- **Detector:** N-SPARC (CF Mode)
- **Laser unit:** LUA-S4 (405nm, 488nm, 561nm, 640nm)
- **Control software:** NIS-Elements AR 6.20.02 (Windows only)
- **Live cell incubator:** Tokai Hit STX
- **Objectives:** 4x, 10x, 60x Oil immersion
- **Stage controller:** Nikon joystick Ti2-S-JS-SS

## Acquisition Settings (from biology team screenshots)

- **Resolution:** 1024x1024
- **Save path:** `D:\Mike Bechill Biofilm Group\YYYY.MM.DD\`
- **Filename:** `YYYY.MM.DD.AB.Z.3.S.C.60XOIL.S9CAI.nd2`
- **Duration:** 6 hours per phase
- **Interval:** No Delay
- **Z-stack:** enabled (3 slices)
- **N-SPARC:** CF Mode active
- **Format:** ND2

## NIS-Elements Python API

- `XY_GetPosition()` → current stage x, y in microns
- `XY_Move(x, y)` → absolute stage position
- `XY_MoveRelative(x, y)` → relative stage move
- `Z_GetPosition()` → current z in microns
- `Z_Move(z)` → absolute z position
- `Z_MoveRelative(z)` → relative z move
- **Warning:** convert numpy types to plain Python int/float first
- Controller connects via USB/LAN (Ti2-CTRE)

## NIS-Elements Jobs API — Key Functions for Acquisition

Source: [NIS-Elements AR Jobs Python API docs](https://www.nisoftware.net/NikonSaleApplication/Help/Docs-AR/eng_ar/task.system_section.html)

- `XY_GetPosition()` → returns current stage x, y in microns
- `XY_Move(x, y)` → moves stage to absolute position
- `XY_MoveRelative(x, y)` → moves relative to current position
- `Z_GetPosition()` → returns current z position in microns
- `Z_Move(z)` → moves to absolute z position
- `Z_MoveRelative(z)` → moves relative to current z
- `ctx.shouldAbort()` → checks if user clicked abort in NIS UI
- `Python_RunFile` / `Python_RunString` → runs Python from a NIS macro
- **Warning:** numpy types must be converted to plain Python int/float before passing to any NIS function
- Execution in the main thread is required for NIS macro functions
- A side thread allows interaction with the JOBS progress dialog

## Next Steps for Acquisition Engine

Planned scripts under `acquisition/`:

- `acquisition/nis_connection.py` → test stage connection (done)
- `acquisition/run_protocol.py` → read YAML and run experiment
- `acquisition/focus_check.py` → detect and correct focus drift
- `acquisition/dashboard.py` → FastAPI live preview dashboard

## SDK Status

- NIS-Elements Jobs Python API confirmed available
- Remote Desktop credentials pending from Briana
- Ti2 SDK link not working — follow up in progress
