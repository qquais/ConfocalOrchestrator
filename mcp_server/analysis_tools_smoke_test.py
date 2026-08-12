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
# acquisition_tools_smoke_test.py's skip_if_unavailable. Only preprocess_frame
# / check_preprocessing_quality and (if reachable) segment_nuclei_image run
# genuinely end-to-end here, against a sample PNG under data/captures/.
#
# Run (from the repo root, with .venv activated):
#   python -m mcp_server.analysis_tools_smoke_test
# ------------------------------------------------------------

import sys
import traceback
from pathlib import Path

from mcp_server import analysis_tools as tools

REPO_ROOT = Path(__file__).resolve().parent.parent
CAPTURES_DIR = REPO_ROOT / "data" / "captures"
SAMPLE_ND2 = next(REPO_ROOT.glob("data/**/*.nd2"), None)
CTC_DATASET = REPO_ROOT / "data" / "datasets" / "Fluo-N2DH-SIM" / "Fluo-N2DH-SIM+" / "01"

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
    sample_image = next(CAPTURES_DIR.glob("*.png"), None)

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
    skip_if_unavailable(
        "compute_shape_metrics",
        lambda: tools.compute_shape_metrics(str(CAPTURES_DIR), "data/analysis/_smoketest_shape_metrics"),
        ImportError, ModuleNotFoundError, FileNotFoundError,
    )
    skip_if_unavailable(
        "track_nuclei_sequence",
        lambda: tools.track_nuclei_sequence(str(CAPTURES_DIR), "data/analysis/_smoketest_tracking"),
        RuntimeError, FileNotFoundError,
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
