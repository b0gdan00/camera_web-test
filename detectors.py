"""
Detection modules — pure OpenCV, no extra dependencies.

- FaceDetector:  Haar cascade (very fast)
- HandDetector:  Skin-color segmentation + contour analysis + convexity defects
"""

import cv2
import numpy as np
import math
import logging
import os

log = logging.getLogger("detectors")


# ══════════════════════════════════════════════════════════════════
#  Face Detector  (Haar Cascade)
# ══════════════════════════════════════════════════════════════════

class FaceDetector:
    """Detect faces and draw styled bounding boxes."""

    COLOR_BOX   = (255, 128, 50)   # BGR — bright orange
    COLOR_LABEL = (255, 255, 255)

    def __init__(self, scale_factor: float = 1.2, min_neighbors: int = 5,
                 min_size: tuple = (60, 60)):
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        if not os.path.exists(cascade_path):
            log.error("Haar cascade not found: %s", cascade_path)
        self._cascade = cv2.CascadeClassifier(cascade_path)
        self._scale = scale_factor
        self._min_neighbors = min_neighbors
        self._min_size = min_size
        log.info("FaceDetector ready")

    def process(self, frame: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self._cascade.detectMultiScale(
            gray,
            scaleFactor=self._scale,
            minNeighbors=self._min_neighbors,
            minSize=self._min_size,
        )

        for (x, y, w, h) in faces:
            # Main rectangle
            cv2.rectangle(frame, (x, y), (x + w, y + h), self.COLOR_BOX, 2, cv2.LINE_AA)

            # Corner accents
            c = max(15, w // 6)
            cv2.line(frame, (x, y), (x + c, y), self.COLOR_BOX, 3)
            cv2.line(frame, (x, y), (x, y + c), self.COLOR_BOX, 3)
            cv2.line(frame, (x + w, y), (x + w - c, y), self.COLOR_BOX, 3)
            cv2.line(frame, (x + w, y), (x + w, y + c), self.COLOR_BOX, 3)
            cv2.line(frame, (x, y + h), (x + c, y + h), self.COLOR_BOX, 3)
            cv2.line(frame, (x, y + h), (x, y + h - c), self.COLOR_BOX, 3)
            cv2.line(frame, (x + w, y + h), (x + w - c, y + h), self.COLOR_BOX, 3)
            cv2.line(frame, (x + w, y + h), (x + w, y + h - c), self.COLOR_BOX, 3)

            # Label
            label = "Face"
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(frame, (x, y - th - 8), (x + tw + 8, y), self.COLOR_BOX, -1)
            cv2.putText(frame, label, (x + 4, y - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, self.COLOR_LABEL, 1, cv2.LINE_AA)

        return frame


# ══════════════════════════════════════════════════════════════════
#  Hand Detector  (pure OpenCV — skin color + contour + defects)
# ══════════════════════════════════════════════════════════════════

class HandDetector:
    """
    Detect hands using skin-color segmentation in YCrCb + HSV space,
    then count fingers via convexity defects on the largest contour.
    No external ML dependencies needed.
    """

    COLOR_CONTOUR = (50, 255, 50)     # green
    COLOR_HULL    = (255, 255, 0)     # cyan
    COLOR_BBOX    = (50, 220, 255)    # yellow
    COLOR_TIP     = (0, 100, 255)     # orange-red
    COLOR_DEFECT  = (255, 0, 150)     # magenta
    COLOR_TEXT    = (255, 255, 255)

    MIN_CONTOUR_AREA = 5000  # ignore small blobs

    def __init__(self):
        # Morphology kernel for cleaning up mask
        self._kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        self._available = True
        log.info("HandDetector ready (OpenCV skin-color method)")

    @property
    def available(self) -> bool:
        return self._available

    def _skin_mask(self, frame: np.ndarray) -> np.ndarray:
        """Create a binary mask of skin-colored regions."""
        # Blur to reduce noise
        blurred = cv2.GaussianBlur(frame, (7, 7), 0)

        # YCrCb skin range
        ycrcb = cv2.cvtColor(blurred, cv2.COLOR_BGR2YCrCb)
        mask_ycrcb = cv2.inRange(ycrcb, (0, 133, 77), (255, 173, 127))

        # HSV skin range (additional filter)
        hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)
        mask_hsv = cv2.inRange(hsv, (0, 30, 60), (20, 150, 255))

        # Combine both masks
        mask = cv2.bitwise_or(mask_ycrcb, mask_hsv)

        # Morphological cleanup
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self._kernel, iterations=2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self._kernel, iterations=1)
        mask = cv2.dilate(mask, self._kernel, iterations=1)

        return mask

    def _count_fingers(self, contour: np.ndarray, hull_indices: np.ndarray,
                       frame: np.ndarray) -> int:
        """Count fingers using convexity defects."""
        if hull_indices is None or len(hull_indices) < 3:
            return 0

        defects = cv2.convexityDefects(contour, hull_indices)
        if defects is None:
            return 0

        finger_count = 0
        for i in range(defects.shape[0]):
            s, e, f, d = defects[i, 0]
            start = tuple(contour[s][0])
            end   = tuple(contour[e][0])
            far   = tuple(contour[f][0])
            depth = d / 256.0

            # Calculate the angle at the defect point
            a = math.sqrt((end[0] - start[0])**2 + (end[1] - start[1])**2)
            b = math.sqrt((far[0] - start[0])**2 + (far[1] - start[1])**2)
            c = math.sqrt((end[0] - far[0])**2   + (end[1] - far[1])**2)

            if b * c == 0:
                continue

            angle = math.acos(
                max(-1, min(1, (b**2 + c**2 - a**2) / (2 * b * c)))
            )

            # A finger gap has: angle < 80° and reasonable depth
            if angle < math.radians(80) and depth > 20:
                finger_count += 1
                # Draw the defect point
                cv2.circle(frame, far, 5, self.COLOR_DEFECT, -1)

        # Number of gaps + 1 = number of fingers (clamped to 5)
        fingers = min(finger_count + 1, 5)

        # If contour is very small or nearly circular → likely a fist (0 fingers)
        area = cv2.contourArea(contour)
        hull_area = cv2.contourArea(cv2.convexHull(contour))
        if hull_area > 0:
            solidity = area / hull_area
            if solidity > 0.9:
                fingers = 0  # closed fist — very solid shape

        return fingers

    def process(self, frame: np.ndarray) -> np.ndarray:
        """Detect hands and fingers, draw on frame."""
        mask = self._skin_mask(frame)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return frame

        # Process top 2 largest contours (up to 2 hands)
        contours = sorted(contours, key=cv2.contourArea, reverse=True)[:2]

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < self.MIN_CONTOUR_AREA:
                continue

            # Convex hull
            hull_drawing = cv2.convexHull(cnt)
            hull_indices = cv2.convexHull(cnt, returnPoints=False)

            # Draw contour and hull
            cv2.drawContours(frame, [cnt], -1, self.COLOR_CONTOUR, 2, cv2.LINE_AA)
            cv2.drawContours(frame, [hull_drawing], -1, self.COLOR_HULL, 1, cv2.LINE_AA)

            # Bounding box
            x, y, w, h = cv2.boundingRect(cnt)
            cv2.rectangle(frame, (x, y), (x + w, y + h), self.COLOR_BBOX, 2, cv2.LINE_AA)

            # Finger count
            fingers = self._count_fingers(cnt, hull_indices, frame)

            # Draw fingertips (topmost points of hull)
            for pt in hull_drawing:
                cv2.circle(frame, tuple(pt[0]), 4, self.COLOR_TIP, -1)

            # Label
            label = f"Hand | Fingers: {fingers}"
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
            cv2.rectangle(frame, (x, y - th - 10), (x + tw + 10, y), self.COLOR_BBOX, -1)
            cv2.putText(frame, label, (x + 5, y - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, self.COLOR_TEXT, 1, cv2.LINE_AA)

        return frame
