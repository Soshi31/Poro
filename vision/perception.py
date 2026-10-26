"""API-ul public de percepție. Nu deține și nu importă actuatoarele robotului."""

from contextlib import ExitStack
import logging
import math
from threading import Condition, Event, Thread
import time

import config
from .camera import Camera
from .events import EventBus, EVENT_TYPES
from .face_detector import FaceDetector
from .face_tracker import FaceTracker
from .motion import MotionDetector
from .pipeline import FaceDetectionWorker
from .scene import SceneState
from .scene_events import SceneEvents
from .slow import SlowVisionWorker


class PerceptionSystem:
    """O instanță pentru durata sesiunii. subscribe() poate preceda start()."""

    def __init__(self, *, event_bus=None):
        for name in ("PERCEPTION_FAST_FPS", "PERCEPTION_PEOPLE_TTL", "PERSON_POSITION_INTERVAL",
                     "MOTION_FPS", "MOTION_EVENT_INTERVAL", "AI_FRAME_TIMEOUT", "SLOW_VISION_TIMEOUT",
                     "SLOW_STARTUP_TIMEOUT", "SLOW_RESULT_TTL"):
            value = getattr(config, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} trebuie să fie pozitiv și finit")
        if not math.isfinite(config.SLOW_VISION_INTERVAL) or config.SLOW_VISION_INTERVAL < 0:
            raise ValueError("SLOW_VISION_INTERVAL trebuie să fie finit și >= 0")
        self._owns_events = event_bus is None
        self.events = event_bus if event_bus is not None else EventBus(config.PERCEPTION_EVENT_CAPACITY)
        self._state = SceneState()
        self._scene_events = SceneEvents(self.events)
        self._stop = Event()
        self._thread = None
        self._error = None
        self._resources = None
        self._used = False
        self.camera = None
        self.face_worker = None
        self._slow = None
        self._slow_condition = Condition()
        self._slow_generation = 0
        self._slow_observed_at = None
        self._slow_failure = None

    def start(self):
        if self._used:
            raise RuntimeError("Folosește o instanță nouă PerceptionSystem pentru o nouă sesiune")
        self._used = True
        self._resources = ExitStack()
        try:
            detector = FaceDetector()
            self._tracker = FaceTracker()  # implementarea existentă, inclusiv hold și inversare
            self._motion = MotionDetector() if config.MOTION_ENABLED else None
            self.camera = self._resources.enter_context(Camera())
            self.face_worker = self._resources.enter_context(FaceDetectionWorker(self.camera, detector))
            self._slow = SlowVisionWorker(self.camera, self._slow_results, self._slow_error)
            self._state.set_running(True)
            self._thread = Thread(target=self._run_fast, name="poro-fast-vision", daemon=True)
            self._thread.start()
            self._resources.callback(self._close_fast)
            self._slow.start()
            self._resources.callback(self._slow.close)
        except BaseException:
            self.close()
            raise
        return self

    def _run_fast(self):
        last_motion_sequence = -1
        next_motion = 0.0
        period = 1.0 / config.PERCEPTION_FAST_FPS
        try:
            while not self._stop.is_set():
                now = time.monotonic()
                self.face_worker.check_health()
                observation = self.face_worker.latest()
                target = self._tracker.update(observation)
                motion = None
                if self._motion is not None and now >= next_motion:
                    frame = self.camera.latest_frame()
                    if frame is not None and frame.sequence != last_motion_sequence:
                        motion = self._motion.update(frame)
                        last_motion_sequence = frame.sequence
                    next_motion = now + 1 / config.MOTION_FPS
                self._state.update_fast(observation, target, motion)
                state = self._state.snapshot(now)
                self._scene_events.update(state, now)
                self._stop.wait(max(0.0, period - (time.monotonic() - now)))
        except Exception as error:
            self._error = error
            self._state.set_running(False, str(error))
            self.events.publish("perception_error", {"message": str(error)},
                                observed_at=time.monotonic(), source="fast_vision")

    def _slow_results(self, frame, results):
        if time.monotonic() - frame.captured_at >= config.SLOW_RESULT_TTL:
            self._slow_error(TimeoutError("Rezultatul SLOW a expirat înainte de publicare"))
            return
        self._state.update_slow(frame.captured_at, results)
        with self._slow_condition:
            self._slow_generation += 1
            self._slow_observed_at = frame.captured_at
            self._slow_failure = None
            self._slow_condition.notify_all()
        for item in results:
            source = item["analyzer"]
            if "error" in item:
                logging.warning("SLOW %s: %s", source, item["error"])
                self.events.publish("perception_error", {"message": item["error"]},
                                    observed_at=frame.captured_at, source=source)
                continue
            result = item["result"]
            for key, event_type in (("objects", "object_detected"), ("gestures", "gesture_detected")):
                if result.get(key):
                    self.events.publish(event_type, {key: result[key]},
                                        observed_at=frame.captured_at, source=source)
            if "scene" in result:
                self.events.publish("scene_updated", result["scene"],
                                    observed_at=frame.captured_at, source=source)

    def _slow_error(self, error):
        logging.warning("SLOW indisponibil (FAST continuă): %s", error)
        self._state.slow_error(str(error))
        with self._slow_condition:
            self._slow_generation += 1
            self._slow_observed_at = time.monotonic()
            self._slow_failure = str(error)
            self._slow_condition.notify_all()
        self.events.publish("perception_error", {"message": str(error)},
                            observed_at=time.monotonic(), source="slow_vision")

    def subscribe(self, event_types=None):
        return self.events.subscribe(EVENT_TYPES if event_types is None else event_types)

    def get_current_scene_state(self):
        return self._state.snapshot()

    def get_visible_people(self):
        return self.get_current_scene_state()["people"]

    def get_visible_objects(self):
        return self.get_current_scene_state()["objects"]

    def has_person(self):
        """Prezență confirmată, inclusiv holding; nu este identificare facială."""
        return self.get_current_scene_state()["has_person"]

    def primary_person_position(self):
        """x/y [-1,1] în imaginea camerei, sau None; fără inversarea ochilor."""
        primary = self.get_current_scene_state()["primary"]
        return primary["position"] if primary else None

    def get_tracking_target(self):
        return self._state.tracking_target()

    def capture_frame_for_ai(self, timeout=None):
        self.check_health()
        return self.camera.capture_frame_for_ai(timeout)

    def request_slow_analysis(self):
        return self._slow.request() if self._slow is not None else False

    def inspect_scene(self, timeout=None):
        """Cere analiza SLOW și așteaptă un rezultat nou, numai din worker-ul agentului."""
        timeout = config.BRAIN_VISUAL_TIMEOUT if timeout is None else timeout
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Timeout-ul analizei vizuale trebuie să fie pozitiv")
        self.check_health()
        requested_at = time.monotonic()
        with self._slow_condition:
            generation = self._slow_generation
        if not self.request_slow_analysis():
            return {"status": "not_configured", "scene": self.get_current_scene_state()}
        deadline = requested_at + timeout
        with self._slow_condition:
            while True:
                if self._slow_generation > generation and self._slow_observed_at >= requested_at:
                    failure = self._slow_failure
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return {"status": "timeout", "scene": self.get_current_scene_state()}
                self._slow_condition.wait(remaining)
        return {"status": "error" if failure else "fresh", "error": failure,
                "scene": self.get_current_scene_state()}

    def check_health(self):
        if self._error is not None:
            raise RuntimeError("FAST VISION a eșuat") from self._error
        if self._stop.is_set() or self.face_worker is None:
            raise RuntimeError("PerceptionSystem nu este pornit")
        self.face_worker.check_health()

    def _close_fast(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            if self._thread.is_alive():
                raise RuntimeError("FAST VISION nu s-a oprit")
            self._thread = None

    def close(self):
        self._stop.set()
        try:
            if self._resources is not None:
                self._resources.close()
                self._resources = None
        finally:
            self._state.set_running(False)
            if self._owns_events:
                self.events.close()

    def __enter__(self):
        return self.start()

    def __exit__(self, *args):
        self.close()
