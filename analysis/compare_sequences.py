"""Compare fluorescence pipeline results for seq01 and seq02.

This script reads the saved trajectory CSV files, calculates a few simple
summary metrics, prints them side by side, and writes the comparison table to
disk for later review.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


BASE_DIR = Path("data/analysis/fluorescence")
SEQ01_CSV = BASE_DIR / "seq01" / "trajectories.csv"
SEQ02_CSV = BASE_DIR / "seq02" / "trajectories.csv"
OUTPUT_CSV = BASE_DIR / "sequence_comparison.csv"


def load_results(csv_path: Path) -> pd.DataFrame:
    """Load one trajectory CSV and attach a sequence label."""

    if not csv_path.exists():
        raise FileNotFoundError(f"Missing results file: {csv_path}")
    return pd.read_csv(csv_path)


def resolve_seq01_path() -> Path:
    """Use the new seq01 folder when present, otherwise the legacy output path."""

    legacy_path = BASE_DIR / "trajectories.csv"
    if SEQ01_CSV.exists():
        return SEQ01_CSV
    if legacy_path.exists():
        return legacy_path
    raise FileNotFoundError(f"Missing results file: {SEQ01_CSV} or {legacy_path}")


def summarize_results(df: pd.DataFrame) -> dict[str, float]:
    """Compute the comparison metrics from one trajectory table."""

    if df.empty:
        return {
            "avg_nuclei_per_frame": 0.0,
            "trajectory_count": 0,
            "avg_track_length_frames": 0.0,
            "avg_nucleus_area_px": 0.0,
        }

    frames = df["frame"].nunique()
    trajectories = df["nucleus_id"].nunique()
    avg_track_length = df.groupby("nucleus_id").size().mean()
    avg_nucleus_area = df["area"].mean()
    avg_nuclei_per_frame = trajectories / frames if frames else 0.0

    return {
        "avg_nuclei_per_frame": round(float(avg_nuclei_per_frame), 2),
        "trajectory_count": int(trajectories),
        "avg_track_length_frames": round(float(avg_track_length), 2),
        "avg_nucleus_area_px": round(float(avg_nucleus_area), 2),
    }


def main() -> None:
    seq01 = summarize_results(load_results(resolve_seq01_path()))
    seq02 = summarize_results(load_results(SEQ02_CSV))

    comparison = pd.DataFrame(
        [
            {"sequence": "seq01", **seq01},
            {"sequence": "seq02", **seq02},
        ]
    )

    print("Fluorescence sequence comparison")
    print("=" * 60)
    print(comparison.to_string(index=False))

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    comparison.to_csv(OUTPUT_CSV, index=False)
    print(f"\nSaved comparison CSV -> {OUTPUT_CSV}")


if __name__ == "__main__":
    main()