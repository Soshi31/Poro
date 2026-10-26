"""Selecție și stabilizare a țintei; independent de cameră, OpenCV și GPIO."""

from dataclasses import dataclass
import math
import time

import config


def largest_face(faces):
    """Strategie înlocuibilă: primește fețe, întoarce o față sau None."""
    return max(faces, key=lambda face: face.area, default=None)


@dataclass(frozen=True)
class TrackingTarget:
    state: str  # tracking, holding, no_target
    x: float | None
    y: float | None


class FaceTracker:
    def __init__(self, selector=largest_face):
        self.selector = selector
        self.hold_seconds = float(config.FACE_TARGET_HOLD_SECONDS)
        self.deadband = float(config.FACE_TARGET_DEADBAND)
        self.confirm_detections = config.FACE_CONFIRM_DETECTIONS
        if not math.isfinite(self.hold_seconds) or self.hold_seconds <= 0:
            raise ValueError("FACE_TARGET_HOLD_SECONDS trebuie să fie pozitiv și finit.")
        if not math.isfinite(self.deadband) or not 0 <= self.deadband < 1:
            raise ValueError("FACE_TARGET_DEADBAND trebuie să fie în [0, 1).")
        if not isinstance(self.confirm_detections, int) or self.confirm_detections < 1:
            raise ValueError("FACE_CONFIRM_DETECTIONS trebuie să fie un întreg pozitiv.")
        self._sequence = -1
        self._last_seen = None
        self._position = None
        self._visible = False
        self._candidate_count = 0
        self._candidate_seen_at = None

    def update(self, observation, now=None):
        now = time.monotonic() if now is None else now
        if observation is not None and observation.sequence > self._sequence:
            self._sequence = observation.sequence
            face = self.selector(observation.faces)
            fresh = 0 <= now - observation.captured_at < self.hold_seconds
            self._visible = face is not None and fresh
            expired = self._last_seen is None or now - self._last_seen >= self.hold_seconds
            if not self._visible:
                self._candidate_count = 0
            elif expired:
                if (self._candidate_seen_at is None
                        or observation.captured_at - self._candidate_seen_at >= self.hold_seconds):
                    self._candidate_count = 0
                self._candidate_count += 1
                self._candidate_seen_at = observation.captured_at
                self._visible = self._candidate_count >= self.confirm_detections
            if self._visible:
                self._candidate_count = 0
                cx, cy = face.center
                x = max(-1.0, min(1.0, cx / observation.frame_width * 2 - 1))
                y = max(-1.0, min(1.0, cy / observation.frame_height * 2 - 1))
                if config.FACE_INVERT_X:
                    x = -x
                if config.FACE_INVERT_Y:
                    y = -y
                if self._position is not None and not expired:
                    # Deadband mobil, util inclusiv departe de centrul imaginii.
                    if abs(x - self._position[0]) < self.deadband:
                        x = self._position[0]
                    if abs(y - self._position[1]) < self.deadband:
                        y = self._position[1]
                self._position = (x, y)
                # Timpul capturii, nu momentul consumării: datele vechi expiră.
                self._last_seen = observation.captured_at
        if self._last_seen is None or now - self._last_seen >= self.hold_seconds:
            return TrackingTarget("no_target", None, None)
        return TrackingTarget("tracking" if self._visible else "holding", *self._position)
