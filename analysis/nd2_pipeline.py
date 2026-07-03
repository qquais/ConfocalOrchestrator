# nd2_pipeline.py
# ------------------------------------------------------------
# Option A: unified pipeline — reads .ND2 directly, no intermediate PNGs.
# Option B: computes 7 shape metrics per frame.
#
# Replaces the two-step workflow:
#   extract_frames.py  (ND2 → PNGs)
#   cellects_pipeline.py (PNGs → CSV)
# Into one command.
#
# Works with:
#   - Single-frame ND2   → produces 1-row CSV
#   - Time-lapse ND2     → one row per timepoint (T axis)
#   - Z-stack ND2        → one row per z-slice
#
# Usage:
#   python3 analysis/nd2_pipeline.py                       # uses ND2_FILE below
#   python3 analysis/nd2_pipeline.py path/to/file.nd2      # or pass path as argument
# ------------------------------------------------------------

import sys
import cv2
import nd2
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
from cellects.image.one_image_analysis import OneImageAnalysis
from cellects.image.shape_descriptors import ShapeDescriptors

WANTED_METRICS = ["area", "perimeter", "circularity",
                  "eccentricity", "major_axis_len", "minor_axis_len", "solidity"]

# ── Config ────────────────────────────────────────────────────────────────────
# Change ND2_FILE to your real time-lapse file when you have one.
ND2_FILE   = "data/samples/MRAP1 KO DN_10X03.nd2"
OUTPUT_DIR = Path("data/nd2_analysis")

# Allow passing ND2 path as a command-line argument:
#   python3 analysis/nd2_pipeline.py path/to/my_timelapse.nd2
if len(sys.argv) > 1:
    ND2_FILE = sys.argv[1]

nd2_path = Path(ND2_FILE)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
CSV_OUT  = OUTPUT_DIR / (nd2_path.stem + "_metrics.csv")
PLOT_OUT = OUTPUT_DIR / (nd2_path.stem + "_growth.png")

# ── 1. Open ND2 and load all frames ──────────────────────────────────────────
print(f"Opening: {nd2_path}")
with nd2.ND2File(nd2_path) as f:
    sizes = f.sizes
    print(f"Dimensions: {sizes}")
    images = f.asarray()   # full array, shape matches sizes

print(f"Array shape: {images.shape}  dtype: {images.dtype}\n")

# ── 2. Build a list of frames to iterate over ─────────────────────────────────
# Each frame is a 2D (grayscale) or 3D (H, W, 3 = colour) array.
#
# Rules:
#   (H, W)       → grayscale single frame
#   (H, W, 3)    → colour single frame  (S=3 axis is last)
#   (T, H, W)    → time-lapse grayscale
#   (T, H, W, 3) → time-lapse colour
#   (Z, H, W)    → z-stack grayscale
#   etc.
#
# Strategy: if last dim == 3 treat as colour, then the frame axis is everything before (H, W, 3).

is_colour = (images.shape[-1] == 3)

if is_colour:
    if images.ndim == 3:           # (H, W, 3) — one colour frame
        frames = [images]
    else:                          # (T, H, W, 3) or similar — multiple colour frames
        frames = [images[i] for i in range(images.shape[0])]
else:
    if images.ndim == 2:           # (H, W) — one grayscale frame
        frames = [images]
    else:                          # (T, H, W) — multiple grayscale frames
        frames = [images[i] for i in range(images.shape[0])]

print(f"Frames to process: {len(frames)}")

# ── 3. Cellects colour-space dict ─────────────────────────────────────────────
csc_dict = {"bgr": np.array([1, 1, 1], dtype=np.int8)}

# ── 4. Segment each frame and compute metrics ─────────────────────────────────
records = []

for frame_idx, frame in enumerate(frames, start=1):

    # Convert frame to BGR uint8 so OpenCV and Cellects can process it.
    # ND2 images can be uint16 (0–65535); we normalise to uint8 (0–255) first.
    frame = np.squeeze(frame)

    if frame.dtype != np.uint8:
        lo, hi = frame.min(), frame.max()
        if hi > lo:
            frame = ((frame - lo) / (hi - lo) * 255).astype(np.uint8)
        else:
            frame = np.zeros_like(frame, dtype=np.uint8)

    # Cellects needs BGR (3-channel). Convert grayscale → BGR if needed.
    if frame.ndim == 2:
        bgr = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    else:
        # PIL/nd2 gives RGB; OpenCV expects BGR — flip channel order
        bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

    # Segmentation
    analysis = OneImageAnalysis(bgr, shape_number=1)
    analysis.convert_and_segment(c_space_dict=csc_dict, color_number=2)
    mask = analysis.binary_image   # 0=background, 1=organism

    # Shape metrics
    sd = ShapeDescriptors(mask, WANTED_METRICS)

    row = {
        "frame":          frame_idx,
        "timepoint":      frame_idx,
        "area_px":        int(sd.descriptors.get("area", mask.sum())),
        "perimeter_px":   round(float(sd.descriptors.get("perimeter", 0)), 2),
        "circularity":    round(float(sd.descriptors.get("circularity", 0)), 4),
        "eccentricity":   round(float(sd.descriptors.get("eccentricity", 0)), 4),
        "major_axis_px":  round(float(sd.descriptors.get("major_axis_len", 0)), 2),
        "minor_axis_px":  round(float(sd.descriptors.get("minor_axis_len", 0)), 2),
        "solidity":       round(float(sd.descriptors.get("solidity", 0)), 4),
    }
    records.append(row)

    print(f"  Frame {frame_idx:02d}/{len(frames)}  "
          f"area={row['area_px']:,}px  "
          f"circ={row['circularity']:.3f}  "
          f"eccen={row['eccentricity']:.3f}")

# ── 5. Save CSV ───────────────────────────────────────────────────────────────
df = pd.DataFrame(records)
df.to_csv(CSV_OUT, index=False)
print(f"\nCSV saved → {CSV_OUT}")
print(df.to_string(index=False))

# ── 6. Plot (only meaningful with multiple frames) ────────────────────────────
if len(df) > 1:
    fig, axes = plt.subplots(3, 1, figsize=(10, 10), sharex=True)
    fig.suptitle(f"Physarum — Shape Metrics\n{nd2_path.name}", fontsize=13)

    panels = [
        ("area_px",      "Area (pixels)",  "steelblue"),
        ("circularity",  "Circularity",    "darkorange"),
        ("eccentricity", "Eccentricity",   "mediumseagreen"),
    ]
    for ax, (col, ylabel, color) in zip(axes, panels):
        ax.plot(df["timepoint"], df[col],
                marker="o", linewidth=2, color=color, markersize=4)
        ax.fill_between(df["timepoint"], df[col], alpha=0.12, color=color)
        ax.set_ylabel(ylabel, fontsize=11)
        ax.grid(True, linestyle="--", alpha=0.4)

    axes[-1].set_xlabel("Timepoint (frame number)", fontsize=11)
    plt.tight_layout()
    plt.savefig(PLOT_OUT, dpi=150)
    plt.close()
    print(f"Plot saved  → {PLOT_OUT}")
else:
    print("(single frame — skipping time-series plot)")

print("\nDone!")
