# NIS-Elements Python / Jobs API Reference

> **Reference document**, not a narrative one — see
> [microscope-notes.md](microscope-notes.md) for how each piece below was
> discovered/confirmed, and
> [nikon-ti2-sdk-api-reference.md](nikon-ti2-sdk-api-reference.md) for the
> **separate** Ti2 ActiveX SDK (`NkTi2Ax`) - a different, lower-level API
> that this project also uses. Don't confuse the two: `nis` (this doc) is
> NIS-Elements' own application-level Python API; `NkTi2Ax` is a device-
> driver SDK confirmed to have **zero** capture surface (stage/turret/
> objective only) - see "How this relates to the Ti2 ActiveX SDK" at the
> bottom.
>
> **2026-08-17 update**: section 3 below (Jobs "PythonScript" task) used
> to be *this project's* only path to real image capture. It no longer
> is — the team decided against routing capture through NIS-Elements at
> all, and it now goes through a Baumer GenICam camera instead (see
> `acquisition/backends/baumer_genicam.py` and `mcp_server/loop_tools.py`'s
> `get_image()`). Section 3 is kept as-is below as an accurate record of
> what NIS-Elements itself is capable of and how that mechanism was
> confirmed working - just no longer what this project actually uses.

## What this actually is

Unlike `NkTi2Ax.py` (a single generated bindings file), "the NIS-Elements
API" in this repo is really **three distinct things**, confirmed at
different times, reached in different ways:

| Surface | What it is | Where it runs | Confirmed |
|---|---|---|---|
| `nis` module | Procedural stage-control functions (`XY_Move`, etc.) | Only inside NIS-Elements' own embedded Python interpreter | Yes - stage functions |
| Jobs "PythonScript" task (`run(imgs, Job, macro, ctx)`) | Inversion-of-control callback NIS-Elements invokes itself when a Job runs | Only inside a Job built in NIS-Elements' JOBS Explorer UI - not importable/callable from this repo | Yes, 2026-08-13 - the only confirmed path to real image data |
| `nis_ar.exe` macro CLI | Command-line macro execution against an already-running NIS-Elements instance | An external OS process (this repo triggers it via `subprocess`) | Yes, 2026-08-13 |

None of these are pip packages or files that live in this repo - see the
"externally-added SDKs" discussion in-session for how that's tracked.
`acquisition/backends/nis_mock.py`'s `MockNIS` is this repo's own
hand-written stand-in for the first two, used for offline development.

## 1. The `nis` module - stage control

Only importable when running *inside* NIS-Elements' bundled Python
(`C:\Program Files\NIS-Elements\Python\python.exe`) with NIS-Elements AR
open - `import nis` raises `ImportError` anywhere else, which is exactly
how every caller in this repo (`stage_positions.py`, `run_protocol.py`,
`nis_jobs_connection_test.py`) detects "am I running on the microscope
PC?" and falls back to `MockNIS` otherwise.

| Function | Signature | Returns / does | Confirmed | Used in this repo |
|---|---|---|---|---|
| `XY_GetPosition()` | `()` | Current stage `(x, y)` in microns | Yes | `stage_positions.py`, `run_protocol.py`, `nis_jobs_connection_test.py` |
| `XY_Move(x, y)` | absolute microns | Moves stage to an absolute XY position | Yes | Same as above |
| `XY_MoveRelative(dx, dy)` | relative microns | Moves stage by an offset from current position | Yes (per microscope-notes.md's Jobs API list) | `MockNIS` only in this repo - no real-`nis` caller currently |
| `Z_GetPosition()` | `()` | Current focus (Z) in microns | Yes | `stage_positions.py`, `run_protocol.py` |
| `Z_Move(z)` | absolute microns | Moves focus to an absolute Z position | Yes | Same as above |
| `Z_MoveRelative(dz)` | relative microns | Moves focus by an offset | Yes | `MockNIS` only, no real-`nis` caller currently |

**Warning that applies to every call above** (repeated in multiple
source files, so worth stating once here): pass plain Python
`int`/`float`, never a `numpy` scalar - `to_plain_float()` wrappers exist
in `stage_positions.py`, `nis_sdk.py`, and `nis_jobs_connection_test.py`
specifically to guard this boundary.

Units are microns for all of the above - unlike the Ti2 ActiveX SDK
(`NkTi2Ax`), whose raw properties are in uncalibrated counts that had to
be empirically derived (see the other reference doc). The `nis` module's
functions were confirmed to already report/accept microns directly.

## 2. `ctx` - the Jobs context object

`ctx.shouldAbort()` reports whether the user clicked "Abort" in NIS-
Elements' own Job UI. This is the *only* confirmed member of `ctx` this
repo uses.

**Open question (unresolved as of this writing)**: exactly how a
standalone script obtains `ctx` when running the "mock" backend path on
real hardware is marked as an unconfirmed TODO in
[`run_protocol.py`](../acquisition/orchestration/run_protocol.py)'s
`resolve_backend()` - it currently guesses `from nis import ctx`, with a
comment noting it may actually need to come from `nis.ctx` instead
(unconfirmed, never tested against real NIS-Elements outside a Job).
Inside a real Jobs "PythonScript" task (see below), `ctx` arrives
differently: as the 4th positional argument to `run(imgs, Job, macro,
ctx)`, injected by NIS-Elements itself - not imported at all. Don't
assume the standalone-script access pattern and the Job-callback access
pattern are the same thing.

`MockNIS.ctx` (a `_MockContext` instance) mimics this with
`shouldAbort()` always returning `False`, since there's no UI to abort
from in the mock.

## 3. Real image capture - the Jobs "PythonScript" task

This is the important, easy-to-miss structural fact: **image capture is
not a function you call.** It's the opposite - NIS-Elements calls *your*
code, once, each time a Job's Capture task produces a frame. Confirmed
exhaustively (see
[`nis_jobs_capture.py`](../acquisition/planned/nis_jobs_capture.py)'s
header) that the Ti2 SDK family (ActiveX/native/`.NET`) has **zero**
capture-related functions at all - this Jobs mechanism is the *only* way
to get real frame data into this repo's Python tooling.

### How it works

1. A Job is built in NIS-Elements' own JOBS Explorer UI (not in this
   repo) with a `Capture` task, immediately followed by a `PythonScript`
   task at the same loop level, with the captured image wired in under
   that task's "Input Images".
2. The code pasted into that PythonScript task must define a top-level
   `run(imgs, Job, macro, ctx)` function - NIS-Elements calls this itself
   when the task executes. `nis_jobs_capture.py`'s `run()` is this
   project's copy-paste source for that function (see its header for why
   it lives outside the normal import graph - `limjob`, which provides
   the image objects, only exists inside NIS-Elements' own Python
   environment and can't be imported/tested from this repo's `.venv`).

| Parameter | Confirmed shape |
|---|---|
| `imgs[0].array()` | `(1, 2048, 2048, 2)`, dtype `uint16` - axis order `(Z, Y, X, Component)`, Z confirmed size 1 for a non-z-stepping Capture task |
| Component axis | Real per-channel data, not padding - confirmed via distinct per-component pixel statistics and isolated single-channel test captures |
| Component→channel mapping | Confirmed **only** for the "5-FAM, TD" combination on the "RootTipTest" experiment (2026-08-13): component 0 = 5-FAM, component 1 = TD. **Not verified to generalize** to a different channel count/order - re-verify per experiment |
| `print()` output visibility | **Unconfirmed** - not observed anywhere in the NIS UI during the live test. `_log()` in `nis_jobs_capture.py` writes to both `print()` and a log file on disk for exactly this reason - the file is the one you can actually trust |
| Exception behavior | Unconfirmed whether an uncaught exception aborts the whole Job or silently stops just this task - `run()` catches and logs everything defensively rather than ever raising past its own boundary |

### Open architecture mismatch (unresolved)

`run_protocol.py`'s `capture_image()` expects one frame Path back per
call (matching `MockNIS.capture()`'s one-call-one-Path contract), but a
real Capture task hands back *every active channel in one call*. Not yet
reconciled - see `nis_jobs_capture.py`'s "STILL UNRESOLVED" section for
the untested candidate fix (`Jobs_RunJobInitParam`'s `"OCSel.OptConf"`
param to force a single-channel Optical Configuration per trigger).

## 4. Triggering a Job from outside NIS - `nis_ar.exe`

Not a Python API at all - a command-line macro interface, confirmed
2026-08-13 to forward a command to an **already-running** NIS-Elements
instance rather than spawning a second one:

```
"C:\Program Files\NIS-Elements\nis_ar.exe" -cw "Jobs_RunJobByName(\"Project\", \"Job\")"
```

| Detail | Confirmed behavior |
|---|---|
| `-cw` | Runs the macro command and waits for it to finish before the process exits |
| Process identity | Forwards to the single running `nis_ar.exe` instance - confirmed via process list (same PID throughout), does not open a second NIS-Elements |
| Exit code | **Not a success signal** - observed as 127 even on a fully successful trigger. This repo's [`nis_jobs_trigger.py`](../acquisition/backends/nis_jobs_trigger.py) verifies success by polling for the expected output file's mtime to change instead (same pattern `start_protocol_run()` uses for the dashboard) |
| `subprocess` output redirection | **Must NOT** pass `capture_output=True`/`stdout=PIPE`/`stderr=PIPE` - confirmed to break the trigger entirely (produced no capture after a full 180s timeout); inherit the parent's stdout/stderr instead |
| Latency | Over 45 seconds end-to-end in measured runs, vs. a few seconds for a manual "Run Job" UI click - timeouts should be generous |
| Macro function used | `Jobs_RunJobByName(ProjDbName, ProjDbJobName)` - project/job names are case-sensitive, no default given deliberately in this repo's wrapper (a typo should fail loudly, not silently trigger the wrong Job) |

This is the "outside NIS" half; `nis_jobs_capture.py`'s `run()` (section
3 above) is the "inside NIS" half that actually receives the frame once
triggered.

## `MockNIS` - the offline stand-in

[`acquisition/backends/nis_mock.py`](../acquisition/backends/nis_mock.py)
reproduces the confirmed subset of the real API above as plain in-memory
state - `XY_GetPosition/XY_Move/XY_MoveRelative/Z_GetPosition/Z_Move/
Z_MoveRelative`, `.ctx.shouldAbort()`, plus a `capture()` convenience
method.

**Caveat worth knowing**: `MockNIS.capture()` is **not** a mock of a
confirmed real `nis.capture()` function - no such function exists (see
section 3 - real capture is the Jobs PythonScript inversion-of-control
pattern, not a callable). It's this project's own placeholder shape for
"something that returns a captured frame path", used by
`run_protocol.py`'s `capture_image()` until that function is wired up to
the real Jobs-based path.

## How this relates to the Ti2 ActiveX SDK (`NkTi2Ax`)

Two genuinely separate Nikon/NIS-provided APIs exist side by side in this
repo, both confirmed working for stage control, for different reasons:

| | `nis` module (this doc) | `NkTi2Ax` ActiveX SDK ([other reference doc](nikon-ti2-sdk-api-reference.md)) |
|---|---|---|
| Requires | NIS-Elements running, embedded Python | SDK installed + approved by Nikon, no NIS-Elements process needed |
| Units | Microns directly | Uncalibrated raw counts - empirically derived |
| Image capture | Yes (Jobs PythonScript task - the only capture path in this repo) | No - confirmed zero capture surface |
| Wired in as | `StagePositionManager(backend="mock")`'s default `nis`/`MockNIS` object | `StagePositionManager(backend="sdk")` / `NISSdk` |
| Abort signal | `ctx.shouldAbort()` (Job UI) | None - no Job UI in this path, dashboard-only abort |

`run_protocol.py --backend mock` uses the `nis`/`MockNIS` path;
`--backend sdk` uses `NkTi2Ax`/`NISSdk` - see that script's own header
comment for the exact tradeoff each backend implies.
