"""
Flask application -- live camera stream with quality/FPS controls.

Routes
------
/              - HTML page with the video player
/video_feed    - MJPEG stream
/snapshot      - Single JPEG snapshot
/api/settings  - GET/POST camera settings (quality, fps, rotation)
/api/logs      - GET server logs (last N lines)
/api/detection - GET/POST detection settings
/api/stats     - GET system resource usage
/api/viewers   - GET current viewers
/api/join      - POST join as viewer (name)
/api/heartbeat - POST keep viewer alive
/api/leave     - POST remove viewer
"""

import atexit
import logging
import os
import threading
import time
import json
import urllib.request
from collections import deque
from flask import Flask, Response, render_template, jsonify, request

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

from camera import Camera

# ── In-memory log buffer ──────────────────────────────────────────
MAX_LOG_LINES = 500

class _LogBuffer(logging.Handler):
    """Captures log records into a thread-safe deque."""

    def __init__(self, maxlen: int = MAX_LOG_LINES):
        super().__init__()
        self._buffer: deque[str] = deque(maxlen=maxlen)
        self._lock_buf = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            with self._lock_buf:
                self._buffer.append(msg)
        except Exception:
            self.handleError(record)

    def get_lines(self, last_n: int = 100) -> list[str]:
        with self._lock_buf:
            items = list(self._buffer)
        return items[-last_n:]

    def count(self) -> int:
        with self._lock_buf:
            return len(self._buffer)


_log_buffer = _LogBuffer(maxlen=MAX_LOG_LINES)
_log_buffer.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
))
logging.root.addHandler(_log_buffer)
logging.root.setLevel(logging.INFO)

log = logging.getLogger("app")

# ── Viewers tracker ───────────────────────────────────────────────
VIEWER_TIMEOUT = 30  # seconds without heartbeat -> remove

_viewers: dict[str, float] = {}  # name -> last_seen timestamp
_viewers_lock = threading.Lock()


def _add_viewer(name: str) -> None:
    with _viewers_lock:
        is_new = name not in _viewers
        _viewers[name] = time.time()
    if is_new:
        log.info("Viewer joined: %s", name)


def _heartbeat_viewer(name: str) -> None:
    with _viewers_lock:
        if name in _viewers:
            _viewers[name] = time.time()


def _remove_viewer(name: str) -> None:
    with _viewers_lock:
        if name in _viewers:
            del _viewers[name]
            log.info("Viewer left: %s", name)


def _get_viewers() -> list[str]:
    now = time.time()
    with _viewers_lock:
        # Clean up stale viewers
        stale = [n for n, t in _viewers.items() if now - t > VIEWER_TIMEOUT]
        for n in stale:
            del _viewers[n]
            log.info("Viewer left (timeout): %s", n)
        return sorted(_viewers.keys())


# ── Camera ────────────────────────────────────────────────────────
CAMERA_SRC   = 0
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
CAMERA_FPS   = 30
JPEG_QUALITY = 80

app = Flask(__name__)


@app.after_request
def add_ngrok_headers(response):
    """Help bypass ngrok browser warning for all responses."""
    response.headers["ngrok-skip-browser-warning"] = "true"
    return response

camera = Camera(
    src=CAMERA_SRC,
    width=CAMERA_WIDTH,
    height=CAMERA_HEIGHT,
    fps=CAMERA_FPS,
    jpeg_quality=JPEG_QUALITY,
).start()

atexit.register(camera.stop)


def _mjpeg_generator():
    while True:
        frame = camera.wait_for_frame(timeout=2.0)
        if frame is None:
            continue
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
        )


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/video_feed")
def video_feed():
    return Response(
        _mjpeg_generator(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/snapshot")
def snapshot():
    frame = camera.get_frame()
    if frame is None:
        return jsonify({"error": "no frame available"}), 503
    return Response(frame, mimetype="image/jpeg")


# ── Camera Settings API ──────────────────────────────────────────

@app.route("/api/settings", methods=["GET"])
def get_settings():
    return jsonify(camera.get_settings())


@app.route("/api/settings", methods=["POST"])
def update_settings():
    data = request.get_json(force=True)
    if "jpeg_quality" in data:
        camera.set_jpeg_quality(int(data["jpeg_quality"]))
    if "fps" in data:
        camera.set_fps(int(data["fps"]))
    if "rotation" in data:
        camera.set_rotation(int(data["rotation"]))
    return jsonify(camera.get_settings())


# ── Logs API ─────────────────────────────────────────────────────

@app.route("/api/logs", methods=["GET"])
def get_logs():
    """Return the last N log lines as JSON."""
    n = request.args.get("n", 100, type=int)
    n = max(1, min(n, MAX_LOG_LINES))
    lines = _log_buffer.get_lines(n)
    return jsonify({"lines": lines, "total": _log_buffer.count()})


# ── Detection API ────────────────────────────────────────────────

@app.route("/api/detection", methods=["GET"])
def get_detection():
    settings = camera.detector.get_settings()
    settings["detections"] = camera.detector.get_last_detections_summary()
    return jsonify(settings)


@app.route("/api/detection", methods=["POST"])
def update_detection():
    data = request.get_json(force=True)
    det = camera.detector

    if "enabled" in data:
        det.set_enabled(bool(data["enabled"]))
    if "confidence" in data:
        det.set_confidence(float(data["confidence"]))
    if "detect_interval" in data:
        det.set_detect_interval(int(data["detect_interval"]))
    if "draw_all_objects" in data:
        det.set_draw_all_objects(bool(data["draw_all_objects"]))

    settings = det.get_settings()
    settings["detections"] = det.get_last_detections_summary()
    return jsonify(settings)


# ── Viewers API ──────────────────────────────────────────────────

@app.route("/api/join", methods=["POST"])
def join_viewer():
    """Join as a viewer. Body: {"name": "..."}"""
    data = request.get_json(force=True)
    name = str(data.get("name", "")).strip()
    if not name or len(name) > 30:
        return jsonify({"error": "Name required (max 30 chars)"}), 400
    _add_viewer(name)
    return jsonify({"ok": True, "viewers": _get_viewers()})


@app.route("/api/heartbeat", methods=["POST"])
def heartbeat():
    """Keep viewer alive. Body: {"name": "..."}"""
    data = request.get_json(force=True)
    name = str(data.get("name", "")).strip()
    if name:
        _heartbeat_viewer(name)
    return jsonify({"ok": True, "viewers": _get_viewers()})


@app.route("/api/viewers", methods=["GET"])
def get_viewers():
    """Get list of current viewers."""
    return jsonify({"viewers": _get_viewers()})


@app.route("/api/leave", methods=["POST"])
def leave_viewer():
    """Remove viewer. Body: {"name": "..."}"""
    data = request.get_json(force=True)
    name = str(data.get("name", "")).strip()
    if name:
        _remove_viewer(name)
    return jsonify({"ok": True, "viewers": _get_viewers()})


# ── System Stats ─────────────────────────────────────────────────

def _get_cpu_temp() -> float | None:
    """Read CPU temperature (Raspberry Pi)."""
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return round(int(f.read().strip()) / 1000, 1)
    except (FileNotFoundError, ValueError):
        pass
    if HAS_PSUTIL:
        temps = psutil.sensors_temperatures()
        if temps:
            for entries in temps.values():
                if entries:
                    return round(entries[0].current, 1)
    return None


def _get_uptime() -> str:
    """Human-readable uptime."""
    try:
        with open("/proc/uptime") as f:
            secs = int(float(f.read().split()[0]))
    except (FileNotFoundError, ValueError):
        if HAS_PSUTIL:
            secs = int(time.time() - psutil.boot_time())
        else:
            return "N/A"
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    mins, _ = divmod(rem, 60)
    parts = []
    if days:  parts.append(f"{days}d")
    if hours: parts.append(f"{hours}h")
    parts.append(f"{mins}m")
    return " ".join(parts)


@app.route("/api/stats", methods=["GET"])
def system_stats():
    """Return system resource usage."""
    stats = {
        "cpu_percent": None,
        "ram_percent": None,
        "ram_used_mb": None,
        "ram_total_mb": None,
        "disk_percent": None,
        "disk_used_gb": None,
        "disk_total_gb": None,
        "cpu_temp": _get_cpu_temp(),
        "uptime": _get_uptime(),
    }
    if HAS_PSUTIL:
        stats["cpu_percent"] = psutil.cpu_percent(interval=0.3)
        mem = psutil.virtual_memory()
        stats["ram_percent"] = round(mem.percent, 1)
        stats["ram_used_mb"] = round(mem.used / 1048576)
        stats["ram_total_mb"] = round(mem.total / 1048576)
        disk = psutil.disk_usage("/")
        stats["disk_percent"] = round(disk.percent, 1)
        stats["disk_used_gb"] = round(disk.used / 1073741824, 1)
        stats["disk_total_gb"] = round(disk.total / 1073741824, 1)
    return jsonify(stats)


def _discover_ngrok_url():
    """Try to find the public ngrok URL and log it."""
    time.sleep(5)  # Let ngrok start up
    for attempt in range(12):  # Try for 1 minute
        try:
            req = urllib.request.urlopen("http://localhost:4040/api/tunnels", timeout=3)
            data = json.loads(req.read().decode())
            tunnels = data.get("tunnels", [])
            for tunnel in tunnels:
                url = tunnel.get("public_url", "")
                if url.startswith("https://"):
                    log.info("")
                    log.info("=" * 55)
                    log.info("  🚀 SITE IS LIVE AT: %s", url)
                    log.info("=" * 55)
                    log.info("")
                    return
        except Exception:
            pass
        time.sleep(5)
    log.warning("Could not find ngrok URL. Check http://localhost:4040 manually.")


if __name__ == "__main__":
    log.info("Starting PiCam Stream server on port 5000")
    # Start URL discovery in background
    threading.Thread(target=_discover_ngrok_url, daemon=True).start()
    app.run(host="0.0.0.0", port=5000, threaded=True, debug=False)
