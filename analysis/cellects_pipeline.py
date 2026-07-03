# cellects_pipeline.py
# ------------------------------------------------------------
# Full end-to-end Cellects pipeline on 25-frame Physarum time-lapse.
#
# What this does:
#   1. Loads all 25 TIFF frames in order
#   2. Segments each frame using Cellects (finds organism vs. background)
#   3. Measures organism area (pixel count) at each timepoint
#   4. Saves results to growth_over_time.csv
#   5. Plots and saves a growth curve (area vs. time)
#
# Run: python3 analysis/cellects_pipeline.py
# ------------------------------------------------------------

import cv2
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
from cellects.image.one_image_analysis import OneImageAnalysis

# ── Paths ─────────────────────────────────────────────────────────────────────
DATA_DIR   = Path("data/physarum_sample/single_experiment")
OUTPUT_DIR = Path("data/physarum_sample")
CSV_OUT    = OUTPUT_DIR / "growth_over_time.csv"
PLOT_OUT   = OUTPUT_DIR / "growth_curve.png"

# ── 1. Load frames in correct numerical order (1, 2, 3 … 25) ─────────────────
# A plain alphabetical sort gives 1, 10, 11 … which is wrong.
# We sort by the integer in the filename instead.
tif_files = sorted(DATA_DIR.glob("image*.tif"),
                   key=lambda p: int(p.stem.replace("image", "")))

print(f"Found {len(tif_files)} frames in {DATA_DIR}")

# ── 2. Build the colour-space dict Cellects needs ─────────────────────────────
# Plain Python dict — Cellects' split_dict() handles conversion to numba types internally.
# "bgr": [1,1,1] means "use all three BGR channels combined" (grayscale-like).
csc_dict = {"bgr": np.array([1, 1, 1], dtype=np.int8)}

# ── 3. Segment every frame and record the organism area ───────────────────────
records = []   # will hold one dict per frame

for frame_idx, tif_path in enumerate(tif_files, start=1):

    # Load image as BGR (OpenCV default — Cellects expects BGR, not RGB)
    img = cv2.imread(str(tif_path))
    if img is None:
        print(f"  WARNING: could not read {tif_path.name}, skipping")
        continue

    # Run Cellects segmentation
    # color_number=2 means split the image into 2 groups: organism vs. background
    analysis = OneImageAnalysis(img, shape_number=1)
    analysis.convert_and_segment(c_space_dict=csc_dict, color_number=2)

    # binary_image: 0 = background, 1 = organism
    # Summing it gives the total number of organism pixels = area
    organism_area = int(analysis.binary_image.sum())

    records.append({
        "frame":                frame_idx,
        "timepoint":            frame_idx,        # rename if you have real timestamps
        "organism_area_pixels": organism_area,
    })

    print(f"  Frame {frame_idx:02d}/{len(tif_files)}  |  area = {organism_area:,} px")

# ── 4. Save CSV ───────────────────────────────────────────────────────────────
df = pd.DataFrame(records)
df.to_csv(CSV_OUT, index=False)
print(f"\nCSV saved: {CSV_OUT}")
print(df.to_string(index=False))

# ── 5. Plot growth curve ──────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(10, 5))

ax.plot(df["timepoint"], df["organism_area_pixels"],
        marker="o", linewidth=2, color="steelblue", markersize=5)

ax.fill_between(df["timepoint"], df["organism_area_pixels"],
                alpha=0.15, color="steelblue")   # shaded area under the curve

ax.set_xlabel("Timepoint (frame number)", fontsize=12)
ax.set_ylabel("Organism area (pixels)", fontsize=12)
ax.set_title("Physarum polycephalum — Growth Over Time\n(Cellects segmentation)", fontsize=13)
ax.grid(True, linestyle="--", alpha=0.5)

# Annotate min and max area points
min_row = df.loc[df["organism_area_pixels"].idxmin()]
max_row = df.loc[df["organism_area_pixels"].idxmax()]
ax.annotate(f"min: {int(min_row.organism_area_pixels):,} px",
            xy=(min_row.timepoint, min_row.organism_area_pixels),
            xytext=(5, 15), textcoords="offset points", fontsize=9, color="red")
ax.annotate(f"max: {int(max_row.organism_area_pixels):,} px",
            xy=(max_row.timepoint, max_row.organism_area_pixels),
            xytext=(5, -20), textcoords="offset points", fontsize=9, color="green")

plt.tight_layout()
plt.savefig(PLOT_OUT, dpi=150)
plt.close()
print(f"Plot saved: {PLOT_OUT}")
print("\nDone! Open growth_curve.png to see the growth dynamics.")
