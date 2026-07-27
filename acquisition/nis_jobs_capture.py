# nis_jobs_capture.py
# ------------------------------------------------------------
# PREP MATERIAL ONLY - NOT WIRED IN, NOT TESTED.
#
# This documents the planned approach for real image capture via
# NIS-Elements' own Jobs API, for whenever JOBS Editor gets licensed on
# this install (confirmed NOT licensed as of 2026-07-27 - checked via
# NIS-Elements' own menu bar, version 6.10.01). Nothing in this file is
# called anywhere. run_protocol.py's capture_image() still correctly
# returns None for backend="sdk"/"bridge", and that remains intentional,
# confirmed-working behavior (see its docstring) - this file changes
# nothing about it.
#
# WHY THIS EXISTS
# ----------------
# The Ti2 SDK family - ActiveX (NkTi2Ax), native C (Ti2_Mic_Driver.dll),
# and the .NET P/Invoke wrapper - has ZERO image-capture surface.
# Confirmed exhaustively: every header Nikon ships, the official
# compiled help file (NIKONTI2_E.chm), and all three binding styles
# expose the same ~16-function set (MIC_Open/Close, MIC_DataGet/DataSet,
# MIC_MetadataGet/Set, MIC_DedicatedCommand, MIC_Convert_*) - stage,
# turret, and objective control only. See docs/microscope-notes.md for
# the stage-control side of this SDK, which IS confirmed working
# (nis_sdk.py, backend="sdk").
#
# Real image capture only exists through NIS-Elements' own Jobs API,
# specifically its "PythonScript" task type - documented locally at
# C:\Program Files\NIS-Elements\Docs\nis\eng_ar\task.system_section.html
# (this is a local install doc, not mirrored into this repo).
#
# THE REFERENCED API
# -------------------
# Per that doc, a PythonScript task - chained immediately after a
# Capture task, at the SAME loop level - must define a module-level
# `run` function with this exact signature:
#
#     import limjob
#
#     def run(imgs: tuple[limjob.Image], Job: limjob.JobParam,
#             macro: limjob.MacroParam, ctx: limjob.RunContext):
#         img = imgs[0]
#         arr = img.array()   # -> numpy.ndarray, shape (Z, Y, X, Component)
#
# NIS-Elements calls this function itself when the Job runs - it is NOT
# something a standalone Python process (like run_protocol.py) can
# import or call directly. It only exists inside a Job built in NIS-
# Elements' own JOBS Explorer UI. This is an inversion-of-control model:
# NIS drives the Job and hands your code a frame, rather than your code
# requesting one.
#
# THIS HAS NEVER BEEN RUN. It's a documented reference, not a confirmed
# fact - treat imgs[0].array()'s existence, shape, and dtype as unverified
# until tested live.
#
# HOW TO CONFIRM IT LIVE, ONCE JOBS EDITOR IS LICENSED
# ------------------------------------------------------
#   1. Menu: View -> Analysis Controls -> JOBS Explorer
#   2. Add New Project (if needed) -> Add New Job -> Job Definition window opens
#   3. Drag in Acquisition -> Capture Current OC (skips needing a separate
#      Capture Definition task - simplest for a first test; it uses
#      whatever Optical Configuration is currently selected)
#   4. Drag in System -> PythonScript immediately after it, at the SAME
#      loop level (Nikon's docs: image access is scoped by loop - the
#      Capture and PythonScript tasks must be siblings)
#   5. Double-click the PythonScript task -> under Input Images, click
#      "+" and select the image the Capture Current OC task produced
#   6. Paste the exact code shown above (or see capture_via_jobs_api()'s
#      docstring below)
#   7. Click Apply first - errors show in a box below the editor; check
#      here before running
#   8. Save the Job, then Run Job
#   9. Confirm and record: does imgs[0].array() actually return a real
#      numpy array? What shape/dtype? Where does print() output surface,
#      if anywhere? Does the shape/dtype match what
#      focus_check.compute_sharpness() expects (grayscale (H,W) or RGB
#      (H,W,3), uint8 0-255 or float 0-1 - see focus_check.py)?
#
# ONCE CONFIRMED LIVE (not before): wire this into run_protocol.py's
# capture_image(), in a new `if backend == "sdk": ...` branch, replacing
# its current `return None` for that backend. Also worth resolving at
# that point, not before: the architecture mismatch between NIS's
# Job-driven capture (inversion of control) and run_protocol.py's
# current external-script-driven loop (it calls nis.XY_Move()/Z_Move()
# imperatively) - how a script triggers a Job's capture on demand is
# itself unconfirmed and may need its own investigation.
# ------------------------------------------------------------


def capture_via_jobs_api():
    """PLACEHOLDER - DO NOT CALL.

    THIS IS UNTESTED. REQUIRES JOBS EDITOR LICENSE, which is not active
    on this install (confirmed via NIS-Elements' menu bar, version
    6.10.01, as of 2026-07-27 - see docs/microscope-notes.md).

    Image capture in the NIS-Elements Jobs API is not invoked by calling
    a function like this one - see this module's header comment. NIS-
    Elements runs a Job (Capture task -> PythonScript task) and calls a
    `run(imgs, Job, macro, ctx)` function it finds inside the
    PythonScript task's own code, handing it an already-captured frame
    as `imgs[0]`. There is currently no confirmed way to trigger that
    from an external process like run_protocol.py.

    This stub exists only so the eventual real function has a concrete
    place to be filled in. It deliberately does not attempt a call -
    imgs[0].array() has never been run against real NIS-Elements and
    could be wrong in ways nobody has checked yet: wrong signature,
    wrong return shape/dtype, or the whole invocation model turning out
    not to fit run_protocol.py's external-script architecture at all.
    """
    raise NotImplementedError(
        "capture_via_jobs_api() is UNTESTED prep material - requires JOBS "
        "Editor license, not available on this install as of 2026-07-27. "
        "Do not call until the imgs[0].array() flow documented in this "
        "file's header has been confirmed live in NIS-Elements' JOBS "
        "Explorer. See the header comment for the exact steps to verify it."
    )
