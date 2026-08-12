# verify_trajectories.py
# ------------------------------------------------------------
# Sanity-checks fluorescence_pipeline.py's tracking output by cropping a
# small window around each tracked nucleus's position, at every frame it
# appears in, straight from the raw frames. This answers the question a
# trajectories.csv alone can't: is there actually a visible, consistent
# bright spot at these coordinates, or did trackpy link together noise
# that happened to land nearby?
#
# Each nucleus gets its own row of crops, contrast-stretched using ONE
# shared scale across that nucleus's own crops (not auto-stretched per
# crop) — the same reasoning as check_photobleaching.py's fixed-contrast
# montage: per-crop auto-stretch would make a real fade-out or a totally
# empty crop look just as "bright" as a strong one.
#
# Run (from the repo root, with .venv activated):
#   python3 validation/verify_trajectories.py \
#       --trajectories results/Timelapse1/05_tracking/trajectories.csv \
#       --frames-dir results/Timelapse1/02_extract_frames/cy5 \
#       --output results/Timelapse1/05_tracking
#
# Requirements: pandas, numpy, tifffile, Pillow (already installed)
# ------------------------------------------------------------

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import tifffile
from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Overlay tracked nucleus positions onto raw frame crops for visual verification.")
    parser.add_argument("--trajectories", type=Path, required=True, help="trajectories.csv from fluorescence_pipeline.py")
    parser.add_argument("--frames-dir", type=Path, required=True, help="Folder of raw t*.tif frames the trajectories were computed from")
    parser.add_argument("--output", type=Path, required=True, help="Folder to write the verification image into")
    parser.add_argument("--crop-size", type=int, default=100, help="Size (px) of the square crop window around each detection (default: 100)")
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def crop_around(frame: np.ndarray, x: float, y: float, size: int) -> np.ndarray:
    """Crop a size x size window centered on (x, y), clamped to the frame bounds."""
    half = size // 2
    h, w = frame.shape
    cx, cy = int(round(x)), int(round(y))
    x0, x1 = max(0, cx - half), min(w, cx + half)
    y0, y1 = max(0, cy - half), min(h, cy + half)
    crop = frame[y0:y1, x0:x1]
    # Pad if we hit an edge, so every crop is the same size for the montage.
    padded = np.zeros((size, size), dtype=frame.dtype)
    padded[: crop.shape[0], : crop.shape[1]] = crop
    return padded


def main() -> None:
    args = parse_args()
    traj_path = resolve_path(args.trajectories)
    frames_dir = resolve_path(args.frames_dir)
    output_dir = resolve_path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    size = args.crop_size

    trajectories = pd.read_csv(traj_path)
    if trajectories.empty:
        print("trajectories.csv is empty — nothing to verify.")
        return

    nucleus_ids = sorted(trajectories["nucleus_id"].unique())
    max_frames_per_nucleus = trajectories.groupby("nucleus_id").size().max()

    tile_label_h = 24
    tile = size + tile_label_h
    row_label_w = 90
    montage = Image.new(
        "RGB",
        (row_label_w + tile * max_frames_per_nucleus, tile * len(nucleus_ids)),
        "black",
    )
    draw = ImageDraw.Draw(montage)
    font = ImageFont.load_default(size=16)

    for row, nucleus_id in enumerate(nucleus_ids):
        rows = trajectories[trajectories["nucleus_id"] == nucleus_id].sort_values("frame")
        crops = []
        for _, r in rows.iterrows():
            frame_path = frames_dir / f"t{int(r['frame']):03d}.tif"
            frame = tifffile.imread(frame_path)
            crops.append((int(r["frame"]), crop_around(frame, r["x"], r["y"], size)))

        # Shared contrast scale across this nucleus's own crops only.
        stacked = np.stack([c for _, c in crops]).astype(np.float32)
        lo, hi = stacked.min(), stacked.max()

        draw.text((5, row * tile + tile // 2 - 8), f"nucleus {nucleus_id}", fill=(255, 255, 0), font=font)

        for col, (frame_idx, crop) in enumerate(crops):
            if hi > lo:
                crop8 = np.clip((crop.astype(np.float32) - lo) / (hi - lo) * 255, 0, 255).astype(np.uint8)
            else:
                crop8 = np.zeros_like(crop, dtype=np.uint8)
            crop_img = Image.fromarray(crop8).convert("RGB")

            # Mark the exact detected centroid with a red crosshair.
            crop_draw = ImageDraw.Draw(crop_img)
            cx, cy = size // 2, size // 2  # crop is centered on the detection by construction
            crop_draw.line([(cx - 8, cy), (cx + 8, cy)], fill=(255, 0, 0), width=1)
            crop_draw.line([(cx, cy - 8), (cx, cy + 8)], fill=(255, 0, 0), width=1)

            x_pos = row_label_w + col * tile
            y_pos = row * tile
            draw.text((x_pos + 4, y_pos), f"t={frame_idx}", fill=(0, 255, 0), font=font)
            montage.paste(crop_img, (x_pos, y_pos + tile_label_h))

    out_path = output_dir / "trajectory_verification.png"
    montage.save(out_path)
    print(f"Saved: {out_path}")
    print(f"\n{len(nucleus_ids)} nuclei, crop size {size}x{size}px, contrast-stretched per-nucleus (shared scale across that nucleus's own frames).")
    print("Look for: a consistent bright spot near the red crosshair across all frames in a row = plausibly real.")
    print("A crosshair sitting on featureless/noisy background, or a spot that jumps around = likely a spurious link.")


if __name__ == "__main__":
    main()
