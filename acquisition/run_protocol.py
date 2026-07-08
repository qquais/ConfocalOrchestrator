# run_protocol.py
# ------------------------------------------------------------
# Loads an acquisition protocol from a YAML file (protocols/example_protocol.yaml)
# and runs it on the Nikon Eclipse Ti2-E via the NIS-Elements Python API:
# for every time point, visit every XY position, step through the z-stack
# at that position, and capture every channel at each z-slice.
#
# >>> Run this script ON the microscope PC, with NIS-Elements AR 6.20.02
# >>> already open. The `nis` module (and the job `ctx` context object used
# >>> for abort checks) are provided by NIS-Elements itself and do not exist
# >>> anywhere else, so this script cannot run standalone on a dev laptop
# >>> (Mac/Linux/plain Windows Python) - it will only import successfully
# >>> inside that environment. Running it on a Mac will fail at the
# >>> `import nis` line below - that is expected.
#
# Run (on the microscope PC, from the NIS-Elements Python console or a
# terminal with the NIS-Elements Python environment active):
#   python run_protocol.py
# ------------------------------------------------------------

import time
from datetime import datetime
from pathlib import Path

import yaml  # PyYAML - reads the .yaml protocol file into a Python dict

# ── 1. Connect to the NIS-Elements Python API ────────────────────────────────
try:
    import nis  # NIS-Elements' own Python API module (only available on the microscope PC)
except ImportError as e:
    raise SystemExit(
        "Could not import the 'nis' module.\n"
        "This script must be run ON the microscope PC, with NIS-Elements "
        "AR 6.20.02 already open, so its Python API is available.\n"
        f"Original error: {e}"
    )

# `ctx` is the job-context object NIS-Elements provides while a script runs
# as a Job; ctx.shouldAbort() reports whether the user clicked the Abort
# button in NIS-Elements.
# TODO: confirm the exact way to get `ctx` once this runs on the scope PC -
# it may need to come from `nis` itself (e.g. `ctx = nis.ctx`) rather than
# a top-level `ctx` module. Not confirmed yet, so this is a placeholder.
try:
    from nis import ctx
except ImportError:
    ctx = None

# Path to the protocol file, relative to this script - matches the existing
# acquisition/ + protocols/ folder layout.
PROTOCOL_PATH = Path(__file__).resolve().parent.parent / "protocols" / "example_protocol.yaml"


def to_plain_float(value) -> float:
    """Convert a numpy scalar (or anything float-like) to a plain Python float.

    NIS-Elements functions expect plain Python numbers, not numpy types.
    """
    return float(value)


def should_abort() -> bool:
    """Return True if the user clicked Abort in NIS-Elements, else False.

    Falls back to "never abort" if `ctx` isn't available (e.g. while reading
    or testing this script off the microscope PC).
    """
    if ctx is None:
        return False
    return ctx.shouldAbort()


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
def capture_image(channel: dict) -> None:
    """Capture a single image on the given channel.

    TODO: replace this placeholder with the real NIS-Elements capture call
    (e.g. a Jobs API "Capture" step) once that function is confirmed - it
    wasn't included in the list of API functions this script was written
    against. For now it just prints, so the loop structure and logging
    below can be tested end-to-end before the real capture call is wired in.
    """
    print(
        f"      Capturing channel '{channel['name']}' "
        f"({channel['laser_wavelength']} nm, {channel['exposure_ms']} ms exposure)..."
    )
    # Real capture call would go here, e.g.: nis.Capture()


# ── 6. Run the full acquisition ──────────────────────────────────────────────
def run_acquisition(protocol: dict) -> int:
    """Loop: time points -> XY positions -> z-slices -> channels.

    Returns the total number of images captured.
    """
    positions = protocol["positions"]
    channels = protocol["channels"]
    z_stack = protocol["z_stack"]
    timelapse = protocol["timelapse"]

    duration_hours = timelapse["duration_hours"]
    interval_minutes = timelapse["interval_minutes"]
    total_timepoints = timelapse.get("total_timepoints")

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
        if should_abort():
            print(f"\nAbort requested by user - stopping before timepoint {timepoint_label}.")
            break

        print(f"\n--- Timepoint {timepoint_label} ---")

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
                        capture_image(channel)
                        images_captured += 1

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
    print(f"Loading protocol from: {PROTOCOL_PATH}")

    try:
        protocol = load_protocol(PROTOCOL_PATH)
    except Exception as e:
        print(f"Failed to load protocol file: {e}")
        return

    print_summary(protocol)

    # ── SAFETY: nothing below this line runs without explicit confirmation ──
    if not confirm_start():
        print("Acquisition cancelled by user. No stage motion performed.")
        return

    print(f"\nAcquisition started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    try:
        images_captured = run_acquisition(protocol)
    except Exception as e:
        print(f"\nAcquisition FAILED: {e}")
        return

    print(f"\nAcquisition complete. Total images captured: {images_captured}")


if __name__ == "__main__":
    main()
