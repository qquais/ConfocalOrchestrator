# run_protocol.py
# ------------------------------------------------------------
# Loads an acquisition protocol from a YAML file (protocols/example_protocol.yaml
# by default - see --protocol) and runs it: for every time point, visit every
# XY position, step through the z-stack at that position, and capture every
# channel at each z-slice.
#
# Stage control goes through one of three backends (--backend, default
# "mock" - safe, no hardware):
#   mock   -> the real NIS-Elements Jobs Python API (`nis` module + `ctx`
#             job-context object) if this happens to be running ON the
#             microscope PC with NIS-Elements open, else nis_mock.MockNIS
#             for offline development. Same as this script's original
#             behavior.
#   sdk    -> nis_sdk.NISSdk - real stage control via the Ti2 ActiveX SDK
#             (confirmed against the Ti2-E Device Simulator - see
#             docs/microscope-notes.md).
#   bridge -> nis_bridge.NISBridge - real stage control via the native-
#             macro bridge (deprioritized now that "sdk" works, kept as
#             a fallback).
#
# Run:
#   python run_protocol.py                                    # mock, example protocol
#   python run_protocol.py --backend sdk --protocol protocols/test_protocol_short.yaml
# ------------------------------------------------------------

import argparse
import threading
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import uvicorn
import yaml  # PyYAML - reads the .yaml protocol file into a Python dict
from PIL import Image

import dashboard  # this repo's acquisition/dashboard.py - shared status dict + web UI
from focus_check import FocusMonitor

# Path to the protocol file, relative to this script - matches the existing
# acquisition/ + protocols/ folder layout. Overridable via --protocol.
PROTOCOL_PATH = Path(__file__).resolve().parent.parent / "protocols" / "example_protocol.yaml"


# ── 1. Resolve the stage-control backend ─────────────────────────────────────
def resolve_backend(name: str):
    """Return (nis, ctx) for the given --backend name.

    `ctx` is the NIS-Elements Jobs API's job-context object -
    ctx.shouldAbort() reports whether the user clicked Abort inside NIS's
    own Job UI. Only "mock" has one (MockNIS.ctx mimics it for offline
    dev). "sdk" and "bridge" talk to the stage directly, with no NIS Job
    running and therefore no Job UI to click Abort in - ctx is None for
    those, and should_abort() below falls back to dashboard-only abort
    checking whenever ctx is None.
    """
    if name == "mock":
        # TODO: confirm the exact way to get `ctx` once this runs on the
        # scope PC - it may need to come from `nis` itself (e.g.
        # `ctx = nis.ctx`) rather than a top-level `ctx` module. Not
        # confirmed yet, so this is a placeholder (unchanged from before).
        try:
            import nis  # NIS-Elements' own Python API module (only available on the microscope PC)
            from nis import ctx
        except ImportError:
            from nis_mock import MockNIS
            nis = MockNIS()
            ctx = nis.ctx
            print(
                "'nis' module not found - using MockNIS (offline/dev mode). "
                "This will not move a real stage or capture real images."
            )
        return nis, ctx
    elif name == "sdk":
        from nis_sdk import NISSdk
        return NISSdk(), None
    elif name == "bridge":
        from nis_bridge import NISBridge
        return NISBridge(), None
    else:
        raise ValueError(f"Unknown backend '{name}'. Expected 'mock', 'sdk', or 'bridge'.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a ConfocalOrchestrator acquisition protocol.")
    parser.add_argument(
        "--backend", choices=("mock", "sdk", "bridge"), default="mock",
        help="Stage-control backend (default: mock - safe, no hardware moves).",
    )
    parser.add_argument(
        "--protocol", type=Path, default=PROTOCOL_PATH,
        help=f"Path to the protocol YAML file (default: {PROTOCOL_PATH}).",
    )
    return parser.parse_args()


def to_plain_float(value) -> float:
    """Convert a numpy scalar (or anything float-like) to a plain Python float.

    NIS-Elements functions expect plain Python numbers, not numpy types.
    """
    return float(value)


def should_abort(ctx) -> bool:
    """Return True if abort was requested from NIS-Elements OR the dashboard.

    Two independent abort sources feed this: the user clicking Abort inside
    NIS-Elements' own Job UI (ctx.shouldAbort() - only checked when `ctx`
    isn't None, i.e. backend="mock"; "sdk"/"bridge" have no Job UI to abort
    from), and the user clicking the "Stop / Abort Acquisition" button on
    the web dashboard (dashboard.acquisition_status["abort_requested"]).
    Either one stops the run at the next check.
    """
    nis_abort = ctx.shouldAbort() if ctx is not None else False
    dashboard_abort = dashboard.acquisition_status["abort_requested"]
    return nis_abort or dashboard_abort


def start_dashboard_server() -> None:
    """Run the dashboard's FastAPI app in a background thread.

    It has to live in THIS process (not a separately-launched `python
    dashboard.py`) so that dashboard.acquisition_status is the exact same
    dict object the acquisition loop below updates - a separate process
    would have its own independent copy and would never see real progress.
    The thread is a daemon so it doesn't stop the script from exiting once
    the acquisition loop finishes.
    """
    def _run():
        uvicorn.run(dashboard.app, host="0.0.0.0", port=8000, log_level="warning")

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    print("Dashboard running at http://localhost:8000 (or http://<this-pc-ip>:8000 remotely)")


# ── 2. Load the protocol file ────────────────────────────────────────────────
def load_protocol(path: Path) -> dict:
    """Read the YAML protocol file and return it as a nested dict."""
    with open(path, "r") as f:
        return yaml.safe_load(f)


# ── 3. Print a human-readable summary before touching any hardware ──────────
def print_summary(protocol: dict) -> None:
    """Print what this run will do: positions, channels, z-stack, duration."""
    info = protocol["protocol"]
    positions = protocol["positions"]
    channels = protocol["channels"]
    z_stack = protocol["z_stack"]
    timelapse = protocol["timelapse"]

    print("=" * 60)
    print(f"Protocol: {info['name']}  (v{info.get('version', '?')})")
    print(f"  {info.get('description', '')}")
    print("=" * 60)
    print(f"Positions:   {len(positions)}  -> {[p['label'] for p in positions]}")
    print(f"Channels:    {len(channels)}  -> {[c['name'] for c in channels]}")
    if z_stack.get("enabled"):
        print(
            f"Z-stack:     {z_stack['num_slices']} slices "
            f"({z_stack['z_start']} to {z_stack['z_end']} um, step {z_stack['z_step']} um)"
        )
    else:
        print("Z-stack:     disabled (single plane per position)")
    interval = timelapse["interval_minutes"]
    print(
        f"Duration:    {timelapse['duration_hours']} hours, "
        f"interval {interval} min ({'continuous' if interval == 0 else 'delayed'} between cycles)"
    )
    print(f"Save to:     {protocol['output']['save_directory']}")
    print("=" * 60)


def confirm_start() -> bool:
    """Ask the user to confirm before any stage movement happens."""
    print("\nSAFETY CHECK")
    print("  This will move the XY stage and Z focus repeatedly for the")
    print("  full duration above. Make sure the sample and objective are")
    print("  correctly loaded before continuing.")
    answer = input("  Type 'yes' to start the acquisition, anything else to cancel: ").strip().lower()
    return answer == "yes"


# ── 4. Work out the Z positions for one z-stack ──────────────────────────────
def get_z_slices(position: dict, z_stack: dict) -> list:
    """Return the list of absolute Z positions (microns) to visit at one XY
    position, based on the protocol's z_stack settings.
    """
    base_z = to_plain_float(position["z"])
    if not z_stack.get("enabled"):
        return [base_z]

    num_slices = z_stack["num_slices"]
    z_start = z_stack["z_start"]
    z_step = z_stack["z_step"]
    return [to_plain_float(base_z + z_start + i * z_step) for i in range(num_slices)]


# ── 5. Capture one image ─────────────────────────────────────────────────────
def capture_image(nis, backend: str, channel: dict) -> Path | None:
    """Capture a single image on the given channel.

    Returns the captured frame's path, or None if this backend can't
    produce a real frame yet.

    Only backend="mock" returns a real file today (nis_mock.MockNIS.capture()
    writes an actual image). "sdk"/"bridge" real image capture is a
    separate TODO from the XY/Z stage control confirmed in nis_sdk.py -
    the real NIS-Elements capture call for those backends hasn't been
    identified yet, so there's nothing to call here for them. Once
    confirmed, add the real call in an `if backend == "sdk": ...` branch
    below so focus-check (see run_acquisition) has real frames on real
    hardware too.
    """
    print(
        f"      Capturing channel '{channel['name']}' "
        f"({channel['laser_wavelength']} nm, {channel['exposure_ms']} ms exposure)..."
    )
    if backend == "mock":
        return nis.capture()
    return None


# ── 6. Run the full acquisition ──────────────────────────────────────────────
def run_acquisition(protocol: dict, nis, ctx, backend: str) -> int:
    """Loop: time points -> XY positions -> z-slices -> channels.

    After each timepoint, runs a focus-drift check (focus_check.FocusMonitor)
    against the timepoint's first captured frame - the first timepoint sets
    the baseline, later ones are compared against it. Only meaningful when
    capture_image() actually returns a frame (backend="mock" today - see
    its docstring); for "sdk"/"bridge" the check is skipped with a note,
    since there's no real frame yet to check.

    Returns the total number of images captured.
    """
    positions = protocol["positions"]
    channels = protocol["channels"]
    z_stack = protocol["z_stack"]
    timelapse = protocol["timelapse"]

    duration_hours = timelapse["duration_hours"]
    interval_minutes = timelapse["interval_minutes"]
    total_timepoints = timelapse.get("total_timepoints")

    focus_monitor = FocusMonitor()

    start_time = time.monotonic()
    images_captured = 0
    timepoint = 0

    # A "timepoint" is one full pass through every position - one snapshot in
    # time of the whole time-lapse. This protocol has total_timepoints=null
    # (interval_minutes=0, "no delay"), so instead of a fixed count we keep
    # looping until duration_hours has elapsed. If a protocol DOES set a
    # fixed total_timepoints, we use that count instead.
    while True:
        elapsed_hours = (time.monotonic() - start_time) / 3600.0

        if total_timepoints is not None:
            if timepoint >= total_timepoints:
                break
            timepoint_label = f"{timepoint + 1}/{total_timepoints}"
        else:
            if elapsed_hours >= duration_hours:
                break
            timepoint_label = f"{timepoint + 1} (elapsed {elapsed_hours:.2f}h / {duration_hours}h)"

        # ── Check for user abort before starting this timepoint ──────────
        if should_abort(ctx):
            print(f"\nAbort requested by user - stopping before timepoint {timepoint_label}.")
            dashboard.update_status(status="aborted")
            break

        print(f"\n--- Timepoint {timepoint_label} ---")

        # First frame captured this timepoint - used as the focus-check
        # reference below (see FocusMonitor docstring / module comment).
        timepoint_reference_frame = None

        try:
            # ── Loop through every XY position ───────────────────────────
            for pos_index, position in enumerate(positions, start=1):
                print(f"  Position {pos_index}/{len(positions)}: '{position['label']}'")

                x = to_plain_float(position["x"])
                y = to_plain_float(position["y"])
                nis.XY_Move(x, y)

                # ── Step through the z-stack at this position ────────────
                z_slices = get_z_slices(position, z_stack)
                for z_index, z in enumerate(z_slices, start=1):
                    print(f"    Z-slice {z_index}/{len(z_slices)}: Z={z:.2f} um")
                    nis.Z_Move(z)

                    # ── Capture every channel at this z-slice ─────────────
                    for channel in channels:
                        frame_path = capture_image(nis, backend, channel)
                        if timepoint_reference_frame is None and frame_path is not None:
                            timepoint_reference_frame = frame_path
                        images_captured += 1
                        dashboard.update_status(
                            timepoint_current=timepoint + 1,
                            position_label=position["label"],
                            channel_name=channel["name"],
                            images_captured=images_captured,
                        )

            # ── Focus-drift check for this timepoint ──────────────────────
            if timepoint_reference_frame is not None:
                frame = np.array(Image.open(timepoint_reference_frame).convert("RGB"))
                if focus_monitor.baseline is None:
                    baseline = focus_monitor.set_baseline(frame)
                    print(f"  Focus baseline set: sharpness={baseline:.6f}")
                else:
                    result = focus_monitor.check(frame)
                    flag = "  <-- POSSIBLE FOCUS DRIFT" if result.drift_detected else ""
                    print(
                        f"  Focus check: sharpness={result.sharpness:.6f} "
                        f"(drop={result.percent_drop:.1%}){flag}"
                    )
                    dashboard.update_status(focus_drift_detected=result.drift_detected)
            elif backend != "mock":
                print(
                    f"  Focus check skipped - backend='{backend}' has no confirmed real "
                    "capture call yet (see capture_image()'s TODO), so there's no frame "
                    "to check focus against."
                )

        except Exception as e:
            # A failure partway through one timepoint (e.g. one bad move or
            # capture) shouldn't throw away hours of an in-progress
            # time-lapse, so we log it and move on to the next timepoint
            # instead of crashing the whole run.
            print(f"  ERROR during timepoint {timepoint_label}: {e}")

        timepoint += 1

        # ── Wait for the next cycle, if the protocol asks for a delay ────
        if interval_minutes > 0:
            print(f"  Waiting {interval_minutes} min before next timepoint...")
            time.sleep(interval_minutes * 60)

    return images_captured


def main():
    args = parse_args()

    print(f"Loading protocol from: {args.protocol}")

    try:
        protocol = load_protocol(args.protocol)
    except Exception as e:
        print(f"Failed to load protocol file: {e}")
        return

    print_summary(protocol)
    print(f"Backend:     {args.backend}")
    print("=" * 60)

    # ── SAFETY: nothing below this line runs without explicit confirmation ──
    if not confirm_start():
        print("Acquisition cancelled by user. No stage motion performed.")
        return

    nis, ctx = resolve_backend(args.backend)

    start_dashboard_server()

    timelapse = protocol["timelapse"]
    dashboard.update_status(
        status="running",
        started_at=time.time(),
        estimated_total_seconds=timelapse["duration_hours"] * 3600,
        timepoint_total=timelapse.get("total_timepoints"),
        images_captured=0,
        error_message=None,
        abort_requested=False,
        focus_drift_detected=False,
    )

    print(f"\nAcquisition started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    try:
        images_captured = run_acquisition(protocol, nis, ctx, args.backend)
    except Exception as e:
        print(f"\nAcquisition FAILED: {e}")
        dashboard.update_status(status="error", error_message=str(e))
        return

    if dashboard.acquisition_status["status"] != "aborted":
        dashboard.update_status(status="complete")

    print(f"\nAcquisition complete. Total images captured: {images_captured}")


if __name__ == "__main__":
    main()
