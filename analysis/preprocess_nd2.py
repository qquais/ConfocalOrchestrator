# preprocess_nd2.py
# ------------------------------------------------------------
# Cleans up a raw confocal frame before it goes into segmentation
# and tracking. Three preprocessing steps, applied in order:
#   1. Gaussian denoising    - smooths out random pixel noise
#   2. Background correction - removes uneven illumination
#   3. Median filtering      - removes salt-and-pepper speckle
#
# Run (from the repo root, with .venv activated):
#   python3 analysis/preprocess_nd2.py
#
# Requirements: scikit-image, numpy, Pillow (already installed)
# ------------------------------------------------------------

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from skimage.color import rgb2gray
from skimage.filters import gaussian, median
from skimage.morphology import disk
from pathlib import Path

# ── 1. Paths ──────────────────────────────────────────────────────────────────
INPUT_IMAGE = "data/analysis/nd2_sample/frame_0.png"
OUTPUT_DIR = Path("data/analysis/preprocessing")
OUTPUT_IMAGE = OUTPUT_DIR / "frame_0_preprocessed.png"      # side-by-side BEFORE/AFTER
AFTER_ONLY_IMAGE = OUTPUT_DIR / "frame_0_after.png"          # preprocessed frame only

# Create the output folder if it doesn't exist yet (mkdir -p equivalent)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── 2. Load the image ─────────────────────────────────────────────────────────
# frame_0.png was saved as RGB, but a confocal channel is really grayscale
# data, so we convert down to a single channel to make filtering simpler.
# rgb2gray() returns a "float" image with values between 0.0 (black) and
# 1.0 (white) — most scikit-image filters expect this format.
print(f"Loading image: {INPUT_IMAGE}")
original_rgb = np.array(Image.open(INPUT_IMAGE).convert("RGB"))
gray = rgb2gray(original_rgb)
print(f"Image size: {gray.shape[1]} x {gray.shape[0]} px (grayscale)")

# ── 3. Gaussian denoising ─────────────────────────────────────────────────────
# Blurs the image slightly with a Gaussian (bell-curve shaped) kernel. This
# averages each pixel together with its neighbours, which smooths out random
# sensor noise while keeping the overall shapes intact. "sigma" controls how
# strong the blur is — bigger sigma = more smoothing.
print("Step 1/3: Gaussian denoising...")
denoised = gaussian(gray, sigma=0.5)

# ── 4. Background correction (illumination correction) ───────────────────────
# Confocal images often have uneven brightness across the field of view
# (e.g. one corner brighter/darker than another). We estimate that slow,
# large-scale brightness trend by blurring with a very large sigma — this
# erases small details like nuclei but keeps the big illumination pattern.
# Dividing the image by this "background" flattens the uneven lighting while
# keeping small structures visible, regardless of whether they are brighter
# or darker than their surroundings.
#
# sigma needs to be bigger than the largest clusters of nuclei in the image
# (here, nuclei clusters span several hundred pixels). If sigma is too small,
# the "background" blur still dips down under dense nuclei clusters, so
# dividing it out cancels out real contrast instead of just fixing lighting.
# validation/check_preprocessing_quality.py caught exactly this with the
# original sigma=50 (contrast and CNR both got WORSE) — sweeping sigma showed
# 400 is big enough to only capture the slow lighting trend, not the nuclei.
print("Step 2/3: Background correction (illumination)...")
background = gaussian(denoised, sigma=400)
corrected = denoised / (background + 1e-6) * background.mean()
corrected = np.clip(corrected, 0, 1)  # keep pixel values in the valid 0.0-1.0 range

# ── 5. Median filtering ───────────────────────────────────────────────────────
# Replaces each pixel with the median (middle) value of its neighbours inside
# a small disk-shaped area. This removes "salt-and-pepper" speckle noise
# (isolated stray bright/dark pixels) without blurring edges as much as a
# Gaussian blur would.
print("Step 3/3: Median filtering...")
final = median(corrected, disk(2))

# ── 6. Convert the float images (0.0-1.0) back to standard 8-bit (0-255) ─────
# so they can be saved as a normal PNG.
original_8bit = (gray * 255).astype(np.uint8)
final_8bit = (final * 255).astype(np.uint8)

# ── 7. Build a side-by-side "before vs after" comparison image ───────────────
before_img = Image.fromarray(original_8bit).convert("RGB")
after_img = Image.fromarray(final_8bit).convert("RGB")

comparison = Image.new("RGB", (before_img.width * 2, before_img.height))
comparison.paste(before_img, (0, 0))
comparison.paste(after_img, (before_img.width, 0))

# Label each half so it's obvious which side is which.
# load_default(size=...) gives us a scalable built-in font (no font file needed).
draw = ImageDraw.Draw(comparison)
font = ImageFont.load_default(size=80)
draw.text((30, 30), "BEFORE", fill=(255, 0, 0), font=font)
draw.text((before_img.width + 30, 30), "AFTER", fill=(255, 0, 0), font=font)

# ── 8. Save the results ───────────────────────────────────────────────────────
comparison.save(OUTPUT_IMAGE)
print(f"\nSaved side-by-side comparison: {OUTPUT_IMAGE}")

# Also save the preprocessed frame on its own (no BEFORE/AFTER labels, not
# pasted next to the original) so downstream steps like segmentation can
# load it directly as a normal image, instead of parsing the comparison PNG.
after_img.save(AFTER_ONLY_IMAGE)
print(f"Saved preprocessed frame only: {AFTER_ONLY_IMAGE}")

print("\nDone! Open the comparison PNG to see raw (left) vs preprocessed (right).")
