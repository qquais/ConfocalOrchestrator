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
- **2026-07-20: Ti2 SDK access approved.** Not yet installed/located on
  this machine (checked `C:\Program Files\NIS-Elements\` and common user
  dirs — nothing found beyond the unrelated `NkImgSDK.dll` imaging SDK).
  Next step: get the actual SDK installer/package onto this machine and
  confirm what Python bindings (if any) it ships with, vs. needing a
  ctypes/cffi wrapper around a C/C++ SDK.

## `acquisition/` Environment Setup (this machine, 2026-07-20)

- Repo was cloned fresh onto this NIS-Elements PC; the `.venv/` used on
  the original dev machine is gitignored and doesn't transfer with
  `git clone` — recreate it locally.
- `python` on PATH resolves to the Windows Store alias stub (not a real
  interpreter) and there's no `py` launcher either. Use NIS-Elements'
  own bundled interpreter instead: `C:\Program Files\NIS-Elements\Python\python.exe`
  (3.12.1) — this is what `.venv/` here was created from.
- Full `requirements.txt` hits a Windows 260-character path limit on
  `torch`'s bundled license files (pulled in via `cellpose`), because
  this repo's folder path is long
  (`...\Bionanomics 4.0.0.110\Github_ConfocalOrchestrator\ConfocalOrchestrator\...`).
  `torch`/`cellpose`/`scikit-image`/`trackpy`/`pandas`/`matplotlib`/`dask`/`nd2`
  are only needed by the image-analysis scripts, not acquisition/stage
  control, so for bridge/stage testing only `fastapi`, `uvicorn`,
  `PyYAML`, `Pillow`, `numpy` were installed. Enabling Windows long-path
  support (`HKLM`, needs admin, machine-wide) would fix this properly if
  the full analysis stack is needed later on this machine.
- Running scripts under `acquisition/` as `python acquisition/foo.py`
  fails with `ModuleNotFoundError: No module named 'acquisition'`
  because the script's own directory (not the repo root) lands on
  `sys.path`. Run as a module from the repo root instead:
  `python -m acquisition.foo`.

## Bridge Backend (`nis_bridge.py` + `bridge_command.mac`) — Status: Blocked, Deprioritized

Attempted full round-trip testing 2026-07-20 (`MockNIS` baseline passed
fine; this section is about the `bridge` backend specifically). Two real
bugs were found and fixed along the way:

1. **NIS macro declaration placement** — NIS's macro language does not
   support variable declarations inside nested `{ }` blocks, only in one
   flat block at the very top of the whole macro. The original macro
   declared locals block-by-block (`if`/`while` bodies each had their own
   declarations-first section) and failed with "Cannot Evaluate the
   Expression" the first time it hit a nested declaration with a pending
   command file. Fixed by flattening every local variable in
   `bridge_command.mac` into one declaration block at the top of the
   file.
2. **Relative vs. absolute path** — `bridge_command.mac`'s `FOLDER`
   constant was a relative path (`"bridge_data\\"`), resolved by
   NIS-Elements against an unknown working directory that never matched
   `nis_bridge.py`'s `BRIDGE_DIR` (`acquisition/bridge_data/`) — tried
   and ruled out `acquisition/bridge_data`, `acquisition/macros/bridge_data`,
   `C:\Program Files\NIS-Elements\Macros\bridge_data`, and
   `C:\Program Files\NIS-Elements\bridge_data` as candidates for where
   NIS was actually resolving the relative path to; none worked. Fixed
   by hardcoding an absolute path in the macro matching `nis_bridge.py`.

**After both fixes, still no working round-trip.** "Macro → Run Macro
From File..." reports "finished, no errors" instantly instead of running
the intended infinite polling loop. Isolated diagnostics (temporary
`debug_probe.mac` / `debug_probe2.mac`, since deleted) ruled out:

- The `bridge_data` path/OneDrive-nesting specifically (tried a trivial
  `C:\` root path — same result).
- The `while` loop / this macro's complexity specifically (a standalone
  5-iteration bounded loop, no `bridge_data` involved, also finished
  instantly with no output).
- Even a single **unconditional, non-looping** `WriteFile()` call
  produced no file and no error.

**Root cause unresolved.** File I/O (or macro execution generally) isn't
behaving as the [nisoftware.net Macro Functions
reference](https://www.nisoftware.net/NikonSaleApplication/Help/Docs-D/eng_d/p4c11s19.html)
describes, and neither NIS's UI nor these diagnostics surfaced why (no
error dialog, no accessible console/log). Full details and exact test
sequence are in `acquisition/macros/README.md`'s "Known issues" section.

**Decision:** deprioritized in favor of the Ti2 SDK backend now that SDK
access has been approved (see SDK Status above) — the bridge/macro
approach was always meant as a stopgap "to get real stage data/control
today while waiting on SDK approval," so with approval granted the SDK
path is the intended one anyway. `nis_bridge.py`'s path/declaration fixes
are left in place as real improvements even though the underlying issue
is unresolved, in case this gets revisited later.

**Still not working / open questions:**
- Why does NIS report macro execution as instantly "finished, no errors"
  even for a single `WriteFile()` call with no loop? (No SDK-side
  console/debug output found yet to investigate further.)
- `run_protocol.py` and `stage_positions.py` have **not** been tested
  against the `bridge` backend as a result — that was blocked on this.
  Both were confirmed working against the `mock` backend during the
  original `MockNIS` baseline check.
