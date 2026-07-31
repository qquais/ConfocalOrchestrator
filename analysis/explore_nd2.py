# explore_nd2.py
# ------------------------------------------------------------
# A beginner-friendly script to open a .ND2 microscopy file,
# print its metadata, and save one image frame as a PNG.
#
# How to run (from the repo root, with .venv activated):
#   python3 analysis/explore_nd2.py
#   python3 analysis/explore_nd2.py --file "data/raw/Timelapse1.nd2"
#
# Requirements:  pip install nd2 numpy Pillow
#
# 2026-07: fixed frame-extraction to handle multi-channel (C axis) files.
# The original version only special-cased RGB (S=3) files; for a real
# multi-channel file it silently repeated frame[0] indexing, which picks
# T=0/C=0 and discards every other channel and timepoint with no message.
# Confirmed against real Dye Trial 1/Z1 data. Now: if a C axis is present, one PNG
# is saved per channel (at T=0/Z=0) with clear filenames — for a full
# per-timepoint extraction of one chosen channel, use extract_frames.py.
# ------------------------------------------------------------

import argparse
from pathlib import Path

import nd2          # reads .ND2 files from Nikon microscopes
import numpy as np  # used to work with image data as arrays
from PIL import Image  # used to save the image as a PNG

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ND2_FILE = REPO_ROOT / "data" / "raw" / "MRAP1 KO DN_10X03.nd2"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "analysis" / "nd2_sample"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Print ND2 metadata and save a preview PNG.")
    parser.add_argument("--file", type=Path, default=DEFAULT_ND2_FILE, help="Path to the .nd2 file")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR, help="Folder to save preview PNG(s) into")
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def to_uint8(frame: np.ndarray) -> np.ndarray:
    """Contrast-stretch a frame's actual min-max range to 0-255."""
    frame = frame.astype(np.float32)
    lo, hi = frame.min(), frame.max()
    if hi > lo:
        frame = (frame - lo) / (hi - lo) * 255
    return np.clip(frame, 0, 255).astype(np.uint8)


def main() -> None:
    args = parse_args()
    nd2_file = resolve_path(args.file)
    output_dir = resolve_path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── 2. Open the file ──────────────────────────────────────────────────────────
    with nd2.ND2File(nd2_file) as f:

        # ── 3. Print basic metadata ───────────────────────────────────────────────
        print("=" * 50)
        print("FILE INFO")
        print("=" * 50)

        # `f.sizes` is a dictionary like {'T': 10, 'C': 2, 'Z': 5, 'Y': 512, 'X': 512}
        # T = timepoints, C = channels, Z = z-slices, Y/X = image height/width
        print(f"Dimensions : {f.sizes}")
        print(f"Data type  : {f.dtype}")   # e.g. uint16 means 16-bit grayscale

        # ── 4. Pixel size (how many micrometres each pixel covers) ────────────────
        try:
            vox = f.voxel_size()
            print(f"Pixel size : x={vox.x:.4f} µm,  y={vox.y:.4f} µm,  z={vox.z:.4f} µm")
        except Exception:
            print("Pixel size : not available in this file")

        # ── 5. Channel names ──────────────────────────────────────────────────────
        meta = f.metadata
        channel_names = []
        if meta and hasattr(meta, "channels") and meta.channels:
            print(f"\nChannels ({len(meta.channels)} total):")
            for i, ch in enumerate(meta.channels):
                name = ch.channel.name if hasattr(ch, "channel") else "unknown"
                channel_names.append(name)
                print(f"  Channel {i}: {name}")
        else:
            print("\nNo channel metadata found in this file.")

        # ── 6. Experiment loops (timepoints, z-stacks, etc.) ─────────────────────
        experiment = f.experiment
        if experiment:
            print("\nExperiment loops:")
            for loop in experiment:
                print(f"  {loop.type}: {loop.count} steps")
        else:
            print("\nNo experiment loop metadata found.")

        print("=" * 50)

        # ── 7. Load the full image array ──────────────────────────────────────────
        print("\nLoading image data into memory...")
        images = f.asarray()
        print(f"Array shape: {images.shape}")
        print(f"Min value  : {images.min()},  Max value: {images.max()}")

        sizes = f.sizes
        is_rgb = sizes.get("S", 1) == 3

    # ── 8. Extract a displayable frame ───────────────────────────────────────
    if is_rgb:
        # Your file has S=3 (RGB colour). asarray() gives shape (Y, X, 3).
        # Only strip leading T/Z axes, never the trailing 3 colour channels.
        frame = images
        while frame.ndim > 3:
            frame = frame[0]
        out_path = output_dir / "frame_0.png"
        Image.fromarray(to_uint8(frame)).save(out_path)
        print(f"\nExtracted frame shape: {frame.shape} (RGB)")
        print(f"Saved PNG  : {out_path}")

    elif "C" in sizes:
        # Real multi-channel file: don't silently collapse to one channel.
        # Save one representative frame (T=0/Z=0) PER channel, clearly labeled.
        axis_order = list(sizes.keys())
        c_axis = axis_order.index("C")
        if c_axis != 1:
            raise ValueError(
                f"Expected axis order (leading, C, Y, X, ...) but got {axis_order} "
                f"for shape {images.shape}."
            )
        n_channels = sizes["C"]
        print(f"\nMulti-channel file ({n_channels} channels) — saving one preview per channel:")
        for c in range(n_channels):
            frame = images[0, c]
            name = channel_names[c] if c < len(channel_names) else f"channel{c}"
            safe_name = name.replace(" ", "_")
            out_path = output_dir / f"frame0_channel{c}_{safe_name}.png"
            Image.fromarray(to_uint8(frame)).save(out_path)
            print(f"  Channel {c} ({name}): saved {out_path}")
        print(
            f"\nNote: this saved only the FIRST timepoint/z-slice of each channel. "
            f"For every timepoint of one chosen channel, use extract_frames.py --channel <n>."
        )

    else:
        # Grayscale / single-channel, no C axis: strip everything down to (Y, X).
        frame = images
        while frame.ndim > 2:
            frame = frame[0]
        out_path = output_dir / "frame_0.png"
        Image.fromarray(to_uint8(frame)).save(out_path)
        print(f"\nExtracted frame shape: {frame.shape}")
        print(f"Saved PNG  : {out_path}")

    print("\nDone! Open the saved PNG(s) to see your microscopy image.")


if __name__ == "__main__":
    main()
