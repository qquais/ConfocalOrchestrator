# segment_nd2.py
# ------------------------------------------------------------
# Uses Cellpose (an ML-based segmentation tool) to automatically
# detect and outline nuclei/cells in a microscopy image.
#
# What is Cellpose?
#   Cellpose is a deep learning model trained on thousands of
#   microscopy images. You give it an image and it draws a "mask"
#   (a filled region) around every cell it finds — automatically,
#   no manual tuning required.
#
# How to run (from the repo root, with .venv activated):
#   python3 analysis/segment_nd2.py
#
# Requirements:  pip install cellpose
# Note: Cellpose installs PyTorch (~1GB). The first run also
#       downloads the nuclei model weights (~200 MB). This is normal.
# ------------------------------------------------------------

import numpy as np
from PIL import Image
from cellpose import models, utils   # cellpose: the segmentation library

# ── 1. Paths ──────────────────────────────────────────────────────────────────
# Reads the PREPROCESSED frame (analysis/preprocess_nd2.py output) instead of
# the raw frame — validation/check_preprocessing_quality.py confirmed this
# version has a better contrast-to-noise ratio, so nuclei should be easier
# for Cellpose to detect. Run preprocess_nd2.py first to generate this file.
INPUT_IMAGE  = "data/analysis/preprocessing/frame_0_after.png"
OUTPUT_IMAGE = "data/analysis/nd2_sample/frame_0_segmented_preprocessed.png"

# ── 2. Load the image ─────────────────────────────────────────────────────────
# We load it as a NumPy array because Cellpose works with arrays, not files.
# Shape will be (height, width, 3) for an RGB image.
print(f"Loading image: {INPUT_IMAGE}")
pil_img = Image.open(INPUT_IMAGE).convert("RGB")
print(f"Original size : {pil_img.width} x {pil_img.height} px")

# ── 2b. Resize to 25% for faster testing ─────────────────────────────────────
# Cellpose on CPU is slow on large images. 25% = ~512x720 px, runs much faster.
# Remove or increase SCALE (up to 1.0) once you're happy with the results.
SCALE = 0.25
new_w = int(pil_img.width  * SCALE)
new_h = int(pil_img.height * SCALE)
pil_img = pil_img.resize((new_w, new_h), Image.LANCZOS)  # LANCZOS = high quality downscale
print(f"Resized to    : {pil_img.width} x {pil_img.height} px  ({int(SCALE*100)}% of original)")

img = np.array(pil_img)
print(f"Array shape   : {img.shape}  (height x width x colour channels)")

# ── 3. Load the Cellpose nuclei model ─────────────────────────────────────────
# model_type='nuclei' uses a model pre-trained specifically on cell nuclei.
# gpu=False runs on CPU (slower but works everywhere without extra setup).
# Set gpu=True if you have a CUDA GPU and want faster results.
print("\nLoading Cellpose nuclei model (downloads on first run)...")
# Cellpose 3.x+ uses CellposeModel instead of the old Cellpose class
# GPU CONFIG: comment/uncomment based on environment
model = models.CellposeModel(model_type="nuclei", gpu=False)  # Mac/CPU (default)
# model = models.CellposeModel(model_type="nuclei", gpu=True)  # HPC/GPU (Gilbreth)

# ── 4. Run segmentation ───────────────────────────────────────────────────────
# model.eval() is the main call that detects cells.
#
# channels=[0, 0] tells Cellpose to treat the image as grayscale.
#   The first 0 = "nucleus channel is grayscale (average of R,G,B)"
#   The second 0 = "no separate cytoplasm channel"
#   If your nuclei are specifically blue (DAPI stain), try channels=[3, 0].
#
# diameter=None lets Cellpose automatically estimate the nucleus size.
#   If results look wrong, set this to the approximate nucleus diameter
#   in pixels (e.g. diameter=30 for small nuclei, diameter=80 for large ones).
print("Running segmentation — this may take a minute on CPU...")
results = model.eval(img, diameter=None, channels=[0, 0])

# results[0] is the mask array — same shape as the image (H, W),
# where each pixel is labelled with the nucleus ID it belongs to.
# Background pixels = 0, first nucleus = 1, second = 2, and so on.
masks = results[0]

# ── 5. Count detected nuclei ──────────────────────────────────────────────────
# The highest number in the mask = total number of detected nuclei.
n_nuclei = int(masks.max())
print(f"\nDetected {n_nuclei} nuclei")

# ── 6. Convert masks to outlines ──────────────────────────────────────────────
# utils.masks_to_outlines() finds the border pixels of each mask region.
# It returns a boolean array (True = outline pixel, False = not an outline).
outlines = utils.masks_to_outlines(masks)   # shape: (H, W), dtype: bool

# ── 7. Draw outlines on the original image ────────────────────────────────────
# We copy the original image so we don't modify it, then colour the
# outline pixels bright green (R=0, G=255, B=0) so they're easy to see.
result = img.copy()
result[outlines] = [0, 255, 0]   # paint outline pixels green

# ── 8. Save the result ────────────────────────────────────────────────────────
Image.fromarray(result).save(OUTPUT_IMAGE)
print(f"Saved       : {OUTPUT_IMAGE}")
print("\nDone! Open the PNG to see green outlines around each detected nucleus.")
print("Tip: if outlines look wrong, try adjusting 'diameter' or 'channels' in step 4.")
