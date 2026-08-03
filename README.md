# ConfocalOrchestrator

An automated pipeline for confocal time-lapse imaging and analysis of *Physarum polycephalum*.

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![NumPy](https://img.shields.io/badge/NumPy-013243?logo=numpy&logoColor=white)
![Pandas](https://img.shields.io/badge/Pandas-150458?logo=pandas&logoColor=white)
![OpenCV](https://img.shields.io/badge/OpenCV-5C3EE8?logo=opencv&logoColor=white)
![scikit--image](https://img.shields.io/badge/scikit--image-F7931E)
![Matplotlib](https://img.shields.io/badge/Matplotlib-11557C)
![Cellpose](https://img.shields.io/badge/Cellpose-4B8BBE)
![pywin32](https://img.shields.io/badge/pywin32-0078D4?logo=windows&logoColor=white)
![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)

## Status

Analysis pipeline validated on real Physarum data. Acquisition side:
**real stage control is confirmed working**, end-to-end — the full
timepoint/position/z-stack/channel loop, plus the web dashboard's
Stop/Abort button, all confirmed against the Ti2-E Device Simulator via
the Ti2 ActiveX SDK (`acquisition/backends/nis_sdk.py`, `--backend sdk`).

**Real image capture is not yet wired in.** The Ti2 SDK family (ActiveX,
native C, .NET) was exhaustively confirmed to have no capture path at
all — capture has to come through NIS-Elements' own Jobs API instead
(Capture task → PythonScript task), which is documented and ready to
test in `acquisition/planned/nis_jobs_capture.py`, but blocked on JOBS Editor
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
plus pluggable stage-control backends, not independent CLI tools.
`acquisition/` is organized into subfolders by role, so the flow is
visible from the folder listing alone, before reading any code:

```
acquisition/
├── calibration/     # one-off scripts that confirmed the hardware connection works
│   ├── nikon_connection_test.py
│   ├── nikon_stage_test.py
│   └── nis_jobs_connection_test.py
├── backends/        # reusable stage-control code, built from what calibration/ confirmed
│   ├── nis_sdk.py
│   └── nis_mock.py
├── orchestration/    # uses backends/ to actually run an experiment
│   ├── stage_positions.py
│   └── run_protocol.py
├── monitoring/       # watches a run while it's happening
│   ├── dashboard.py
│   └── focus_check.py
└── planned/          # documented but not wired in yet
    └── nis_jobs_capture.py
```

This table tracks role and confirmed status per file instead of input/output:

| File | Role | Status |
|---|---|---|
| `orchestration/run_protocol.py` | Orchestrator — reads a protocol YAML, loops timepoints → positions → z-stack → channels, captures, runs focus-check, drives the dashboard | Loop confirmed end-to-end (incl. abort) against `--backend sdk`; real capture still pending |
| `backends/nis_sdk.py` | `NISSdk` backend — real stage control via the Ti2 ActiveX SDK | Confirmed, primary backend |
| `backends/nis_mock.py` | `MockNIS` backend — offline/no-hardware simulation; also the only source of real captured frames today | Working, offline-dev fallback |
| `orchestration/stage_positions.py` | `StagePositionManager` — save/list/go-to named stage positions (`protocols/stage_positions.json`) | Working |
| `planned/nis_jobs_capture.py` | Documented plan + untested placeholder for real image capture via NIS-Elements' Jobs API | Blocked on JOBS Editor licensing |
| `monitoring/dashboard.py` | Live web UI (`localhost:8000`) — status, latest frame, Stop/Abort | Working, tested incl. abort |
| `monitoring/focus_check.py` | `FocusMonitor` — Laplacian-variance focus-drift detection | Working; only runs once a real frame exists (mock today) |
| `calibration/nis_jobs_connection_test.py` | Standalone confirmation script for the NIS-Elements Jobs API (`XY_GetPosition`/`XY_Move`) | One-off, already confirmed |
| `calibration/nikon_connection_test.py` | Standalone confirmation script — ActiveX connection pattern + turret property | One-off, already confirmed |
| `calibration/nikon_stage_test.py` | Standalone confirmation script — XY/Z stage property names and units | One-off, already confirmed |

See `docs/microscope-notes.md` for full investigation detail behind each confirmed/blocked status above.

### Backends: `mock` vs `sdk`

Two files can drive the stage through either a fake, no-hardware backend or the real one — `orchestration/run_protocol.py` and `orchestration/stage_positions.py`. Neither one auto-detects which to use; you always choose explicitly, and both default to `mock` so a script can never accidentally move real hardware.

- **`mock`** — safe, in-memory fake (`backends/nis_mock.MockNIS`), or the real NIS-Elements Jobs API (`import nis`) if that happens to be importable. No real stage motion unless you're inside NIS-Elements' own Python environment.
- **`sdk`** — real hardware, via the Ti2 ActiveX SDK (`backends/nis_sdk.NISSdk`). This is the one that actually moves the real microscope stage.

| File | How the backend is chosen |
|---|---|
| `orchestration/run_protocol.py` | CLI flag: `--backend mock\|sdk` (default `mock`) |
| `orchestration/stage_positions.py` | Constructor argument: `StagePositionManager(backend="mock"\|"sdk")` — the `__main__` demo block hardcodes `backend="mock"` (no CLI flag), so using `sdk` here means importing `StagePositionManager` yourself, or editing that line |

`calibration/nikon_connection_test.py`, `calibration/nikon_stage_test.py`, and `backends/nis_sdk.py` don't have a mock option at all — they connect directly via `win32com.client.Dispatch(...AutoConnectMicroscope...)`, which always reaches whatever's actually running (real hardware if present, otherwise the Ti2-E simulator).

### Running each script

`orchestration/stage_positions.py` and `orchestration/run_protocol.py` import sibling folders as a package (`acquisition.backends...`, `acquisition.monitoring...`), so they must be run as a module with `python -m`, **from the repo root**. The rest have no cross-folder imports and can still be run directly by path.

| File | Command (from repo root) | Arguments |
|---|---|---|
| `orchestration/run_protocol.py` | `python -m acquisition.orchestration.run_protocol --backend sdk --protocol protocols/example_protocol.yaml` | `--backend mock\|sdk` (default `mock`), `--protocol <path>` (default `protocols/example_protocol.yaml`) |
| `orchestration/stage_positions.py` | `python -m acquisition.orchestration.stage_positions` | none — backend is set in code (see above), always `mock` when run directly |
| `backends/nis_sdk.py` | `python acquisition/backends/nis_sdk.py` | none — smoke test, just prints current position |
| `calibration/nikon_connection_test.py` | `python acquisition/calibration/nikon_connection_test.py` | none — moves the turret, no confirmation prompt |
| `calibration/nikon_stage_test.py` | `python acquisition/calibration/nikon_stage_test.py` or `... --read` | `--read` (optional) — single snapshot and exit, no pause/prompt |
| `calibration/nis_jobs_connection_test.py` | `python nis_jobs_connection_test.py` | none — must be run from inside NIS-Elements' own Python console (the `nis` module doesn't exist anywhere else) |
| `backends/nis_mock.py` | `python acquisition/backends/nis_mock.py` | none — runs its own self-test/demo, purely in-memory |
| `monitoring/dashboard.py` | `python acquisition/monitoring/dashboard.py` | none — normally launched automatically by `run_protocol.py`; run directly only to test the UI on its own |
| `monitoring/focus_check.py` | `python3 acquisition/monitoring/focus_check.py` | none — self-contained demo, simulates progressive defocus and plots sharpness |
| `planned/nis_jobs_capture.py` | not runnable | documentation/placeholder only — its function raises `NotImplementedError` by design |

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

- Python 3.12
- nd2 — read Nikon ND2 files
- Cellects — Physarum segmentation and shape tracking
- Cellpose — nucleus segmentation (comparison)
- OpenCV, NumPy, Pillow, pandas, matplotlib
- FastAPI, uvicorn — acquisition dashboard web server
- pywin32 — Ti2 ActiveX SDK bindings (Windows-only, acquisition side)

## Getting Started

```bash
git clone <repo-url>
cd ConfocalOrchestrator
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> Hardware integration status: real stage control is confirmed working end-to-end against the Ti2-E Device Simulator via the Ti2 ActiveX SDK (`--backend sdk`, see `acquisition/backends/nis_sdk.py` and `docs/microscope-notes.md`). Real image capture is documented and ready to test (`acquisition/planned/nis_jobs_capture.py`) but blocked on NIS-Elements' JOBS Editor being licensed on the install. Nothing here has been run against the real physical microscope yet.

## License

MIT License — `LICENSE` file to be added.

## Acknowledgments

- **Primary developer:** [Qurratul Ain Quais](https://github.com/qquais)
- **Organization:** [Bionanomics](https://github.com/BioNanomics)
- **Organization:** [Medical Informatics Engineering, Inc.](https://github.com/mieweb)
- **Research advisor:** [Doug Horner](https://github.com/horner)
