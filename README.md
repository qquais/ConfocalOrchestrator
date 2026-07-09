# ConfocalOrchestrator

An automated pipeline for confocal time-lapse imaging and analysis of *Physarum polycephalum*.

## Status

Early development — Stage 1 (Discovery & Setup) moving into acquisition integration. Analysis pipeline validated on real Physarum data; hardware specs and NIS-Elements API documented (see `docs/microscope-notes.md`), first stage-connection script drafted (`acquisition/nis_connection.py`), and a real biofilm imaging protocol captured (`protocols/example_protocol.yaml`). Still pending: Remote Desktop access to the microscope PC to actually test the connection.

## About

This project automates two things that are currently done manually in the lab:

1. Running overnight imaging sessions on the Nikon Eclipse Ti2 / N-SPARC confocal microscope
2. Analysing time-lapse data — segmenting the organism and tracking growth metrics across frames

## Analysis Pipeline

Scripts handle the full ND2 → results workflow:

| Script | Input | Output |
|---|---|---|
| `analysis/explore_nd2.py` | ND2 file | Metadata + first frame PNG |
| `analysis/extract_frames.py` | ND2 file | Numbered PNGs in `data/frames/` |
| `analysis/preprocess_nd2.py` | Raw frame | Denoised + background-corrected + speckle-filtered frame |
| `analysis/cellects_pipeline.py` | TIFF or PNG folder | CSV + growth curve plot |
| `analysis/nd2_pipeline.py` | ND2 file | CSV + growth curve plot (no intermediate files) |
| `analysis/segment_nd2.py` | Single PNG | Cellpose segmentation overlay |
| `analysis/track_nuclei.py` | PNG frame sequence | Per-nucleus trajectories CSV + visualisation (Cellpose + trackpy) |
| `analysis/convert_to_ometiff.py` | ND2 file | OME-TIFF (pixels + metadata in one open format) |

**Metrics tracked per frame:** area, perimeter, circularity, eccentricity, major/minor axis length, solidity.

## Data Folder Structure

```
data/
├── raw/          # ND2 files from the microscope
├── frames/       # Extracted PNG frames
├── datasets/     # Reference/validation datasets
└── analysis/     # Script outputs (CSV, plots)
```

## Project Structure

```
ConfocalOrchestrator/
├── acquisition/     # Microscope control and image capture (in progress)
│                    #   nis_connection.py — stage connection smoke test (done)
│                    #   run_protocol.py — reads a protocol YAML and runs the full
│                    #     timepoint/position/z-stack/channel loop (done, untested on real hardware)
│                    #   dashboard.py — live web dashboard (status/frame/abort), wired into
│                    #     run_protocol.py's loop so it reflects a real run (done, tested)
│                    #   focus_check.py — Laplacian-variance focus drift detection,
│                    #     the safety net for overnight runs (done, tested; not yet
│                    #     called from run_protocol.py's loop)
├── analysis/        # Preprocessing, segmentation, and tracking scripts
├── validation/      # Accuracy benchmarking
├── protocols/       # Imaging protocol files (e.g. example_protocol.yaml)
└── docs/            # Project documentation (e.g. microscope-notes.md)
```

## Tech Stack

- Python 3.13
- nd2 — read Nikon ND2 files
- Cellects — Physarum segmentation and shape tracking
- Cellpose — nucleus segmentation (comparison)
- OpenCV, NumPy, Pillow, pandas, matplotlib

## Getting Started

```bash
git clone <repo-url>
cd ConfocalOrchestrator
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> Hardware integration (NIS-Elements microscope control) is underway: hardware specs, the confirmed NIS-Elements Jobs Python API, and a first stage-connection script are in place (see `docs/microscope-notes.md`). It hasn't been tested against the real microscope yet — that needs Remote Desktop access to the microscope PC, which is pending.
