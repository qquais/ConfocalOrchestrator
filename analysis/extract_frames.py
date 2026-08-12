# extract_frames.py
# Extract every frame from an .ND2 file and save as PNG + TIFF files.
# Output: <output>/img001.png, img002.png, ...  and  <output>/t000.tif, t001.tif, ...
#
# Run: python3 analysis/extract_frames.py
#      python3 analysis/extract_frames.py --file "data/raw/Timelapse1.nd2" --channel 0
#
# 2026-07: fixed to handle multi-channel ND2 files. The original version only
# handled (T,H,W)/(T,H,W,3)-shaped arrays and crashed with
# "TypeError: Cannot handle this data type: (1, 1, 1024), |u1" on real Dye
# Trial 1/Z1 data, because it treated the C axis as if it were the frame axis.
#
# 2026-08: added support for 5D (T, Z, C, Y, X) files — a real Z-stack
# time-lapse (348 timepoints x 31 Z-slices x 2 channels, 42GB uncompressed)
# has both T and Z as separate loop axes, which the single-leading-axis
# logic above can't handle. For that shape, each timepoint's Z-stack is
# collapsed via max-intensity projection (brightest pixel at each x,y
# across all Z-slices) into one 2D frame — standard practice when the
# focal plane containing the signal isn't known in advance. This path also
# reads frames lazily via f.read_frame() instead of f.asarray(), since
# loading a 42GB array in one call is wasteful even when it technically
# fits in RAM.

import argparse
import nd2
import numpy as np
import tifffile
from PIL import Image
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ND2_FILE = REPO_ROOT / "data" / "raw" / "MRAP1 KO DN_10X03.nd2"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "frames"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract every frame from an ND2 file as PNG + TIFF.")
    parser.add_argument("--file", type=Path, default=DEFAULT_ND2_FILE, help="Path to the .nd2 file")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR, help="Folder to save frames into")
    parser.add_argument(
        "--channel",
        type=int,
        default=0,
        help="Which channel to extract for multi-channel files (default: 0). "
        "Ignored for RGB (S=3) or single-channel files.",
    )
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    """Treat relative paths as repo-root paths so the script is easy to run from anywhere."""
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def save_frame(frame: np.ndarray, index: int, output_dir: Path) -> None:
    """Save one frame as both raw 16-bit TIFF and contrast-stretched 8-bit PNG."""
    # Raw 16-bit TIFF — this is what fluorescence_pipeline.py's --data flag
    # globs for (t*.tif), so this output is directly consumable by it.
    tifffile.imwrite(output_dir / f"t{index:03d}.tif", frame)

    # Contrast-stretched 8-bit PNG — for quick viewing and as input to
    # preprocess_nd2.py / segment_nd2.py.
    f32 = frame.astype(np.float32)
    lo, hi = f32.min(), f32.max()
    if hi > lo:
        png_frame = (f32 - lo) / (hi - lo) * 255
    else:
        png_frame = np.zeros_like(f32)
    png_frame = np.clip(png_frame, 0, 255).astype(np.uint8)

    filename = output_dir / f"img{index + 1:03d}.png"
    Image.fromarray(png_frame).save(filename)
    print(f"  Saved {filename}")


def main() -> None:
    args = parse_args()
    nd2_file = resolve_path(args.file)
    output_dir = resolve_path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    with nd2.ND2File(nd2_file) as f:
        sizes = f.sizes
        print(f"File dimensions: {sizes}")

        if "T" in sizes and "Z" in sizes and "C" in sizes:
            # 5D file: T timepoints x Z slices x C channels. Read lazily via
            # read_frame() instead of asarray() to avoid loading the whole
            # (potentially many-GB) array into RAM at once. loop_indices
            # confirms the nesting order (T outer/slower, Z inner/faster —
            # matches sizes' key order), so frame index = t * Z_count + z.
            n_channels = sizes["C"]
            if not (0 <= args.channel < n_channels):
                raise ValueError(f"--channel {args.channel} out of range; file has {n_channels} channel(s)")
            t_count, z_count = sizes["T"], sizes["Z"]
            print(
                f"5D file detected (T={t_count}, Z={z_count}, C={n_channels}) — "
                f"extracting channel {args.channel} via max-intensity projection across Z, per timepoint"
            )
            for t in range(t_count):
                z_stack = np.stack([f.read_frame(t * z_count + z)[args.channel] for z in range(z_count)])
                projected = z_stack.max(axis=0)
                save_frame(projected, t, output_dir)
            print(f"\nDone. {t_count} frame(s) (max-projected over {z_count} Z-slices each) saved to {output_dir}/")
            return

        images = f.asarray()

    print(f"Array shape: {images.shape}")

    is_rgb = images.shape[-1] == 3 and images.ndim == 3
    is_single_2d = images.ndim == 2

    if is_rgb or is_single_2d:
        # Single frame, no time/z/channel axis to loop over.
        frames = [images]
    elif "C" in sizes:
        # Real multi-channel file: pick one channel and loop over whatever the
        # leading axis is (T for time-lapse, Z for a z-stack). f.sizes preserves
        # axis order, so the C axis's position tells us how to index it.
        axis_order = list(sizes.keys())
        c_axis = axis_order.index("C")
        if c_axis != 1:
            raise ValueError(
                f"Expected axis order (leading, C, Y, X, ...) but got {axis_order} "
                f"for shape {images.shape} — extraction logic assumes C is the second axis."
            )
        n_channels = sizes["C"]
        if not (0 <= args.channel < n_channels):
            raise ValueError(f"--channel {args.channel} out of range; file has {n_channels} channel(s)")
        frames = [images[i, args.channel] for i in range(images.shape[0])]
        print(f"Extracting channel {args.channel} of {n_channels} across {len(frames)} leading-axis steps")
    else:
        # No C axis, no RGB — plain (T,H,W)/(Z,H,W) grayscale, original behavior.
        frames = [images[i] for i in range(images.shape[0])]

    print(f"Frames to save: {len(frames)}")

    for i, frame in enumerate(frames):
        save_frame(frame, i, output_dir)

    print(f"\nDone. {len(frames)} frame(s) saved to {output_dir}/ (TIFF: t*.tif, PNG: img*.png)")


if __name__ == "__main__":
    main()
