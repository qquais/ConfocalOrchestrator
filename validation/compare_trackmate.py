"""Compare pipeline detections against TrackMate ground truth.

This script measures how well the fluorescence pipeline tracked nuclei in
Fluo-N2DH-SIM+ sequence 01 by comparing detected nucleus positions against
ground-truth segmentation masks.

Precision means: of the nuclei we detected, how many were correct.
Recall means: of the ground-truth nuclei, how many we found.
F1 score balances precision and recall in one number.
Detection accuracy here is defined as TP / total ground-truth nuclei.
"""

from __future__ import annotations

import re
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import tifffile
from PIL import Image
from skimage.measure import regionprops


REPO_ROOT = Path(__file__).resolve().parents[1]

PIPELINE_CSV = REPO_ROOT / "data" / "analysis" / "fluorescence" / "trajectories.csv"
DATASET_ROOT = REPO_ROOT / "data" / "datasets" / "Fluo-N2DH-SIM" / "Fluo-N2DH-SIM+"
SEQ_DIR = DATASET_ROOT / "01"
GT_SEG_DIR = DATASET_ROOT / "01_GT" / "SEG"
GT_TRACK_DIR = DATASET_ROOT / "01_GT" / "TRA"

OUTPUT_DIR = REPO_ROOT / "validation" / "results"
SUMMARY_CSV = OUTPUT_DIR / "tracking_accuracy.csv"
VIZ_IMAGE = OUTPUT_DIR / "accuracy_visualization.png"

MATCH_THRESHOLD_PX = 10.0
MAX_VIS_FRAMES = 10


def extract_number(path: Path) -> int | None:
    """Pull the last number from a file name such as man_track000.tif."""

    match = re.search(r"(\d+)(?!.*\d)", path.stem)
    if not match:
        return None
    return int(match.group(1))


def load_pipeline_results(csv_path: Path) -> pd.DataFrame:
    """Load the nucleus tracks produced by the analysis pipeline."""

    if not csv_path.exists():
        raise FileNotFoundError(f"Pipeline results not found: {csv_path}")

    detections = pd.read_csv(csv_path)
    required_columns = {"nucleus_id", "frame", "x", "y", "area"}
    missing = required_columns - set(detections.columns)
    if missing:
        raise ValueError(f"Pipeline CSV is missing columns: {sorted(missing)}")

    return detections


def load_track_annotations(track_path: Path) -> pd.DataFrame:
    """Load man_track.txt so we can report the GT track spans too."""

    rows = []
    if not track_path.exists():
        raise FileNotFoundError(f"Track annotation file not found: {track_path}")

    with track_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 4:
                continue
            rows.append(
                {
                    "track_id": int(parts[0]),
                    "start_frame": int(parts[1]),
                    "end_frame": int(parts[2]),
                    "parent_track_id": int(parts[3]),
                }
            )

    return pd.DataFrame(rows)


def load_ground_truth_masks(gt_dir: Path) -> dict[int, np.ndarray]:
    """Load GT mask TIFFs and return a mapping of frame index -> mask image.

    The file names in CTC data often look like man_track000.tif, but we also
    support other naming styles by extracting the frame number from the file
    name. If a file has no digits, we fall back to lexicographic order.
    """

    # Different datasets sometimes use slightly different naming conventions
    # or extension casing, so we try a few common patterns before giving up.
    tif_files = sorted(gt_dir.glob("*.tif"))
    if not tif_files:
        tif_files = sorted(gt_dir.glob("*.TIF"))
    if not tif_files:
        tif_files = sorted(gt_dir.glob("man_seg*.tif"))
    if not tif_files:
        tif_files = sorted(gt_dir.glob("man_seg*.TIF"))
    if not tif_files:
        tif_files = sorted(gt_dir.parent.rglob("man_seg*.tif"))
    if not tif_files:
        tif_files = sorted(gt_dir.parent.rglob("man_seg*.TIF"))
    if not tif_files:
        raise FileNotFoundError(f"No GT mask TIFFs found in: {gt_dir}")

    indexed_files: list[tuple[int, Path]] = []
    unindexed_files: list[Path] = []
    for path in tif_files:
        frame_index = extract_number(path)
        if frame_index is None:
            unindexed_files.append(path)
        else:
            indexed_files.append((frame_index, path))

    masks: dict[int, np.ndarray] = {}
    if indexed_files:
        for frame_index, path in sorted(indexed_files, key=lambda item: item[0]):
            masks[frame_index] = tifffile.imread(path)
    else:
        # If the file names do not contain numbers, we assume they are already
        # sorted in frame order.
        for frame_index, path in enumerate(sorted(unindexed_files)):
            masks[frame_index] = tifffile.imread(path)

    return masks


def mask_centroids(mask: np.ndarray) -> np.ndarray:
    """Return the centroid of each labeled object in a segmentation mask."""

    centroids = []
    for region in regionprops(mask):
        cy, cx = region.centroid
        centroids.append((cx, cy))
    return np.asarray(centroids, dtype=float)


def greedy_match(detections: np.ndarray, ground_truth: np.ndarray, threshold_px: float):
    """Match detections to GT points using the nearest valid unused pair.

    We keep the logic simple and beginner friendly: compute all pairwise
    distances, sort them from smallest to largest, and greedily assign each
    detection and GT point at most once.
    """

    if len(detections) == 0 or len(ground_truth) == 0:
        return [], [], []

    deltas = detections[:, None, :] - ground_truth[None, :, :]
    distances = np.sqrt((deltas ** 2).sum(axis=2))

    candidate_pairs: list[tuple[float, int, int]] = []
    for det_idx in range(distances.shape[0]):
        for gt_idx in range(distances.shape[1]):
            distance = float(distances[det_idx, gt_idx])
            if distance <= threshold_px:
                candidate_pairs.append((distance, det_idx, gt_idx))

    candidate_pairs.sort(key=lambda item: item[0])

    matched_det: set[int] = set()
    matched_gt: set[int] = set()
    matches: list[tuple[int, int, float]] = []

    for distance, det_idx, gt_idx in candidate_pairs:
        if det_idx in matched_det or gt_idx in matched_gt:
            continue
        matched_det.add(det_idx)
        matched_gt.add(gt_idx)
        matches.append((det_idx, gt_idx, distance))

    unmatched_detections = [idx for idx in range(len(detections)) if idx not in matched_det]
    unmatched_ground_truth = [idx for idx in range(len(ground_truth)) if idx not in matched_gt]

    return matches, unmatched_detections, unmatched_ground_truth


def load_raw_frame(frame_index: int) -> np.ndarray | None:
    """Load the original fluorescence frame for visualization."""

    frame_path = SEQ_DIR / f"t{frame_index:03d}.tif"
    if not frame_path.exists():
        return None
    return tifffile.imread(frame_path)


def safe_divide(numerator: float, denominator: float) -> float:
    """Return 0 when the denominator is zero."""

    if denominator == 0:
        return 0.0
    return numerator / denominator


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    pipeline = load_pipeline_results(PIPELINE_CSV)
    gt_masks = load_ground_truth_masks(GT_SEG_DIR)
    track_annotations = load_track_annotations(GT_TRACK_DIR / "man_track.txt")

    print("Loaded pipeline detections:", len(pipeline))
    print("Loaded GT frames:", len(gt_masks))
    print("Loaded GT tracks:", len(track_annotations))

    common_frames = sorted(set(pipeline["frame"].astype(int)).intersection(gt_masks.keys()))
    if not common_frames:
        raise RuntimeError("No overlapping frames were found between the pipeline CSV and GT masks.")

    frame_rows = []
    visualization_rows = []

    for frame_index in common_frames:
        frame_detections = pipeline[pipeline["frame"].astype(int) == frame_index].reset_index(drop=True)
        det_points = frame_detections[["x", "y"]].to_numpy(dtype=float)

        gt_points = mask_centroids(gt_masks[frame_index])
        matches, unmatched_detections, unmatched_gt = greedy_match(
            det_points, gt_points, MATCH_THRESHOLD_PX
        )

        tp = len(matches)
        fp = len(unmatched_detections)
        fn = len(unmatched_gt)

        precision = safe_divide(tp, tp + fp)
        recall = safe_divide(tp, tp + fn)
        f1 = safe_divide(2 * precision * recall, precision + recall)
        detection_accuracy = safe_divide(tp, len(gt_points))

        frame_rows.append(
            {
                "frame": frame_index,
                "pipeline_detections": len(det_points),
                "ground_truth_nuclei": len(gt_points),
                "true_positives": tp,
                "false_positives": fp,
                "false_negatives": fn,
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "f1_score": round(f1, 4),
                "detection_accuracy": round(detection_accuracy, 4),
            }
        )

        visualization_rows.append(
            {
                "frame": frame_index,
                "raw_frame": load_raw_frame(frame_index),
                "detections": det_points,
                "gt_points": gt_points,
                "matches": matches,
                "unmatched_detections": unmatched_detections,
                "unmatched_gt": unmatched_gt,
            }
        )

    frame_table = pd.DataFrame(frame_rows)

    total_tp = int(frame_table["true_positives"].sum())
    total_fp = int(frame_table["false_positives"].sum())
    total_fn = int(frame_table["false_negatives"].sum())
    total_gt = int(frame_table["ground_truth_nuclei"].sum())

    overall_precision = safe_divide(total_tp, total_tp + total_fp)
    overall_recall = safe_divide(total_tp, total_tp + total_fn)
    overall_f1 = safe_divide(2 * overall_precision * overall_recall, overall_precision + overall_recall)
    overall_accuracy = safe_divide(total_tp, total_gt)

    overall_row = pd.DataFrame(
        [
            {
                "frame": "overall",
                "pipeline_detections": int(frame_table["pipeline_detections"].sum()),
                "ground_truth_nuclei": total_gt,
                "true_positives": total_tp,
                "false_positives": total_fp,
                "false_negatives": total_fn,
                "precision": round(overall_precision, 4),
                "recall": round(overall_recall, 4),
                "f1_score": round(overall_f1, 4),
                "detection_accuracy": round(overall_accuracy, 4),
            }
        ]
    )

    summary = pd.concat([frame_table, overall_row], ignore_index=True)
    print("\nPer-frame breakdown")
    print(summary.to_string(index=False))

    summary.to_csv(SUMMARY_CSV, index=False)
    print(f"\nSaved summary CSV: {SUMMARY_CSV}")

    # The visualization uses one panel per frame. Green circles are correct
    # matches, red x marks are false positives, and yellow circles are missed
    # ground-truth nuclei.
    n_frames = min(len(visualization_rows), MAX_VIS_FRAMES)
    cols = 2
    rows = int(np.ceil(n_frames / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(12, 5 * rows))
    axes = np.atleast_1d(axes).ravel()

    for ax in axes[n_frames:]:
        ax.axis("off")

    for ax, item in zip(axes, visualization_rows[:n_frames]):
        raw_frame = item["raw_frame"]
        if raw_frame is not None:
            ax.imshow(raw_frame, cmap="gray")
        else:
            ax.set_facecolor("black")

        gt_points = item["gt_points"]
        detections = item["detections"]

        if len(gt_points):
            ax.scatter(gt_points[:, 0], gt_points[:, 1], s=60, facecolors="none", edgecolors="cyan", label="GT")

        matched_det_indices = {det_idx for det_idx, _, _ in item["matches"]}
        matched_gt_indices = {gt_idx for _, gt_idx, _ in item["matches"]}

        if len(detections):
            det_colors = ["lime" if idx in matched_det_indices else "red" for idx in range(len(detections))]
            det_markers = ["o" if idx in matched_det_indices else "x" for idx in range(len(detections))]
            for idx, (x, y) in enumerate(detections):
                ax.scatter(
                    x,
                    y,
                    s=70,
                    c=det_colors[idx],
                    marker=det_markers[idx],
                    linewidths=1.8,
                )

        if len(gt_points):
            missed_gt = [idx for idx in range(len(gt_points)) if idx not in matched_gt_indices]
            if missed_gt:
                missed = gt_points[missed_gt]
                ax.scatter(missed[:, 0], missed[:, 1], s=90, facecolors="none", edgecolors="yellow", linewidths=1.8, label="Missed")

        ax.set_title(
            f"Frame {item['frame']} | TP={len(item['matches'])} FP={len(item['unmatched_detections'])} FN={len(item['unmatched_gt'])}"
        )
        ax.set_axis_off()

    fig.suptitle("Detection accuracy: matched vs missed nuclei", fontsize=14)
    plt.tight_layout()
    plt.savefig(VIZ_IMAGE, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved visualization: {VIZ_IMAGE}")


if __name__ == "__main__":
    main()