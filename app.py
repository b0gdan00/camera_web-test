"""
Flask application — live camera stream with quality/FPS controls.

Routes
------
/              – HTML page with the video player
/video_feed    – MJPEG stream
/snapshot      – Single JPEG snapshot
/api/settings  – GET/POST camera settings (quality, fps)
"""

import atexit
from flask import Flask, Response, render_template, jsonify, request

from camera import Camera

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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True, debug=False)
