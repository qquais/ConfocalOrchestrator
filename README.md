# ConfocalOrchestrator

An automated pipeline for confocal time-lapse imaging and nucleus tracking in *Physarum polycephalum*.

## Status

🚧 Early development — Stage 1 (Discovery & Setup).

## About

This project automates two things that are currently done manually in the lab:

1. Running overnight imaging sessions on the N-SPARC confocal microscope
2. Tracking nuclei across hundreds of frames in the recorded time-lapse data

## Project Structure

```
ConfocalOrchestrator/
├── acquisition/     # Microscope control and image capture
├── analysis/        # Nucleus segmentation and tracking
├── validation/      # Accuracy benchmarking
├── protocols/       # Example imaging protocol files
└── docs/            # Project documentation
```

## Tech Stack

- Python 3.11
- OpenCV, scikit-image, Cellpose
- FastAPI
- tifffile / aicsimageio

## Getting Started

```bash
git clone <repo-url>
cd ConfocalOrchestrator
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

> ⚠️ Hardware integration (microscope control) is still being scoped. Early work focuses on the analysis pipeline using existing data.