# nis_jobs_capture.py
# ------------------------------------------------------------
# CONFIRMED LIVE 2026-08-13 - the run() function below has been executed
# against real NIS-Elements (JOBS Editor now licensed - was confirmed
# unlicensed as of 2026-07-27, see docs/microscope-notes.md's "Image
# Capture" section for the full confirmed findings and open questions).
# Nothing in this file is imported/called by run_protocol.py or any
# other script in this repo - it exists to be copy-pasted into a NIS-
# Elements Job's PythonScript task, which is the only way this code
# ever actually runs (see "WHY THIS EXISTS").
#
# CONFIRMED (via a TestCapture Job: Capture -> Python Script, no
# z-stepping, no sample on the stage):
#   - imgs[0].array() returns a real numpy array, shape
#     (1, 2048, 2048, 2), dtype uint16 - NOT (1, 1024, 1024, 1) as
#     originally guessed from older ND2 sample metadata (see
#     docs/microscope-notes.md's "Real Sample Data").
#   - The trailing axis of size 2 is real per-channel data, not a
#     duplicated/garbage axis - one Capture task call returned TWO
#     channels/components at once (confirmed via distinct per-
#     component pixel statistics).
#   - CONFIRMED (2026-08-13, follow-up test with a real sample loaded -
#     an Arabidopsis root tip, "RootTipTest" experiment): component
#     index -> channel mapping, verified by capturing with only one
#     channel active at a time (not just inferred from a filename):
#       component 0 = 5-FAM - flat/no real signal on this sample
#       component 1 = TD    - real structured signal (min=50/max=613/
#                              mean=71.4/std=20.5 isolated; matches the
#                              combined two-channel capture's component
#                              1 almost exactly)
#     5-FAM produced no real fluorescence signal on this particular
#     sample/config - its reported emission range (560-850nm) is
#     unusually red-shifted for FAM (normally ~505-545nm), so this may
#     be a filter-cube misconfiguration rather than a real absence of
#     dye - worth checking with whoever set up "RootTipTest" before
#     trusting 5-FAM data from this config.
#   - print() output was NOT confirmed visible anywhere in the NIS UI
#     during this test - only the log-file and JSON-file writes were
#     checked afterward. Treat print() as still unconfirmed; keep
#     relying on file output for anything that needs to be seen.
#
# CONFIRMED (2026-08-13) - external trigger mechanism:
#   NIS-Elements' own executable supports command-line macro execution
#   even against an ALREADY-RUNNING instance:
#     "C:\Program Files\NIS-Elements\nis_ar.exe" -cw "Jobs_RunJobByName(\"Arabidopsis\", \"TestCapture\")"
#   -cw runs the macro command and waits for it to finish. Tested live
#   from a plain subprocess call (not from inside NIS) while NIS-
#   Elements was already running: confirmed it does NOT spawn a second
#   instance (process list showed the same single nis_ar.exe PID
#   throughout) and DOES trigger a real Job run - a fresh capture
#   landed in results/capture/ with real signal data. This is the
#   external-trigger mechanism run_protocol.py needs.
#   CAVEATS:
#     - The launching subprocess's own exit code was 127, NOT 0, despite
#       success - do not use this process's exit code as a success
#       signal. Verify success by polling for the expected output file
#       to appear/update instead (same pattern start_protocol_run()
#       already uses for the dashboard).
#     - Took notably longer than a manual "Run Job" click in the UI
#       (over 45 seconds, vs. a few seconds when clicked directly) -
#       account for this in timeout design, don't assume it's fast.
#     - Jobs_RunJobByName takes (ProjDbName, ProjDbJobName) - no job key
#       lookup needed for this simple case.
#
# STILL UNRESOLVED (see docs/microscope-notes.md for detail):
#   - Architecture mismatch: run_protocol.py's capture_image() is
#     called once per channel and expects one frame back per call
#     (matching MockNIS.capture()'s one-Path-per-call contract). A real
#     Capture task instead hands back every active channel together in
#     one call (see CONFIRMED above) - this file now saves one PNG per
#     component, but nothing yet reconciles "one call -> N files" with
#     capture_image()'s "one call -> one Path" contract. One plausible
#     fix, NOT yet tested: use Jobs_RunJobInitParam(JobdefDbKey,
#     JobParamJson) to set "OCSel.OptConf" to a single-channel Optical
#     Configuration before each trigger, so one call = one channel
#     again - matching capture_image()'s existing contract instead of
#     requiring it to change. Needs live testing before relying on it.
#   - Whether _capture_count (module-level Python state) persists
#     across separate -cw-triggered Job runs, or resets each time
#     (each trigger may be a fresh execution context) - untested. If it
#     resets, filenames will need a different uniqueness source (e.g.
#     a timestamp is already included, so collisions are unlikely, but
#     verify before relying on the sequence number ordering anything).
#
# WHY THIS EXISTS
# ----------------
# The Ti2 SDK family - ActiveX (NkTi2Ax), native C (Ti2_Mic_Driver.dll),
# and the .NET P/Invoke wrapper - has ZERO image-capture surface.
# Confirmed exhaustively: every header Nikon ships, the official
# compiled help file (NIKONTI2_E.chm), and all three binding styles
# expose the same ~16-function set (MIC_Open/Close, MIC_DataGet/DataSet,
# MIC_MetadataGet/Set, MIC_DedicatedCommand, MIC_Convert_*) - stage,
# turret, and objective control only. See docs/microscope-notes.md for
# the stage-control side of this SDK, which IS confirmed working
# (backends/nis_sdk.py, backend="sdk").
#
# Real image capture only exists through NIS-Elements' own Jobs API,
# specifically its "PythonScript" task type - documented locally at
# C:\Program Files\NIS-Elements\Docs\nis\eng_ar\task.system_section.html
# (this is a local install doc, not mirrored into this repo). NIS-
# Elements calls the run() function below itself when the Job runs - it
# is NOT something a standalone Python process (like run_protocol.py)
# can import or call directly. It only exists inside a Job built in
# NIS-Elements' own JOBS Explorer UI. This is an inversion-of-control
# model: NIS drives the Job and hands your code a frame, rather than
# your code requesting one. `limjob` itself only exists inside NIS-
# Elements' own Python environment - it cannot be imported or tested
# from this repo's .venv, which is why this file has no automated test;
# the CONFIRMED section above is the closest thing to one.
#
# WHAT THE run() FUNCTION BELOW DOES (once pasted into a PythonScript task)
# ---------------------------------------------------------------------
# 1. Reads imgs[0].array() and logs its shape/dtype.
# 2. Squeezes a size-1 leading Z axis (confirmed size 1 for a Capture
#    task with no z-stepping - see CONFIRMED above). Warns instead of
#    silently dropping data if Z ever comes back >1 - this file's job
#    is single-frame capture, not stack handling; a real z-stack should
#    chain one Capture+PythonScript pair per slice at the Job level
#    instead.
# 3. Saves EACH component along the trailing axis as its own 16-bit
#    grayscale PNG (confirmed real frames are uint16 - see CONFIRMED
#    above), into the SAME acquisition/backends/nis_mock.CAPTURE_DIR
#    used by MockNIS.capture(), named
#    capture_<timestamp>_<seq>_ch<component_index>.png. One Capture
#    call producing multiple channel files (not one) is exactly the
#    mismatch flagged in "STILL UNRESOLVED" above - not yet reconciled
#    with run_protocol.py's per-channel capture_image() contract.
# 4. Never raises past its own try/except - an uncaught exception inside
#    a PythonScript task's run() may abort the whole Job or may just
#    silently stop that task (unconfirmed either way) - so every step
#    logs defensively rather than assuming a Python traceback will be
#    visible anywhere useful (print() itself is unconfirmed - see
#    CONFIRMED above).
#
# NOT part of this file's scope: writing the final per-experiment .nd2
# file matching example_protocol.yaml's output.save_directory/
# filename_convention - that's NIS-Elements' own Job-level Save/Export
# task (configured in JOBS Explorer, not Python), separate from this
# PythonScript task's array access. This file is about getting frame
# data INTO this repo's Python-side tooling (focus-drift checking,
# sharpness scoring) during a run, not about replacing NIS's own save
# path.
#
# REMAINING STEPS
# ------------------------------------------------------
#   1. DONE (2026-08-13) - 5-FAM/TD component-index mapping confirmed
#      independently via isolated single-channel captures - see
#      CONFIRMED above.
#   2. IN PROGRESS - reconcile "one Capture call -> N channel files"
#      with run_protocol.py's "one capture_image() call -> one Path"
#      per-channel loop. Next test: does Jobs_RunJobInitParam's
#      "OCSel.OptConf" JSON param reliably select a single-channel
#      Optical Configuration per -cw trigger? If yes, one call = one
#      channel again, matching capture_image()'s existing contract.
#   3. DONE (2026-08-13) - external trigger confirmed via
#      "nis_ar.exe" -cw "Jobs_RunJobByName(...)" against the already-
#      running instance - see CONFIRMED above.
#   4. Once 2 is resolved, wire this into run_protocol.py's
#      capture_image(), in a new `if backend == "sdk": ...` branch,
#      replacing its current `return None` for that backend.
# ------------------------------------------------------------

import time
from datetime import datetime
from pathlib import Path

# Reuses the exact same capture directory as MockNIS.capture()
# (acquisition/backends/nis_mock.py) - see point 3 in "WHAT THE run()
# FUNCTION BELOW DOES" above for why that matters once this is wired in.
CAPTURE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "captures"
CAPTURE_LOG_PATH = Path(__file__).resolve().parent.parent.parent / "logs" / "nis_jobs_capture.log"

# Persists across calls within one NIS-Elements Python session, the same
# way MockNIS._capture_count does within one MockNIS instance - NOT
# independently confirmed to survive across repeated run() calls in one
# Job run (the 2026-08-13 test was a single Capture, so this has only
# been exercised at count=1). If it resets every call, every frame
# overwrites capture_..._0001_ch0.png instead of incrementing - that
# would be visible immediately as missing frames in CAPTURE_DIR.
_capture_count = 0


def _log(message: str) -> None:
    """Write a timestamped line to both print() and a log file on disk.

    Two independent output paths because where print() output surfaces
    from inside a NIS-Elements PythonScript task was NOT confirmed
    visible during the 2026-08-13 live test (see this file's header) -
    the log file is the fallback that's guaranteed readable from
    outside NIS-Elements afterward, from any machine that can see this
    repo's logs/ directory.
    """
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}"
    print(line)
    try:
        CAPTURE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CAPTURE_LOG_PATH, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass  # best-effort - never let logging itself break capture


def _save_components(arr) -> list[Path]:
    """Normalize one Capture call's array and save each channel/
    component as its own 16-bit PNG in CAPTURE_DIR. Returns the list of
    written paths (one per component).

    arr is confirmed (2026-08-13, see this file's header) as
    (Z, Y, X, Component) with Z=1, Component=2 for a live two-channel
    capture - this squeezes the Z axis (warning instead of silently
    dropping data if it's ever >1) and loops over Component, saving
    each as capture_<timestamp>_<seq>_ch<i>.png.
    """
    global _capture_count

    import numpy as np
    from PIL import Image

    _log(f"raw array shape={arr.shape} dtype={arr.dtype}")

    frame = np.asarray(arr)
    if frame.ndim == 4:
        z_count = frame.shape[0]
        if z_count > 1:
            _log(
                f"WARNING: array has {z_count} Z slices - this run() only "
                "saves the first. A real z-stack should chain one Capture+"
                "PythonScript pair per slice at the Job level instead."
            )
        frame = frame[0]  # -> (Y, X, Component)
    elif frame.ndim == 2:
        frame = frame[..., np.newaxis]  # -> (Y, X, 1), so the loop below still works

    num_components = frame.shape[-1]
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    _capture_count += 1
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    paths = []
    for i in range(num_components):
        channel = frame[..., i]
        dest = CAPTURE_DIR / f"capture_{timestamp}_{_capture_count:04d}_ch{i}.png"

        # 16-bit grayscale ("I;16") to preserve real camera dynamic
        # range (confirmed uint16, see this file's header) - PIL can
        # only write this mode from a uint16 array; fall back to an
        # 8-bit convert for anything else rather than erroring on an
        # unexpected dtype.
        if channel.dtype == np.uint16:
            Image.fromarray(channel, mode="I;16").save(dest)
        else:
            Image.fromarray(channel).convert("L").save(dest)

        paths.append(dest)
        _log(
            f"saved {dest} (component {i}/{num_components}, "
            f"shape={channel.shape} dtype={channel.dtype}, "
            f"min={channel.min()} max={channel.max()})"
        )

    return paths


def run(imgs, Job, macro, ctx):
    """Entry point NIS-Elements calls for this PythonScript task - see
    this file's header comment for the exact Job setup this expects
    (one Capture task immediately before it, at the same loop level,
    with this image wired in under Input Images).

    CONFIRMED LIVE 2026-08-13 against real hardware (no sample loaded) -
    see this file's header for exactly what was and wasn't verified
    before relying on this against a live sample/full protocol.
    """
    start = time.monotonic()
    try:
        if not imgs:
            _log("ERROR: run() called with no input images - check the "
                 "PythonScript task's Input Images configuration.")
            return
        img = imgs[0]
        arr = img.array()
        paths = _save_components(arr)
        _log(f"run() completed in {time.monotonic() - start:.3f}s -> {paths}")
    except Exception as e:
        # Deliberately caught and logged rather than re-raised - an
        # uncaught exception's effect on the Job (abort vs. silently
        # stop this task) is unconfirmed, which would be far worse than
        # losing one frame.
        _log(f"ERROR in run(): {type(e).__name__}: {e}")
