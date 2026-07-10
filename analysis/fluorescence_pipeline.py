# fluorescence_pipeline.py
# -----------------------------------------------------------------------
# Full nucleus-tracking pipeline run on REAL fluorescence microscopy data:
# the Fluo-N2DH-SIM+ dataset from the Cell Tracking Challenge (CTC).
#
# Unlike our earlier brightfield/ND2 samples, this dataset is the correct
# DATA TYPE for the pipeline: bright glowing nuclei on a dark background,
# which is what Cellpose's nucleus model and the rest of this pipeline
# expect. It's simulated data, but it mimics real Physarum nuclear imaging.
#
# PIPELINE OVERVIEW
# -----------------
#   01/t000.tif ... t009.tif  (first 10 real time-lapse frames)
#       |
#       v  Step 1 — Load frames in order (tifffile)
#       v  Step 2 — Gaussian denoise each frame (scikit-image)
#       v  Step 3 — Cellpose detects nuclei in each frame  -> mask arrays
#       v  Step 4 — regionprops extracts centroid + area per nucleus
#       v  Step 5 — trackpy links the SAME nucleus across frames -> trajectories
#       v  Step 6 — Save CSV + visualisation
#
# How to run (from the repo root, with .venv activated):
#   python3 analysis/fluorescence_pipeline.py
#
# Requirements: cellpose, trackpy, scikit-image, tifffile, matplotlib, pandas
#
# NOTE ON RUNTIME: Cellpose here uses the cellpose-SAM model (cellpose v4),
# which is much slower per-image on CPU than the old "nuclei" model used in
# earlier scripts (segment_nd2.py / track_nuclei.py) — roughly ~3 minutes
# per 690x628 frame on Apple Silicon CPU. 10 frames takes ~30 minutes.
# -----------------------------------------------------------------------

import time
import os
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import tifffile
import trackpy as tp                          # particle/nucleus tracking library
from cellpose import models
from skimage.filters import gaussian
from skimage.measure import regionprops       # measures shape properties of labelled regions
from skimage.util import img_as_float

try:
    from analysis.cellpose_runtime import resolve_cellpose_gpu_mode
except ImportError:
    from cellpose_runtime import resolve_cellpose_gpu_mode

# ── CONFIGURATION ──────────────────────────────────────────────────────────────

DEFAULT_DATA_DIR = Path("data/datasets/Fluo-N2DH-SIM/Fluo-N2DH-SIM+/01")

env_data_dir = os.getenv("FLUORESCENCE_DATA_DIR")
if env_data_dir:
    DATA_DIR = Path(env_data_dir)
else:
    DATA_DIR = DEFAULT_DATA_DIR

OUTPUT_DIR = Path("data/analysis/fluorescence")
TRAJ_CSV   = OUTPUT_DIR / "trajectories.csv"
VIZ_IMAGE  = OUTPUT_DIR / "trajectories.png"

N_FRAMES = 10   # how many frames to load, in order, from DATA_DIR

# Gaussian denoising strength (Step 2). These are clean simulated images,
# so a small sigma is enough to smooth sensor-style noise without blurring
# nuclei away.
GAUSSIAN_SIGMA = 1.0

# Cellpose nucleus diameter in pixels. None = auto-detect from the image.
NUCLEUS_DIAMETER = None

# trackpy linking parameters (Step 5).
# SEARCH_RANGE is set to roughly 2x the nucleus diameter Cellpose finds in
# frame 0 (measured below, after segmentation) so a nucleus can be matched
# to itself in the next frame even with modest simulated drift, without
# being so large that unrelated nearby nuclei get confused for each other.
MEMORY = 2       # max frames a nucleus can be missed and still be re-linked
MIN_FRAMES = 3   # drop trajectories shorter than this many frames (likely noise)

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── STEP 1: Load the first N_FRAMES real frames, in order ─────────────────────
print("=" * 60)
print("STEP 1 — Loading real fluorescence frames")
print("=" * 60)

frame_paths = sorted(DATA_DIR.glob("t*.tif"))[:N_FRAMES]
if len(frame_paths) < N_FRAMES:
    raise RuntimeError(
        f"Expected at least {N_FRAMES} TIFF frames in {DATA_DIR}, found {len(frame_paths)}. "
        "Set FLUORESCENCE_DATA_DIR to a folder containing t000.tif, t001.tif, ..."
    )

frames = [tifffile.imread(p) for p in frame_paths]

print(f"  Source folder : {DATA_DIR}")
print(f"  Frames loaded : {len(frames)}  ({frame_paths[0].name} .. {frame_paths[-1].name})")
print(f"  Frame shape   : {frames[0].shape}  dtype={frames[0].dtype}")

# ── STEP 2: Gaussian denoising (scikit-image) ──────────────────────────────────
# img_as_float() converts the 16-bit images to float64 in [0, 1] so scikit-image
# filters behave predictably. Cellpose normalizes intensities internally
# (percentile-based), so feeding it a [0, 1] float image works the same as
# feeding it the raw 16-bit image.
print("\n" + "=" * 60)
print("STEP 2 — Gaussian denoising (sigma=%.1f)" % GAUSSIAN_SIGMA)
print("=" * 60)

denoised_frames = [gaussian(img_as_float(f), sigma=GAUSSIAN_SIGMA) for f in frames]
print(f"  Denoised {len(denoised_frames)} frames")

# ── STEP 3: Cellpose nucleus segmentation ──────────────────────────────────────
# cellpose v4 uses a single general-purpose "cellpose-SAM" model
# (pretrained_model='cpsam_v2') instead of the old model_type="nuclei"/"cyto"
# dictionary from earlier cellpose versions. channels=[0, 0] tells it the
# image is single-channel grayscale with no separate cytoplasm channel.
print("\n" + "=" * 60)
print("STEP 3 — Cellpose segmentation (detecting nuclei in each frame)")
print("=" * 60)
print("  Loading Cellpose model (cellpose-SAM, cpsam_v2)...")

USE_GPU = resolve_cellpose_gpu_mode()
print(f"  GPU mode     : {'enabled' if USE_GPU else 'disabled'}")
model = models.CellposeModel(gpu=USE_GPU)

all_masks = []
for i, frame in enumerate(denoised_frames):
    t0 = time.time()
    masks, flows, styles = model.eval(frame, channels=[0, 0], diameter=NUCLEUS_DIAMETER)
    all_masks.append(masks)
    n_detected = int(masks.max())
    print(f"  Frame {i} ({frame_paths[i].name}): {n_detected} nuclei detected "
          f"[{time.time() - t0:.1f}s]")

# ── STEP 4: Extract centroids + area with regionprops ──────────────────────────
print("\n" + "=" * 60)
print("STEP 4 — Extracting nucleus centroids (mask -> centroid per nucleus)")
print("=" * 60)

rows = []
for frame_idx, masks in enumerate(all_masks):
    for region in regionprops(masks):
        cy, cx = region.centroid   # regionprops gives (row, col) = (y, x) order
        rows.append({
            "frame": frame_idx,
            "x": cx,
            "y": cy,
            "area": region.area,
        })

detections = pd.DataFrame(rows)
print(f"  Total point detections across all {N_FRAMES} frames: {len(detections)}")

# ── STEP 5: Link detections into trajectories with trackpy ─────────────────────
# Nucleus diameter measured from frame 0's segmentation sets the search range:
# a nucleus should not need to move further than ~2 diameters between frames.
diam_est = np.sqrt(detections.loc[detections["frame"] == 0, "area"].median() / np.pi) * 2
search_range = max(15, int(diam_est * 2))

print("\n" + "=" * 60)
print("STEP 5 — Linking nuclei into trajectories (trackpy)")
print("=" * 60)
print(f"  search_range = {search_range} px  (~2x median nucleus diameter of frame 0)")
print(f"  memory       = {MEMORY} frames")

trajectories = tp.link(detections, search_range=search_range, memory=MEMORY,
                        adaptive_stop=0.1, adaptive_step=0.95)
n_raw = trajectories["particle"].nunique()
print(f"  Linked {len(trajectories)} detections -> {n_raw} raw trajectories")

trajectories = tp.filter_stubs(trajectories, threshold=MIN_FRAMES)
n_kept = trajectories["particle"].nunique()
print(f"  After removing tracks shorter than {MIN_FRAMES} frames: {n_kept} trajectories kept")

# ── STEP 6: Save trajectory CSV + visualisation ────────────────────────────────
print("\n" + "=" * 60)
print("STEP 6 — Saving trajectory CSV and visualisation")
print("=" * 60)

output = (
    trajectories.reset_index(drop=True)
    [["particle", "frame", "x", "y", "area"]]
    .rename(columns={"particle": "nucleus_id"})
    .sort_values(["nucleus_id", "frame"])
    .reset_index(drop=True)
)
output.to_csv(TRAJ_CSV, index=False)
print(f"  Saved CSV : {TRAJ_CSV}  ({len(output)} rows)")

fig, ax = plt.subplots(figsize=(10, 9))
ax.imshow(frames[0], cmap="gray")

unique_ids = output["nucleus_id"].unique()
color_map = plt.cm.tab20(np.linspace(0, 1, len(unique_ids)))

for nucleus_id, color in zip(unique_ids, color_map):
    traj = output[output["nucleus_id"] == nucleus_id].sort_values("frame")
    ax.plot(traj["x"], traj["y"], "-o", color=color, markersize=3, linewidth=1.2)

ax.set_title(
    f"Nucleus trajectories — Fluo-N2DH-SIM+ seq. 01, frames 0-{N_FRAMES - 1}\n"
    f"{n_kept} trajectories over {len(unique_ids)} tracked nuclei",
    fontsize=11,
)
ax.set_xlabel("x (pixels)")
ax.set_ylabel("y (pixels)")
plt.tight_layout()
plt.savefig(VIZ_IMAGE, dpi=150)
plt.close()
print(f"  Saved plot: {VIZ_IMAGE}")

# ── SUMMARY ─────────────────────────────────────────────────────────────────────
avg_len = output.groupby("nucleus_id").size().mean()
total_nuclei_detected = len(detections)

print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
print(f"  Frames processed        : {N_FRAMES}")
print(f"  Total nuclei detected   : {total_nuclei_detected}  (sum across all frames)")
print(f"  Raw trajectories linked : {n_raw}")
print(f"  Trajectories kept       : {n_kept}  (>= {MIN_FRAMES} frames long)")
print(f"  Average track length    : {avg_len:.1f} frames")
print(f"\n  Trajectory CSV : {TRAJ_CSV}")
print(f"  Visualisation  : {VIZ_IMAGE}")
