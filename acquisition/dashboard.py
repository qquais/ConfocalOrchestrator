# dashboard.py
# ------------------------------------------------------------
# A live web dashboard for monitoring a ConfocalOrchestrator acquisition run
# remotely. It shows the latest captured frame, current progress, and lets
# you send a Stop/Abort request - all from a browser, without needing to be
# at the microscope PC.
#
# This script runs FINE on a Mac (unlike nis_connection.py / run_protocol.py)
# because it doesn't talk to NIS-Elements at all. It only reads/writes the
# `acquisition_status` dict below. Later, run_protocol.py (running on the
# microscope PC) will import that dict and call `update_status(...)` as it
# moves through timepoints/positions/channels, so this dashboard reflects a
# real run. For now, it starts in the "idle" state with placeholder values.
#
# Run (works right now, on Mac or the microscope PC):
#   python acquisition/dashboard.py
# Then open http://localhost:8000 in a browser.
# ------------------------------------------------------------

import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

# ── 1. Shared in-memory status dict ──────────────────────────────────────────
# This is the ONE place acquisition state lives. No database - just a plain
# Python dict that every request reads from (and /abort writes to). Later,
# run_protocol.py will import `acquisition_status` (or call `update_status`)
# from its own process/import to keep this in sync with a real run.
acquisition_status = {
    "status": "idle",                # "idle" | "running" | "complete" | "error" | "aborted"
    "timepoint_current": 0,
    "timepoint_total": None,         # None = open-ended run (protocol doesn't fix a total ahead of time)
    "position_label": None,
    "channel_name": None,
    "images_captured": 0,
    "started_at": None,              # epoch seconds when the run started (None until running)
    "estimated_total_seconds": None,  # expected run length in seconds, e.g. duration_hours * 3600
    "error_message": None,
    "abort_requested": False,
}


def update_status(**fields) -> None:
    """Update one or more fields in the shared status dict at once.

    Example (called from run_protocol.py once it's wired up):
        update_status(status="running", timepoint_current=3, position_label="sample_center")
    """
    acquisition_status.update(fields)


def get_elapsed_and_remaining_seconds():
    """Compute (elapsed_seconds, remaining_seconds) from the shared status.

    remaining_seconds is None if we don't yet know how long the run is
    expected to take (e.g. before it starts, or for an open-ended protocol).
    """
    started_at = acquisition_status["started_at"]
    if started_at is None:
        return 0.0, None

    elapsed = time.time() - started_at
    total = acquisition_status["estimated_total_seconds"]
    remaining = max(0.0, total - elapsed) if total is not None else None
    return elapsed, remaining


# ── 2. Where the latest frame image lives ────────────────────────────────────
# Placeholder for now: a sample frame from the analysis pipeline. Once real
# acquisition is wired up, run_protocol.py can overwrite this same file (or
# this path variable) with the actual latest captured frame.
LATEST_FRAME_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "analysis" / "nd2_sample" / "frame_0.png"
)

app = FastAPI()


# ── 3. GET /status -> current acquisition state as JSON ─────────────────────
@app.get("/status")
def get_status() -> JSONResponse:
    """Return every status field, plus computed elapsed/remaining time."""
    elapsed_seconds, remaining_seconds = get_elapsed_and_remaining_seconds()
    return JSONResponse(
        {
            **acquisition_status,
            "elapsed_seconds": round(elapsed_seconds, 1),
            "remaining_seconds": round(remaining_seconds, 1) if remaining_seconds is not None else None,
        }
    )


# ── 4. GET /frame -> latest captured frame as an image ───────────────────────
@app.get("/frame")
def get_frame() -> FileResponse:
    """Return the latest frame image (currently a placeholder sample frame)."""
    if not LATEST_FRAME_PATH.exists():
        raise HTTPException(status_code=404, detail=f"No frame found at {LATEST_FRAME_PATH}")
    return FileResponse(LATEST_FRAME_PATH, media_type="image/png")


# ── 5. POST /abort -> request the acquisition to stop ────────────────────────
@app.post("/abort")
def post_abort() -> JSONResponse:
    """Set the abort flag so a running acquisition can stop at its next check.

    NOTE: this only sets a flag in this dashboard's shared dict. Once
    run_protocol.py is wired up to read it (alongside its existing
    ctx.shouldAbort() check), setting this flag will actually stop the scope.
    """
    acquisition_status["abort_requested"] = True
    acquisition_status["status"] = "aborted"
    return JSONResponse({"ok": True, "message": "Abort requested."})


# ── 6. GET / -> the dashboard page itself (plain HTML + JavaScript) ─────────
DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
  <title>ConfocalOrchestrator - Acquisition Dashboard</title>
  <style>
    body { font-family: sans-serif; max-width: 720px; margin: 40px auto; padding: 0 16px; }
    h1 { font-size: 1.4em; }
    .frame-box { text-align: center; margin-bottom: 20px; }
    .frame-box img { max-width: 100%; border: 1px solid #ccc; }
    table { width: 100%; border-collapse: collapse; margin-bottom: 20px; }
    td { padding: 6px 8px; border-bottom: 1px solid #eee; }
    td.label { color: #666; width: 45%; }
    #status-badge {
      display: inline-block; padding: 2px 10px; border-radius: 10px;
      color: white; font-weight: bold; text-transform: uppercase; font-size: 0.85em;
    }
    #abort-btn {
      background: #c0392b; color: white; border: none; padding: 10px 20px;
      font-size: 1em; border-radius: 4px; cursor: pointer;
    }
    #abort-btn:hover { background: #922b21; }
  </style>
</head>
<body>
  <h1>ConfocalOrchestrator Acquisition Dashboard</h1>

  <div class="frame-box">
    <img id="frame-img" src="/frame" alt="Latest frame">
  </div>

  <table>
    <tr><td class="label">Status</td><td><span id="status-badge">-</span></td></tr>
    <tr><td class="label">Timepoint</td><td id="timepoint">-</td></tr>
    <tr><td class="label">Position</td><td id="position">-</td></tr>
    <tr><td class="label">Channel</td><td id="channel">-</td></tr>
    <tr><td class="label">Elapsed time</td><td id="elapsed">-</td></tr>
    <tr><td class="label">Estimated time remaining</td><td id="remaining">-</td></tr>
    <tr><td class="label">Total images captured</td><td id="images">-</td></tr>
  </table>

  <button id="abort-btn" onclick="sendAbort()">Stop / Abort Acquisition</button>

  <script>
    // Colors for each possible status value, used on the badge above.
    const STATUS_COLORS = {
      idle: "#7f8c8d",
      running: "#27ae60",
      complete: "#2980b9",
      error: "#c0392b",
      aborted: "#e67e22",
    };

    // Turn a number of seconds into an "Hh Mm Ss" style string for display.
    function formatSeconds(totalSeconds) {
      if (totalSeconds === null || totalSeconds === undefined) return "-";
      const s = Math.floor(totalSeconds);
      const h = Math.floor(s / 3600);
      const m = Math.floor((s % 3600) / 60);
      const sec = s % 60;
      return `${h}h ${m}m ${sec}s`;
    }

    // Ask the backend for the latest status and update the page with it.
    async function refreshStatus() {
      try {
        const response = await fetch("/status");
        const data = await response.json();

        const badge = document.getElementById("status-badge");
        badge.textContent = data.status;
        badge.style.backgroundColor = STATUS_COLORS[data.status] || "#7f8c8d";

        const tpCurrent = data.timepoint_current ?? "-";
        const tpTotal = data.timepoint_total ?? "?";
        document.getElementById("timepoint").textContent = `Timepoint ${tpCurrent} of ${tpTotal}`;

        document.getElementById("position").textContent = data.position_label ?? "-";
        document.getElementById("channel").textContent = data.channel_name ?? "-";
        document.getElementById("elapsed").textContent = formatSeconds(data.elapsed_seconds);
        document.getElementById("remaining").textContent = formatSeconds(data.remaining_seconds);
        document.getElementById("images").textContent = data.images_captured ?? 0;
      } catch (err) {
        console.error("Failed to fetch /status:", err);
      }
    }

    // Reload the frame image every 5 seconds. The "?t=..." query string is a
    // cache-buster - without it, the browser might just reuse the old image
    // instead of asking the server for a fresh one.
    function refreshFrame() {
      document.getElementById("frame-img").src = "/frame?t=" + Date.now();
    }

    // Ask the user to confirm, then tell the backend to abort the run.
    async function sendAbort() {
      if (!confirm("Stop the current acquisition run?")) return;
      await fetch("/abort", { method: "POST" });
      refreshStatus();
    }

    refreshStatus();
    refreshFrame();
    setInterval(refreshStatus, 2000);  // poll status every 2 seconds
    setInterval(refreshFrame, 5000);   // reload the frame image every 5 seconds
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def get_dashboard() -> str:
    """Serve the dashboard page itself."""
    return DASHBOARD_HTML


# ── 7. Run the dashboard with: python acquisition/dashboard.py ──────────────
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
