"""Analyze whether Physarum nuclei move in a synchronized way.

Biologically, synchronization here means that nuclei do not move as isolated
points. Instead, they may speed up and slow down together, or even travel in
the same direction at the same time. In *Physarum polycephalum*, that kind of
coordinated motion can reflect shared cytoplasmic streaming or a common
mechanical signal running through the plasmodium.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import pearsonr


REPO_ROOT = Path(__file__).resolve().parents[1]
INPUT_CSV = REPO_ROOT / "data" / "analysis" / "fluorescence" / "trajectories.csv"
OUTPUT_DIR = REPO_ROOT / "data" / "analysis" / "synchronization"
VELOCITY_CSV = OUTPUT_DIR / "velocity_over_time.csv"
CORRELATION_CSV = OUTPUT_DIR / "correlation_matrix.csv"
REPORT_TXT = OUTPUT_DIR / "sync_report.txt"
PLOT_PNG = OUTPUT_DIR / "synchronization_analysis.png"


ALIGNMENT_THRESHOLD = 0.75
MAJORITY_FRACTION = 0.60


def load_trajectories(csv_path: Path) -> pd.DataFrame:
    """Load the saved fluorescence trajectories and validate the columns."""

    if not csv_path.exists():
        raise FileNotFoundError(f"Missing trajectories file: {csv_path}")

    df = pd.read_csv(csv_path)
    required_columns = {"nucleus_id", "frame", "x", "y", "area"}
    missing = required_columns - set(df.columns)
    if missing:
        raise ValueError(f"Trajectory CSV is missing columns: {sorted(missing)}")

    return df.copy()


def calculate_velocities(trajectories: pd.DataFrame) -> pd.DataFrame:
    """Turn positions into frame-to-frame velocities.

    We use the next frame minus the current frame so the motion is measured as
    a displacement across time. A row is only kept when the two frames are
    consecutive, which keeps the values easy to interpret.
    """

    ordered = trajectories.sort_values(["nucleus_id", "frame"]).copy()
    group = ordered.groupby("nucleus_id", sort=False)

    ordered["previous_frame"] = group["frame"].shift(1)
    ordered["previous_x"] = group["x"].shift(1)
    ordered["previous_y"] = group["y"].shift(1)

    ordered["frame_gap"] = ordered["frame"] - ordered["previous_frame"]
    ordered["velocity_x"] = ordered["x"] - ordered["previous_x"]
    ordered["velocity_y"] = ordered["y"] - ordered["previous_y"]
    ordered["speed"] = np.sqrt(ordered["velocity_x"] ** 2 + ordered["velocity_y"] ** 2)

    velocities = ordered.loc[ordered["frame_gap"] == 1, [
        "nucleus_id",
        "previous_frame",
        "frame",
        "velocity_x",
        "velocity_y",
        "speed",
    ]].copy()

    velocities["nucleus_id"] = velocities["nucleus_id"].astype(int)
    velocities["previous_frame"] = velocities["previous_frame"].astype(int)
    velocities["frame"] = velocities["frame"].astype(int)
    velocities.sort_values(["frame", "nucleus_id"], inplace=True)

    return velocities.reset_index(drop=True)


def safe_pearsonr(series_a: pd.Series, series_b: pd.Series) -> float:
    """Compute Pearson correlation while handling short or constant series."""

    common = pd.concat([series_a, series_b], axis=1).dropna()
    if len(common) < 2:
        return float("nan")

    values_a = common.iloc[:, 0].to_numpy(dtype=float)
    values_b = common.iloc[:, 1].to_numpy(dtype=float)

    if np.isclose(values_a.std(ddof=0), 0.0) or np.isclose(values_b.std(ddof=0), 0.0):
        return float("nan")

    result = pearsonr(values_a, values_b)
    return float(result.statistic if hasattr(result, "statistic") else result[0])


def build_correlation_matrix(velocities: pd.DataFrame) -> pd.DataFrame:
    """Correlate each nucleus' speed profile with every other nucleus."""

    speed_table = velocities.pivot(index="frame", columns="nucleus_id", values="speed").sort_index()
    nucleus_ids = list(speed_table.columns)

    matrix = pd.DataFrame(np.nan, index=nucleus_ids, columns=nucleus_ids, dtype=float)

    for i, nucleus_a in enumerate(nucleus_ids):
        matrix.loc[nucleus_a, nucleus_a] = 1.0
        for nucleus_b in nucleus_ids[i + 1 :]:
            corr = safe_pearsonr(speed_table[nucleus_a], speed_table[nucleus_b])
            matrix.loc[nucleus_a, nucleus_b] = corr
            matrix.loc[nucleus_b, nucleus_a] = corr

    matrix.index.name = "nucleus_id"
    matrix.columns.name = "nucleus_id"
    return matrix


def summarize_pairs(correlation_matrix: pd.DataFrame) -> tuple[list[tuple[int, int, float]], list[tuple[int, int, float]], float]:
    """Return the strongest and weakest synchronized nucleus pairs."""

    pair_rows: list[tuple[int, int, float]] = []
    nucleus_ids = list(correlation_matrix.index)

    for i, nucleus_a in enumerate(nucleus_ids):
        for nucleus_b in nucleus_ids[i + 1 :]:
            corr = correlation_matrix.loc[nucleus_a, nucleus_b]
            if pd.isna(corr):
                continue
            pair_rows.append((int(nucleus_a), int(nucleus_b), float(corr)))

    if not pair_rows:
        return [], [], float("nan")

    pair_rows.sort(key=lambda item: item[2], reverse=True)
    top_pairs = pair_rows[:5]
    bottom_pairs = sorted(pair_rows, key=lambda item: item[2])[:5]

    correlations = np.array([item[2] for item in pair_rows], dtype=float)
    mean_score = float(np.nanmean(correlations))

    return top_pairs, bottom_pairs, mean_score


def detect_synchronization_events(velocities: pd.DataFrame) -> list[dict[str, float | int]]:
    """Find frames where most nuclei move in a similar direction.

    For Physarum, a synchronized movement event is a frame where the nuclei are
    not just moving, but moving in roughly the same direction at the same time.
    """

    events: list[dict[str, float | int]] = []

    for frame, frame_df in velocities.groupby("frame", sort=True):
        vectors = frame_df[["velocity_x", "velocity_y"]].to_numpy(dtype=float)
        speeds = frame_df["speed"].to_numpy(dtype=float)

        moving_mask = speeds > 1e-9
        if moving_mask.sum() < 2:
            continue

        moving_vectors = vectors[moving_mask]
        moving_speeds = speeds[moving_mask]

        dominant_direction = moving_vectors.sum(axis=0)
        dominant_norm = float(np.linalg.norm(dominant_direction))
        if np.isclose(dominant_norm, 0.0):
            continue

        dot_products = moving_vectors @ dominant_direction
        cosines = dot_products / (moving_speeds * dominant_norm)

        aligned_fraction = float((cosines >= ALIGNMENT_THRESHOLD).mean())
        mean_speed = float(moving_speeds.mean())

        if aligned_fraction >= MAJORITY_FRACTION:
            events.append(
                {
                    "frame": int(frame),
                    "aligned_fraction": round(aligned_fraction, 3),
                    "mean_speed": round(mean_speed, 3),
                    "aligned_nuclei": int((cosines >= ALIGNMENT_THRESHOLD).sum()),
                    "moving_nuclei": int(moving_mask.sum()),
                }
            )

    return events


def make_visualization(
    correlation_matrix: pd.DataFrame,
    velocities: pd.DataFrame,
    events: list[dict[str, float | int]],
) -> None:
    """Create a heatmap plus a time-series plot for the synchronization story."""

    speed_by_frame = velocities.groupby("frame", sort=True)["speed"].agg(["mean", "std", "count"]).reset_index()
    event_frames = [int(item["frame"]) for item in events]

    fig, (ax_heatmap, ax_speed) = plt.subplots(2, 1, figsize=(14, 12), gridspec_kw={"height_ratios": [3, 2]})

    heatmap = ax_heatmap.imshow(correlation_matrix.to_numpy(dtype=float), cmap="coolwarm", vmin=-1, vmax=1)
    ax_heatmap.set_title("Nucleus speed correlation matrix")
    ax_heatmap.set_xlabel("Nucleus ID")
    ax_heatmap.set_ylabel("Nucleus ID")

    tick_positions = np.arange(len(correlation_matrix.index))
    tick_labels = [str(int(nucleus_id)) for nucleus_id in correlation_matrix.index]
    ax_heatmap.set_xticks(tick_positions)
    ax_heatmap.set_xticklabels(tick_labels, rotation=90)
    ax_heatmap.set_yticks(tick_positions)
    ax_heatmap.set_yticklabels(tick_labels)
    fig.colorbar(heatmap, ax=ax_heatmap, fraction=0.046, pad=0.04, label="Pearson r")

    ax_speed.plot(speed_by_frame["frame"], speed_by_frame["mean"], color="navy", marker="o", linewidth=2, label="Average speed")
    ax_speed.fill_between(
        speed_by_frame["frame"],
        speed_by_frame["mean"] - speed_by_frame["std"].fillna(0.0),
        speed_by_frame["mean"] + speed_by_frame["std"].fillna(0.0),
        color="navy",
        alpha=0.15,
        label="Mean ± SD",
    )

    for idx, frame in enumerate(event_frames):
        label = "Synchronization event" if idx == 0 else None
        ax_speed.axvspan(frame - 0.45, frame + 0.45, color="tomato", alpha=0.18, label=label)
        event_speed = speed_by_frame.loc[speed_by_frame["frame"] == frame, "mean"]
        if not event_speed.empty:
            ax_speed.scatter([frame], [float(event_speed.iloc[0])], color="tomato", s=60, zorder=5)

    ax_speed.set_title("Average nucleus speed over time")
    ax_speed.set_xlabel("Frame")
    ax_speed.set_ylabel("Mean speed (pixels/frame)")
    ax_speed.legend(loc="best")
    ax_speed.grid(alpha=0.25)

    fig.suptitle("Physarum nucleus synchronization analysis", fontsize=15)
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(PLOT_PNG, dpi=180, bbox_inches="tight")
    plt.close(fig)


def build_report(
    trajectories: pd.DataFrame,
    velocities: pd.DataFrame,
    correlation_matrix: pd.DataFrame,
    top_pairs: list[tuple[int, int, float]],
    bottom_pairs: list[tuple[int, int, float]],
    mean_score: float,
    events: list[dict[str, float | int]],
) -> str:
    """Write a concise human-readable summary of the synchronization results."""

    lines: list[str] = []
    lines.append("Physarum nucleus synchronization report")
    lines.append("=" * 44)
    lines.append(f"Input trajectory rows: {len(trajectories)}")
    lines.append(f"Unique nuclei: {trajectories['nucleus_id'].nunique()}")
    lines.append(f"Frames observed: {trajectories['frame'].nunique()}")
    lines.append(f"Velocity rows analyzed: {len(velocities)}")
    lines.append("")
    lines.append("Interpretation")
    lines.append("--------------")
    lines.append(
        "A higher correlation means two nuclei speed up and slow down together more often, "
        "which is one sign of coordinated movement in the Physarum plasmodium."
    )
    lines.append("")
    lines.append(f"Mean pairwise synchronization score: {mean_score:.3f}")
    lines.append("")
    lines.append("Top 5 most synchronized pairs")
    lines.append("------------------------------")
    if top_pairs:
        for nucleus_a, nucleus_b, corr in top_pairs:
            lines.append(f"nuclei {nucleus_a:>2d} and {nucleus_b:>2d}: r = {corr:.3f}")
    else:
        lines.append("No valid pairwise correlations were available.")

    lines.append("")
    lines.append("Top 5 least synchronized pairs")
    lines.append("-------------------------------")
    if bottom_pairs:
        for nucleus_a, nucleus_b, corr in bottom_pairs:
            lines.append(f"nuclei {nucleus_a:>2d} and {nucleus_b:>2d}: r = {corr:.3f}")
    else:
        lines.append("No valid pairwise correlations were available.")

    lines.append("")
    lines.append("Synchronization events")
    lines.append("----------------------")
    if events:
        for event in events:
            lines.append(
                f"frame {event['frame']}: {event['aligned_nuclei']}/{event['moving_nuclei']} "
                f"nuclei aligned (fraction {event['aligned_fraction']:.3f}, mean speed {event['mean_speed']:.3f})"
            )
    else:
        lines.append("No frames met the majority-alignment threshold.")

    lines.append("")
    lines.append("Outputs")
    lines.append("-------")
    lines.append(f"Velocity table: {VELOCITY_CSV}")
    lines.append(f"Correlation matrix: {CORRELATION_CSV}")
    lines.append(f"Visualization: {PLOT_PNG}")

    return "\n".join(lines)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    trajectories = load_trajectories(INPUT_CSV)
    velocities = calculate_velocities(trajectories)
    correlation_matrix = build_correlation_matrix(velocities)
    top_pairs, bottom_pairs, mean_score = summarize_pairs(correlation_matrix)
    events = detect_synchronization_events(velocities)

    velocities.to_csv(VELOCITY_CSV, index=False)
    correlation_matrix.to_csv(CORRELATION_CSV)
    make_visualization(correlation_matrix, velocities, events)

    report_text = build_report(
        trajectories=trajectories,
        velocities=velocities,
        correlation_matrix=correlation_matrix,
        top_pairs=top_pairs,
        bottom_pairs=bottom_pairs,
        mean_score=mean_score,
        events=events,
    )
    REPORT_TXT.write_text(report_text + "\n", encoding="utf-8")

    print(report_text)


if __name__ == "__main__":
    main()