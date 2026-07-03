# cellects_pipeline.py
# ------------------------------------------------------------
# Full end-to-end Cellects pipeline on 25-frame Physarum time-lapse.
#
# Option A: reads TIFF frames directly — no intermediate PNG step
# Option B: computes 7 shape metrics per frame, not just area
#
# Metrics saved per frame:
#   area          — organism size in pixels
#   perimeter     — border length in pixels
#   circularity   — 1.0 = perfect circle, lower = more irregular/branched
#   eccentricity  — 0 = circle, 1 = line (how elongated the organism is)
#   major_axis    — length of longest axis through the organism (pixels)
#   minor_axis    — length of shortest axis (pixels)
#   solidity      — area / convex_hull_area (1.0 = no holes/indentations)
#
# Run: python3 analysis/cellects_pipeline.py
# ------------------------------------------------------------

import cv2
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
from cellects.image.one_image_analysis import OneImageAnalysis
from cellects.image.shape_descriptors import ShapeDescriptors

WANTED_METRICS = ["area", "perimeter", "circularity",
                  "eccentricity", "major_axis_len", "minor_axis_len", "solidity"]

# ── Paths ─────────────────────────────────────────────────────────────────────
DATA_DIR   = Path("data/datasets/physarum_sample/single_experiment")
OUTPUT_DIR = Path("data/analysis/physarum_sample")
CSV_OUT    = OUTPUT_DIR / "growth_over_time.csv"
PLOT_OUT   = OUTPUT_DIR / "growth_curve.png"

# ── 1. Load frames in correct numerical order ─────────────────────────────────
# Supports both .tif  (image1.tif  … from Cellects sample data)
#          and .png  (img001.png … from extract_frames.py)
# Sorted by the trailing number in the filename so order is always 1, 2, 3 …
import re

def _frame_number(path):
    match = re.search(r"(\d+)", path.stem)
    return int(match.group(1)) if match else 0

tif_files = sorted(
    list(DATA_DIR.glob("*.tif")) + list(DATA_DIR.glob("*.png")),
    key=_frame_number
)
print(f"Found {len(tif_files)} frames in {DATA_DIR}\n")

# ── 2. Colour-space dict for Cellects segmentation ───────────────────────────
csc_dict = {"bgr": np.array([1, 1, 1], dtype=np.int8)}

# ── 3. Segment every frame and compute shape metrics ─────────────────────────
records = []

for frame_idx, tif_path in enumerate(tif_files, start=1):

    img = cv2.imread(str(tif_path))
    if img is None:
        print(f"  WARNING: could not read {tif_path.name}, skipping")
        continue

    # Cellects segmentation → binary_image (0=background, 1=organism)
    analysis = OneImageAnalysis(img, shape_number=1)
    analysis.convert_and_segment(c_space_dict=csc_dict, color_number=2)
    mask = analysis.binary_image   # dtype uint8, values 0 or 1

    # ShapeDescriptors computes all metrics from the binary mask in one call
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

    print(f"  Frame {frame_idx:02d}/{len(tif_files)}  "
          f"area={row['area_px']:,}px  "
          f"circ={row['circularity']:.3f}  "
          f"eccen={row['eccentricity']:.3f}")

# ── 4. Save CSV ───────────────────────────────────────────────────────────────
df = pd.DataFrame(records)
df.to_csv(CSV_OUT, index=False)
print(f"\nCSV saved → {CSV_OUT}")
print(df.to_string(index=False))

# ── 5. Plot: 3-panel growth figure ───────────────────────────────────────────
fig, axes = plt.subplots(3, 1, figsize=(10, 10), sharex=True)
fig.suptitle("Physarum polycephalum — Shape Metrics Over Time", fontsize=14)

panels = [
    ("area_px",      "Area (pixels)",    "steelblue"),
    ("circularity",  "Circularity",      "darkorange"),
    ("eccentricity", "Eccentricity",     "mediumseagreen"),
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
print("\nDone!")
