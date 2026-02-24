"""
Camera abstraction layer.

On Raspberry Pi (aarch64/armv7l) uses Picamera2 for native, low-latency capture.
On other platforms falls back to OpenCV VideoCapture (USB / built-in webcam).
Supports runtime quality/FPS settings.
"""

import platform
import time
import threading
import logging
import cv2

from object_detector import ObjectDetector

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("camera")

_USE_PICAMERA2 = False
try:
    if platform.machine() in ("aarch64", "armv7l"):
        from picamera2 import Picamera2  # type: ignore
        _USE_PICAMERA2 = True
        log.info("Picamera2 found — will use native Pi camera")
except ImportError:
    log.info("Picamera2 not available — will use OpenCV")


class Camera:
    """Thread-safe camera wrapper."""

    def __init__(self, src: int = 0, width: int = 640, height: int = 480,
                 fps: int = 30, jpeg_quality: int = 80):
        self._width = width
        self._height = height
        self._fps = fps
        self._jpeg_quality = jpeg_quality
        self._rotation = 0  # 0, 90, 180, 270

        self._frame: bytes | None = None
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._running = False
        self._settings_lock = threading.Lock()

        # Object detector
        self.detector = ObjectDetector()

        if _USE_PICAMERA2:
            self._cap = None
            log.info("Initializing Picamera2...")
            try:
                self._picam = Picamera2()
                config = self._picam.create_video_configuration(
                    main={"size": (width, height), "format": "RGB888"},
                )
                self._picam.configure(config)
                log.info("Picamera2 configured: %dx%d", width, height)
            except Exception as e:
                log.error("Picamera2 init failed: %s — falling back to OpenCV", e)
                self._picam = None
                self._cap = self._open_cv_capture(src, width, height, fps)
        else:
            self._picam = None
            self._cap = self._open_cv_capture(src, width, height, fps)

    @staticmethod
    def _open_cv_capture(src, width, height, fps):
        sources = [src] if src != 0 else [0, 1, 2]
        for idx in sources:
            log.info("Trying OpenCV VideoCapture(%d)...", idx)
            cap = cv2.VideoCapture(idx)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
                cap.set(cv2.CAP_PROP_FPS, fps)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                ok, frame = cap.read()
                if ok and frame is not None:
                    log.info("✅ OpenCV camera opened on index %d (%dx%d)",
                             idx, int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                             int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
                    return cap
                else:
                    log.warning("  index %d opened but returned no frame", idx)
                    cap.release()
            else:
                log.warning("  index %d could not be opened", idx)
        log.error("❌ No working camera found via OpenCV!")
        return None

    # ── Settings API ─────────────────────────────────────────
    def set_jpeg_quality(self, quality: int) -> None:
        with self._settings_lock:
            self._jpeg_quality = max(10, min(100, quality))
            log.info("JPEG quality set to %d", self._jpeg_quality)

    def set_fps(self, fps: int) -> None:
        with self._settings_lock:
            self._fps = max(1, min(60, fps))
            log.info("Target FPS set to %d", self._fps)

    def set_rotation(self, degrees: int) -> None:
        """Set rotation: 0, 90, 180, or 270 degrees."""
        degrees = degrees % 360
        if degrees not in (0, 90, 180, 270):
            degrees = 0
        with self._settings_lock:
            self._rotation = degrees
            log.info("Rotation set to %d degrees", degrees)

    def get_settings(self) -> dict:
        with self._settings_lock:
            return {
                "jpeg_quality": self._jpeg_quality,
                "fps": self._fps,
                "rotation": self._rotation,
            }

    # ── Capture thread ───────────────────────────────────────
    def start(self) -> "Camera":
        if self._running:
            return self
        self._running = True

        if self._picam is not None:
            log.info("Starting Picamera2...")
            self._picam.start()
            log.info("Picamera2 started")

        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        log.info("Capture thread started (target FPS=%d)", self._fps)
        return self

    def stop(self) -> None:
        self._running = False
        if hasattr(self, "_thread"):
            self._thread.join(timeout=3)
        if self._picam is not None:
            self._picam.stop()
        elif self._cap is not None:
            self._cap.release()

    def _capture_loop(self) -> None:
        frame_count = 0
        error_count = 0

        while self._running:
            with self._settings_lock:
                encode_params = [cv2.IMWRITE_JPEG_QUALITY, self._jpeg_quality]
                interval = 1.0 / self._fps
                rotation = self._rotation

            t0 = time.monotonic()

            try:
                if self._picam is not None:
                    frame = self._picam.capture_array()
                elif self._cap is not None and self._cap.isOpened():
                    ok, frame = self._cap.read()
                    if not ok:
                        error_count += 1
                        if error_count % 100 == 1:
                            log.warning("OpenCV read() failed (%d)", error_count)
                        time.sleep(0.05)
                        continue
                else:
                    if error_count == 0:
                        log.error("No camera backend available")
                    error_count += 1
                    time.sleep(1)
                    continue
            except Exception as e:
                error_count += 1
                if error_count % 50 == 1:
                    log.error("Capture error: %s", e)
                time.sleep(0.1)
                continue

            error_count = 0

            # Apply rotation
            if rotation == 90:
                frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
            elif rotation == 180:
                frame = cv2.rotate(frame, cv2.ROTATE_180)
            elif rotation == 270:
                frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

            # Run object detection (if enabled)
            frame = self.detector.process_frame(frame)

            ok, buf = cv2.imencode(".jpg", frame, encode_params)
            if ok:
                jpeg = buf.tobytes()
                with self._lock:
                    self._frame = jpeg
                self._event.set()

                frame_count += 1
                if frame_count == 1:
                    log.info("✅ First frame captured!")
                elif frame_count % 300 == 0:
                    log.info("Captured %d frames", frame_count)

            elapsed = time.monotonic() - t0
            sleep_time = interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    # ── Public API ───────────────────────────────────────────
    def get_frame(self) -> bytes | None:
        with self._lock:
            return self._frame

    def wait_for_frame(self, timeout: float = 1.0) -> bytes | None:
        self._event.wait(timeout=timeout)
        self._event.clear()
        with self._lock:
            return self._frame
