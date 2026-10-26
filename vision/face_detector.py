"""Detecție OpenCV pe luminanță; fără selecție de ținte sau acces la ochi."""

from dataclasses import dataclass
import math
from pathlib import Path

import config


@dataclass(frozen=True)
class Face:
    x: int
    y: int
    width: int
    height: int

    @property
    def center(self):
        return self.x + self.width / 2, self.y + self.height / 2

    @property
    def area(self):
        return self.width * self.height


@dataclass(frozen=True)
class FaceObservation:
    sequence: int
    captured_at: float
    frame_width: int
    frame_height: int
    faces: tuple[Face, ...]


class FaceDetector:
    def __init__(self):
        try:
            import cv2
        except ImportError as error:
            raise RuntimeError(
                "Lipsește OpenCV. Rulează: sudo apt install python3-opencv opencv-data"
            ) from error
        self._cv2 = cv2
        path = Path(config.FACE_CASCADE_PATH)
        if not path.is_file():
            raise FileNotFoundError(
                f"Lipsește cascada {path}. Rulează: sudo apt install opencv-data"
            )
        if not math.isfinite(config.FACE_SCALE_FACTOR) or config.FACE_SCALE_FACTOR <= 1:
            raise ValueError("FACE_SCALE_FACTOR trebuie să fie > 1 și finit.")
        if config.FACE_MIN_NEIGHBORS < 1 or config.FACE_OPENCV_THREADS < 1:
            raise ValueError("FACE_MIN_NEIGHBORS și FACE_OPENCV_THREADS trebuie să fie pozitive.")
        if len(config.FACE_MIN_SIZE) != 2 or any(v <= 0 for v in config.FACE_MIN_SIZE):
            raise ValueError("FACE_MIN_SIZE trebuie să conțină două dimensiuni pozitive.")
        cv2.setNumThreads(config.FACE_OPENCV_THREADS)
        self._cascade = cv2.CascadeClassifier(str(path))
        if self._cascade.empty():
            raise ValueError(f"Cascadă OpenCV invalidă: {path}")

    def detect(self, frame):
        gray = frame.gray
        height, width = gray.shape
        scale = 2 if width >= 320 and height >= 240 else 1
        small = gray[::scale, ::scale] if scale > 1 else gray
        if config.FACE_EQUALIZE_HIST:
            small = self._cv2.equalizeHist(small)
        min_w, min_h = config.FACE_MIN_SIZE
        boxes = self._cascade.detectMultiScale(
            small, scaleFactor=config.FACE_SCALE_FACTOR,
            minNeighbors=config.FACE_MIN_NEIGHBORS,
            minSize=(max(15, min_w // scale), max(15, min_h // scale)),
        )
        return FaceObservation(
            frame.sequence, frame.captured_at, width, height,
            tuple(Face(*(int(v) * scale for v in box)) for box in boxes),
        )
