"""Fluorescence nucleus tracking pipeline with command-line arguments.

This script links glowing nuclei in fluorescence time-lapse frames, then saves
the trajectories and a simple overlay plot. The default settings still run the
original Physarum fluorescence dataset, but you can now point it at another
frame folder without setting environment variables first.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import tifffile
import trackpy as tp
from cellpose import models
from skimage.filters import gaussian
from skimage.measure import regionprops
from skimage.util import img_as_float

try:
    from analysis.cellpose_runtime import resolve_cellpose_gpu_mode
except ImportError:
    from cellpose_runtime import resolve_cellpose_gpu_mode


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = REPO_ROOT / "data" / "datasets" / "Fluo-N2DH-SIM" / "Fluo-N2DH-SIM+" / "01"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "analysis" / "fluorescence"

# Gaussian denoising strength (Step 2). These are clean simulated images,
# so a small sigma is enough to smooth sensor-style noise without blurring
# nuclei away.
GAUSSIAN_SIGMA = 1.0

# Cellpose nucleus diameter in pixels. None = auto-detect from the image.
NUCLEUS_DIAMETER = None

# trackpy linking parameters (Step 5).
MEMORY = 2  # max frames a nucleus can be missed and still be re-linked
MIN_FRAMES = 3  # drop trajectories shorter than this many frames (likely noise)


def parse_args() -> argparse.Namespace:
    """Read the dataset, output folder, and frame count from the command line."""

    parser = argparse.ArgumentParser(description="Track fluorescence nuclei across frames.")
    parser.add_argument(
        "--data",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="Folder containing TIFF frames (default: original Fluo-N2DH-SIM+ seq. 01)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Folder where CSV and PNG results will be written",
    )
    parser.add_argument(
        "--frames",
        type=int,
        default=10,
        help="How many frames to process",
    )
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    """Treat relative paths as repo-root paths so the script is easy to run."""

    if path.is_absolute():
        return path
    return REPO_ROOT / path


def main() -> None:
    args = parse_args()
    data_dir = resolve_path(args.data)
    output_dir = resolve_path(args.output)
    n_frames = args.frames

    traj_csv = output_dir / "trajectories.csv"
    viz_image = output_dir / "trajectories.png"

    output_dir.mkdir(parents=True, exist_ok=True)

    # STEP 1: Load the first N frames in order.
    print("=" * 60)
    print("STEP 1 — Loading real fluorescence frames")
    print("=" * 60)

    frame_paths = sorted(data_dir.glob("t*.tif"))[:n_frames]
    if len(frame_paths) < n_frames:
        raise RuntimeError(
            f"Expected at least {n_frames} TIFF frames in {data_dir}, found {len(frame_paths)}. "
            "Make sure the folder contains files like t000.tif, t001.tif, ..."
        )

    frames = [tifffile.imread(path) for path in frame_paths]

    print(f"  Source folder : {data_dir}")
    print(f"  Frames loaded : {len(frames)}  ({frame_paths[0].name} .. {frame_paths[-1].name})")
    print(f"  Frame shape   : {frames[0].shape}  dtype={frames[0].dtype}")

    # STEP 2: Gaussian denoising.
    # img_as_float() converts the 16-bit images to float64 in [0, 1] so
    # scikit-image filters behave predictably.
    print("\n" + "=" * 60)
    print("STEP 2 — Gaussian denoising (sigma=%.1f)" % GAUSSIAN_SIGMA)
    print("=" * 60)

    denoised_frames = [gaussian(img_as_float(frame), sigma=GAUSSIAN_SIGMA) for frame in frames]
    print(f"  Denoised {len(denoised_frames)} frames")
    print("  Note: Cellpose runs on the raw 16-bit frames because the denoised frames are only for inspection.")

    # STEP 3: Cellpose nucleus segmentation.
    print("\n" + "=" * 60)
    print("STEP 3 — Cellpose segmentation (detecting nuclei in each frame)")
    print("=" * 60)
    print("  Loading Cellpose model (cellpose-SAM, cpsam_v2)...")

    use_gpu = resolve_cellpose_gpu_mode()
    print(f"  GPU mode     : {'enabled' if use_gpu else 'disabled'}")
    model = models.CellposeModel(gpu=use_gpu)

    all_masks = []
    for index, frame in enumerate(frames):
        t0 = time.time()
        masks, flows, styles = model.eval(frame, channels=[0, 0], diameter=NUCLEUS_DIAMETER)
        all_masks.append(masks)
        detected_count = int(masks.max())
        print(f"  Frame {index} ({frame_paths[index].name}): {detected_count} nuclei detected [{time.time() - t0:.1f}s]")

    # STEP 4: Extract centroids + area.
    print("\n" + "=" * 60)
    print("STEP 4 — Extracting nucleus centroids (mask -> centroid per nucleus)")
    print("=" * 60)

    rows = []
    for frame_index, masks in enumerate(all_masks):
        for region in regionprops(masks):
            cy, cx = region.centroid  # regionprops gives (row, col) = (y, x) order
            rows.append(
                {
                    "frame": frame_index,
                    "x": cx,
                    "y": cy,
                    "area": region.area,
                }
            )

    detections = pd.DataFrame(rows)
    print(f"  Total point detections across all {n_frames} frames: {len(detections)}")

    # STEP 5: Link detections into trajectories with trackpy.
    if detections.empty:
        search_range = 15
    else:
        diam_est = np.sqrt(detections.loc[detections["frame"] == 0, "area"].median() / np.pi) * 2
        search_range = max(15, int(diam_est * 2))

    print("\n" + "=" * 60)
    print("STEP 5 — Linking nuclei into trajectories (trackpy)")
    print("=" * 60)
    print(f"  search_range = {search_range} px  (~2x median nucleus diameter of frame 0)")
    print(f"  memory       = {MEMORY} frames")

    if detections.empty:
        trajectories = pd.DataFrame(columns=["frame", "x", "y", "area", "particle"])
        n_raw = 0
        n_kept = 0
        print("  No detections found, so no trajectories were linked")
    else:
        trajectories = tp.link(
            detections,
            search_range=search_range,
            memory=MEMORY,
            adaptive_stop=0.1,
            adaptive_step=0.95,
        )
        n_raw = trajectories["particle"].nunique()
        print(f"  Linked {len(trajectories)} detections -> {n_raw} raw trajectories")

        trajectories = tp.filter_stubs(trajectories, threshold=MIN_FRAMES)
        n_kept = trajectories["particle"].nunique()
        print(f"  After removing tracks shorter than {MIN_FRAMES} frames: {n_kept} trajectories kept")

    # STEP 6: Save trajectory CSV + visualisation.
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
    output.to_csv(traj_csv, index=False)
    print(f"  Saved CSV : {traj_csv}  ({len(output)} rows)")

    fig, ax = plt.subplots(figsize=(10, 9))
    ax.imshow(frames[0], cmap="gray")

    unique_ids = output["nucleus_id"].unique() if not output.empty else []
    color_map = plt.cm.tab20(np.linspace(0, 1, len(unique_ids))) if len(unique_ids) else []

    for nucleus_id, color in zip(unique_ids, color_map):
        traj = output[output["nucleus_id"] == nucleus_id].sort_values("frame")
        ax.plot(traj["x"], traj["y"], "-o", color=color, markersize=3, linewidth=1.2)

    ax.set_title(
        f"Nucleus trajectories — seq. {data_dir.name}, frames 0-{n_frames - 1}\n"
        f"{n_kept} trajectories over {len(unique_ids)} tracked nuclei",
        fontsize=11,
    )
    ax.set_xlabel("x (pixels)")
    ax.set_ylabel("y (pixels)")
    plt.tight_layout()
    plt.savefig(viz_image, dpi=150)
    plt.close()
    print(f"  Saved plot: {viz_image}")

    # SUMMARY
    avg_len = 0.0 if output.empty else output.groupby("nucleus_id").size().mean()
    total_nuclei_detected = len(detections)

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Frames processed        : {n_frames}")
    print(f"  Total nuclei detected   : {total_nuclei_detected}  (sum across all frames)")
    print(f"  Raw trajectories linked : {n_raw}")
    print(f"  Trajectories kept       : {n_kept}  (>= {MIN_FRAMES} frames long)")
    print(f"  Average track length    : {avg_len:.1f} frames")
    print(f"\n  Trajectory CSV : {traj_csv}")
    print(f"  Visualisation  : {viz_image}")


if __name__ == "__main__":
    main()
