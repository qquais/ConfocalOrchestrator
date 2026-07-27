# ConfocalOrchestrator

An automated pipeline for confocal time-lapse imaging and analysis of *Physarum polycephalum*.

## Status

Analysis pipeline validated on real Physarum data. Acquisition side:
**real stage control is confirmed working**, end-to-end — the full
timepoint/position/z-stack/channel loop, plus the web dashboard's
Stop/Abort button, all confirmed against the Ti2-E Device Simulator via
the Ti2 ActiveX SDK (`acquisition/nis_sdk.py`, `--backend sdk`).

**Real image capture is not yet wired in.** The Ti2 SDK family (ActiveX,
native C, .NET) was exhaustively confirmed to have no capture path at
all — capture has to come through NIS-Elements' own Jobs API instead
(Capture task → PythonScript task), which is documented and ready to
test in `acquisition/nis_jobs_capture.py`, but blocked on JOBS Editor
being licensed on the install. Once that's confirmed live, it gets
wired into `run_protocol.py`'s `capture_image()`.

Not yet tested against the real physical microscope — everything above
is confirmed against the simulator only. See `docs/microscope-notes.md`
for full investigation detail and confirmed API specifics.

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
| `analysis/fluorescence_pipeline.py` | Fluorescence TIFF frame folder (`--data`/`--output`/`--frames` CLI args) | Per-nucleus trajectories CSV + tracking visualisation PNG (Cellpose + trackpy) |
| `analysis/synchronization.py` | Trajectories CSV (from `fluorescence_pipeline.py`) | Velocity CSV, nucleus-pair correlation matrix CSV, text report, and a heatmap + speed-over-time plot — measures whether nuclei move in a coordinated way |
| `analysis/compare_sequences.py` | Two trajectory CSVs (`seq01`/`seq02` under `data/analysis/fluorescence/`) | Printed + saved side-by-side comparison table (avg nuclei/frame, track length, nucleus area) |

`analysis/cellpose_runtime.py` isn't a standalone script — it's a shared helper (`resolve_cellpose_gpu_mode()`) imported by the Cellpose-based scripts above to resolve the `CELLPOSE_GPU` setting consistently.

Cellpose defaults to `CELLPOSE_GPU=auto`, which uses CUDA when PyTorch can see a GPU and falls back to CPU otherwise. To force GPU mode, run a script like `CELLPOSE_GPU=1 python3 analysis/segment_nd2.py`.

**Metrics tracked per frame:** area, perimeter, circularity, eccentricity, major/minor axis length, solidity.

## Acquisition Pipeline

Unlike the analysis scripts above (each a standalone file-in/file-out
transform), acquisition is a live control system — one orchestrator
plus pluggable stage-control backends, not independent CLI tools. So
this table tracks role and confirmed status per file instead of
input/output:

| File | Role | Status |
|---|---|---|
| `run_protocol.py` | Orchestrator — reads a protocol YAML, loops timepoints → positions → z-stack → channels, captures, runs focus-check, drives the dashboard | Loop confirmed end-to-end (incl. abort) against `--backend sdk`; real capture still pending |
| `nis_sdk.py` | `NISSdk` backend — real stage control via the Ti2 ActiveX SDK | Confirmed, primary backend |
| `nis_mock.py` | `MockNIS` backend — offline/no-hardware simulation; also the only source of real captured frames today | Working, offline-dev fallback |
| `stage_positions.py` | `StagePositionManager` — save/list/go-to named stage positions (`protocols/stage_positions.json`) | Working |
| `nis_jobs_capture.py` | Documented plan + untested placeholder for real image capture via NIS-Elements' Jobs API | Blocked on JOBS Editor licensing |
| `dashboard.py` | Live web UI (`localhost:8000`) — status, latest frame, Stop/Abort | Working, tested incl. abort |
| `focus_check.py` | `FocusMonitor` — Laplacian-variance focus-drift detection | Working; only runs once a real frame exists (mock today) |
| `nis_connection.py` | Standalone confirmation script for the NIS-Elements Jobs API (`XY_GetPosition`/`XY_Move`) | One-off, already confirmed |
| `nikon_test.py` | Standalone confirmation script — ActiveX connection pattern + turret property | One-off, already confirmed |
| `nikon_stage_test.py` | Standalone confirmation script — XY/Z stage property names and units | One-off, already confirmed |

See `docs/microscope-notes.md` for full investigation detail behind each confirmed/blocked status above.

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
├── acquisition/     # Microscope control and image capture — see "Acquisition Pipeline" above
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

> Hardware integration status: real stage control is confirmed working end-to-end against the Ti2-E Device Simulator via the Ti2 ActiveX SDK (`--backend sdk`, see `acquisition/nis_sdk.py` and `docs/microscope-notes.md`). Real image capture is documented and ready to test (`acquisition/nis_jobs_capture.py`) but blocked on NIS-Elements' JOBS Editor being licensed on the install. Nothing here has been run against the real physical microscope yet.
