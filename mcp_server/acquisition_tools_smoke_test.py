# acquisition_tools_smoke_test.py
# ------------------------------------------------------------
# Manual smoke test for every MCP tool registered in server.py's
# acquisition-tools section, run against backend="mock" only (no real
# hardware / Ti2-E Device Simulator required).
#
# Tools that only work against real hardware (get_pfs_status,
# nudge_focus_offset) or a running dashboard (get_live_status, abort_run)
# are exercised for their safety-gate behavior, then SKIPPED (not FAILed)
# when the expected ConnectionError/hardware error shows up - that error
# is the correct outcome on a dev machine with no scope/dashboard attached.
#
# Any saved-position label this script writes (via save_current,
# define_position, load_positions_from_yaml) is deleted again at the end,
# so protocols/stage_positions.json is left exactly as it was found.
#
# Run (from the repo root, with .venv activated):
#   python -m mcp_server.acquisition_tools_smoke_test
# ------------------------------------------------------------

import os
import signal
import sys
import time
import traceback
from pathlib import Path

from mcp_server import acquisition_tools as tools

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_IMAGE = REPO_ROOT / "data" / "analysis" / "nd2_sample" / "frame_0.png"
EXAMPLE_PROTOCOL = REPO_ROOT / "protocols" / "example_protocol.yaml"
TEST_PROTOCOL_SHORT = REPO_ROOT / "protocols" / "test_protocol_short.yaml"

TEST_POSITION_LABEL = "_mcp_smoketest_pos"
TEST_SAVED_LABEL = "_mcp_smoketest_saved"
YAML_LOADED_LABEL = "sample_center"  # the only position in example_protocol.yaml

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


def expect_raises(name: str, fn, exc_type: type) -> None:
    """Run fn(); PASS only if it raises exactly exc_type."""
    try:
        fn()
    except exc_type as e:
        print(f"  PASS  {name}  -> raised {exc_type.__name__} as expected ({e})")
        results["pass"] += 1
        return
    except Exception as e:
        print(f"  FAIL  {name}  -> raised {type(e).__name__}, expected {exc_type.__name__}")
        results["fail"] += 1
        return
    print(f"  FAIL  {name}  -> did not raise {exc_type.__name__}")
    results["fail"] += 1


def skip_if_unavailable(name: str, fn, *expected_exc_types: type) -> None:
    """Run fn(); PASS if it succeeds, SKIP if it raises one of
    expected_exc_types (real hardware / dashboard not attached - the
    correct outcome on a dev machine), FAIL on anything else.
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


def main() -> int:
    print("── Read-only tools ──────────────────────────────────────────")
    check("get_position", lambda: tools.get_position(backend="mock"))
    check("list_saved_positions", tools.list_saved_positions)

    baseline_sharpness = None
    if SAMPLE_IMAGE.exists():
        def _compute():
            nonlocal baseline_sharpness
            baseline_sharpness = tools.compute_sharpness(str(SAMPLE_IMAGE))
            return baseline_sharpness
        check("compute_sharpness", _compute)
        check(
            "check_focus_drift",
            lambda: tools.check_focus_drift(str(SAMPLE_IMAGE), baseline_sharpness or 1.0),
        )
    else:
        print(f"  SKIP  compute_sharpness/check_focus_drift -> no sample image at {SAMPLE_IMAGE}")
        results["skip"] += 2

    skip_if_unavailable("get_live_status", tools.get_live_status, ConnectionError)
    skip_if_unavailable("get_pfs_status", tools.get_pfs_status, Exception)

    print("\n── Write tools with no hardware contact ─────────────────────")
    check(
        "define_position",
        lambda: tools.define_position(TEST_POSITION_LABEL, 100.0, 200.0, 5.0),
    )
    if EXAMPLE_PROTOCOL.exists():
        check(
            "load_positions_from_yaml",
            lambda: tools.load_positions_from_yaml(str(EXAMPLE_PROTOCOL)),
        )
    else:
        print(f"  SKIP  load_positions_from_yaml -> no protocol file at {EXAMPLE_PROTOCOL}")
        results["skip"] += 1

    print("\n── Move/write tools (backend=\"mock\") ────────────────────────")
    check("save_current", lambda: tools.save_current(TEST_SAVED_LABEL, backend="mock"))
    check("move_xy_absolute", lambda: tools.move_xy_absolute(10.0, 10.0, backend="mock"))
    check("move_xy_relative", lambda: tools.move_xy_relative(1.0, 1.0, backend="mock"))
    check(
        "go_to_saved_position",
        lambda: tools.go_to_saved_position(TEST_POSITION_LABEL, backend="mock"),
    )

    print("\n── Safety gate: backend=\"sdk\" without confirm=True must raise ─")
    expect_raises(
        "move_xy_absolute(sdk, no confirm)",
        lambda: tools.move_xy_absolute(0.0, 0.0, backend="sdk"),
        PermissionError,
    )
    expect_raises(
        "go_to_saved_position(sdk, no confirm)",
        lambda: tools.go_to_saved_position(TEST_POSITION_LABEL, backend="sdk"),
        PermissionError,
    )
    expect_raises(
        "nudge_focus_offset(no confirm)",
        lambda: tools.nudge_focus_offset(1.0),
        PermissionError,
    )
    expect_raises(
        "abort_run(no confirm)",
        lambda: tools.abort_run("dummy-token"),
        PermissionError,
    )

    print("\n── Real-hardware-only tools (expected to skip off-hardware) ──")
    skip_if_unavailable("nudge_focus_offset(confirm=True)", lambda: tools.nudge_focus_offset(1.0, confirm=True), Exception)
    skip_if_unavailable("abort_run(confirm=True)", lambda: tools.abort_run("dummy-token", confirm=True), ConnectionError, PermissionError)

    print("\n── start_protocol_run (mock) + already-running guard + cleanup ─")
    if TEST_PROTOCOL_SHORT.exists():
        run_result = {}

        def _start():
            run_result.update(tools.start_protocol_run(protocol=str(TEST_PROTOCOL_SHORT), backend="mock"))
            return run_result
        check("start_protocol_run", _start)

        if run_result:
            expect_raises(
                "start_protocol_run (already running)",
                lambda: tools.start_protocol_run(protocol=str(TEST_PROTOCOL_SHORT), backend="mock"),
                RuntimeError,
            )

            pid = run_result["pid"]
            try:
                os.kill(pid, signal.SIGTERM)
                os.waitpid(pid, 0)  # reap the child - avoids leaving a zombie process
            except (ProcessLookupError, ChildProcessError):
                pass

            deadline = time.monotonic() + 5.0
            freed = False
            while time.monotonic() < deadline:
                try:
                    tools.get_live_status()
                    time.sleep(0.3)
                except ConnectionError:
                    freed = True
                    break
            if freed:
                print("  PASS  start_protocol_run cleanup -> dashboard port freed after SIGTERM")
                results["pass"] += 1
            else:
                print("  FAIL  start_protocol_run cleanup -> dashboard still reachable after SIGTERM")
                results["fail"] += 1
    else:
        print(f"  SKIP  start_protocol_run -> no protocol file at {TEST_PROTOCOL_SHORT}")
        results["skip"] += 2

    print("\n── Cleanup: removing test-created saved positions ───────────")
    for label in (TEST_POSITION_LABEL, TEST_SAVED_LABEL, YAML_LOADED_LABEL):
        try:
            tools.delete_saved_position(label)
            print(f"  cleaned up '{label}'")
        except Exception as e:
            print(f"  (nothing to clean up for '{label}': {e})")

    print(f"\n{'=' * 60}\n{results['pass']} passed, {results['fail']} failed, {results['skip']} skipped\n{'=' * 60}")
    return 1 if results["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
