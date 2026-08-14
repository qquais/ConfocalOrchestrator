# center_on_sample.py
# ------------------------------------------------------------
# Standalone script (deliberately NOT an MCP tool - see mcp_server/
# acquisition_tools.py's top-of-file comment on what's exposed there
# and why): capture an image, find the centroid of the brightest
# region in it, and move the stage so that point is centered in the
# field of view.
#
# "Centroid of the brightest region" is a best-guess default for what
# "get the pixel... center" meant (see project chat, 2026-08-14) - NOT
# confirmed against the original request. If a different definition of
# "the pixel" was actually meant (a specific detected feature, a
# particular channel, a bounding-box center instead of a mass-weighted
# centroid, an ML-segmented object), swap out find_centroid_offset()'s
# thresholding step - the rest of this file (offset -> stage move) does
# not depend on how the target pixel was chosen.
#
# SAFETY - two independent halves, two different risk levels:
#   find_centroid_offset() - pure image analysis, NO hardware contact.
#     Fully testable offline against any already-captured image file
#     (e.g. data/captures/*.png, results/arabidopsis/frames/*.png) -
#     do this FIRST, extensively, before ever touching real hardware.
#   center_on_sample() - adds a real XY stage move on top. backend=
#     "mock" (default) is safe; backend="sdk" requires confirm=True,
#     same gate pattern as every hardware-move tool in
#     mcp_server/acquisition_tools.py. nis_sdk.NISSdk's own
#     MAX_XY_STEP_UM per-call cap and travel-range checks still apply
#     regardless of what this script computes - a bad centroid can move
#     the field of view to the wrong place, but cannot exceed the
#     existing per-call distance cap or push past the stage's known
#     travel limits. Z is never touched.
#
# UNCONFIRMED - image-axis-to-stage-axis mapping: this assumes image
# +x (right) = stage +x and image +y (down) = stage +y, i.e. no flip/
# mirror between camera and stage coordinate systems. This has NOT
# been verified live (would need: center on a known offset, capture
# again, confirm the target actually moved toward image-center).
# Confirm this with a real test before trusting center_on_sample() on
# a sample you can't afford to lose from view - see "HOW TO TEST
# SAFELY" below.
#
# HOW TO TEST SAFELY
# -------------------
#   1. Run find_centroid_offset() against several already-captured
#      images (no hardware, no risk) - sanity-check the reported
#      centroid/offset by eye against the actual image.
#   2. Run center_on_sample() with backend="mock" (default) - confirms
#      the offset-to-move math and unit conversion without touching
#      real hardware; prints what it WOULD do.
#   3. Only once 1-2 look right: a single center_on_sample() call with
#      backend="sdk", confirm=True, on a sample where being off-center
#      is not a problem - verify the axis-mapping assumption above by
#      checking the result, not by trusting this comment.
# ------------------------------------------------------------

from pathlib import Path

import numpy as np
from PIL import Image
from skimage.filters import threshold_otsu
from skimage.measure import label, regionprops


def find_centroid_offset(image_path: str | Path, pixel_size_um_per_px: float) -> dict:
    """Find the centroid of the largest bright region in an image and
    return its offset from the image center, in both pixels and
    microns. Pure image analysis - does not touch any hardware.

    pixel_size_um_per_px: microns per pixel for THIS capture - varies
    with objective/zoom, read it off NIS's own status bar (e.g. the
    "0.50 um/px" shown there) for the config actually used. There is
    no reliable way to infer this from the image file itself (the
    diagnostic capture script's PNGs carry no pixel-size metadata), so
    getting this value right is the caller's responsibility - a wrong
    value here directly produces a wrong stage move.

    Method: Otsu threshold (automatic, not manually tuned) to separate
    foreground from background, keep only the LARGEST connected
    foreground region (so a few stray bright noise pixels elsewhere in
    the frame don't skew the centroid), then compute that region's
    center of mass. See this file's header for why this specific
    method was chosen as a first guess, not a confirmed spec.

    Returns: {
        "centroid_px": (row, col) - centroid position in pixel coords,
        "image_center_px": (row, col) - the image's own center pixel,
        "offset_px": (drow, dcol) - centroid minus image center,
        "offset_um": (dy, dx) - offset_px converted to microns,
        "foreground_fraction": float - fraction of pixels above
            threshold; sanity-check this isn't ~0.0 (nothing found) or
            ~1.0 (thresholding failed to separate anything, e.g. an
            overexposed or completely blank frame),
    }
    """
    # Deliberately NOT Image.open(...).convert("L") - PIL's 16-bit ->
    # 8-bit conversion uses a naive fixed scale (roughly value >> 8),
    # which would crush our genuinely low-signal real captures (raw
    # values like 42-639 out of a possible 0-65535) down toward zero
    # before thresholding ever runs, risking Otsu picking a meaningless
    # threshold. Load the native array instead - threshold_otsu works
    # fine directly on uint16 data, no precision loss.
    image = np.array(Image.open(image_path))
    if image.ndim == 3:
        image = image.mean(axis=-1)  # collapse RGB to grayscale by averaging, if ever given a color image

    threshold = threshold_otsu(image)
    binary = image > threshold
    foreground_fraction = float(binary.mean())

    labeled = label(binary)
    regions = regionprops(labeled)
    if not regions:
        raise ValueError(
            f"No foreground region found in {image_path} after Otsu "
            f"thresholding (threshold={threshold}) - the frame may be "
            "blank/featureless. Nothing to center on."
        )
    largest_region = max(regions, key=lambda r: r.area)
    centroid_row, centroid_col = largest_region.centroid  # (row, col) = (y, x)

    image_center_row = image.shape[0] / 2.0
    image_center_col = image.shape[1] / 2.0

    offset_row_px = centroid_row - image_center_row
    offset_col_px = centroid_col - image_center_col

    return {
        "centroid_px": (centroid_row, centroid_col),
        "image_center_px": (image_center_row, image_center_col),
        "offset_px": (offset_row_px, offset_col_px),
        "offset_um": (
            offset_row_px * pixel_size_um_per_px,
            offset_col_px * pixel_size_um_per_px,
        ),
        "foreground_fraction": foreground_fraction,
    }


def center_on_sample(
    image_path: str | Path,
    pixel_size_um_per_px: float,
    backend: str = "mock",
    confirm: bool = False,
) -> dict:
    """Find the brightest region's centroid in `image_path` and move
    the XY stage so that point is centered in the field of view.

    backend: "mock" (default, safe) or "sdk" (real hardware - requires
    confirm=True, same gate as every other move tool in this repo).

    See this file's header for the UNCONFIRMED image-axis-to-stage-axis
    assumption this relies on, and "HOW TO TEST SAFELY" before running
    this with backend="sdk" for the first time.
    """
    if backend not in ("mock", "sdk"):
        raise ValueError(f"Unknown backend '{backend}'. Expected 'mock' or 'sdk'.")
    if backend == "sdk" and not confirm:
        raise PermissionError(
            "backend='sdk' controls real microscope hardware and requires "
            "confirm=True. Refusing to proceed without explicit confirmation."
        )

    result = find_centroid_offset(image_path, pixel_size_um_per_px)
    offset_y_um, offset_x_um = result["offset_um"]

    if backend == "mock":
        from acquisition.backends.nis_mock import MockNIS
        nis = MockNIS()
    else:
        from acquisition.backends.nis_sdk import NISSdk
        nis = NISSdk()

    current_x, current_y = nis.XY_GetPosition()
    # UNCONFIRMED axis mapping - see this file's header. offset_x_um is
    # image-column-based (horizontal), offset_y_um is image-row-based
    # (vertical) - assumed to map directly onto stage X/Y with no
    # flip. Verify before trusting on a sample you can't re-find.
    target_x = current_x + offset_x_um
    target_y = current_y + offset_y_um

    nis.XY_Move(target_x, target_y)
    new_x, new_y = nis.XY_GetPosition()

    return {
        **result,
        "position_before": (current_x, current_y),
        "position_after": (new_x, new_y),
        "backend": backend,
    }


def capture_and_center(
    project: str,
    job: str,
    pixel_size_um_per_px: float | None = None,
    channel: str | None = None,
    backend: str = "mock",
    confirm: bool = False,
) -> dict:
    """The full "capture, then center" flow this file's header
    describes: trigger a real capture (acquisition.backends.
    nis_jobs_trigger.trigger_capture()), then center the stage on the
    resulting image's brightest region.

    project, job: the exact Project/Job names as they exist in NIS's
    own Jobs database - no default (see trigger_capture()'s docstring
    for why: "Arabidopsis"/"TestCapture" was this repo's throwaway
    debug Job, not something to silently default real runs to).

    pixel_size_um_per_px: normally leave this as None - trigger_capture()
    already reads the REAL calibrated pixel size from the .nd2 file NIS
    itself saves for this capture (confirmed 2026-08-14 to match NIS's
    own status bar exactly), which is more reliable than a value typed
    in by hand (which can silently go stale as objective/zoom change).
    Only pass this explicitly to override that - e.g. if
    trigger_capture() couldn't find the .nd2 file for this install (see
    its own WARNING output if so) and returned pixel_size_um_per_px as
    None, in which case this function raises rather than guessing.

    channel: which captured channel to center on, e.g. "TD" or
        "5-FAM" - required if the capture returns more than one
        channel (see nis_jobs_trigger.COMPONENT_CHANNEL_NAMES; that
        mapping is confirmed only for the 5-FAM+TD combination, see
        that module's caveats). Ignored if only one channel comes back.

    Capture triggering always talks to real NIS-Elements - there is no
    mock capture (same as every other Jobs-API capability in this
    repo, see nis_jobs_trigger.py). `backend`/`confirm` here apply only
    to the STAGE MOVE half, same meaning as in center_on_sample().
    """
    from acquisition.backends.nis_jobs_trigger import trigger_capture

    capture_result = trigger_capture(project, job)
    paths = capture_result["paths"]

    if pixel_size_um_per_px is None:
        pixel_size_um_per_px = capture_result["pixel_size_um_per_px"]
        if pixel_size_um_per_px is None:
            raise ValueError(
                "Could not determine the real pixel size for this capture "
                "(trigger_capture() couldn't find/read the matching .nd2 "
                "file - see the WARNING it printed) - pass "
                "pixel_size_um_per_px explicitly to override."
            )

    if len(paths) == 1:
        image_path = next(iter(paths.values()))
    elif channel is not None and channel in paths:
        image_path = paths[channel]
    else:
        raise ValueError(
            f"Capture returned {len(paths)} channel(s) ({list(paths)}) - "
            "pass `channel` (one of the names above) to pick which one "
            "to center on."
        )

    center_result = center_on_sample(
        image_path, pixel_size_um_per_px, backend=backend, confirm=confirm
    )
    return {**center_result, "capture": capture_result}


def _print_center_result(result: dict) -> None:
    print(f"Centroid (row, col): {result['centroid_px']}")
    print(f"Offset (px):         {result['offset_px']}")
    print(f"Offset (um):         {result['offset_um']}")
    print(f"Foreground fraction: {result['foreground_fraction']:.1%}")
    print(f"Position before:     {result['position_before']}")
    print(f"Position after:      {result['position_after']}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Find the brightest region in an image and center the stage on it."
    )
    parser.add_argument(
        "--image", type=str, default=None,
        help="Test against an already-captured image file instead of triggering a "
             "fresh capture - no hardware contact at all, safe to run anytime. "
             "Requires --pixel-size (no .nd2 file to read it from in this mode).",
    )
    parser.add_argument(
        "--pixel-size", type=float, default=None, dest="pixel_size_um_per_px",
        help="Microns per pixel - only needed with --image. In live mode (no --image), "
             "this is read automatically from the real .nd2 file NIS saves; leave unset "
             "unless you need to override that.",
    )
    parser.add_argument("--channel", type=str, default=None, help="Which channel to center on (e.g. TD, 5-FAM) when a fresh capture returns more than one.")
    parser.add_argument(
        "--project", type=str, default=None,
        help='Project name as it exists in NIS Jobs, e.g. "Arabidopsis". '
             "Required unless --image is given (no default - see trigger_capture()'s docstring).",
    )
    parser.add_argument(
        "--job", type=str, default=None,
        help='Job name as it exists in NIS Jobs, e.g. "TestCapture". Required unless --image is given.',
    )
    parser.add_argument("--backend", choices=("mock", "sdk"), default="mock")
    parser.add_argument("--confirm", action="store_true", help="Required alongside --backend sdk.")
    args = parser.parse_args()

    if args.image:
        if args.pixel_size_um_per_px is None:
            parser.error("--pixel-size is required when --image is given.")
        result = center_on_sample(
            args.image, args.pixel_size_um_per_px, backend=args.backend, confirm=args.confirm
        )
    else:
        if not args.project or not args.job:
            parser.error("--project and --job are required when --image is not given.")
        result = capture_and_center(
            args.project, args.job, pixel_size_um_per_px=args.pixel_size_um_per_px,
            channel=args.channel, backend=args.backend, confirm=args.confirm,
        )
    _print_center_result(result)
