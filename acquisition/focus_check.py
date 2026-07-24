# focus_check.py
# ------------------------------------------------------------
# Focus drift detection - the safety net for long overnight runs.
#
# Over a multi-hour time-lapse, the focal plane can drift away from the
# sample (thermal expansion of the stage/objective, mechanical settling,
# sample creep) with nobody watching to notice. This module gives
# run_protocol.py a cheap way to check "does this frame still look as sharp
# as when the run started?" after every timepoint.
#
# METHOD - Laplacian variance (a standard no-reference sharpness metric):
#   1. Convert the frame to grayscale.
#   2. Apply a Laplacian filter (2nd derivative) - it responds strongly to
#      edges/fine detail and near-zero to smooth regions.
#   3. Take the VARIANCE of the filtered image.
#        - In-focus frame  -> sharp edges          -> high variance
#        - Out-of-focus frame -> edges smoothed away -> low variance
#
# USAGE (once wired into run_protocol.py's timepoint loop):
#   monitor = FocusMonitor()
#   monitor.set_baseline(first_frame)              # right after focus is confirmed good
#   ...
#   result = monitor.check(latest_frame)
#   if result.drift_detected:
#       print(f"WARNING: possible focus drift ({result.percent_drop:.0%} sharpness drop)")
#
# Run this file directly for a demo (from the repo root, with .venv activated):
#   python3 acquisition/focus_check.py
#
# Requirements: scikit-image, numpy, Pillow, matplotlib (already installed)
# ------------------------------------------------------------

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image
from skimage.color import rgb2gray
from skimage.filters import gaussian, laplace


# ── 1. The sharpness metric itself ───────────────────────────────────────────
def compute_sharpness(image: np.ndarray) -> float:
    """Return the Laplacian-variance sharpness score of an image.

    Higher = sharper / more in-focus. Accepts a grayscale (H, W) or RGB
    (H, W, 3) array in either uint8 (0-255) or float (0.0-1.0) form.
    """
    gray = rgb2gray(image) if image.ndim == 3 else image
    if gray.dtype != np.float64:
        gray = gray.astype(np.float64) / 255.0 if gray.max() > 1.0 else gray.astype(np.float64)
    edges = laplace(gray)
    return float(edges.var())


# ── 2. Result of one drift check ─────────────────────────────────────────────
@dataclass
class FocusCheckResult:
    sharpness: float          # this frame's Laplacian-variance score
    baseline: float           # the reference score it's being compared against
    percent_drop: float       # fraction below baseline, e.g. 0.35 = 35% less sharp
    drift_detected: bool      # True once the drop has persisted long enough to flag


# ── 3. Stateful monitor - tracks sharpness across a whole time-lapse run ────
class FocusMonitor:
    """Compares each new timepoint's sharpness against a baseline frame and
    flags sustained drops as likely focus drift.

    A single soft/blurry frame (motion, a bubble drifting through, a noisy
    sensor read) shouldn't trigger a false alarm on an unattended overnight
    run, so drift is only reported once the sharpness has stayed below
    `drop_threshold` for `consecutive_required` checks in a row. One sharp
    frame in between resets that streak.
    """

    def __init__(self, drop_threshold: float = 0.4, consecutive_required: int = 2):
        """
        drop_threshold: fraction below baseline that counts as "low" for one
            frame, e.g. 0.4 = flag frames that are 40% less sharp than baseline.
        consecutive_required: how many "low" frames in a row before
            drift_detected actually flips True.
        """
        self.drop_threshold = drop_threshold
        self.consecutive_required = consecutive_required
        self.baseline: float | None = None
        self._consecutive_low = 0

    def set_baseline(self, image: np.ndarray) -> float:
        """Record this frame's sharpness as the reference "good focus" value.

        Call this once, right after the operator has confirmed focus looks
        correct (e.g. on the first timepoint of a run).
        """
        self.baseline = compute_sharpness(image)
        self._consecutive_low = 0
        return self.baseline

    def check(self, image: np.ndarray) -> FocusCheckResult:
        """Score a new frame against the baseline and update the drift state."""
        if self.baseline is None:
            raise RuntimeError("FocusMonitor.set_baseline() must be called before check().")

        sharpness = compute_sharpness(image)
        # A zero baseline (e.g. a blank/featureless reference frame) makes
        # "percent drop" undefined - treat as no drop rather than divide by
        # zero, since there's no real signal to measure drift against.
        percent_drop = max(0.0, (self.baseline - sharpness) / self.baseline) if self.baseline > 0 else 0.0

        if percent_drop >= self.drop_threshold:
            self._consecutive_low += 1
        else:
            self._consecutive_low = 0

        drift_detected = self._consecutive_low >= self.consecutive_required

        return FocusCheckResult(
            sharpness=sharpness,
            baseline=self.baseline,
            percent_drop=percent_drop,
            drift_detected=drift_detected,
        )


# ── 4. Demo / self-test ──────────────────────────────────────────────────────
if __name__ == "__main__":
    import matplotlib.pyplot as plt

    INPUT_IMAGE = "data/analysis/nd2_sample/frame_0.png"
    OUTPUT_DIR = Path("data/analysis/focus_check")
    OUTPUT_PLOT = OUTPUT_DIR / "sharpness_over_time.png"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("Focus drift detection demo")
    print("=" * 60)
    print(f"Loading baseline (in-focus) frame: {INPUT_IMAGE}")

    sharp = np.array(Image.open(INPUT_IMAGE).convert("RGB"))

    # Simulate progressive defocus by blurring the same frame with increasing
    # sigma - stands in for the microscope's focal plane slowly drifting away
    # over a real overnight run, without needing real drifted data on hand.
    simulated_timepoints = {
        "t0 (baseline, in focus)": sharp,
        "t1 (still in focus)": sharp,
        "t2 (mild drift)": gaussian(sharp, sigma=1.5, channel_axis=-1),
        "t3 (moderate drift)": gaussian(sharp, sigma=3.0, channel_axis=-1),
        "t4 (severe drift)": gaussian(sharp, sigma=6.0, channel_axis=-1),
        "t5 (recovered, re-focused)": sharp,
    }

    monitor = FocusMonitor(drop_threshold=0.4, consecutive_required=2)
    baseline_score = monitor.set_baseline(simulated_timepoints["t0 (baseline, in focus)"])
    print(f"Baseline sharpness: {baseline_score:.6f}\n")

    labels, scores, drops, flags = [], [], [], []
    for label, frame in simulated_timepoints.items():
        result = monitor.check(frame)
        flag = "  <-- DRIFT DETECTED" if result.drift_detected else ""
        print(
            f"  {label:30s} sharpness={result.sharpness:.6f}  "
            f"drop={result.percent_drop:6.1%}{flag}"
        )
        labels.append(label)
        scores.append(result.sharpness)
        drops.append(result.percent_drop)
        flags.append(result.drift_detected)

    # ── Plot sharpness across the simulated run ──────────────────────────────
    fig, ax = plt.subplots(figsize=(9, 5))
    colors = ["#c0392b" if f else "#27ae60" for f in flags]
    ax.bar(range(len(labels)), scores, color=colors)
    ax.axhline(baseline_score * (1 - monitor.drop_threshold), color="gray", linestyle="--",
               label=f"drift threshold ({monitor.drop_threshold:.0%} below baseline)")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=30, ha="right")
    ax.set_ylabel("Sharpness (Laplacian variance)")
    ax.set_title("Simulated focus drift across a time-lapse run")
    ax.legend()
    plt.tight_layout()
    plt.savefig(OUTPUT_PLOT, dpi=150)
    plt.close()

    print(f"\nSaved plot: {OUTPUT_PLOT}")
    print("\nDone. Green bars = in focus, red bars = drift flagged.")
