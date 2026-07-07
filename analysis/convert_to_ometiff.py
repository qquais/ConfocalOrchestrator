# convert_to_ometiff.py
# ------------------------------------------------------------
# Converts a raw .ND2 microscopy file into a standard OME-TIFF file.
#
# Why OME-TIFF? A plain .ND2 file only works with Nikon software, and a
# plain .tiff/.png only stores pixels. OME-TIFF is an open, widely
# supported format that stores the pixel data AND the scientific metadata
# (pixel size, channel names, timestamps, ...) together in one file, using
# a standard XML schema that other tools (ImageJ/Fiji, napari, Python
# libraries, etc.) all know how to read.
#
# Run (from the repo root, with .venv activated):
#   python3 analysis/convert_to_ometiff.py
#
# Requirements: nd2, tifffile, numpy (already installed)
# ------------------------------------------------------------

from datetime import datetime
from pathlib import Path

import nd2          # reads .ND2 files from Nikon microscopes
import tifffile      # writes/reads OME-TIFF files

# ── 1. Paths ──────────────────────────────────────────────────────────────────
ND2_FILE = "data/raw/MRAP1 KO DN_10X03.nd2"
OUTPUT_DIR = Path("data/analysis/ometiff")
OUTPUT_FILE = OUTPUT_DIR / "output.ome.tiff"

# Create the output folder if it doesn't exist yet (mkdir -p equivalent)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── 2. Open the ND2 file and read the pixel data + metadata ──────────────────
with nd2.ND2File(ND2_FILE) as f:

    # Pixel data. Shape/axis order matches f.sizes, e.g. (Y, X, S) for this
    # single-frame RGB brightfield file.
    print(f"Loading pixel data from: {ND2_FILE}")
    image = f.asarray()
    print(f"Array shape : {image.shape}  (dtype: {image.dtype})")

    # f.sizes is an ordered dict like {'Y': 2048, 'X': 2880, 'S': 3}.
    # Its keys, joined together, give the axis-order string ("YXS") that
    # tifffile needs to know which array dimension is which.
    axes = "".join(f.sizes.keys())
    print(f"Axis order  : {axes}")

    # Pixel size in micrometres (how much real-world distance one pixel covers)
    voxel = f.voxel_size()
    pixel_size_x = voxel.x
    pixel_size_y = voxel.y
    pixel_size_z = voxel.z
    print(f"Pixel size  : x={pixel_size_x:.4f} um, y={pixel_size_y:.4f} um, z={pixel_size_z:.4f} um")

    # Channel names (e.g. "Brightfield", "DAPI", "GFP", ...)
    meta = f.metadata
    if meta and meta.channels:
        channel_names = [ch.channel.name for ch in meta.channels]
    else:
        channel_names = ["Channel0"]
    print(f"Channels    : {channel_names}")

    # Acquisition timestamp. text_info['date'] holds a human-readable date
    # string like "11/1/2023  3:10:05 PM" — we parse it into a proper
    # datetime object so it can be written as an OME AcquisitionDate.
    date_str = " ".join(f.text_info.get("date", "").split())  # collapse extra spaces
    try:
        acquisition_date = datetime.strptime(date_str, "%m/%d/%Y %I:%M:%S %p")
        print(f"Acquired on : {acquisition_date.isoformat()}")
    except ValueError:
        acquisition_date = None
        print("Acquired on : not available in this file")

# ── 3. Decide the TIFF "photometric" mode ────────────────────────────────────
# 'rgb' when the file stores 3 colour samples per pixel (like our brightfield
# image), otherwise 'minisblack' for single-channel grayscale data.
is_rgb = "S" in axes and image.shape[axes.index("S")] == 3
photometric = "rgb" if is_rgb else "minisblack"
print(f"\nPhotometric : {photometric}")

# ── 4. Build the OME metadata dictionary ─────────────────────────────────────
# tifffile turns this dict into a proper OME-XML block and embeds it in the
# TIFF's ImageDescription tag, so the metadata travels inside the file itself.
ome_metadata = {
    "axes": axes,
    "PhysicalSizeX": pixel_size_x,
    "PhysicalSizeXUnit": "um",
    "PhysicalSizeY": pixel_size_y,
    "PhysicalSizeYUnit": "um",
}

# Only include Z spacing if this file actually has a Z-stack.
if "Z" in axes:
    ome_metadata["PhysicalSizeZ"] = pixel_size_z
    ome_metadata["PhysicalSizeZUnit"] = "um"

# Only include per-channel names if this file has a real "C" (fluorescence
# channel) axis — brightfield RGB files use "S" (colour samples) instead.
if "C" in axes:
    ome_metadata["Channel"] = {"Name": channel_names}

if acquisition_date is not None:
    ome_metadata["AcquisitionDate"] = acquisition_date.isoformat()

# ── 5. Write the OME-TIFF file ────────────────────────────────────────────────
print(f"\nWriting OME-TIFF: {OUTPUT_FILE}")
tifffile.imwrite(
    OUTPUT_FILE,
    image,
    photometric=photometric,
    metadata=ome_metadata,
)
print("Saved.")

# ── 6. Verify: read the file back and print its metadata ────────────────────
# This confirms the pixel data round-trips correctly and the OME-XML metadata
# really was embedded in the saved file (not just held in memory).
print(f"\nVerifying by reading back: {OUTPUT_FILE}")
with tifffile.TiffFile(OUTPUT_FILE) as tif:
    readback_image = tif.asarray()
    print(f"Read-back array shape : {readback_image.shape}  (dtype: {readback_image.dtype})")
    print(f"Pixel data matches original: {(readback_image == image).all()}")

    print("\nEmbedded OME-XML metadata:")
    print(tif.ome_metadata)

print("\nDone! The OME-TIFF now carries pixel size, channel, and timestamp metadata with it.")
