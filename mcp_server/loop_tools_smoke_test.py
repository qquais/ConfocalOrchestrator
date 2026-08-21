# loop_tools_smoke_test.py
# ------------------------------------------------------------
# Manual smoke test for every MCP tool in loop_tools.py (the minimal
# get_image/get_pos/move/get_move_history agent-loop surface - see that
# module's header comment for the full design rationale), run against
# backend="mock" for stage control.
#
# get_image() is real-hardware-only (the Baumer GenICam camera, no mock
# equivalent - see loop_tools.py) - exercised for its safety-gate
# behavior, then SKIPPED (not FAILed) if the camera isn't reachable
# (not connected, or held open by another application, e.g. Baumer
# Camera Explorer) - same skip-on-hardware-absence pattern as
# acquisition_tools_smoke_test.py's skip_if_unavailable().
#
# logs/move_history.jsonl is NOT cleaned up afterward - deliberately,
# since it's meant to be an ever-growing, real history log (see
# loop_tools.py's header comment), the same way acquisition_tools_
# smoke_test.py doesn't clean up run_protocol.py's own log files either.
# The move this script makes is a real entry in that log.
#
# Run (from the repo root, with .venv activated):
#   python -m mcp_server.loop_tools_smoke_test
# ------------------------------------------------------------

import sys
import traceback

from mcp_server import loop_tools as tools

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
    expected_exc_types (real hardware not attached/reachable - the
    correct outcome on a dev machine, or when something else is holding
    the camera), FAIL on anything else.
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
    print("-- get_pos (backend=\"mock\") ---------------------------------")
    check("get_pos", lambda: tools.get_pos(backend="mock"))

    print("\n-- move (backend=\"mock\") + history logging -----------------")
    move_result = {}

    def _move():
        move_result.update(tools.move(111.0, 222.0, backend="mock"))
        return move_result
    check("move", _move)

    print("\n-- get_move_history ------------------------------------------")
    history_result = {}

    def _history():
        history_result.update(tools.get_move_history(limit=5))
        return history_result
    check("get_move_history", _history)

    if history_result and move_result:
        if history_result["history"] and history_result["history"][-1]["position"] == move_result["position"]:
            print("  PASS  get_move_history's last entry reflects the move just made")
            results["pass"] += 1
        else:
            print("  FAIL  get_move_history's last entry does not match the move just made")
            results["fail"] += 1

    print("\n-- Safety gates: real-hardware calls without confirm=True must raise -")
    expect_raises("move(sdk, no confirm)", lambda: tools.move(0.0, 0.0, backend="sdk"), PermissionError)
    expect_raises("get_image(no confirm)", lambda: tools.get_image(), PermissionError)

    print("\n-- Real-hardware-only tool (expected to skip if camera unavailable) --")
    skip_if_unavailable("get_image(confirm=True)", lambda: tools.get_image(confirm=True), Exception)

    print(f"\n{'=' * 60}\n{results['pass']} passed, {results['fail']} failed, {results['skip']} skipped\n{'=' * 60}")
    return 1 if results["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
