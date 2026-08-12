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
#   python3 analysis/segment_nd2.py --input <preprocessed_frame.png> --output <out.png>
#
# Requirements:  pip install cellpose
# Note: Cellpose installs PyTorch (~1GB). The first run also
#       downloads model weights. This is normal.
#
# 2026-07: switched from model_type="nuclei" to Cellpose's default model
# (Cellpose-SAM). The "nuclei" model was tested against real Physarum
# fluorescence data and found 0 nuclei; the default model, used by
# fluorescence_pipeline.py, found real detections on the same kind of
# data — confirmed against real Dye Trial 1/Z1 fluorescence frames.
# ------------------------------------------------------------

import argparse
from pathlib import Path

import numpy as np
from PIL import Image
from cellpose import models, utils   # cellpose: the segmentation library

try:
    from analysis.cellpose_runtime import resolve_cellpose_gpu_mode
except ImportError:
    from cellpose_runtime import resolve_cellpose_gpu_mode

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_IMAGE = REPO_ROOT / "data" / "analysis" / "preprocessing" / "frame_0_after.png"
DEFAULT_OUTPUT_IMAGE = REPO_ROOT / "data" / "analysis" / "nd2_sample" / "frame_0_segmented_preprocessed.png"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Segment nuclei/cells in a single image with Cellpose.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_IMAGE, help="Image to segment")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_IMAGE, help="Where to save the outlined result")
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def main() -> None:
    args = parse_args()
    input_image = resolve_path(args.input)
    output_image = resolve_path(args.output)
    output_image.parent.mkdir(parents=True, exist_ok=True)

    # ── 1. Load the image ─────────────────────────────────────────────────────────
    # We load it as a NumPy array because Cellpose works with arrays, not files.
    # Shape will be (height, width, 3) for an RGB image.
    print(f"Loading image: {input_image}")
    pil_img = Image.open(input_image).convert("RGB")
    print(f"Original size : {pil_img.width} x {pil_img.height} px")

    # ── 1b. Resize to 25% for faster testing ─────────────────────────────────────
    # Cellpose on CPU is slow on large images. 25% = ~512x720 px, runs much faster.
    # Remove or increase SCALE (up to 1.0) once you're happy with the results.
    #
    # Tradeoff to know about: on real Physarum fluorescence data, this downscale
    # (plus the 8-bit PNG conversion) can lose faint/sparse signal entirely — this
    # script found 0 objects on real data that fluorescence_pipeline.py (which
    # runs Cellpose on the full-resolution raw 16-bit frame, no downscale) found
    # real detections in. A "0 objects" result here doesn't necessarily mean
    # there's nothing in the image — try SCALE=1.0, or use
    # fluorescence_pipeline.py directly, before concluding the frame is empty.
    SCALE = 0.25
    new_w = int(pil_img.width * SCALE)
    new_h = int(pil_img.height * SCALE)
    pil_img = pil_img.resize((new_w, new_h), Image.LANCZOS)  # LANCZOS = high quality downscale
    print(f"Resized to    : {pil_img.width} x {pil_img.height} px  ({int(SCALE * 100)}% of original)")

    img = np.array(pil_img)
    print(f"Array shape   : {img.shape}  (height x width x colour channels)")

    # ── 2. Load the Cellpose model ────────────────────────────────────────────────
    # Default model (Cellpose-SAM) — model_type="nuclei" found 0 detections on
    # real Physarum fluorescence data (Dye Trial 1/Z1); the default model is
    # what actually worked. GPU mode is resolved from CELLPOSE_GPU and falls
    # back to CPU if CUDA is unavailable.
    print("\nLoading Cellpose model (downloads on first run)...")
    USE_GPU = resolve_cellpose_gpu_mode()
    print(f"GPU mode       : {'enabled' if USE_GPU else 'disabled'}")
    model = models.CellposeModel(gpu=USE_GPU)

    # ── 3. Run segmentation ───────────────────────────────────────────────────────
    # model.eval() is the main call that detects cells.
    #
    # channels=[0, 0] tells Cellpose to treat the image as grayscale.
    #   The first 0 = "nucleus channel is grayscale (average of R,G,B)"
    #   The second 0 = "no separate cytoplasm channel"
    #   If your nuclei are specifically blue (DAPI stain), try channels=[3, 0].
    #
    # diameter=None lets Cellpose automatically estimate the object size.
    #   If results look wrong, set this to the approximate diameter in
    #   pixels (e.g. diameter=30 for small nuclei, diameter=80 for large ones).
    print("Running segmentation — this may take a minute on CPU...")
    results = model.eval(img, diameter=None, channels=[0, 0])

    # results[0] is the mask array — same shape as the image (H, W),
    # where each pixel is labelled with the object ID it belongs to.
    # Background pixels = 0, first object = 1, second = 2, and so on.
    masks = results[0]

    # ── 4. Count detected objects ─────────────────────────────────────────────────
    # The highest number in the mask = total number of detected objects.
    n_detected = int(masks.max())
    print(f"\nDetected {n_detected} object(s)")

    # ── 5. Convert masks to outlines ──────────────────────────────────────────────
    # utils.masks_to_outlines() finds the border pixels of each mask region.
    # It returns a boolean array (True = outline pixel, False = not an outline).
    outlines = utils.masks_to_outlines(masks)   # shape: (H, W), dtype: bool

    # ── 6. Draw outlines on the original image ────────────────────────────────────
    # We copy the original image so we don't modify it, then colour the
    # outline pixels bright green (R=0, G=255, B=0) so they're easy to see.
    result = img.copy()
    result[outlines] = [0, 255, 0]   # paint outline pixels green

    # ── 7. Save the result ────────────────────────────────────────────────────────
    Image.fromarray(result).save(output_image)
    print(f"Saved       : {output_image}")
    print("\nDone! Open the PNG to see green outlines around each detected object.")
    print("Tip: if outlines look wrong, try adjusting 'diameter' or 'channels' in step 3.")


if __name__ == "__main__":
    main()
