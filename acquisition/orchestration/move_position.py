# move_position.py
# ------------------------------------------------------------
# Standalone script to move the XY stage to a specific position from
# the command line - the code equivalent of NIS-Elements' own "Move
# this Point to Center" right-click feature, but callable directly
# instead of clicking in the UI.
#
# This does not add any new stage-control capability - it's a thin CLI
# wrapper over acquisition.backends.nis_sdk.NISSdk / nis_mock.MockNIS's
# already-confirmed XY_Move/XY_MoveRelative (the same functions
# center_on_sample.py and mcp_server/acquisition_tools.py's
# move_xy_absolute/move_xy_relative already call) - built as its own
# file so it can be run directly, the same way nis_jobs_trigger.py and
# center_on_sample.py are run directly, without going through MCP.
#
# SAFETY - same gate pattern as every other move tool in this repo:
# backend="mock" (default) is safe; backend="sdk" requires confirm=True.
# nis_sdk.NISSdk's own MAX_XY_STEP_UM per-call cap and travel-range
# checks still apply regardless of what's passed here. Z is never
# touched - this only moves XY.
#
# Usage (from the repo root, with .venv activated):
#   Absolute move (to a specific stage position, in microns):
#     python -m acquisition.orchestration.move_position --x -8732 --y 8868 --backend mock
#     python -m acquisition.orchestration.move_position --x -8732 --y 8868 --backend sdk --confirm
#   Relative move (by an offset from the current position, in microns):
#     python -m acquisition.orchestration.move_position --dx 100 --dy -50 --backend mock
# ------------------------------------------------------------


def move_absolute(x: float, y: float, backend: str = "mock", confirm: bool = False) -> dict:
    """Move the XY stage to an absolute (x, y) position, in microns.

    backend: "mock" (default, safe) or "sdk" (real hardware - requires
    confirm=True, same gate as every other move tool in this repo).
    """
    if backend not in ("mock", "sdk"):
        raise ValueError(f"Unknown backend '{backend}'. Expected 'mock' or 'sdk'.")
    if backend == "sdk" and not confirm:
        raise PermissionError(
            "backend='sdk' controls real microscope hardware and requires "
            "confirm=True. Refusing to proceed without explicit confirmation."
        )

    if backend == "mock":
        from acquisition.backends.nis_mock import MockNIS
        nis = MockNIS()
    else:
        from acquisition.backends.nis_sdk import NISSdk
        nis = NISSdk()

    before = nis.XY_GetPosition()
    nis.XY_Move(x, y)
    after = nis.XY_GetPosition()

    return {"position_before": before, "position_after": after, "backend": backend}


def move_relative(dx: float, dy: float, backend: str = "mock", confirm: bool = False) -> dict:
    """Move the XY stage by (dx, dy) microns relative to its current position.

    backend: "mock" (default, safe) only - nis_sdk.NISSdk has no
    XY_MoveRelative method (same limitation noted in
    mcp_server/acquisition_tools.py's move_xy_relative) - use
    move_absolute with an explicit target position on real hardware
    instead.
    """
    if backend == "sdk":
        raise NotImplementedError(
            "Relative XY moves are not available on backend='sdk' - "
            "nis_sdk.NISSdk has no XY_MoveRelative method. Use "
            "move_absolute with an explicit target position instead."
        )
    if backend != "mock":
        raise ValueError(f"Unknown backend '{backend}'. Expected 'mock' or 'sdk'.")

    from acquisition.backends.nis_mock import MockNIS
    nis = MockNIS()

    before = nis.XY_GetPosition()
    nis.XY_MoveRelative(dx, dy)
    after = nis.XY_GetPosition()

    return {"position_before": before, "position_after": after, "backend": backend}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Move the XY stage to a position - code equivalent of "
        "NIS-Elements' 'Move this Point to Center' feature."
    )
    parser.add_argument("--x", type=float, default=None, help="Absolute target X, in microns.")
    parser.add_argument("--y", type=float, default=None, help="Absolute target Y, in microns.")
    parser.add_argument("--dx", type=float, default=None, help="Relative move in X, in microns.")
    parser.add_argument("--dy", type=float, default=None, help="Relative move in Y, in microns.")
    parser.add_argument("--backend", choices=("mock", "sdk"), default="mock")
    parser.add_argument("--confirm", action="store_true", help="Required alongside --backend sdk.")
    args = parser.parse_args()

    if args.x is not None and args.y is not None:
        result = move_absolute(args.x, args.y, backend=args.backend, confirm=args.confirm)
    elif args.dx is not None and args.dy is not None:
        result = move_relative(args.dx, args.dy, backend=args.backend, confirm=args.confirm)
    else:
        parser.error("Pass either --x and --y (absolute) or --dx and --dy (relative).")

    print(f"Position before: {result['position_before']}")
    print(f"Position after:  {result['position_after']}")
