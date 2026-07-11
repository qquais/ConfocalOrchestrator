# track_nuclei.py
# -----------------------------------------------------------------------
# Individual nucleus tracking pipeline — the core analysis step.
#
# PIPELINE OVERVIEW
# -----------------
#   frame_0.png  (copied N times to simulate a time-lapse)
#       |
#       v  Step 1 — Cellpose detects nuclei in each frame  → mask arrays
#       v  Step 2 — regionprops extracts centroids (x, y) per nucleus
#       v  Step 3 — trackpy links the SAME nucleus across frames → trajectories
#       v  Step 4 — Save CSV  +  visualisation
#
# When you have real ND2 time-lapse frames, replace the frame-list creation
# in Step 1 with actual file loading — everything else stays the same.
#
# How to run (from the repo root, with .venv activated):
#   python3 analysis/track_nuclei.py
#
# Requirements:
#   pip install cellpose trackpy scikit-image matplotlib pandas
# -----------------------------------------------------------------------

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from PIL import Image
from cellpose import models
from skimage.measure import regionprops   # measures shape properties of labelled regions
import trackpy as tp                       # particle/nucleus tracking library

try:
    from analysis.cellpose_runtime import resolve_cellpose_gpu_mode
except ImportError:
    from cellpose_runtime import resolve_cellpose_gpu_mode

# ── CONFIGURATION ──────────────────────────────────────────────────────────────
# Adjust these settings without touching the rest of the script.

INPUT_IMAGE  = "data/analysis/nd2_sample/frame_0.png"   # base frame
OUTPUT_DIR   = "data/analysis/tracking"                  # all outputs go here
TRAJ_CSV     = os.path.join(OUTPUT_DIR, "nucleus_trajectories.csv")
VIZ_IMAGE    = os.path.join(OUTPUT_DIR, "nucleus_trajectories.png")

# How many fake time-lapse frames to create by repeating the base image.
# With real data, replace the frame list below instead of changing this number.
N_FAKE_FRAMES = 5

# Cellpose nucleus diameter in pixels (after resizing).
# None = auto-detect. Set a number (e.g. 30) if auto-detect gives wrong results.
NUCLEUS_DIAMETER = None

# Resize scale applied to the image before Cellpose (matches segment_nd2.py).
# 0.25 = 25% of original size — keeps CPU runtime manageable.
SCALE = 0.25

# trackpy linking parameters — see Step 4 for a detailed explanation.
# With identical fake frames (zero displacement), even 1 pixel works.
# For real data, tune this to the typical nucleus displacement per frame
# (e.g. 5–15 px).  Too large → SubnetOversizeException on dense fields.
SEARCH_RANGE = 5    # max pixels a nucleus can move between consecutive frames
MEMORY       = 2    # max frames a nucleus can be absent and still be re-linked

# Minimum number of frames a nucleus must appear in to be kept in the output.
# Removes spurious one-frame detections caused by image noise.
MIN_FRAMES = 2

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ── STEP 1: Load the image and build the frame list ────────────────────────────
# We load one real microscopy image and repeat it N times to simulate a
# time-lapse sequence.  Because every frame is identical, all nuclei will
# appear stationary (displacement = 0) — that's expected for this demo.
#
# REAL DATA: replace the list comprehension below with something like:
#   frames = [np.array(Image.open(f).convert("RGB")) for f in sorted(frame_files)]
print("=" * 60)
print("STEP 1 — Preparing frames")
print("=" * 60)

pil_base = Image.open(INPUT_IMAGE).convert("RGB")

new_w = int(pil_base.width  * SCALE)
new_h = int(pil_base.height * SCALE)
pil_base = pil_base.resize((new_w, new_h), Image.LANCZOS)  # high-quality downscale
base_img = np.array(pil_base)                               # shape: (H, W, 3)

frames = [base_img.copy() for _ in range(N_FAKE_FRAMES)]

print(f"  Base image      : {INPUT_IMAGE}")
print(f"  Resized to      : {new_w} x {new_h} px  ({int(SCALE * 100)}% of original)")
print(f"  Frames prepared : {N_FAKE_FRAMES} (identical copies — replace with real frames later)")

# ── STEP 2: Run Cellpose on every frame ────────────────────────────────────────
# Cellpose is a deep-learning model trained on microscopy images.
# For each frame it returns a "mask array" — same size as the image,
# where each pixel contains the nucleus ID it belongs to (0 = background).
#   e.g.  mask[y, x] = 3  means that pixel belongs to nucleus #3
print("\n" + "=" * 60)
print("STEP 2 — Cellpose segmentation  (detecting nuclei in each frame)")
print("=" * 60)
print("  Loading Cellpose nuclei model (downloads weights ~200 MB on first run)...")

USE_GPU = resolve_cellpose_gpu_mode()
print(f"  GPU mode     : {'enabled' if USE_GPU else 'disabled'}")
model = models.CellposeModel(model_type="nuclei", gpu=USE_GPU)

all_masks = []   # one mask array per frame

for i, frame in enumerate(frames):
    print(f"  Segmenting frame {i}/{N_FAKE_FRAMES - 1} ...", end=" ", flush=True)
    results   = model.eval(frame, diameter=NUCLEUS_DIAMETER, channels=[0, 0])
    # results[0] = mask array  |  results[1] = flows  |  results[2] = styles
    masks = results[0]
    all_masks.append(masks)
    n_detected = int(masks.max())   # highest ID in the mask = total nucleus count
    print(f"detected {n_detected} nuclei")

# ── STEP 3: Extract centroids with regionprops ─────────────────────────────────
# regionprops() measures properties of each numbered region in a mask.
# We need the CENTROID: the (y, x) coordinates of the centre of each nucleus.
#
# Why centroids?  trackpy works with point positions, not filled regions.
# We reduce each blob → one point, then track those points across time.
print("\n" + "=" * 60)
print("STEP 3 — Extracting nucleus centroids  (mask → centroid per nucleus)")
print("=" * 60)

rows = []   # collect one dict per detected nucleus per frame

for frame_idx, masks in enumerate(all_masks):
    props = regionprops(masks)        # list of RegionProperties objects, one per nucleus
    for region in props:
        cy, cx = region.centroid      # regionprops gives (row, col) = (y, x) order
        rows.append({
            "frame": frame_idx,
            "x":     cx,              # column coordinate
            "y":     cy,              # row coordinate
            "area":  region.area,     # nucleus size in pixels (bonus metric)
        })

detections = pd.DataFrame(rows)

print(f"  Total point detections across all {N_FAKE_FRAMES} frames: {len(detections)}")
print()
print(detections.head(10).to_string(index=False))

# ── STEP 4: Link detections into trajectories with trackpy ─────────────────────
# trackpy answers the question:
#   "Is the nucleus at position (x1, y1) in frame 5 the SAME nucleus
#    as (x2, y2) in frame 6?"
#
# It solves this as a MINIMUM-COST ASSIGNMENT PROBLEM:
#   Find the set of frame-to-frame links that minimises total displacement,
#   while respecting:
#     - search_range: a nucleus cannot jump more than this many pixels per frame
#     - memory: a nucleus can be absent (e.g. out of focus) for this many frames
#               and still be re-linked when it reappears
#
# The output adds a 'particle' column — a consistent integer ID for each
# nucleus that is the same across all frames where it appears.
print("\n" + "=" * 60)
print("STEP 4 — Linking nuclei into trajectories  (trackpy)")
print("=" * 60)
print(f"  search_range = {SEARCH_RANGE} px  — max displacement allowed between frames")
print(f"  memory       = {MEMORY} frames   — max gap before a track is broken")

# tp.link() requires columns named 'frame', 'x', 'y' — exactly what we have.
# adaptive_stop/adaptive_step: if a subnet is too large, trackpy automatically
# reduces search_range (by adaptive_step each attempt) until it's manageable,
# stopping when it reaches adaptive_stop fraction of the original search_range.
# This prevents SubnetOversizeException on dense nucleus fields.
trajectories = tp.link(detections, search_range=SEARCH_RANGE, memory=MEMORY,
                        adaptive_stop=0.1, adaptive_step=0.95)

n_raw = trajectories["particle"].nunique()
print(f"\n  Linked {len(trajectories)} detections → {n_raw} raw trajectories")

# Remove trajectories that are too short — they are usually noise.
trajectories = tp.filter_stubs(trajectories, threshold=MIN_FRAMES)
n_kept = trajectories["particle"].nunique()
print(f"  After removing tracks shorter than {MIN_FRAMES} frames: {n_kept} trajectories kept")

# ── STEP 5: Save trajectory CSV ────────────────────────────────────────────────
# Output columns:
#   nucleus_id — consistent integer ID for the same nucleus across frames
#   frame      — time index (0, 1, 2, …)
#   x          — horizontal centroid position (pixels)
#   y          — vertical centroid position (pixels)
#   area       — nucleus area (pixels) — useful for size filtering later
print("\n" + "=" * 60)
print("STEP 5 — Saving trajectory CSV")
print("=" * 60)

output = (
    trajectories.reset_index(drop=True)   # trackpy sets 'frame' as index — drop it first
    [["particle", "frame", "x", "y", "area"]]
    .rename(columns={"particle": "nucleus_id"})
    .sort_values(["nucleus_id", "frame"])
    .reset_index(drop=True)
)

output.to_csv(TRAJ_CSV, index=False)
print(f"  Saved : {TRAJ_CSV}")
print(f"  Shape : {len(output)} rows  x  {len(output.columns)} columns")
print()
print(output.head(15).to_string(index=False))

# ── STEP 6: Visualise trajectories ─────────────────────────────────────────────
# Background: last frame of the time-lapse (greyscale).
# Overlay:    one coloured line per nucleus, connecting its centroid positions
#             across frames.  Each colour = one unique nucleus ID.
print("\n" + "=" * 60)
print("STEP 6 — Visualising trajectories")
print("=" * 60)

fig, ax = plt.subplots(figsize=(10, 8))

# Show the microscopy image as a dark background
ax.imshow(frames[-1], cmap="gray", alpha=0.85)

# Assign a distinct colour to each nucleus
unique_ids = output["nucleus_id"].unique()
color_map  = plt.cm.tab20(np.linspace(0, 1, len(unique_ids)))

for nucleus_id, color in zip(unique_ids, color_map):
    traj = output[output["nucleus_id"] == nucleus_id].sort_values("frame")

    # Draw the trajectory line (connect centroids across frames)
    ax.plot(traj["x"], traj["y"],
            "-o", color=color, markersize=4, linewidth=1.5)

    # Label the nucleus ID at the position it first appears
    first_row = traj.iloc[0]
    ax.text(first_row["x"] + 3, first_row["y"] - 3,
            str(int(nucleus_id)),
            color=color, fontsize=7, fontweight="bold")

ax.set_title(
    f"Nucleus trajectories — {n_kept} nuclei tracked across {N_FAKE_FRAMES} frames\n"
    f"(Stationary dots expected: all frames are identical copies of frame_0.png)",
    fontsize=11,
)
ax.set_xlabel("x  (pixels)")
ax.set_ylabel("y  (pixels)")
plt.tight_layout()

plt.savefig(VIZ_IMAGE, dpi=150)
plt.close()
print(f"  Saved : {VIZ_IMAGE}")

# ── DONE ───────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("DONE")
print("=" * 60)
print(f"  Trajectory CSV   : {TRAJ_CSV}")
print(f"  Visualisation    : {VIZ_IMAGE}")
print()
print("Next steps:")
print("  1. Replace the fake frame list (Step 1) with real ND2 time-lapse frames")
print("  2. Tune SEARCH_RANGE to match how far nuclei actually move per frame")
print("  3. Tune NUCLEUS_DIAMETER if Cellpose over- or under-segments nuclei")
print("  4. Increase MIN_FRAMES to remove more short/spurious tracks")
