# explore_nd2.py
# ------------------------------------------------------------
# A beginner-friendly script to open a .ND2 microscopy file,
# print its metadata, and save one image frame as a PNG.
#
# How to run (from the repo root, with .venv activated):
#   python3 analysis/explore_nd2.py
#
# Requirements:  pip install nd2 numpy Pillow
# ------------------------------------------------------------

import nd2          # reads .ND2 files from Nikon microscopes
import numpy as np  # used to work with image data as arrays
from PIL import Image  # used to save the image as a PNG

# ── 1. Point to your .ND2 file ────────────────────────────────────────────────
# Change this path to wherever your sample file lives.
ND2_FILE = "data/raw/MRAP1 KO DN_10X03.nd2"

# ── 2. Open the file ──────────────────────────────────────────────────────────
# `with` automatically closes the file when the block ends.
with nd2.ND2File(ND2_FILE) as f:

    # ── 3. Print basic metadata ───────────────────────────────────────────────

    print("=" * 50)
    print("FILE INFO")
    print("=" * 50)

    # `f.sizes` is a dictionary like {'T': 10, 'C': 2, 'Z': 5, 'Y': 512, 'X': 512}
    # T = timepoints, C = channels, Z = z-slices, Y/X = image height/width
    print(f"Dimensions : {f.sizes}")
    print(f"Data type  : {f.dtype}")   # e.g. uint16 means 16-bit grayscale

    # ── 4. Pixel size (how many micrometres each pixel covers) ────────────────
    # voxel_size() returns (z, y, x) in micrometres — more reliable than attrs
    try:
        vox = f.voxel_size()
        print(f"Pixel size : x={vox.x:.4f} µm,  y={vox.y:.4f} µm,  z={vox.z:.4f} µm")
    except Exception:
        print("Pixel size : not available in this file")

    # ── 5. Channel names ──────────────────────────────────────────────────────
    # Channels are the different fluorescence colours used during imaging.
    meta = f.metadata
    if meta and hasattr(meta, "channels") and meta.channels:
        print(f"\nChannels ({len(meta.channels)} total):")
        for i, ch in enumerate(meta.channels):
            # The channel name is nested a few levels deep in the metadata object
            name = ch.channel.name if hasattr(ch, "channel") else "unknown"
            print(f"  Channel {i}: {name}")
    else:
        print("\nNo channel metadata found in this file.")

    # ── 6. Experiment loops (timepoints, z-stacks, etc.) ─────────────────────
    experiment = f.experiment
    if experiment:
        print("\nExperiment loops:")
        for loop in experiment:
            # Each loop tells you what was repeated: time, z-position, etc.
            print(f"  {loop.type}: {loop.count} steps")
    else:
        print("\nNo experiment loop metadata found.")

    print("=" * 50)

    # ── 7. Load the full image array ──────────────────────────────────────────
    # `f.asarray()` loads every frame into a NumPy array.
    # Shape will match f.sizes, e.g. (T, C, Z, Y, X).
    print("\nLoading image data into memory...")
    images = f.asarray()
    print(f"Array shape: {images.shape}")
    print(f"Min value  : {images.min()},  Max value: {images.max()}")

    # ── 8. Extract a displayable frame ───────────────────────────────────────
    # Your file has S=3 (RGB colour). asarray() gives shape (Y, X, 3).
    # PIL's Image.fromarray() expects exactly (H, W, 3) for colour images,
    # so we must NOT strip those 3 colour channels — only strip T/Z axes if present.
    sizes = f.sizes
    is_rgb = sizes.get("S", 1) == 3  # True when the file has 3 colour components

    if is_rgb:
        # Remove any leading T/Z dimensions by collapsing them to index 0,
        # but stop before we touch the last axis (the 3 colour channels).
        frame = images
        while frame.ndim > 3:
            frame = frame[0]          # drop one leading axis at a time
        # frame is now (Y, X, 3) — exactly what PIL needs for RGB
    else:
        # Grayscale / single-channel: strip everything down to (Y, X)
        frame = images
        while frame.ndim > 2:
            frame = frame[0]

    print(f"\nExtracted frame shape: {frame.shape}")

    # ── 9. Contrast normalisation to 0-255 ───────────────────────────────────
    # We stretch the actual min→max range to fill 0-255 so the image looks bright.
    # Example: if pixel values are 10-187, after normalisation they become 0-255.
    frame = frame.astype(np.float32)          # float maths to avoid overflow

    lo = frame.min()
    hi = frame.max()
    print(f"Contrast stretch: {lo:.0f} → {hi:.0f}  mapped to  0 → 255")

    if hi > lo:
        frame = (frame - lo) / (hi - lo) * 255   # stretch to full 0-255 range

    frame = np.clip(frame, 0, 255).astype(np.uint8)  # clip any floating-point drift

    # ── 10. Save as PNG ───────────────────────────────────────────────────────
    out_path = "data/analysis/nd2_sample/frame_0.png"
    img = Image.fromarray(frame)
    img.save(out_path)
    print(f"Saved PNG  : {out_path}")
    print("\nDone! Open the PNG file to see your microscopy image.")
