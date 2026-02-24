"""
Object detection module using YOLOv4-tiny via OpenCV DNN.

Features:
  - Configurable target classes (default: cat)
  - "Orange cat" mode: detects cats + verifies orange/ginger fur via HSV color
  - Adjustable confidence threshold and detection interval
  - Draws bounding boxes with labels on frames
  - Thread-safe settings

Usage:
    from object_detector import ObjectDetector

    detector = ObjectDetector()
    if detector.available:
        annotated_frame = detector.detect(frame)
"""

import os
import logging
import threading
import time

import cv2
import numpy as np

log = logging.getLogger("detector")

MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
WEIGHTS   = os.path.join(MODEL_DIR, "yolov4-tiny.weights")
CONFIG    = os.path.join(MODEL_DIR, "yolov4-tiny.cfg")
NAMES     = os.path.join(MODEL_DIR, "coco.names")

# COCO classes of interest (index -> name)
# cat = 15 in coco.names (0-indexed)
CAT_CLASS_ID = 15

# HSV range for orange/ginger fur
# Hue: 5-25 (orange), Saturation: 40-255, Value: 80-255
ORANGE_HUE_LOW  = 5
ORANGE_HUE_HIGH = 28
ORANGE_SAT_LOW  = 40
ORANGE_VAL_LOW  = 80


class ObjectDetector:
    """YOLOv4-tiny object detector with orange cat detection."""

    def __init__(self):
        self._lock = threading.Lock()

        # Settings (thread-safe via _lock)
        self._enabled = False
        self._confidence = 0.45
        self._nms_threshold = 0.4
        self._detect_interval = 3          # detect every N-th frame
        self._target_classes: set[int] = {CAT_CLASS_ID}  # default: cat only
        self._orange_cat_mode = True       # highlight orange cats
        self._draw_all_objects = False      # if True, draw all 80 COCO classes

        # State
        self._frame_counter = 0
        self._last_detections: list[dict] = []
        self._last_detect_time = 0.0
        self._classes: list[str] = []
        self._net = None
        self._output_layers: list[str] = []
        self._available = False

        self._load_model()

    def _load_model(self) -> None:
        """Try to load YOLOv4-tiny model."""
        if not all(os.path.isfile(f) for f in [WEIGHTS, CONFIG, NAMES]):
            log.warning(
                "Model files not found in %s. "
                "Run 'python download_model.py' to download them.",
                MODEL_DIR,
            )
            return

        try:
            with open(NAMES, "r") as f:
                self._classes = [line.strip() for line in f.readlines()]

            log.info("Loading YOLOv4-tiny model...")
            t0 = time.monotonic()
            self._net = cv2.dnn.readNetFromDarknet(CONFIG, WEIGHTS)

            # Use CPU (Pi 4 has no CUDA)
            self._net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
            self._net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)

            layer_names = self._net.getLayerNames()
            out_indices = self._net.getUnconnectedOutLayers()
            self._output_layers = [
                layer_names[i - 1] for i in out_indices.flatten()
            ]

            elapsed = time.monotonic() - t0
            log.info(
                "YOLOv4-tiny loaded in %.1fs (%d classes)",
                elapsed, len(self._classes),
            )
            self._available = True

        except Exception as e:
            log.error("Failed to load YOLO model: %s", e)
            self._net = None

    # ── Properties ────────────────────────────────────────────

    @property
    def available(self) -> bool:
        return self._available

    # ── Settings API ──────────────────────────────────────────

    def get_settings(self) -> dict:
        with self._lock:
            return {
                "enabled": self._enabled,
                "confidence": self._confidence,
                "detect_interval": self._detect_interval,
                "orange_cat_mode": self._orange_cat_mode,
                "draw_all_objects": self._draw_all_objects,
                "available": self._available,
            }

    def set_enabled(self, on: bool) -> None:
        with self._lock:
            self._enabled = on
            if not on:
                self._last_detections = []
            log.info("Detection %s", "enabled" if on else "disabled")

    def set_confidence(self, val: float) -> None:
        with self._lock:
            self._confidence = max(0.1, min(0.95, val))
            log.info("Confidence threshold: %.2f", self._confidence)

    def set_detect_interval(self, n: int) -> None:
        with self._lock:
            self._detect_interval = max(1, min(30, n))
            log.info("Detect interval: every %d frames", self._detect_interval)

    def set_orange_cat_mode(self, on: bool) -> None:
        with self._lock:
            self._orange_cat_mode = on
            log.info("Orange cat mode: %s", on)

    def set_draw_all_objects(self, on: bool) -> None:
        with self._lock:
            self._draw_all_objects = on
            if on:
                self._target_classes = set(range(len(self._classes)))
            else:
                self._target_classes = {CAT_CLASS_ID}
            log.info("Draw all objects: %s", on)

    # ── Detection ─────────────────────────────────────────────

    def process_frame(self, frame: np.ndarray) -> np.ndarray:
        """
        Process a frame: run detection (if interval hit) and draw boxes.
        Returns annotated frame (or original if detection disabled).
        """
        with self._lock:
            enabled = self._enabled
            interval = self._detect_interval

        if not enabled or not self._available:
            return frame

        self._frame_counter += 1

        # Run detection on every N-th frame
        if self._frame_counter % interval == 0:
            detections = self._run_detection(frame)
            with self._lock:
                self._last_detections = detections
                self._last_detect_time = time.monotonic()

        # Draw cached detections on every frame
        with self._lock:
            detections = self._last_detections

        if detections:
            frame = self._draw_detections(frame, detections)

        return frame

    def _run_detection(self, frame: np.ndarray) -> list[dict]:
        """Run YOLOv4-tiny on a frame and return detections."""
        h, w = frame.shape[:2]

        with self._lock:
            confidence_thresh = self._confidence
            nms_thresh = self._nms_threshold
            target_classes = self._target_classes.copy()
            orange_mode = self._orange_cat_mode

        # Create blob (resize to 416x416 for YOLO)
        blob = cv2.dnn.blobFromImage(
            frame, 1.0 / 255.0, (416, 416),
            swapRB=True, crop=False,
        )
        self._net.setInput(blob)
        outputs = self._net.forward(self._output_layers)

        boxes = []
        confidences = []
        class_ids = []

        for output in outputs:
            for detection in output:
                scores = detection[5:]
                class_id = int(np.argmax(scores))
                conf = float(scores[class_id])

                if conf < confidence_thresh:
                    continue
                if class_id not in target_classes:
                    continue

                # Scale box to frame size
                cx = int(detection[0] * w)
                cy = int(detection[1] * h)
                bw = int(detection[2] * w)
                bh = int(detection[3] * h)
                x = cx - bw // 2
                y = cy - bh // 2

                boxes.append([x, y, bw, bh])
                confidences.append(conf)
                class_ids.append(class_id)

        # Non-maximum suppression
        indices = cv2.dnn.NMSBoxes(boxes, confidences, confidence_thresh, nms_thresh)

        detections = []
        for i in indices.flatten() if len(indices) > 0 else []:
            x, y, bw, bh = boxes[i]
            det = {
                "class_id": class_ids[i],
                "class_name": self._classes[class_ids[i]] if class_ids[i] < len(self._classes) else "unknown",
                "confidence": confidences[i],
                "box": (x, y, bw, bh),
                "is_orange_cat": False,
            }

            # Orange cat check
            if orange_mode and class_ids[i] == CAT_CLASS_ID:
                det["is_orange_cat"] = self._check_orange(frame, x, y, bw, bh)

            detections.append(det)

        return detections

    def _check_orange(self, frame: np.ndarray, x: int, y: int,
                       w: int, h: int) -> bool:
        """Check if the detected cat region has orange/ginger fur."""
        fh, fw = frame.shape[:2]
        # Clamp to frame bounds
        x1 = max(0, x)
        y1 = max(0, y)
        x2 = min(fw, x + w)
        y2 = min(fh, y + h)

        if x2 - x1 < 10 or y2 - y1 < 10:
            return False

        roi = frame[y1:y2, x1:x2]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

        # Create mask for orange pixels
        lower = np.array([ORANGE_HUE_LOW, ORANGE_SAT_LOW, ORANGE_VAL_LOW])
        upper = np.array([ORANGE_HUE_HIGH, 255, 255])
        mask = cv2.inRange(hsv, lower, upper)

        # If more than 15% of pixels are orange, it's an orange cat
        orange_ratio = np.count_nonzero(mask) / mask.size
        log.debug("Orange ratio for cat: %.2f", orange_ratio)

        return orange_ratio > 0.15

    def _draw_detections(self, frame: np.ndarray,
                          detections: list[dict]) -> np.ndarray:
        """Draw bounding boxes and labels on frame."""
        frame = frame.copy()

        for det in detections:
            x, y, w, h = det["box"]
            conf = det["confidence"]
            name = det["class_name"]
            is_orange = det["is_orange_cat"]

            # Colors
            if is_orange:
                color = (0, 140, 255)    # Orange (BGR)
                label = f"ORANGE CAT {conf:.0%}"
            elif det["class_id"] == CAT_CLASS_ID:
                color = (0, 255, 128)    # Green
                label = f"Cat {conf:.0%}"
            else:
                color = (255, 178, 50)   # Blue-ish
                label = f"{name} {conf:.0%}"

            # Draw box
            cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)

            # Draw label background
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
            cv2.rectangle(frame, (x, y - th - 10), (x + tw + 6, y), color, -1)

            # Draw label text
            cv2.putText(
                frame, label, (x + 3, y - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                (0, 0, 0) if is_orange else (255, 255, 255),
                1, cv2.LINE_AA,
            )

            # Extra highlight for orange cat
            if is_orange:
                cv2.rectangle(frame, (x - 2, y - 2), (x + w + 2, y + h + 2),
                              (0, 100, 255), 3)

        return frame

    def get_last_detections_summary(self) -> list[dict]:
        """Return summary of last detections for API."""
        with self._lock:
            return [
                {
                    "class": d["class_name"],
                    "confidence": round(d["confidence"], 3),
                    "orange_cat": d["is_orange_cat"],
                    "box": d["box"],
                }
                for d in self._last_detections
            ]
