# analysis_tools_smoke_test.py
# ------------------------------------------------------------
# Manual smoke test for every MCP tool registered in server.py's
# analysis-tools section. No microscope/hardware involved - these tools
# only touch files under data/ - but most need real inputs (an .ND2 file,
# a Cell Tracking Challenge dataset, a multi-frame TIFF sequence) that
# aren't checked into the repo (data/ is gitignored) and aren't present on
# every dev machine.
#
# Tools with no usable input available on THIS machine, or whose optional
# dependency (e.g. cellects) isn't installed, are exercised for a sane
# error (not a crash) and SKIPPED (not FAILed) - same convention as
# acquisition_tools_smoke_test.py's skip_if_unavailable.
#
# Sample data discovery (updated 2026-08-12 after finding data/captures/
# never actually existed on the machine used for real-data verification,
# which silently skipped preprocess_frame/segment_nuclei_image/
# track_nuclei_sequence every run instead of exercising them for real):
#   - single-frame tools (preprocess_frame, check_preprocessing_quality,
#     segment_nuclei_image) fall back to data/captures/*.png if present,
#     else the first PNG under data/frames/ (extract_nd2_frames' own
#     output from the read-only-tools section above, so this is
#     self-sufficient - no separate prep step needed).
#   - multi-frame tools (track_nuclei_sequence, compute_shape_metrics) look
#     for data/captures/t*.tif first, else any t*.tif sequence already
#     under data/frames/**/ (e.g. a real per-channel extraction someone
#     prepared by hand - nd2's own frame layout doesn't support pulling a
#     single real channel's time series directly, so this can't be fully
#     automated here; see extract_nd2_frames' docstring for why). If
#     neither exists, these SKIP with a message explaining how to prepare
#     one rather than just "no data found".
#
# Run (from the repo root, with .venv activated):
#   python -m mcp_server.analysis_tools_smoke_test
# ------------------------------------------------------------

import sys
import traceback
from pathlib import Path
from typing import Optional

from mcp_server import analysis_tools as tools

REPO_ROOT = Path(__file__).resolve().parent.parent
CAPTURES_DIR = REPO_ROOT / "data" / "captures"
SAMPLE_ND2 = next(REPO_ROOT.glob("data/**/*.nd2"), None)
CTC_DATASET = REPO_ROOT / "data" / "datasets" / "Fluo-N2DH-SIM" / "Fluo-N2DH-SIM+" / "01"


def _find_sample_image() -> Optional[Path]:
    """A single real (or placeholder) frame for the single-frame tools."""
    found = next(CAPTURES_DIR.glob("*.png"), None)
    if found:
        return found
    return next((REPO_ROOT / "data" / "frames").glob("*.png"), None) if (REPO_ROOT / "data" / "frames").exists() else None


def _find_frame_sequence_dir() -> Optional[Path]:
    """A folder of real (or placeholder) t*.tif frames for the multi-frame tools."""
    if next(CAPTURES_DIR.glob("t*.tif"), None):
        return CAPTURES_DIR
    frames_root = REPO_ROOT / "data" / "frames"
    if not frames_root.exists():
        return None
    for candidate_tif in frames_root.glob("**/t*.tif"):
        return candidate_tif.parent
    return None

results = {"pass": 0, "fail": 0, "skip": 0}


def check(name: str, fn) -> None:
    """Run fn(); PASS if it returns without raising."""
    try:
        value = fn()
        print(f"  PASS  {name}  -> {value!r}")
        results["pass"] += 1
    except Exception as e:
        print(f"  FAIL  {name}  -> {type(e).__name__}: {e}")
        traceback.print_exc()
        results["fail"] += 1


def skip_if_unavailable(name: str, fn, *expected_exc_types: type) -> None:
    """Run fn(); PASS if it succeeds, SKIP if it raises one of
    expected_exc_types (missing sample data / optional dependency - the
    correct outcome on a dev machine without that data/package), FAIL on
    anything else.
    """
    try:
        value = fn()
        print(f"  PASS  {name}  -> {value!r}")
        results["pass"] += 1
    except expected_exc_types as e:
        print(f"  SKIP  {name}  -> {type(e).__name__}: {e}")
        results["skip"] += 1
    except Exception as e:
        print(f"  FAIL  {name}  -> {type(e).__name__}: {e}")
        traceback.print_exc()
        results["fail"] += 1


def skip(name: str, reason: str) -> None:
    print(f"  SKIP  {name}  -> {reason}")
    results["skip"] += 1


def main() -> int:
    sample_image = _find_sample_image()
    frame_sequence_dir = _find_frame_sequence_dir()

    print("── Read-only / conversion tools (need a real .ND2 file) ─────")
    if SAMPLE_ND2:
        check("inspect_nd2_metadata", lambda: tools.inspect_nd2_metadata(str(SAMPLE_ND2)))
        check("convert_nd2_to_ometiff", lambda: tools.convert_nd2_to_ometiff(str(SAMPLE_ND2)))
        check("extract_nd2_frames", lambda: tools.extract_nd2_frames(str(SAMPLE_ND2)))
    else:
        for name in ("inspect_nd2_metadata", "convert_nd2_to_ometiff", "extract_nd2_frames"):
            skip(name, f"no .nd2 file found under {REPO_ROOT / 'data'}")

    comparison_path = None
    print("\n── Preprocessing / segmentation (real run on a sample PNG) ──")
    if sample_image:
        def _preprocess():
            nonlocal comparison_path
            result = tools.preprocess_frame(str(sample_image))
            comparison_path = result["comparison_path"]
            return result
        check("preprocess_frame", _preprocess)

        if comparison_path:
            check(
                "check_preprocessing_quality",
                lambda: tools.check_preprocessing_quality(comparison_path),
            )
        else:
            skip("check_preprocessing_quality", "preprocess_frame did not produce a comparison image")

        # Cellpose downloads its model weights on first use - skip cleanly
        # if that fails (e.g. no network access) rather than failing the run.
        skip_if_unavailable(
            "segment_nuclei_image",
            lambda: tools.segment_nuclei_image(str(sample_image)),
            Exception,
        )
    else:
        for name in ("preprocess_frame", "check_preprocessing_quality", "segment_nuclei_image"):
            skip(name, f"no sample PNG found under {CAPTURES_DIR}")

    print("\n── Shape-metrics / tracking pipelines (need cellects / a frame sequence) ─")
    if frame_sequence_dir:
        skip_if_unavailable(
            "compute_shape_metrics",
            lambda: tools.compute_shape_metrics(str(frame_sequence_dir), "data/analysis/_smoketest_shape_metrics"),
            ImportError, ModuleNotFoundError, FileNotFoundError,
        )
        # A real per-timepoint sequence can be dozens-to-hundreds of frames (a real
        # 217-frame run took ~3.5 minutes on this node's GPU) - cap what the smoke
        # test itself exercises so a routine run stays fast; run the tool directly
        # with a larger n_frames for a real full-sequence check (see this module's
        # docstring / analysis_tools.py's VERIFIED block for that result).
        skip_if_unavailable(
            "track_nuclei_sequence",
            lambda: tools.track_nuclei_sequence(str(frame_sequence_dir), "data/analysis/_smoketest_tracking", n_frames=10),
            RuntimeError, FileNotFoundError,
        )
    else:
        for name in ("compute_shape_metrics", "track_nuclei_sequence"):
            skip(
                name,
                f"no t*.tif sequence found under {CAPTURES_DIR} or data/frames/**/ - "
                "extract_nd2_frames doesn't produce this format/naming directly (it "
                "flattens all axes into contrast-stretched img*.png, not a "
                "single-channel raw t*.tif time series); prepare one by hand from a "
                "real multi-channel .nd2 file, e.g.: read each timepoint's chosen "
                "channel via nd2.ND2File(...).asarray()[:, channel_index] and "
                "tifffile.imwrite each as t000.tif, t001.tif, ... into a folder "
                "under data/frames/",
            )

    print("\n── Cross-sequence analysis (need prior pipeline outputs) ────")
    skip_if_unavailable("analyze_synchronization", tools.analyze_synchronization, FileNotFoundError)
    skip_if_unavailable("compare_trajectory_sequences", tools.compare_trajectory_sequences, FileNotFoundError)

    print("\n── Validation (compare_trackmate needs the CTC dataset) ─────")
    if CTC_DATASET.exists():
        skip_if_unavailable("compare_trackmate", tools.compare_trackmate, FileNotFoundError, RuntimeError)
    else:
        skip("compare_trackmate", f"no Cell Tracking Challenge dataset found under {CTC_DATASET}")

    print(f"\n{'=' * 60}\n{results['pass']} passed, {results['fail']} failed, {results['skip']} skipped\n{'=' * 60}")
    return 1 if results["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
