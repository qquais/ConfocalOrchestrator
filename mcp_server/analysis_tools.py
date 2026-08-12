# analysis_tools.py
# ------------------------------------------------------------
# Tool implementations for the ConfocalOrchestrator MCP server's analysis
# tools. Each function below is registered as an MCP tool in server.py.
#
# These tools never touch microscope hardware - they read/write image
# files, CSVs, and plots under data/. No safety gate is required (compare
# acquisition_tools.py's _require_confirm_for_sdk), but several tools are
# compute/GPU heavy (Cellpose segmentation, trackpy linking) and can take
# from seconds to minutes depending on frame count and image size.
#
# The analysis/*.py scripts this module wraps (explore_nd2.py,
# convert_to_ometiff.py, extract_frames.py, preprocess_nd2.py,
# segment_nd2.py, cellects_pipeline.py / nd2_pipeline.py,
# fluorescence_pipeline.py) are flat top-level scripts with hardcoded
# paths, not importable functions - so their logic is reimplemented here
# as parameterized functions. analysis/compare_sequences.py and
# analysis/synchronization.py already expose clean functions, so those
# are imported and reused directly.
#
# Heavy third-party deps (nd2, tifffile, cv2, cellects, cellpose,
# trackpy, skimage, matplotlib) are imported lazily inside each function
# so the MCP server starts quickly and a missing optional dependency only
# breaks the tool that needs it.
#
# EXECUTION MODEL (decided, not just defaulted): every tool below runs
# synchronously and blocks until done, including segment_nuclei_image and
# track_nuclei_sequence (Cellpose, seconds-minutes on CPU/small GPU).
# No job/status-handle polling pattern is implemented. Reasoning: this
# server only runs over stdio for a single local client (see server.py) -
# there's no shared/remote transport or queue infra on the Fort Wayne node
# to poll against, so a job handle would add a second code path with
# nothing to poll it concurrently. Revisit this if/when tools are exposed
# over a shared transport (e.g. multiple concurrent callers, or a
# request that can legitimately run for the hours a full acquisition run
# takes - contrast with start_protocol_run in acquisition_tools.py, which
# already returns immediately because it launches a background process).
#
# VERIFIED vs EXPERIMENTAL (per docs/pipeline-overview.md's Status section
# and each wrapped module's own docstring - not re-verified here against
# real Physarum data as part of this change):
#   VERIFIED on real Physarum fluorescence nuclear data (denoise -> segment
#   -> track, end-to-end): preprocess_frame, segment_nuclei_image,
#   track_nuclei_sequence, and analyze_synchronization (operates on
#   track_nuclei_sequence's own output; analysis/synchronization.py's
#   docstring is written specifically in terms of Physarum nuclei).
#   Format/metadata-only, not data-dependent: inspect_nd2_metadata,
#   convert_nd2_to_ometiff, extract_nd2_frames.
#   EXPERIMENTAL - not confirmed against real Physarum data: compute_shape_metrics
#   (Cellects whole-organism shape path - pipeline-overview.md only confirms
#   the denoise/segment/track path, not this one) and
#   compare_trajectory_sequences (depends on whatever seq01/seq02 CSVs the
#   caller points it at).
#   EXPERIMENTAL by construction, real-data ground truth doesn't exist yet:
#   check_preprocessing_quality (reference-free metrics only, no labelled
#   ground truth - see its own top-of-function note) and compare_trackmate
#   (only the synthetic Fluo-N2DH-SIM+ Cell Tracking Challenge dataset has
#   the segmentation ground truth this needs; no such ground truth exists
#   for real Physarum data yet).
# ------------------------------------------------------------

import math
from pathlib import Path


# ── Read-only tools ──────────────────────────────────────────────────────


def inspect_nd2_metadata(nd2_path: str) -> dict:
    """Read and return a .ND2 file's metadata (dimensions, dtype, pixel
    size, channel names, experiment loops) without loading pixel data or
    writing anything.
    """
    import nd2

    with nd2.ND2File(nd2_path) as f:
        sizes = dict(f.sizes)
        dtype = str(f.dtype)
        try:
            voxel = f.voxel_size()
            pixel_size_um = {"x": voxel.x, "y": voxel.y, "z": voxel.z}
        except Exception:
            pixel_size_um = None
        meta = f.metadata
        channels = (
            [ch.channel.name for ch in meta.channels]
            if meta and getattr(meta, "channels", None)
            else []
        )
        experiment = (
            [{"type": str(loop.type), "count": loop.count} for loop in f.experiment]
            if f.experiment
            else []
        )

    return {
        "path": nd2_path,
        "dimensions": sizes,
        "dtype": dtype,
        "pixel_size_um": pixel_size_um,
        "channels": channels,
        "experiment": experiment,
    }


# ── Conversion / extraction tools ────────────────────────────────────────


def convert_nd2_to_ometiff(nd2_path: str, output_path: str = None) -> dict:
    """Convert a raw .ND2 file into a standard OME-TIFF file, embedding
    pixel size / channel / acquisition-date metadata as OME-XML.

    output_path: defaults to data/analysis/ometiff/<nd2 stem>.ome.tiff.
    """
    from datetime import datetime

    import nd2
    import tifffile

    nd2_path = Path(nd2_path)
    out_path = Path(output_path) if output_path else Path("data/analysis/ometiff") / (nd2_path.stem + ".ome.tiff")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with nd2.ND2File(nd2_path) as f:
        image = f.asarray()
        axes = "".join(f.sizes.keys())
        voxel = f.voxel_size()
        meta = f.metadata
        channel_names = (
            [ch.channel.name for ch in meta.channels] if meta and meta.channels else ["Channel0"]
        )
        date_str = " ".join(f.text_info.get("date", "").split())
        try:
            acquisition_date = datetime.strptime(date_str, "%m/%d/%Y %I:%M:%S %p")
        except ValueError:
            acquisition_date = None

    is_rgb = "S" in axes and image.shape[axes.index("S")] == 3
    photometric = "rgb" if is_rgb else "minisblack"

    ome_metadata = {
        "axes": axes,
        "PhysicalSizeX": voxel.x,
        "PhysicalSizeXUnit": "um",
        "PhysicalSizeY": voxel.y,
        "PhysicalSizeYUnit": "um",
    }
    if "Z" in axes:
        ome_metadata["PhysicalSizeZ"] = voxel.z
        ome_metadata["PhysicalSizeZUnit"] = "um"
    if "C" in axes:
        ome_metadata["Channel"] = {"Name": channel_names}
    if acquisition_date is not None:
        ome_metadata["AcquisitionDate"] = acquisition_date.isoformat()

    tifffile.imwrite(out_path, image, photometric=photometric, metadata=ome_metadata)

    return {
        "output_path": str(out_path),
        "shape": list(image.shape),
        "axes": axes,
        "photometric": photometric,
        "channels": channel_names,
        "pixel_size_um": {"x": voxel.x, "y": voxel.y, "z": voxel.z},
    }


def extract_nd2_frames(nd2_path: str, output_dir: str = "data/frames") -> dict:
    """Extract every frame from a .ND2 file (single image, time-lapse, or
    Z-stack) and save each as a contrast-stretched PNG.
    """
    import nd2
    import numpy as np
    from PIL import Image

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with nd2.ND2File(nd2_path) as f:
        images = f.asarray()

    is_rgb = images.shape[-1] == 3 and images.ndim == 3
    is_single_2d = images.ndim == 2
    frames = [images] if (is_rgb or is_single_2d) else [images[i] for i in range(images.shape[0])]

    saved_paths = []
    for i, frame in enumerate(frames):
        frame = frame.astype(np.float32)
        lo, hi = frame.min(), frame.max()
        if hi > lo:
            frame = (frame - lo) / (hi - lo) * 255
        frame = np.clip(frame, 0, 255).astype(np.uint8)
        filename = out_dir / f"img{i + 1:03d}.png"
        Image.fromarray(frame).save(filename)
        saved_paths.append(str(filename))

    return {"frame_count": len(saved_paths), "output_paths": saved_paths}


# ── Preprocessing / segmentation tools ───────────────────────────────────


def preprocess_frame(
    image_path: str,
    output_dir: str = "data/analysis/preprocessing",
    gaussian_sigma: float = 0.5,
    background_sigma: float = 400.0,
    median_disk_radius: int = 2,
) -> dict:
    """Clean up a raw grayscale frame before segmentation/tracking: Gaussian
    denoising, then illumination (background) correction, then median
    despeckling. Writes a side-by-side BEFORE/AFTER PNG and an AFTER-only
    PNG (ready for segment_nuclei_image).

    background_sigma must be bigger than the largest clusters of features
    in the image, or the background estimate will cancel out real contrast
    instead of just fixing uneven lighting (see analysis/preprocess_nd2.py).
    """
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    from skimage.color import rgb2gray
    from skimage.filters import gaussian, median
    from skimage.morphology import disk

    image_path = Path(image_path)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    comparison_path = out_dir / f"{image_path.stem}_preprocessed.png"
    after_only_path = out_dir / f"{image_path.stem}_after.png"

    original_rgb = np.array(Image.open(image_path).convert("RGB"))
    gray = rgb2gray(original_rgb)

    denoised = gaussian(gray, sigma=gaussian_sigma)
    background = gaussian(denoised, sigma=background_sigma)
    corrected = np.clip(denoised / (background + 1e-6) * background.mean(), 0, 1)
    final = median(corrected, disk(median_disk_radius))

    before_img = Image.fromarray((gray * 255).astype(np.uint8)).convert("RGB")
    after_img = Image.fromarray((final * 255).astype(np.uint8)).convert("RGB")

    comparison = Image.new("RGB", (before_img.width * 2, before_img.height))
    comparison.paste(before_img, (0, 0))
    comparison.paste(after_img, (before_img.width, 0))
    draw = ImageDraw.Draw(comparison)
    font = ImageFont.load_default(size=80)
    draw.text((30, 30), "BEFORE", fill=(255, 0, 0), font=font)
    draw.text((before_img.width + 30, 30), "AFTER", fill=(255, 0, 0), font=font)
    comparison.save(comparison_path)
    after_img.save(after_only_path)

    return {
        "comparison_path": str(comparison_path),
        "preprocessed_path": str(after_only_path),
        "image_size": [gray.shape[1], gray.shape[0]],
    }


def segment_nuclei_image(
    image_path: str,
    output_path: str = None,
    diameter: float = None,
    scale: float = 0.25,
    use_gpu: bool = None,
) -> dict:
    """Run Cellpose's nuclei model on a single image and save the original
    image with detected-nucleus outlines drawn in green.

    scale: resize factor applied before segmentation (0.25 = 25%, faster on
    CPU). diameter: expected nucleus diameter in pixels after resizing, or
    None to auto-detect. use_gpu: None resolves via CELLPOSE_GPU / CUDA
    availability (see analysis/cellpose_runtime.py).
    """
    import numpy as np
    from PIL import Image
    from cellpose import models, utils

    from analysis.cellpose_runtime import resolve_cellpose_gpu_mode

    image_path = Path(image_path)
    out_path = (
        Path(output_path)
        if output_path
        else Path("data/analysis/nd2_sample") / f"{image_path.stem}_segmented.png"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    pil_img = Image.open(image_path).convert("RGB")
    if scale != 1.0:
        pil_img = pil_img.resize(
            (int(pil_img.width * scale), int(pil_img.height * scale)), Image.LANCZOS
        )
    img = np.array(pil_img)

    if use_gpu is None:
        use_gpu = resolve_cellpose_gpu_mode()
    model = models.CellposeModel(model_type="nuclei", gpu=use_gpu)
    masks = model.eval(img, diameter=diameter, channels=[0, 0])[0]
    n_nuclei = int(masks.max())

    outlines = utils.masks_to_outlines(masks)
    result = img.copy()
    result[outlines] = [0, 255, 0]
    Image.fromarray(result).save(out_path)

    return {
        "nuclei_count": n_nuclei,
        "output_path": str(out_path),
        "image_size": [img.shape[1], img.shape[0]],
        "gpu_used": use_gpu,
    }


def check_preprocessing_quality(
    comparison_image: str = "data/analysis/preprocessing/frame_0_preprocessed.png",
    output_dir: str = "data/analysis/validation",
    uniformity_grid: int = 4,
) -> dict:
    """Score a preprocess_frame BEFORE/AFTER comparison image on four
    reference-free quality metrics (background noise, foreground/background
    contrast, contrast-to-noise ratio, illumination uniformity) and report
    whether preprocessing improved or worsened each one.

    EXPERIMENTAL / groundwork: there's no hand-labelled ground truth yet, so
    this can't say preprocessing improved segmentation accuracy - only that
    it changed these four numbers in the expected direction. See
    validation/check_preprocessing_quality.py (the script this reimplements
    as a parameterized function) for the full metric rationale.

    comparison_image: the side-by-side PNG written by preprocess_frame
    (its "comparison_path" return value) - loaded and split back into the
    original BEFORE/AFTER halves rather than re-running preprocessing.
    Writes a metrics-report CSV and a red-overlay PNG showing which pixels
    the Otsu foreground mask picked - open it to sanity-check the mask
    actually lines up with real nuclei before trusting the numbers.
    """
    import numpy as np
    import pandas as pd
    from PIL import Image
    from skimage.color import rgb2gray
    from skimage.filters import threshold_otsu

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_csv = out_dir / "preprocessing_quality_report.csv"
    mask_overlay_path = out_dir / "otsu_mask_overlay.png"

    comparison = np.array(Image.open(comparison_image).convert("RGB"))
    half_width = comparison.shape[1] // 2
    before_rgb = comparison[:, :half_width]
    after_rgb = comparison[:, half_width:]
    before = rgb2gray(before_rgb)
    after = rgb2gray(after_rgb)

    # Mask computed once from the ORIGINAL image and reused on both, so the
    # comparison always measures the same physical regions before vs after.
    threshold = threshold_otsu(before)
    foreground_mask = before < threshold
    background_mask = ~foreground_mask

    def _metrics(gray_image):
        fg_mean = gray_image[foreground_mask].mean()
        bg_mean = gray_image[background_mask].mean()
        bg_noise = gray_image[background_mask].std()
        contrast = abs(bg_mean - fg_mean)
        cnr = contrast / (bg_noise + 1e-8)
        return bg_noise, contrast, cnr

    def _uniformity(gray_image):
        tile_h = gray_image.shape[0] // uniformity_grid
        tile_w = gray_image.shape[1] // uniformity_grid
        tile_means = []
        for row in range(uniformity_grid):
            for col in range(uniformity_grid):
                y0, y1 = row * tile_h, (row + 1) * tile_h
                x0, x1 = col * tile_w, (col + 1) * tile_w
                tile_bg_mask = background_mask[y0:y1, x0:x1]
                if tile_bg_mask.sum() < 50:
                    continue
                tile_means.append(gray_image[y0:y1, x0:x1][tile_bg_mask].mean())
        return float(np.std(tile_means))

    before_noise, before_contrast, before_cnr = _metrics(before)
    after_noise, after_contrast, after_cnr = _metrics(after)
    before_uniformity = _uniformity(before)
    after_uniformity = _uniformity(after)

    def _verdict(before_value, after_value, lower_is_better):
        improved = (after_value < before_value) if lower_is_better else (after_value > before_value)
        return "IMPROVED" if improved else "WORSE"

    rows = [
        {
            "metric": "Background noise (std dev)", "before": before_noise, "after": after_noise,
            "verdict": _verdict(before_noise, after_noise, lower_is_better=True),
        },
        {
            "metric": "Foreground/background contrast", "before": before_contrast, "after": after_contrast,
            "verdict": _verdict(before_contrast, after_contrast, lower_is_better=False),
        },
        {
            "metric": "Contrast-to-noise ratio (CNR)", "before": before_cnr, "after": after_cnr,
            "verdict": _verdict(before_cnr, after_cnr, lower_is_better=False),
        },
        {
            "metric": "Illumination non-uniformity", "before": before_uniformity, "after": after_uniformity,
            "verdict": _verdict(before_uniformity, after_uniformity, lower_is_better=True),
        },
    ]
    pd.DataFrame(rows).to_csv(report_csv, index=False)

    overlay = before_rgb.copy()
    overlay[foreground_mask] = [255, 0, 0]
    Image.fromarray(overlay).save(mask_overlay_path)

    return {
        "report_csv": str(report_csv),
        "mask_overlay_path": str(mask_overlay_path),
        "metrics": rows,
    }


# ── Shape-metrics / tracking pipelines ───────────────────────────────────


def compute_shape_metrics(frames_dir: str, output_dir: str, file_pattern: str = None) -> dict:
    """Segment every frame in a folder (Cellects) and compute per-frame
    shape metrics over time: area, perimeter, circularity, eccentricity,
    major/minor axis length, solidity. Writes a CSV and (for >1 frame) a
    3-panel growth-curve PNG.

    file_pattern: glob pattern for frame files (e.g. "*.tif"). None matches
    both "*.tif" and "*.png". Frames are ordered by the trailing number in
    each filename.
    """
    import re

    import cv2
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    from cellects.image.one_image_analysis import OneImageAnalysis
    from cellects.image.shape_descriptors import ShapeDescriptors

    wanted_metrics = [
        "area", "perimeter", "circularity",
        "eccentricity", "major_axis_len", "minor_axis_len", "solidity",
    ]

    frames_dir = Path(frames_dir)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_out = out_dir / "growth_over_time.csv"
    plot_out = out_dir / "growth_curve.png"

    def _frame_number(path):
        match = re.search(r"(\d+)", path.stem)
        return int(match.group(1)) if match else 0

    patterns = [file_pattern] if file_pattern else ["*.tif", "*.png"]
    frame_files = sorted(
        {p for pattern in patterns for p in frames_dir.glob(pattern)}, key=_frame_number
    )
    if not frame_files:
        raise FileNotFoundError(f"No frames matching {patterns} found in {frames_dir}")

    csc_dict = {"bgr": np.array([1, 1, 1], dtype=np.int8)}
    records = []
    for frame_idx, frame_path in enumerate(frame_files, start=1):
        img = cv2.imread(str(frame_path))
        if img is None:
            continue
        analysis = OneImageAnalysis(img, shape_number=1)
        analysis.convert_and_segment(c_space_dict=csc_dict, color_number=2)
        mask = analysis.binary_image
        sd = ShapeDescriptors(mask, wanted_metrics)
        records.append({
            "frame": frame_idx,
            "timepoint": frame_idx,
            "area_px": int(sd.descriptors.get("area", mask.sum())),
            "perimeter_px": round(float(sd.descriptors.get("perimeter", 0)), 2),
            "circularity": round(float(sd.descriptors.get("circularity", 0)), 4),
            "eccentricity": round(float(sd.descriptors.get("eccentricity", 0)), 4),
            "major_axis_px": round(float(sd.descriptors.get("major_axis_len", 0)), 2),
            "minor_axis_px": round(float(sd.descriptors.get("minor_axis_len", 0)), 2),
            "solidity": round(float(sd.descriptors.get("solidity", 0)), 4),
        })

    df = pd.DataFrame(records)
    df.to_csv(csv_out, index=False)

    plot_path = None
    if len(df) > 1:
        fig, axes = plt.subplots(3, 1, figsize=(10, 10), sharex=True)
        fig.suptitle("Shape Metrics Over Time", fontsize=14)
        panels = [
            ("area_px", "Area (pixels)", "steelblue"),
            ("circularity", "Circularity", "darkorange"),
            ("eccentricity", "Eccentricity", "mediumseagreen"),
        ]
        for ax, (col, ylabel, color) in zip(axes, panels):
            ax.plot(df["timepoint"], df[col], marker="o", linewidth=2, color=color, markersize=4)
            ax.fill_between(df["timepoint"], df[col], alpha=0.12, color=color)
            ax.set_ylabel(ylabel, fontsize=11)
            ax.grid(True, linestyle="--", alpha=0.4)
        axes[-1].set_xlabel("Timepoint (frame number)", fontsize=11)
        plt.tight_layout()
        plt.savefig(plot_out, dpi=150)
        plt.close()
        plot_path = str(plot_out)

    return {
        "frame_count": len(records),
        "csv_path": str(csv_out),
        "plot_path": plot_path,
        "records": records,
    }


def track_nuclei_sequence(
    frames_dir: str,
    output_dir: str,
    n_frames: int = 10,
    frame_glob: str = "t*.tif",
    diameter: float = None,
    search_range: int = None,
    memory: int = 2,
    min_frames: int = 3,
    use_gpu: bool = None,
) -> dict:
    """Detect nuclei in each of the first `n_frames` frames (Cellpose) and
    link them into trajectories across time (trackpy). Writes a trajectory
    CSV (nucleus_id, frame, x, y, area) and an overlay visualization PNG.

    search_range: max pixel displacement allowed between frames for the
    same nucleus; None auto-estimates it from frame 0's median nucleus
    diameter. memory: max frames a nucleus can be missed and still be
    re-linked. min_frames: trajectories shorter than this are dropped.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    import tifffile
    import trackpy as tp
    from cellpose import models
    from skimage.measure import regionprops

    from analysis.cellpose_runtime import resolve_cellpose_gpu_mode

    frames_dir = Path(frames_dir)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    traj_csv = out_dir / "trajectories.csv"
    viz_image = out_dir / "trajectories_visual.png"

    frame_paths = sorted(frames_dir.glob(frame_glob))[:n_frames]
    if len(frame_paths) < n_frames:
        raise RuntimeError(
            f"Expected at least {n_frames} frames matching '{frame_glob}' in {frames_dir}, "
            f"found {len(frame_paths)}."
        )
    frames = [tifffile.imread(path) for path in frame_paths]

    if use_gpu is None:
        use_gpu = resolve_cellpose_gpu_mode()
    model = models.CellposeModel(gpu=use_gpu)

    all_masks = [model.eval(frame, channels=[0, 0], diameter=diameter)[0] for frame in frames]

    rows = []
    for frame_index, masks in enumerate(all_masks):
        for region in regionprops(masks):
            cy, cx = region.centroid
            rows.append({"frame": frame_index, "x": cx, "y": cy, "area": region.area})
    detections = pd.DataFrame(rows)

    if search_range is None:
        if detections.empty:
            search_range = 15
        else:
            diam_est = np.sqrt(detections.loc[detections["frame"] == 0, "area"].median() / np.pi) * 2
            search_range = max(15, int(diam_est * 2))

    if detections.empty:
        trajectories = pd.DataFrame(columns=["frame", "x", "y", "area", "particle"])
        n_raw = n_kept = 0
    else:
        trajectories = tp.link(
            detections, search_range=search_range, memory=memory,
            adaptive_stop=0.1, adaptive_step=0.95,
        )
        n_raw = trajectories["particle"].nunique()
        trajectories = tp.filter_stubs(trajectories, threshold=min_frames)
        n_kept = trajectories["particle"].nunique()

    output = (
        trajectories.reset_index(drop=True)[["particle", "frame", "x", "y", "area"]]
        .rename(columns={"particle": "nucleus_id"})
        .sort_values(["nucleus_id", "frame"])
        .reset_index(drop=True)
    )
    output.to_csv(traj_csv, index=False)

    fig, ax = plt.subplots(figsize=(16, 12))
    ax.imshow(frames[0], cmap="gray")
    unique_ids = output["nucleus_id"].unique() if not output.empty else []
    color_map = plt.cm.rainbow(np.linspace(0, 1, len(unique_ids))) if len(unique_ids) else []
    for nucleus_id, color in zip(unique_ids, color_map):
        traj = output[output["nucleus_id"] == nucleus_id].sort_values("frame")
        ax.plot(traj["x"], traj["y"], color=color, linewidth=3.0, alpha=0.95)
    ax.set_title(f"{len(unique_ids)} Nuclei Tracked Across {len(frames)} Frames", fontsize=18, weight="bold")
    ax.set_xlabel("x (pixels)")
    ax.set_ylabel("y (pixels)")
    ax.set_facecolor("black")
    plt.tight_layout()
    plt.savefig(viz_image, dpi=150)
    plt.close()

    avg_len = 0.0 if output.empty else float(output.groupby("nucleus_id").size().mean())

    return {
        "frames_processed": len(frames),
        "total_detections": len(detections),
        "raw_trajectories": int(n_raw),
        "trajectories_kept": int(n_kept),
        "avg_track_length_frames": round(avg_len, 2),
        "search_range_px": search_range,
        "trajectories_csv": str(traj_csv),
        "visualization_path": str(viz_image),
    }


# ── Cross-sequence analysis tools ────────────────────────────────────────


def analyze_synchronization(trajectories_csv: str = None) -> dict:
    """Analyze whether nuclei in a trajectory CSV move in a synchronized
    way (correlated speed profiles, majority-aligned movement events).
    Wraps analysis/synchronization.py's functions - output CSVs, the
    report, and the plot are written to data/analysis/synchronization/
    (paths fixed by that module).

    trajectories_csv: path to a CSV with nucleus_id, frame, x, y, area
    columns (the format produced by track_nuclei_sequence). Defaults to
    analysis/synchronization.py's own default input path if omitted.
    """
    from analysis import synchronization as sync

    csv_path = Path(trajectories_csv) if trajectories_csv else sync.INPUT_CSV
    sync.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    trajectories = sync.load_trajectories(csv_path)
    velocities = sync.calculate_velocities(trajectories)
    correlation_matrix = sync.build_correlation_matrix(velocities)
    top_pairs, _bottom_pairs, mean_score = sync.summarize_pairs(correlation_matrix)
    events = sync.detect_synchronization_events(velocities)

    velocities.to_csv(sync.VELOCITY_CSV, index=False)
    correlation_matrix.to_csv(sync.CORRELATION_CSV)
    sync.make_visualization(correlation_matrix, velocities, events)

    report_text = sync.build_report(
        trajectories=trajectories,
        velocities=velocities,
        correlation_matrix=correlation_matrix,
        top_pairs=top_pairs,
        bottom_pairs=_bottom_pairs,
        mean_score=mean_score,
        events=events,
    )
    sync.REPORT_TXT.write_text(report_text + "\n", encoding="utf-8")

    return {
        "input_csv": str(csv_path),
        "unique_nuclei": int(trajectories["nucleus_id"].nunique()),
        "frames_observed": int(trajectories["frame"].nunique()),
        "mean_synchronization_score": None if math.isnan(mean_score) else round(mean_score, 3),
        "synchronization_events": len(events),
        "top_synchronized_pairs": [
            {"nucleus_a": a, "nucleus_b": b, "correlation": round(r, 3)} for a, b, r in top_pairs
        ],
        "velocity_csv": str(sync.VELOCITY_CSV),
        "correlation_matrix_csv": str(sync.CORRELATION_CSV),
        "report_path": str(sync.REPORT_TXT),
        "plot_path": str(sync.PLOT_PNG),
    }


def compare_trajectory_sequences(
    seq01_csv: str = None, seq02_csv: str = None, output_csv: str = None
) -> dict:
    """Compare two trajectory CSVs (e.g. two tracked sequences) on average
    nuclei per frame, trajectory count, average track length, and average
    nucleus area. Wraps analysis/compare_sequences.py.

    Any of the three paths left as None falls back to
    analysis/compare_sequences.py's own defaults.
    """
    import pandas as pd

    from analysis import compare_sequences as compare

    seq01_path = Path(seq01_csv) if seq01_csv else compare.resolve_seq01_path()
    seq02_path = Path(seq02_csv) if seq02_csv else compare.SEQ02_CSV
    out_path = Path(output_csv) if output_csv else compare.OUTPUT_CSV

    seq01_summary = compare.summarize_results(compare.load_results(seq01_path))
    seq02_summary = compare.summarize_results(compare.load_results(seq02_path))

    comparison = pd.DataFrame([
        {"sequence": "seq01", **seq01_summary},
        {"sequence": "seq02", **seq02_summary},
    ])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    comparison.to_csv(out_path, index=False)

    return {
        "seq01": {"path": str(seq01_path), **seq01_summary},
        "seq02": {"path": str(seq02_path), **seq02_summary},
        "output_csv": str(out_path),
    }


def compare_trackmate(pipeline_csv: str = None) -> dict:
    """Score a trajectory CSV (track_nuclei_sequence's output format)
    against Cell Tracking Challenge ground-truth segmentation masks -
    per-frame and overall precision/recall/F1/detection-accuracy. Wraps
    validation/compare_trackmate.py and reuses its main() as-is (rather than
    reimplementing its plotting logic here), so results and output paths
    match running that script directly.

    EXPERIMENTAL: the only ground truth wired up is the synthetic
    Fluo-N2DH-SIM+ Cell Tracking Challenge dataset (validation/compare_trackmate.py's
    fixed GT_SEG_DIR/GT_TRACK_DIR) - no TrackMate/CTC-style ground truth
    exists yet for real Physarum data, so this cannot currently score a
    real-data tracking run, only a run against that CTC sequence.

    pipeline_csv: path to a trajectories CSV (nucleus_id, frame, x, y, area).
    Defaults to validation/compare_trackmate.py's own PIPELINE_CSV constant.
    Writes a per-frame + overall summary CSV and a detection-accuracy
    visualization PNG to validation/results/ (paths fixed by that module).
    """
    import pandas as pd

    from validation import compare_trackmate as ctm

    original_pipeline_csv = ctm.PIPELINE_CSV
    if pipeline_csv:
        ctm.PIPELINE_CSV = Path(pipeline_csv)
    try:
        ctm.main()
    finally:
        ctm.PIPELINE_CSV = original_pipeline_csv

    summary = pd.read_csv(ctm.SUMMARY_CSV)
    overall = summary[summary["frame"] == "overall"].iloc[0].to_dict()

    return {
        "pipeline_csv": str(pipeline_csv or original_pipeline_csv),
        "frames_compared": len(summary) - 1,
        "overall": overall,
        "summary_csv": str(ctm.SUMMARY_CSV),
        "visualization_path": str(ctm.VIZ_IMAGE),
    }
