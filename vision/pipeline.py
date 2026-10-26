"""Worker de detecție: publică doar ultimul rezultat, fără a controla ochii."""

import math
from threading import Event, Lock, Thread
import time

import config


class FaceDetectionWorker:
    def __init__(self, camera, detector):
        self.camera = camera
        self.detector = detector
        if not math.isfinite(config.FACE_DETECTION_FPS) or config.FACE_DETECTION_FPS <= 0:
            raise ValueError("FACE_DETECTION_FPS trebuie să fie pozitiv și finit.")
        self._period = 1.0 / config.FACE_DETECTION_FPS
        self._stop = Event()
        self._lock = Lock()
        self._thread = None
        self._latest = None
        self._error = None
        self._count = 0
        self._last_completed = None

    def start(self):
        if self._thread is not None:
            raise RuntimeError("Worker-ul este deja pornit.")
        self._stop.clear()
        self._latest = self._error = None
        self._count = 0
        self._last_completed = time.monotonic()
        self._thread = Thread(target=self._run, name="poro-face-detection", daemon=True)
        self._thread.start()
        return self

    def _run(self):
        sequence = -1
        try:
            while not self._stop.is_set():
                started = time.monotonic()
                self.camera.check_health()
                frame = self.camera.latest_frame()
                if frame is not None and frame.sequence != sequence:
                    result = self.detector.detect(frame)
                    sequence = frame.sequence
                    with self._lock:
                        self._latest = result
                        self._count += 1
                        self._last_completed = time.monotonic()
                self._stop.wait(max(0.0, self._period - (time.monotonic() - started)))
        except Exception as error:
            with self._lock:
                self._error = error

    def latest(self):
        with self._lock:
            return self._latest

    @property
    def count(self):
        with self._lock:
            return self._count

    def check_health(self):
        self.camera.check_health()
        with self._lock:
            error, completed = self._error, self._last_completed
        if error is not None:
            raise RuntimeError("Detecția fețelor a eșuat.") from error
        if completed is not None and time.monotonic() - completed > max(5.0, self._period * 3):
            raise RuntimeError("Worker-ul de detecție nu mai livrează rezultate.")

    def close(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            if self._thread.is_alive():
                raise RuntimeError("Worker-ul OpenCV nu s-a oprit în 2 secunde.")
            self._thread = None

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
