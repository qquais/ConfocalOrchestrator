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
    pixel_size_um_per_px: float,
    backend: str = "mock",
    confirm: bool = False,
    exposure_time_us: float | None = None,
    gain: float | None = None,
) -> dict:
    """The full "capture, then center" flow this file's header
    describes: grab a real frame from the Baumer GenICam camera
    (acquisition.backends.baumer_genicam.BaumerGenICam), then center the
    stage on the resulting image's brightest region.

    2026-08-20: capture no longer goes through NIS-Elements/Jobs at all
    (team decision, 2026-08-17 - see mcp_server/loop_tools.py's header
    comment) - this used to call acquisition.backends.nis_jobs_trigger.
    trigger_capture() instead; that path is superseded.

    pixel_size_um_per_px: REQUIRED, no default. The old NIS-Jobs path
    could auto-read this from the .nd2 file NIS saved alongside each
    capture - the Baumer camera has no equivalent auto-calibration (see
    baumer_genicam.py's header), so there is currently no way to derive
    this automatically. Calibrate it once per objective/zoom in use
    (e.g. image a stage micrometer) and pass the result in - a wrong
    value here directly produces a wrong stage move.

    exposure_time_us, gain: optional - applied via BaumerGenICam.
    set_settings() before capturing if given; see that method's
    docstring for confirmed valid ranges/units.

    No `channel`/multi-channel selection anymore either - the old NIS-
    Jobs path could return several fluorescence channels per capture
    (see nis_jobs_trigger.COMPONENT_CHANNEL_NAMES); the Baumer camera has
    no fluorescence/laser-line control and always returns one RGB frame.

    `backend`/`confirm` apply only to the STAGE MOVE half, same meaning
    as in center_on_sample() - the camera itself has no mock/backend
    concept (real hardware only, no simulator equivalent to fall back to).
    """
    from acquisition.backends.baumer_genicam import BaumerGenICam

    camera = BaumerGenICam()
    try:
        if exposure_time_us is not None or gain is not None:
            camera.set_settings(exposure_time_us=exposure_time_us, gain=gain)
        image_path = camera.capture()
    finally:
        camera.close()

    center_result = center_on_sample(
        image_path, pixel_size_um_per_px, backend=backend, confirm=confirm
    )
    return {**center_result, "capture_path": str(image_path)}


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
             "fresh Baumer capture - no hardware contact at all, safe to run anytime.",
    )
    parser.add_argument(
        "--pixel-size", type=float, required=True, dest="pixel_size_um_per_px",
        help="Microns per pixel for whatever objective/zoom is in use - always required. "
             "No auto-calibration source exists for the Baumer camera (see "
             "capture_and_center()'s docstring) - calibrate this once and pass it in.",
    )
    parser.add_argument("--exposure-us", type=float, default=None, dest="exposure_time_us", help="Camera exposure time in microseconds (live capture only).")
    parser.add_argument("--gain", type=float, default=None, help="Camera gain, camera's own unit-less scale (live capture only).")
    parser.add_argument("--backend", choices=("mock", "sdk"), default="mock")
    parser.add_argument("--confirm", action="store_true", help="Required alongside --backend sdk.")
    args = parser.parse_args()

    if args.image:
        result = center_on_sample(
            args.image, args.pixel_size_um_per_px, backend=args.backend, confirm=args.confirm
        )
    else:
        result = capture_and_center(
            args.pixel_size_um_per_px, backend=args.backend, confirm=args.confirm,
            exposure_time_us=args.exposure_time_us, gain=args.gain,
        )
    _print_center_result(result)
