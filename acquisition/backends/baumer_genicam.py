# baumer_genicam.py
# ------------------------------------------------------------
# Real image capture from the Baumer VCXU-23C camera via GenICam/GenTL,
# confirmed working end-to-end 2026-08-10 using the `harvesters` Python
# library against the camera's own bgapi2_usb.cti GenTL producer
# (installed with Baumer Camera Explorer).
#
# NOT the confocal detector: this scope's real acquisition path is the
# N-SPARC (CF Mode) detector via NIS-Elements (see docs/microscope-notes.md's
# "Hardware Stack"). The Baumer VCXU-23C is a separate industrial color
# camera found already installed on the microscope PC (Baumer Camera
# Explorer + Toshiba Teli GenICam SDK) - NIS-Elements 6.20.02 LO
# (build 2065) has no GenICam/USB3-Vision driver module installed, so
# this camera isn't reachable from NIS-Elements today (blocked on a
# Nikon installer/license, tracked separately - not addressed here).
#
# This module is a standalone, real-hardware capture() matching
# nis_mock.MockNIS.capture()'s shape (same CAPTURE_DIR, same
# timestamp+sequence filename convention, returns a Path) - useful for
# exercising the rest of the pipeline (focus_check, dashboard) against
# real captured frames instead of only the mock's copied sample PNG.
# Not wired into run_protocol.py's capture_image() - it captures from the
# wrong camera for that (see above), so doing so is a deliberate separate
# decision, not a drop-in replacement for the "sdk" backend's TODO there.
#
# Requires `pip install harvesters` (confirmed against harvesters==1.4.3,
# genicam==1.5.1). A camera can only be held by one application at a
# time - close Baumer Camera Explorer (or any other GenICam consumer)
# before using this.
# ------------------------------------------------------------

import os
from datetime import datetime
from pathlib import Path

from harvesters.core import Harvester
from PIL import Image

# Same directory nis_mock.MockNIS.capture() writes to, so frames from
# either backend land in one place.
CAPTURE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "captures"

# GenTL producer folders confirmed present on the microscope PC,
# 2026-08-10. Checked in addition to GENICAM_GENTL64_PATH (not instead
# of) because a machine-level env var change doesn't propagate to
# already-running processes/shells until they're relaunched - confirmed
# hitting this exact issue while testing, so the env var alone isn't
# reliable here.
FALLBACK_CTI_DIRS = [
    r"C:\Program Files\Baumer Camera Explorer",
    r"C:\Program Files\TOSHIBA TELI\TeliCamSDK\TeliCamApi\bin\x64",
]


def find_cti_files() -> list[str]:
    """Return every .cti GenTL producer file findable via GENICAM_GENTL64_PATH
    plus FALLBACK_CTI_DIRS (see module comment re: stale env vars)."""
    env_dirs = [d for d in os.environ.get("GENICAM_GENTL64_PATH", "").split(os.pathsep) if d]
    dirs = list(dict.fromkeys(env_dirs + FALLBACK_CTI_DIRS))
    cti_files = []
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            if name.lower().endswith(".cti"):
                cti_files.append(os.path.join(d, name))
    return cti_files


class BaumerGenICam:
    """Real capture() from a GenICam camera (confirmed against the Baumer
    VCXU-23C over USB3), matching nis_mock.MockNIS.capture()'s shape:
    writes a timestamped PNG to CAPTURE_DIR and returns its Path.

    Only implements capture() - no stage control. Pair with
    nis_sdk.NISSdk for XY/Z if a caller needs both.
    """

    def __init__(self):
        cti_files = find_cti_files()
        if not cti_files:
            raise RuntimeError(
                "No GenTL producer (.cti) files found - check "
                "GENICAM_GENTL64_PATH or FALLBACK_CTI_DIRS in this module."
            )
        self._harvester = Harvester()
        for cti in cti_files:
            self._harvester.add_file(cti)
        self._harvester.update()
        if not self._harvester.device_info_list:
            self._harvester.reset()
            raise RuntimeError(
                f"GenTL producer(s) loaded ({len(cti_files)}) but no camera "
                "was found - check it's connected and powered, and not "
                "already open in another application (e.g. Baumer Camera "
                "Explorer can only be open in one place at a time)."
            )
        self._acquirer = self._harvester.create(0)
        self._acquirer.start()
        self._capture_count = 0

    def capture(self) -> Path:
        """Grab one live frame and save it as a timestamped PNG in
        CAPTURE_DIR, same filename convention as MockNIS.capture()."""
        CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
        self._capture_count += 1
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = CAPTURE_DIR / f"capture_{timestamp}_{self._capture_count:04d}.png"

        with self._acquirer.fetch(timeout=5) as buffer:
            component = buffer.payload.components[0]
            frame = component.data.reshape(component.height, component.width)
            # VCXU-23C reports BayerRG8 (confirmed 2026-08-10) - this
            # saves the raw single-channel Bayer mosaic as-is, not
            # demosaiced to color, since cv2 isn't a project dependency
            # yet. Add a Bayer->RGB step (e.g.
            # cv2.cvtColor(frame, cv2.COLOR_BayerRG2RGB)) if true color
            # output is needed later.
            Image.fromarray(frame, mode="L").save(dest)

        return dest

    def close(self) -> None:
        self._acquirer.stop()
        self._acquirer.destroy()
        self._harvester.reset()


if __name__ == "__main__":
    cam = BaumerGenICam()
    try:
        print("Connected. Capturing one frame...")
        path = cam.capture()
        print(f"Saved: {path}")
    finally:
        cam.close()
