# check_preprocessing_quality.py
# -----------------------------------------------------------------------
# VALIDATION GROUNDWORK
#
# We don't have hand-labelled ground truth yet, so we can't say
# "preprocessing improved segmentation accuracy by X%". What we CAN do is
# check, with objective numbers, that preprocessing (analysis/preprocess_nd2.py)
# actually improved image quality instead of just "looking different".
#
# We compute four reference-free metrics, before vs after, over the SAME
# foreground (nuclei) / background regions in both images:
#   1. Background noise       - lower after  = denoising worked
#   2. Foreground contrast    - kept/higher  = nuclei are still visible
#   3. Contrast-to-noise ratio (CNR) - higher = overall signal quality improved
#   4. Illumination uniformity - lower spread = background correction worked
#
# This establishes a pattern (shared mask, before/after metrics, saved
# report) that later validation work (segmentation accuracy, tracking vs
# TrackMate) can reuse.
#
# How to run (from the repo root, with .venv activated):
#   python3 validation/check_preprocessing_quality.py
#
# Requirements: numpy, pandas, Pillow, scikit-image (already installed)
# -----------------------------------------------------------------------

import numpy as np
import pandas as pd
from pathlib import Path
from PIL import Image
from skimage.color import rgb2gray
from skimage.filters import threshold_otsu

# ── CONFIGURATION ──────────────────────────────────────────────────────────────
# preprocess_nd2.py saves ONE image: the original (left half) and the
# preprocessed result (right half) pasted side by side. We load that single
# file and split it back into two arrays instead of re-running preprocessing.
COMPARISON_IMAGE = "data/analysis/preprocessing/frame_0_preprocessed.png"
OUTPUT_DIR = Path("data/analysis/validation")
REPORT_CSV = OUTPUT_DIR / "preprocessing_quality_report.csv"
MASK_OVERLAY_IMAGE = OUTPUT_DIR / "otsu_mask_overlay.png"

# Grid size used to check illumination uniformity (see Step 4).
UNIFORMITY_GRID = 4  # 4x4 = 16 tiles across the image

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── STEP 1: Load the before/after comparison image and split it in half ──────
print("=" * 60)
print("STEP 1 — Loading before/after images")
print("=" * 60)

comparison = np.array(Image.open(COMPARISON_IMAGE).convert("RGB"))
half_width = comparison.shape[1] // 2

before_rgb = comparison[:, :half_width]
after_rgb = comparison[:, half_width:]

# Convert to grayscale float (0.0-1.0) — same format the filters used internally.
before = rgb2gray(before_rgb)
after = rgb2gray(after_rgb)

print(f"  Loaded        : {COMPARISON_IMAGE}")
print(f"  Each half size: {before.shape[1]} x {before.shape[0]} px")

# ── STEP 2: Build a foreground/background mask from the ORIGINAL image ──────
# We use Otsu's method to automatically pick a brightness threshold that best
# separates two groups of pixels. Nuclei are dark on a light background, so
# "foreground" = pixels darker than the threshold.
#
# Important: we compute this mask ONCE, from the ORIGINAL image, and reuse it
# on both images. That keeps the comparison fair — we're always measuring
# the same physical regions, before and after preprocessing.
print("\n" + "=" * 60)
print("STEP 2 — Building a shared foreground/background mask (Otsu)")
print("=" * 60)

threshold = threshold_otsu(before)
foreground_mask = before < threshold   # dark pixels = nuclei
background_mask = ~foreground_mask

fg_fraction = foreground_mask.mean() * 100
print(f"  Otsu threshold      : {threshold:.4f}")
print(f"  Foreground (nuclei) : {fg_fraction:.1f}% of pixels")
print(f"  Background          : {100 - fg_fraction:.1f}% of pixels")


# ── STEP 3: Compute contrast / noise metrics for one image ───────────────────
def compute_metrics(gray_image):
    """Return (background_noise, contrast, cnr) for gray_image, using the
    shared foreground/background mask from Step 2."""
    fg_mean = gray_image[foreground_mask].mean()
    bg_mean = gray_image[background_mask].mean()
    bg_noise = gray_image[background_mask].std()  # spread of background pixels

    contrast = abs(bg_mean - fg_mean)
    cnr = contrast / (bg_noise + 1e-8)  # tiny epsilon avoids divide-by-zero

    return bg_noise, contrast, cnr


# ── STEP 4: Compute illumination uniformity for one image ────────────────────
def compute_uniformity(gray_image):
    """Split the image into a grid of tiles, measure the average BACKGROUND
    brightness in each tile, then return the spread (std) across tiles.
    A perfectly evenly-lit image would have the same background brightness
    everywhere, so a lower spread means more uniform illumination."""
    tile_h = gray_image.shape[0] // UNIFORMITY_GRID
    tile_w = gray_image.shape[1] // UNIFORMITY_GRID

    tile_means = []
    for row in range(UNIFORMITY_GRID):
        for col in range(UNIFORMITY_GRID):
            y0, y1 = row * tile_h, (row + 1) * tile_h
            x0, x1 = col * tile_w, (col + 1) * tile_w

            tile_bg_mask = background_mask[y0:y1, x0:x1]
            if tile_bg_mask.sum() < 50:  # skip tiles with barely any background
                continue

            tile_pixels = gray_image[y0:y1, x0:x1][tile_bg_mask]
            tile_means.append(tile_pixels.mean())

    return float(np.std(tile_means))


print("\n" + "=" * 60)
print("STEP 3/4 — Computing quality metrics (before vs after)")
print("=" * 60)

before_noise, before_contrast, before_cnr = compute_metrics(before)
after_noise, after_contrast, after_cnr = compute_metrics(after)

before_uniformity = compute_uniformity(before)
after_uniformity = compute_uniformity(after)

# ── STEP 5: Build and print the comparison report ────────────────────────────
print("\n" + "=" * 60)
print("STEP 5 — Quality report")
print("=" * 60)


def verdict(before_value, after_value, lower_is_better):
    improved = (after_value < before_value) if lower_is_better else (after_value > before_value)
    return "IMPROVED" if improved else "WORSE"


rows = [
    {
        "metric": "Background noise (std dev)",
        "before": before_noise,
        "after": after_noise,
        "verdict": verdict(before_noise, after_noise, lower_is_better=True),
    },
    {
        "metric": "Foreground/background contrast",
        "before": before_contrast,
        "after": after_contrast,
        "verdict": verdict(before_contrast, after_contrast, lower_is_better=False),
    },
    {
        "metric": "Contrast-to-noise ratio (CNR)",
        "before": before_cnr,
        "after": after_cnr,
        "verdict": verdict(before_cnr, after_cnr, lower_is_better=False),
    },
    {
        "metric": "Illumination non-uniformity",
        "before": before_uniformity,
        "after": after_uniformity,
        "verdict": verdict(before_uniformity, after_uniformity, lower_is_better=True),
    },
]

report = pd.DataFrame(rows)
print(report.to_string(index=False))

report.to_csv(REPORT_CSV, index=False)
print(f"\nSaved report: {REPORT_CSV}")

# ── STEP 6: Save a mask overlay so you can eyeball whether Otsu got it right ─
# If the red overlay does NOT line up with the visible nuclei, the metrics
# above aren't trustworthy — the mask (and possibly the threshold) needs fixing.
print("\n" + "=" * 60)
print("STEP 6 — Saving mask overlay for a visual sanity check")
print("=" * 60)

overlay = before_rgb.copy()
overlay[foreground_mask] = [255, 0, 0]  # paint detected nuclei pixels red

Image.fromarray(overlay).save(MASK_OVERLAY_IMAGE)
print(f"  Saved: {MASK_OVERLAY_IMAGE}")

print("\nDone! Check the verdict column above, and open the mask overlay to")
print("confirm the red pixels actually line up with real nuclei.")
