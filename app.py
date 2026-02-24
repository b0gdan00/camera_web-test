"""
Flask application -- live camera stream with quality/FPS controls.

Routes
------
/              - HTML page with the video player
/video_feed    - MJPEG stream
/snapshot      - Single JPEG snapshot
/api/settings  - GET/POST camera settings (quality, fps)
/api/logs      - GET server logs (last N lines)
"""

import atexit
import logging
import threading
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


# Install the buffer handler on the root logger so we capture everything
_log_buffer = _LogBuffer(maxlen=MAX_LOG_LINES)
_log_buffer.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
))
logging.root.addHandler(_log_buffer)
logging.root.setLevel(logging.INFO)

log = logging.getLogger("app")

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
    return jsonify(camera.get_settings())


@app.route("/api/logs", methods=["GET"])
def get_logs():
    """Return the last N log lines as JSON."""
    n = request.args.get("n", 100, type=int)
    n = max(1, min(n, MAX_LOG_LINES))
    lines = _log_buffer.get_lines(n)
    return jsonify({"lines": lines, "total": _log_buffer.count()})


if __name__ == "__main__":
    log.info("Starting PiCam Stream server on port 5000")
    app.run(host="0.0.0.0", port=5000, threaded=True, debug=False)
