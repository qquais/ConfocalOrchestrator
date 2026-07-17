# acquisition/macros/

Native NIS-Elements macro(s) for the "bridge" stage-control backend
(`acquisition/nis_bridge.py`). See that file's module docstring, and
`acquisition/stage_positions.py`'s backend comment block, for how this
fits alongside the `mock` and future `sdk` backends.

## bridge_command.mac

A file-polling loop, written in NIS-Elements' native macro language, that
lets `acquisition/nis_bridge.py` (plain Python) get real stage data out of
NIS-Elements today - via NIS's own `Stg_` functions - without waiting on
Ti2 SDK approval from Nikon.

**How it works:** the macro polls for `bridge_data/command.txt`. When
Python writes a command there (`GET_POS`, or `MOVE_XY` + an `x,y` line),
the macro calls the matching `Stg_` function and writes
`"<status>,<x>,<y>,<z>"` to `bridge_data/response.txt`, then deletes
`command.txt` so it can't re-trigger. `nis_bridge.py` writes the command,
polls for the response, and cleans it up after reading.

**Only the `Stg_` function calls and status codes in this macro are
confirmed.** The plain-text file I/O and string-handling calls
(`FileExists`, `FileReadText`, `FileWriteText`, `FileDelete`, `GetLine`,
`GetToken`, `StrToDouble`, `IntToStr`, `DoubleToStr`, `Wait`) are written
as a best-guess starting structure and are **not** verified against this
install's real Macro Language Reference - see the `UNVERIFIED` comments
inside `bridge_command.mac` for exactly which lines to check and correct
first.

### How to activate it

1. Confirm `bridge_data/` (created automatically by `nis_bridge.py` on
   first use, but you can also create it yourself) is reachable from
   wherever NIS-Elements resolves relative paths from - adjust the
   `FOLDER` constant at the top of `bridge_command.mac` if it isn't next
   to this file as written.
2. Open NIS-Elements.
3. **Macro menu -> Run Macro From File...** and select
   `bridge_command.mac`.
4. It runs an infinite polling loop - it will keep going until you stop
   it explicitly from NIS's macro/run controls. Closing the macro editor
   window is not the same as stopping it; use Stop/Abort.
5. Leave it running for as long as you want `nis_bridge.NISBridge` to be
   able to talk to real hardware from Python. Stop it when you're done.

### Requirements

- Python and NIS-Elements must be running on the **same machine**. This
  is plain local file exchange (reading/writing files on local disk) -
  there is no networking and no shared drive involved.
- `bridge_command.mac` must already be running inside NIS-Elements
  *before* calling any `NISBridge` method from Python - otherwise Python
  will wait out its timeout and raise `TimeoutError`.

### Safety warning

`NISBridge.move_xy()` requires `confirm=True` to be passed explicitly -
there is no default-on path to real stage motion from Python. The macro
itself does not add any additional safety gate of its own: it will call
`StgMoveXY` for any `MOVE_XY` command it receives, trusting that Python
only ever sends one after its own `confirm=True` check has passed.

**Never run `bridge_command.mac` against a machine with real hardware
attached without first verifying nothing else is actively using the
stage** (no other acquisition, calibration, or manual joystick operation
in progress). A stray `MOVE_XY` command arriving mid-operation would move
the stage regardless of what NIS-Elements' UI is doing at the time.
