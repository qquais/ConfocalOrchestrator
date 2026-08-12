# check_photobleaching.py
# ------------------------------------------------------------
# Checks whether a fluorescence channel's signal fades (photobleaches)
# over the course of a time-lapse ND2 file, and produces two visuals
# to communicate the finding to a non-technical audience:
#   1. A brightness-vs-frame line plot, with the "usable" window shaded
#      (usable = signal still clearly above the noise floor).
#   2. A frame-by-frame picture strip at a FIXED contrast scale per
#      channel, so fading is actually visible. This matters:
#      extract_frames.py's PNGs are contrast-stretched PER FRAME, which
#      would make even a fully-bleached (near-noise) frame look just as
#      "bright" as a strong one after auto-stretching — the opposite of
#      what we want to show here.
#
# Background: fluorescent dyes lose the ability to fluoresce the more
# they're hit by the excitation laser — each exposure has a small chance
# of permanently damaging the dye molecule. Under repeated imaging this
# can exhaust the usable signal within the first few percent of a
# time-lapse, well before the acquisition itself finishes.
#
# Run (from the repo root, with .venv activated):
#   python3 validation/check_photobleaching.py --file "data/raw/Timelapse1.nd2"
#
# Requirements: nd2, numpy, matplotlib, Pillow (already installed)
# ------------------------------------------------------------

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import nd2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "analysis" / "photobleaching"

# Frames noise floor is estimated from: values below this are treated as
# "no real signal, just camera/background noise" for the shaded window.
NOISE_FLOOR_FRACTION = 0.15  # 15% of peak brightness


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check a fluorescence channel for photobleaching over a time-lapse.")
    parser.add_argument("--file", type=Path, required=True, help="Path to the .nd2 file")
    parser.add_argument("--fluor-channel", type=int, default=0, help="Fluorescence channel index to check for bleaching (default: 0)")
    parser.add_argument("--reference-channel", type=int, default=1, help="Non-fluorescence reference channel, e.g. brightfield (default: 1)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR, help="Folder to write plot/montage into")
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def to_uint8_fixed_scale(frame: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """Contrast-stretch using a SHARED lo/hi across all frames (not this frame's own min/max)."""
    frame = frame.astype(np.float32)
    if hi > lo:
        frame = (frame - lo) / (hi - lo) * 255
    return np.clip(frame, 0, 255).astype(np.uint8)


def main() -> None:
    args = parse_args()
    nd2_file = resolve_path(args.file)
    output_dir = resolve_path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Opening: {nd2_file}")
    with nd2.ND2File(nd2_file) as f:
        sizes = f.sizes
        print(f"Dimensions: {sizes}")
        if "T" not in sizes:
            raise ValueError(f"File has no time axis (sizes={sizes}) — photobleaching needs a time-lapse.")
        images = f.asarray()  # (T, C, Y, X)

    n_frames = images.shape[0]
    fluor = images[:, args.fluor_channel]      # (T, Y, X)
    reference = images[:, args.reference_channel]

    fluor_max = fluor.max(axis=(1, 2)).astype(float)
    fluor_mean = fluor.mean(axis=(1, 2)).astype(float)
    ref_max = reference.max(axis=(1, 2)).astype(float)

    # ── 1. Brightness-vs-frame plot ───────────────────────────────────────
    peak = fluor_max.max()
    peak_frame = int(fluor_max.argmax())
    noise_floor = peak * NOISE_FLOOR_FRACTION
    usable_frames = np.where(fluor_max >= noise_floor)[0]
    usable_end = int(usable_frames.max()) if len(usable_frames) else 0

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(range(n_frames), fluor_max, label=f"Fluorescence channel {args.fluor_channel} — peak brightness", color="crimson", linewidth=2)
    ax.plot(range(n_frames), fluor_mean, label=f"Fluorescence channel {args.fluor_channel} — mean brightness", color="salmon", linewidth=1, linestyle="--")
    ax.axhline(noise_floor, color="gray", linestyle=":", label=f"Noise floor ({NOISE_FLOOR_FRACTION:.0%} of peak)")
    ax.axvspan(0, usable_end, color="green", alpha=0.08, label=f"Usable window (frames 0-{usable_end})")
    ax.set_xlabel("Frame number")
    ax.set_ylabel("Pixel intensity (0-4095 for 12-bit data)")
    ax.set_title(f"Photobleaching check — {nd2_file.name}, channel {args.fluor_channel}")
    ax.legend(loc="upper right")
    ax.grid(alpha=0.2)
    fig.tight_layout()
    plot_path = output_dir / "brightness_over_time.png"
    fig.savefig(plot_path, dpi=150)
    plt.close(fig)

    print(f"\nPeak brightness: {peak:.0f} at frame {peak_frame}")
    print(f"Noise floor ({NOISE_FLOOR_FRACTION:.0%} of peak): {noise_floor:.0f}")
    print(f"Usable window: frames 0-{usable_end} ({usable_end + 1} of {n_frames} frames, {(usable_end + 1) / n_frames:.1%})")
    print(f"Saved: {plot_path}")

    # ── 2. Fixed-contrast frame montage ───────────────────────────────────
    sample_frames = sorted(set(min(t, n_frames - 1) for t in [0, peak_frame, usable_end, n_frames // 4, n_frames // 2, n_frames - 1]))
    fluor_lo, fluor_hi = 0.0, peak       # SAME scale for every fluorescence frame
    ref_lo, ref_hi = 0.0, ref_max.max()  # SAME scale for every reference frame

    tile_h, tile_w = fluor.shape[1], fluor.shape[2]
    label_h = 40
    montage = Image.new("RGB", (tile_w * len(sample_frames), (tile_h + label_h) * 2), "black")
    draw = ImageDraw.Draw(montage)
    font = ImageFont.load_default(size=28)

    for col, t in enumerate(sample_frames):
        fluor_img = Image.fromarray(to_uint8_fixed_scale(fluor[t], fluor_lo, fluor_hi)).convert("RGB")
        ref_img = Image.fromarray(to_uint8_fixed_scale(reference[t], ref_lo, ref_hi)).convert("RGB")

        x = col * tile_w
        montage.paste(fluor_img, (x, label_h))
        montage.paste(ref_img, (x, tile_h + 2 * label_h))
        draw.text((x + 10, 5), f"t={t}  (ch{args.fluor_channel})", fill=(255, 80, 80), font=font)
        draw.text((x + 10, tile_h + label_h + 5), f"t={t}  (ch{args.reference_channel})", fill=(120, 220, 120), font=font)

    montage_path = output_dir / "frame_montage_fixed_contrast.png"
    montage.save(montage_path)
    print(f"Saved: {montage_path}")
    print(f"\nTop row = fluorescence channel {args.fluor_channel} (same brightness scale across all tiles — real fading, not a display artifact)")
    print(f"Bottom row = reference channel {args.reference_channel} (same brightness scale — shown for comparison)")


if __name__ == "__main__":
    main()
