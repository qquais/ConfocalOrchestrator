# ConfocalOrchestrator

An automated pipeline for confocal time-lapse imaging and analysis of *Physarum polycephalum*.

## Status

Early development — Stage 1 (Discovery & Setup). Analysis pipeline validated on real Physarum data.

## About

This project automates two things that are currently done manually in the lab:

1. Running overnight imaging sessions on the Nikon Eclipse Ti2 / N-SPARC confocal microscope
2. Analysing time-lapse data — segmenting the organism and tracking growth metrics across frames

## Analysis Pipeline

Three scripts handle the full ND2 → results workflow:

| Script | Input | Output |
|---|---|---|
| `analysis/explore_nd2.py` | ND2 file | Metadata + first frame PNG |
| `analysis/extract_frames.py` | ND2 file | Numbered PNGs in `data/frames/` |
| `analysis/cellects_pipeline.py` | TIFF or PNG folder | CSV + growth curve plot |
| `analysis/nd2_pipeline.py` | ND2 file | CSV + growth curve plot (no intermediate files) |
| `analysis/segment_nd2.py` | Single PNG | Cellpose segmentation overlay |

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
├── analysis/        # Segmentation and tracking scripts
├── validation/      # Accuracy benchmarking
├── protocols/       # Imaging protocol files
└── docs/            # Project documentation
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

> Hardware integration (NIS-Elements microscope control) is still being scoped. Current work focuses on the analysis pipeline using existing ND2 data.
