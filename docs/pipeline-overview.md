# Pipeline Overview

> Written for the biology team — this explains what the software does, in plain terms, from "microscope takes a picture" to "here's a spreadsheet of tracked nuclei."

## 1. Project Overview

ConfocalOrchestrator automates overnight confocal time-lapse imaging of *Physarum polycephalum* on the lab's Nikon microscope, and then automatically analyzes the resulting images — segmenting the organism/nuclei in each frame and tracking how they move and grow over time. The goal is to remove manual babysitting from both running the microscope overnight and processing the images afterward.

## 2. Two Components

The project is split into two independent halves:

- **Acquisition** (`acquisition/`) — controls the microscope itself: reads a protocol file describing the experiment, drives the stage/z-focus/channels through NIS-Elements, watches for focus drift, and saves images to disk. This part talks directly to the microscope hardware.
- **Analysis** (`analysis/`) — takes the saved image files (no microscope needed) and turns them into measurements: denoising, detecting cells/nuclei, and tracking them frame-to-frame into a results CSV. This part runs on any computer (e.g. a laptop) once the images exist.

Acquisition produces the files that Analysis consumes — they don't need to run at the same time or on the same machine.

## 3. Full Pipeline Flow

```
Protocol YAML (protocols/example_protocol.yaml)
        |
        v   describes: objective, positions, z-stack, channels, timing
NIS-Elements SDK (acquisition/run_protocol.py)
        |
        v   drives the stage, focus, and channels on the real microscope
ND2 files saved (Nikon's native image format, one per position/z/channel/timepoint)
        |
        v   analysis/preprocess_nd2.py
Denoised frame  (Gaussian blur + illumination correction + speckle removal, via scikit-image)
        |
        v   analysis/fluorescence_pipeline.py
Segmented nuclei  (Cellpose detects each nucleus as a labeled blob per frame)
        |
        v   analysis/track_nuclei.py  (trackpy)
Linked trajectories  (the same nucleus is given one consistent ID across all frames)
        |
        v
Trajectory CSV  (nucleus_id, frame, x, y, area) + a plot of the tracked paths
```

**In plain terms:** you describe the experiment once in a YAML file, the microscope runs it unattended overnight and saves images, and then a chain of analysis scripts cleans up each image, finds every nucleus in it, and stitches those detections together into "nucleus #7 was here at t=0, here at t=1, here at t=2..." — ready to plot or measure growth/movement from.

## 4. Key Scripts

### Acquisition

| Script | What it does |
|---|---|
| `acquisition/nis_connection.py` | Smoke test — confirms the microscope PC's NIS-Elements Python API is reachable and the stage can be read/moved |
| `acquisition/run_protocol.py` | Reads a protocol YAML and runs the full experiment: loops over every timepoint, stage position, z-slice, and channel, capturing an image at each step |
| `acquisition/focus_check.py` | Safety net for overnight runs — measures image sharpness (Laplacian variance) each timepoint and flags if the focus has drifted |
| `acquisition/dashboard.py` | Live web page (FastAPI) showing run progress and the latest captured frame, with a Stop/Abort button — so you can check on an overnight run remotely |

### Analysis

| Script | Input | Output |
|---|---|---|
| `analysis/explore_nd2.py` | ND2 file | Metadata + first frame PNG |
| `analysis/extract_frames.py` | ND2 file | Numbered PNGs in `data/frames/` |
| `analysis/preprocess_nd2.py` | Raw frame | Denoised + background-corrected + speckle-filtered frame |
| `analysis/fluorescence_pipeline.py` | Fluorescence TIFF frames | Cellpose-segmented nuclei, centroids, and a trajectory CSV + plot (full end-to-end demo pipeline) |
| `analysis/segment_nd2.py` | Single PNG | Cellpose segmentation overlay (organism/nucleus outlines) |
| `analysis/track_nuclei.py` | PNG frame sequence | Per-nucleus trajectories CSV + visualization (Cellpose + trackpy) |
| `analysis/cellects_pipeline.py` | TIFF or PNG folder | CSV + growth curve plot (Cellects — whole-organism shape tracking) |
| `analysis/nd2_pipeline.py` | ND2 file | CSV + growth curve plot, no intermediate files saved |
| `analysis/convert_to_ometiff.py` | ND2 file | OME-TIFF (pixels + metadata bundled in one open format) |

**Metrics tracked per frame:** area, perimeter, circularity, eccentricity, major/minor axis length, solidity.

## 5. Data Folder Structure

```
data/
├── raw/          # ND2 files saved directly by the microscope
├── frames/       # Extracted PNG frames (one per timepoint)
├── datasets/     # Reference/validation datasets (e.g. Cell Tracking Challenge samples)
└── analysis/     # Every script's output lives here, one subfolder per script/purpose
                  #   e.g. preprocessing/, tracking/, fluorescence/, ometiff/
```

Nothing here needs to be created by hand — each script creates its own output subfolder under `data/analysis/` the first time it runs.

## 6. Hardware

- **Microscope body:** Nikon Eclipse Ti2-E (inverted)
- **Confocal scanner:** Nikon AX
- **Detector:** N-SPARC (CF Mode)
- **Laser unit:** LUA-S4 — 405nm, 488nm, 561nm, 640nm
- **Control software:** NIS-Elements AR 6.20.02 (Windows only — the acquisition scripts must run on the microscope PC itself)
- **Live cell incubator:** Tokai Hit STX
- **Objectives:** 4x, 10x, 60x Oil immersion
- **Stage:** Motorized, Ti2-CTRE controller, ±57mm (X) / ±36.5mm (Y) travel, 0.01µm minimum focus step

Full spec sheet and confirmed NIS-Elements API notes: `docs/microscope-notes.md`.

## 7. Status

**Done:**
- Analysis pipeline validated end-to-end on real fluorescence nuclear data (denoise → segment → track → CSV)
- Hardware specs and NIS-Elements Jobs API documented
- Example imaging protocol captured from the biology team (`protocols/example_protocol.yaml`)
- First stage-connection script written (`acquisition/nis_connection.py`)
- `run_protocol.py` written — reads a protocol YAML and runs the full timepoint/position/z-stack/channel loop
- Live dashboard (`dashboard.py`) built and wired into `run_protocol.py`'s loop
- Focus drift detection (`focus_check.py`) built and tested standalone

**Pending:**
- Remote Desktop access to the microscope PC, to actually test `run_protocol.py` and `nis_connection.py` against the real hardware (currently untested outside a dev laptop)
- Wiring `focus_check.py` into `run_protocol.py`'s timepoint loop (currently a separate, untested integration)
- Confirming several protocol placeholders with the biology team: dye/fluorophore names, laser power, exposure time per channel, real stage coordinates, and the exact meaning of the "S9CAI" filename tag
- Confirming how the job-context object (`ctx`, used for abort checks) is actually obtained on the microscope PC
