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
/api/viewers   - GET current viewers
/api/join      - POST join as viewer (name)
/api/heartbeat - POST keep viewer alive
"""

import atexit
import logging
import threading
import time
from collections import deque
from flask import Flask, Response, render_template, jsonify, request

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


if __name__ == "__main__":
    log.info("Starting PiCam Stream server on port 5000")
    app.run(host="0.0.0.0", port=5000, threaded=True, debug=False)
