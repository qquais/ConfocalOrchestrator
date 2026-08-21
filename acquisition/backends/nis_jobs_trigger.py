# nis_jobs_trigger.py
# ------------------------------------------------------------
# SUPERSEDED 2026-08-17 - the team decided against real image capture
# going through NIS-Elements/Jobs at all (see mcp_server/loop_tools.py's
# header comment for the full rationale); real capture now goes through
# the Baumer GenICam camera instead (acquisition/backends/
# baumer_genicam.py), no longer via trigger_capture() below. This file
# is left as-is as a historical record of a confirmed-working mechanism
# (center_on_sample.py's capture_and_center() used to depend on it and
# has since been migrated to the Baumer camera too) - not something to
# build new work against.
#
# External-process trigger for the NIS-Elements "TestCapture" Job.
# CONFIRMED LIVE 2026-08-13 (see docs/microscope-notes.md's "Image
# Capture" section for the full history).
#
# This is the "outside NIS" half of real image capture:
# acquisition/planned/nis_jobs_capture.py's run() function is the
# "inside NIS" half (pasted into the Job's PythonScript task - reads
# the captured array from within NIS's own Python engine). This module
# is what an external Python process (eventually run_protocol.py) runs
# to make that Job actually fire, on demand, with no human clicking
# "Run Job" - the piece needed for a real unattended automated run.
#
# CONFIRMED mechanism (2026-08-13):
#   Launching "nis_ar.exe" -cw "Jobs_RunJobByName(Project, Job)" as a
#   subprocess, while NIS-Elements is ALREADY running, does NOT open a
#   second instance - it forwards the macro command to the running
#   instance and -cw waits for it to finish. Verified: process list
#   showed the same single nis_ar.exe PID throughout, and a real fresh
#   capture landed on disk afterward.
#
# CONFIRMED WORKING END-TO-END from this module's own trigger_capture()
# (not just a raw shell command) 2026-08-13, after fixing the
# capture_output bug below - triggered the Job, waited correctly, and
# saved a real capture (capture_20260813_180625_ch0.png).
#
# CAVEATS (all confirmed 2026-08-13):
#   - The launching subprocess's own exit code was 127 despite success.
#     Do NOT treat a nonzero exit code as failure - this module verifies
#     success by polling for the expected output file's mtime to
#     change instead, same pattern as start_protocol_run()'s dashboard
#     polling elsewhere in this repo.
#   - Took over 45 seconds end-to-end in the measured runs (vs. a few
#     seconds when "Run Job" is clicked directly in the NIS UI) -
#     TRIGGER_TIMEOUT_SEC below is generous on purpose; tighten it only
#     after more timing data.
#   - CRITICAL: do not pass capture_output=True/stdout=PIPE/stderr=PIPE
#     to the subprocess.run call below. Redirecting this process's
#     output into pipes broke the trigger entirely (produced no
#     capture at all after a full 180s timeout) - the same command run
#     with output NOT redirected succeeded twice in a row. Root cause
#     not fully understood (plausibly interferes with however -cw's
#     single-instance forwarding communicates with the running
#     instance) - treat this as a hard constraint, not a style choice.
#   - The currently-live PythonScript task in the real "TestCapture"
#     Job is still the DIAGNOSTIC script (writes captured_frame.npy +
#     array_info.json to a FIXED path, overwritten every run) - NOT the
#     production _save_components version in nis_jobs_capture.py (that
#     one saves per-channel PNGs with unique names, but has only been
#     smoke-tested offline against a saved .npy, never pasted into NIS
#     and run live). This module works against the diagnostic script's
#     CONFIRMED-LIVE fixed-path output, and immediately copies the raw
#     array out to a uniquely-named location after each trigger so the
#     next trigger's overwrite can't race it.
#   - Channel-to-component-index mapping (COMPONENT_CHANNEL_NAMES
#     below) is CONFIRMED ONLY for the "5-FAM, TD" two-channel
#     combination tested live on the "RootTipTest" experiment
#     (2026-08-13, see docs/microscope-notes.md) - NOT verified to
#     generalize to a different channel count or ordering. Re-verify
#     (isolated single-channel captures, same method as before) before
#     trusting this mapping for a different protocol/experiment.
#   - NOT YET wired into run_protocol.py's capture_image() - this is a
#     standalone, independently-testable piece. Wire it in only after
#     it's been exercised enough to trust its timeout/error handling
#     under repeated calls, not just the one manual test so far.
# ------------------------------------------------------------

import subprocess
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

NIS_EXE_PATH = Path(r"C:\Program Files\NIS-Elements\nis_ar.exe")

# All capture-related results/ output nests under this ONE folder
# (2026-08-14, at the user's request, so it isn't scattered across
# multiple similarly-named results/ folders) - split two ways inside it:
#   results/capture/captured_frame.npy, preview.png, array_info.json
#     - FIXED names, overwritten every run - scratch handoff from the
#     diagnostic PythonScript task inside NIS, not a historical record.
#   results/capture/capture_log/capture_<timestamp>.json
#     - one PER CAPTURE, never overwritten, kept in its own subfolder
#     since this list only grows over time and would otherwise clutter
#     the scratch files above - see _log_capture_result() below.
RESULTS_CAPTURE_DIR = REPO_ROOT / "results" / "capture"

# Fixed-path output of the CURRENTLY-LIVE diagnostic PythonScript task
# in NIS's "TestCapture" Job - see the CAVEATS above. If that script is
# ever replaced with nis_jobs_capture.py's production _save_components
# version, this module's _read_latest_capture() will need updating to
# match its (different, per-channel) output naming instead.
DIAGNOSTIC_OUTPUT_NPY = RESULTS_CAPTURE_DIR / "captured_frame.npy"

CAPTURE_DIR = REPO_ROOT / "data" / "captures"

# One JSON record per capture, named with the same timestamp as that
# capture's PNG files in CAPTURE_DIR - so you can find "what happened
# during this specific capture" (project/job, channels, real pixel
# size, which files it produced) without re-deriving it from the image
# files themselves or trusting console output that's already scrolled
# away. A SEPARATE FILE per capture (not one shared/growing log file),
# so this stays easy to browse as capture count grows over time.
RESULTS_LOG_DIR = RESULTS_CAPTURE_DIR / "capture_log"

# CONFIRMED 2026-08-13 for the "RootTipTest" experiment's 5-FAM+TD
# combination only - see the CAVEATS above before reusing this for a
# different experiment/channel set.
COMPONENT_CHANNEL_NAMES = ["5-FAM", "TD"]

TRIGGER_TIMEOUT_SEC = 180.0
POLL_INTERVAL_SEC = 1.0

# Where the TestCapture Job's "Alternative Storage Location" task
# (added 2026-08-14, alongside an "OCSel" task that forces the Job onto
# an isolated "QuaisTest_RootTipTestCopy" experiment copy - see
# docs/microscope-notes.md) saves its .nd2 files. FLAT - "Put files
# from all runs into specified folder (add a distinguishing unique
# prefix)" was chosen, so every capture's .nd2 lands directly in this
# one folder with a unique timestamp prefix, e.g.
# 20260814_171756_519__Channel5-FAM,TD_Seq0000.nd2 - NOT nested under
# project/job/<timestamp>/ subfolders the way NIS's own Jobs database
# default location was (see git history for that older path/pattern,
# from before this Job was rebuilt with Alternative Storage Location).
# Install- and Job-configuration-specific - re-confirm/update this if
# the Job's storage settings ever change again.
CAPTURE_ND2_DIR = Path(r"D:\QurratulAin_ConfocalOrchestratorProject\RootTipTestCaptures")


def _file_mtime(path: Path) -> float:
    """Return a file's mtime, or 0.0 if it doesn't exist yet - lets the
    first-ever trigger (no prior capture on disk) work the same way as
    later ones, without a special case."""
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return 0.0


def _read_pixel_size_um(after_mtime: float) -> float | None:
    """Find the real .nd2 file NIS auto-saved for this Job run (newest
    file directly under CAPTURE_ND2_DIR - flat, see that constant's
    comment - created after `after_mtime`) and read its calibrated
    pixel size in microns/pixel, the same way mcp_server/
    analysis_tools.py already does for post-hoc ND2 analysis
    (nd2.ND2File(...).voxel_size()).

    This is the CORRECT source of pixel size - confirmed 2026-08-14 to
    match NIS's own status bar exactly (0.7553 um/px vs. displayed
    "0.76 um/px") - rather than a value typed in by hand each time,
    which can silently go stale as objective/zoom changes.

    No longer takes project/job - CAPTURE_ND2_DIR is a single fixed
    folder now (the Alternative Storage Location task ignores NIS's
    project/job database structure entirely), so there's nothing
    project/job-specific left to build a path from.

    Returns None (does not raise) if no matching .nd2 file is found -
    callers should fall back to requiring an explicit pixel size rather
    than fail outright, since this depends on CAPTURE_ND2_DIR being
    correct for this install/Job configuration (see its own caveat) and
    on x/y pixel size being equal (assumed - not verified for a
    non-square-pixel setup).
    """
    import nd2

    candidates = [
        p for p in CAPTURE_ND2_DIR.glob("*.nd2")
        if p.stat().st_mtime >= after_mtime
    ]
    if not candidates:
        return None
    newest = max(candidates, key=lambda p: p.stat().st_mtime)

    with nd2.ND2File(newest) as f:
        voxel = f.voxel_size()
        if voxel.x != voxel.y:
            # Non-square pixels would break the simple offset_px *
            # pixel_size_um_per_px math in center_on_sample.py - flag
            # loudly rather than silently pick one axis.
            raise ValueError(
                f"{newest} has non-square pixels (x={voxel.x}, y={voxel.y} "
                "um/px) - center_on_sample.py's offset math assumes "
                "square pixels and needs updating before this is safe "
                "to use here."
            )
        return voxel.x


def _log_capture_result(
    project: str, job: str, timestamp: str, result: dict
) -> Path:
    """Write a single JSON record for one capture to RESULTS_LOG_DIR,
    named to match the timestamped subfolder already used for that
    capture's PNG files in CAPTURE_DIR (e.g. capture_20260814_172615.json
    for data/captures/20260814_172615/5-FAM.png, TD.png) - a persistent
    record of what happened, since trigger_capture()'s return value otherwise only
    exists in memory for whoever called it.
    """
    import json

    RESULTS_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = RESULTS_LOG_DIR / f"capture_{timestamp}.json"

    record = {
        "timestamp": timestamp,
        "project": project,
        "job": job,
        "shape": result["shape"],
        "dtype": result["dtype"],
        "pixel_size_um_per_px": result["pixel_size_um_per_px"],
        "paths": {name: str(p) for name, p in result["paths"].items()},
    }
    with open(log_path, "w") as f:
        json.dump(record, f, indent=2)

    return log_path


def trigger_capture(
    project: str,
    job: str,
    timeout_sec: float = TRIGGER_TIMEOUT_SEC,
) -> dict:
    """Trigger the named NIS-Elements Job from outside NIS, wait for a
    fresh capture to land, split it into one file per channel, and
    return their paths.

    project, job: the exact Project/Job names as they exist in NIS's
    own Jobs database (case-sensitive) - e.g. "Arabidopsis"/
    "TestCapture" was this repo's throwaway debug Job used to confirm
    this whole mechanism (2026-08-13), NOT a default to build real
    experiments against. No default is given deliberately - pass the
    real project/job you mean to run every time, so a typo or stale
    value fails loudly instead of silently triggering the wrong Job.

    Returns {"paths": {channel_name: Path, ...}, "shape": tuple,
    "dtype": str} - see this module's CAVEATS for what's confirmed vs.
    assumed about the underlying mechanism.

    Raises RuntimeError if no fresh capture appears within timeout_sec -
    this does NOT necessarily mean the trigger command itself failed;
    it may also mean the Job's Capture task errored inside NIS (e.g.
    "Camera is not connected", seen during testing) before ever
    reaching the PythonScript task that writes the output file.
    """
    import numpy as np
    from PIL import Image

    baseline_mtime = _file_mtime(DIAGNOSTIC_OUTPUT_NPY)

    macro_command = f'Jobs_RunJobByName("{project}", "{job}")'
    cmd = [str(NIS_EXE_PATH), "-cw", macro_command]

    # -cw is documented to wait for the macro to finish before this
    # process exits, but its own exit code isn't a reliable success
    # signal (see CAVEATS) - the real confirmation is the polling loop
    # below. subprocess.run's timeout is just a backstop in case -cw
    # itself hangs indefinitely (not observed so far, but untested at
    # scale).
    #
    # CONFIRMED 2026-08-13: do NOT pass capture_output=True (or
    # stdout=/stderr=PIPE) here - redirecting this process's
    # stdout/stderr into pipes appears to break -cw's ability to
    # forward the command to the already-running NIS-Elements instance
    # (a run with capture_output=True produced no capture at all after
    # 180s; the identical command run twice with output NOT redirected,
    # both directly via a shell and via this exact subprocess.run call,
    # succeeded both times). Inherit the parent's stdout/stderr instead.
    try:
        subprocess.run(cmd, timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        pass  # fall through to the polling loop - it may have still succeeded

    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if _file_mtime(DIAGNOSTIC_OUTPUT_NPY) > baseline_mtime:
            break
        time.sleep(POLL_INTERVAL_SEC)
    else:
        raise RuntimeError(
            f"No fresh capture appeared at {DIAGNOSTIC_OUTPUT_NPY} within "
            f"{timeout_sec:.0f}s of triggering Job '{job}' in project "
            f"'{project}'. This may mean the Capture task itself errored "
            "inside NIS (e.g. camera not connected) before reaching the "
            "PythonScript task - check NIS-Elements directly."
        )

    # Small extra pause - the file's mtime can update slightly before
    # the write is fully flushed to disk; not otherwise confirmed
    # necessary, but cheap insurance against a truncated read.
    time.sleep(0.5)

    arr = np.load(DIAGNOSTIC_OUTPUT_NPY)
    frame = np.asarray(arr)
    if frame.ndim == 4:
        frame = frame[0]  # (Z, Y, X, Component) -> (Y, X, Component), Z confirmed size 1
    num_components = frame.shape[-1] if frame.ndim == 3 else 1
    if frame.ndim == 2:
        frame = frame[..., np.newaxis]

    if num_components == len(COMPONENT_CHANNEL_NAMES):
        channel_names = COMPONENT_CHANNEL_NAMES
    else:
        channel_names = [f"ch{i}" for i in range(num_components)]

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # One subfolder per capture (not flat filenames) - all of that
    # capture's channels live together, e.g.
    # data/captures/20260814_181649/5-FAM.png, TD.png - easier to
    # browse than N similarly-prefixed files per capture in one flat
    # folder, and the folder name alone identifies which capture it is.
    capture_dir = CAPTURE_DIR / timestamp
    capture_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for i, name in enumerate(channel_names):
        channel = frame[..., i]
        safe_name = name.replace("/", "-")
        dest = capture_dir / f"{safe_name}.png"
        if channel.dtype == np.uint16:
            Image.fromarray(channel, mode="I;16").save(dest)
        else:
            Image.fromarray(channel).convert("L").save(dest)
        paths[name] = dest

    try:
        pixel_size_um_per_px = _read_pixel_size_um(baseline_mtime)
    except Exception as e:
        # Don't let a pixel-size lookup problem (e.g. CAPTURE_ND2_DIR
        # wrong for this install/Job configuration) throw away an
        # otherwise-successful capture - the caller can still fall back
        # to an explicit value. Surface it as None + a note rather than
        # raising.
        pixel_size_um_per_px = None
        print(f"WARNING: could not read real pixel size for this capture: {e}")

    result = {
        "paths": paths,
        "shape": tuple(arr.shape),
        "dtype": str(arr.dtype),
        "pixel_size_um_per_px": pixel_size_um_per_px,
    }

    log_path = _log_capture_result(project, job, timestamp, result)
    result["log_path"] = log_path

    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Trigger a NIS-Elements Job from outside NIS.")
    parser.add_argument("project", help='Project name as it exists in NIS Jobs, e.g. "Arabidopsis".')
    parser.add_argument("job", help='Job name as it exists in NIS Jobs, e.g. "TestCapture".')
    args = parser.parse_args()

    result = trigger_capture(args.project, args.job)
    print(f"shape={result['shape']} dtype={result['dtype']}")
    print(f"pixel_size_um_per_px={result['pixel_size_um_per_px']}")
    for name, path in result["paths"].items():
        print(f"  {name}: {path}")
    print(f"log: {result['log_path']}")
