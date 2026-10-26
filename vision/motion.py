"""Mișcare nesemantică pe 160x120: blur, diferență între cadre, prag."""

import cv2

import config


class MotionDetector:
    def __init__(self):
        if not 0 < config.MOTION_MIN_FRACTION <= 1:
            raise ValueError("MOTION_MIN_FRACTION trebuie să fie în (0, 1]")
        if not 0 < config.MOTION_PIXEL_THRESHOLD < 255:
            raise ValueError("MOTION_PIXEL_THRESHOLD trebuie să fie în (0, 255)")
        self._previous = None
        self._previous_at = None

    def update(self, frame):
        gray = cv2.resize(frame.gray, (160, 120), interpolation=cv2.INTER_AREA)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        result = {"observed_at": frame.captured_at, "active": False,
                  "changed_fraction": 0.0, "bbox": None}
        if self._previous is not None and frame.captured_at - self._previous_at < 1.0:
            diff = cv2.absdiff(gray, self._previous)
            mask = cv2.threshold(diff, config.MOTION_PIXEL_THRESHOLD, 255, cv2.THRESH_BINARY)[1]
            fraction = cv2.countNonZero(mask) / mask.size
            result["changed_fraction"] = round(fraction, 4)
            result["active"] = fraction >= config.MOTION_MIN_FRACTION
            if result["active"]:
                x, y, w, h = cv2.boundingRect(mask)
                result["bbox"] = [x / 160, y / 120, w / 160, h / 120]
        self._previous, self._previous_at = gray, frame.captured_at
        return result
