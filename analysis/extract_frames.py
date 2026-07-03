# extract_frames.py
# Extract every frame from an .ND2 file and save as PNG files.
# Output: data/cellects_test/img001.png, img002.png, ...
#
# Run: python3 analysis/extract_frames.py

import nd2
import numpy as np
from PIL import Image
from pathlib import Path

ND2_FILE  = "data/samples/MRAP1 KO DN_10X03.nd2"
OUTPUT_DIR = Path("data/cellects_test")

# Create output folder (mkdir -p equivalent)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

with nd2.ND2File(ND2_FILE) as f:
    print(f"File dimensions: {f.sizes}")
    images = f.asarray()   # load full array into memory

print(f"Array shape: {images.shape}")

# Build a list of 2D/3D frames to save.
# The array axes depend on what the file contains:
#   - Single image (Y, X) or (Y, X, 3): one frame
#   - Time-lapse  (T, Y, X) or (T, Y, X, 3): T frames
#   - Z-stack     (Z, Y, X) or (Z, Y, X, 3): Z frames
#
# Strategy: treat the first axis as the frame index.
# If the array is only 2D (Y, X) or 3D (Y, X, 3) — it's a single frame.

is_rgb = images.shape[-1] == 3 and images.ndim == 3   # shape is (Y, X, 3)
is_single_2d = images.ndim == 2                        # shape is (Y, X)

if is_rgb or is_single_2d:
    # Only one frame in the file
    frames = [images]
else:
    # Multiple frames along the first axis
    frames = [images[i] for i in range(images.shape[0])]

print(f"Frames to save: {len(frames)}")

for i, frame in enumerate(frames):
    # Contrast-stretch each frame to 0-255 so it displays clearly
    frame = frame.astype(np.float32)
    lo, hi = frame.min(), frame.max()
    if hi > lo:
        frame = (frame - lo) / (hi - lo) * 255
    frame = np.clip(frame, 0, 255).astype(np.uint8)

    # Name: img001.png, img002.png, ...
    filename = OUTPUT_DIR / f"img{i+1:03d}.png"
    Image.fromarray(frame).save(filename)
    print(f"  Saved {filename}")

print(f"\nDone. {len(frames)} PNG(s) saved to {OUTPUT_DIR}/")
