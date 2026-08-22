# pixel_calibration.py
# ------------------------------------------------------------
# Compute real-world microns-per-pixel from an image of a periodic
# calibration reference (a stage micrometer's ruled graduation marks,
# or anything else with a precisely known, repeating spacing) - closes
# the pixel-size calibration gap flagged repeatedly elsewhere in this
# repo (baumer_genicam.py, center_on_sample.py): unlike the old NIS/.nd2
# capture path, the Baumer camera has no automatic calibration source,
# so this has to be measured from an actual image instead.
#
# METHOD: FFT-based periodicity detection, not per-line edge detection.
# A 1D intensity profile is taken across the image (averaged along the
# axis parallel to the ruling lines), then its FFT's dominant non-DC
# frequency peak gives the repeating line spacing in pixels directly -
# robust to noise, uneven illumination, and a few missing/blurred lines,
# without needing to correctly detect every individual line's position
# the way naive peak-finding would.
#
# UNTESTED against a real stage micrometer as of 2026-08-21 (none was
# available) - validated only against a synthetic image with known
# exact spacing (see this file's __main__ block) to confirm the FFT
# math itself is correct. Confirm against a real calibration slide
# before trusting a result for actual measurement/analysis work.
# ------------------------------------------------------------

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def calibrate_pixel_size(
    image_path: str | Path,
    known_spacing_um: float,
    axis: str = "horizontal",
) -> dict:
    """Detect a periodic ruled pattern's pixel spacing in `image_path`
    and convert it to real microns-per-pixel using `known_spacing_um`
    (the real-world distance between adjacent marks on whatever
    calibration reference is in the image, e.g. a stage micrometer's
    10um divisions).

    axis: "horizontal" - marks are vertical lines spaced apart along X
        (measures a profile averaged down each column). "vertical" -
        marks are horizontal lines spaced apart along Y (profile
        averaged across each row). Pick whichever matches how the
        ruling is actually oriented in the image - rotate/crop the
        image first if the ruling isn't roughly axis-aligned, since the
        FFT profile assumes it is.

    Returns {
        "um_per_pixel": float - the calibration result,
        "detected_pixel_spacing": float - line-to-line spacing found, in pixels,
        "known_spacing_um": float - echoes the input, for the record,
        "confidence_ratio": float - how much the detected peak stands out
            from the average background frequency content. Values well
            above ~5-10 suggest a clear, trustworthy periodic pattern;
            values near 1 mean no clear periodicity was found - treat
            the result as unreliable and check the image/axis choice.
    }

    Raises ValueError if no periodic pattern is detected at all (flat/
    uniform profile - nothing to measure).
    """
    image = np.array(Image.open(image_path).convert("L")).astype(float)

    if axis == "horizontal":
        profile = image.mean(axis=0)  # collapse rows -> 1D profile along X
    elif axis == "vertical":
        profile = image.mean(axis=1)  # collapse columns -> 1D profile along Y
    else:
        raise ValueError(f"Unknown axis '{axis}'. Expected 'horizontal' or 'vertical'.")

    profile = profile - profile.mean()
    windowed = profile * np.hanning(len(profile))

    fft_magnitude = np.abs(np.fft.rfft(windowed))
    freqs = np.fft.rfftfreq(len(windowed))  # cycles per pixel

    # Skip the DC bin and the lowest ~1% of frequencies - broad
    # illumination gradients (see this repo's own uneven-Kohler-
    # illumination captures) show up as strong low-frequency content
    # that would otherwise swamp the real ruling-spacing peak.
    min_freq_idx = max(1, len(freqs) // 100)
    search_region = fft_magnitude[min_freq_idx:]

    if search_region.max() <= 0:
        raise ValueError(
            "No periodic pattern detected in the image - check it actually "
            "shows ruled calibration markings, and that `axis` matches "
            "their orientation."
        )

    peak_idx = int(np.argmax(search_region)) + min_freq_idx
    dominant_freq = freqs[peak_idx]  # cycles per pixel

    pixel_spacing = 1.0 / dominant_freq
    um_per_pixel = known_spacing_um / pixel_spacing
    confidence_ratio = float(fft_magnitude[peak_idx] / (search_region.mean() + 1e-9))

    return {
        # float(...) - pixel_spacing/um_per_pixel are numpy.float64 here
        # (derived from freqs, a numpy array) - convert to plain Python
        # floats at this API boundary, same convention used throughout
        # this repo (see nis_sdk.py/stage_positions.py's to_plain_float)
        # so callers never see a type that doesn't serialize cleanly.
        "um_per_pixel": float(um_per_pixel),
        "detected_pixel_spacing": float(pixel_spacing),
        "known_spacing_um": known_spacing_um,
        "confidence_ratio": confidence_ratio,
    }


def make_calibration_overlay(
    image_path: str | Path,
    detected_pixel_spacing: float,
    axis: str,
    output_path: str | Path,
) -> Path:
    """Draw the detected line spacing as evenly-spaced overlay lines on
    top of the original image and save it - a visual sanity check (for
    a human, or for the model looking at the returned image) that the
    detected spacing actually lines up with the real markings, rather
    than trusting the FFT number blind.
    """
    image = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    width, height = image.size

    if axis == "horizontal":
        x = 0.0
        while x < width:
            draw.line([(x, 0), (x, height)], fill=(255, 0, 0), width=2)
            x += detected_pixel_spacing
    else:
        y = 0.0
        while y < height:
            draw.line([(0, y), (width, y)], fill=(255, 0, 0), width=2)
            y += detected_pixel_spacing

    output_path = Path(output_path)
    image.save(output_path)
    return output_path


if __name__ == "__main__":
    # Synthetic validation: a known-exact 40px line spacing should
    # round-trip back to itself through calibrate_pixel_size(), proving
    # the FFT math is correct independent of any real hardware/slide.
    import tempfile

    width, height = 1920, 1200
    true_spacing_px = 40.0
    known_spacing_um = 10.0  # pretend each line is a 10um division

    arr = np.zeros((height, width), dtype=np.uint8)
    x = 0.0
    while x < width:
        col = int(round(x))
        if col < width:
            arr[:, max(0, col - 1):col + 2] = 255
        x += true_spacing_px

    with tempfile.TemporaryDirectory() as tmp:
        test_path = Path(tmp) / "synthetic_ruler.png"
        Image.fromarray(arr).save(test_path)

        result = calibrate_pixel_size(test_path, known_spacing_um, axis="horizontal")
        print(f"True spacing:      {true_spacing_px} px")
        print(f"Detected spacing:  {result['detected_pixel_spacing']:.3f} px")
        print(f"um_per_pixel:      {result['um_per_pixel']:.4f}")
        print(f"Expected um/px:    {known_spacing_um / true_spacing_px:.4f}")
        print(f"Confidence ratio:  {result['confidence_ratio']:.1f}")

        overlay_path = Path(tmp) / "overlay.png"
        make_calibration_overlay(test_path, result["detected_pixel_spacing"], "horizontal", overlay_path)
        print(f"Overlay saved (in temp dir, for this test only): {overlay_path}")
