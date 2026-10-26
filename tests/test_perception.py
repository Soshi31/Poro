"""Regresii deterministe pentru API/event bus. Nicio cameră simulată în aplicație."""

import json
import time
import unittest
from unittest.mock import patch

import numpy as np

import config
from vision.analyzers import SceneMetricsAnalyzer, validate_result
from vision.camera import AIFrame, CameraFrame
from vision.events import EventBus
from vision.face_detector import Face, FaceObservation
from vision.face_tracker import FaceTracker, TrackingTarget
from vision.motion import MotionDetector
from vision.scene import SceneState
from vision.scene_events import SceneEvents
from vision.slow import SlowVisionWorker


class EventTests(unittest.TestCase):
    def test_fanout_filter_and_immutable_payload(self):
        bus = EventBus(2)
        first = bus.subscribe("person_seen")
        second = bus.subscribe()
        source = {"nested": {"value": 1}}
        bus.publish("person_seen", source, observed_at=1, source="test")
        source["nested"]["value"] = 100
        event = first.poll()
        event.data["nested"]["value"] = 200
        self.assertEqual(second.poll().data["nested"]["value"], 1)
        bus.publish("motion_detected", {}, observed_at=1, source="test")
        self.assertIsNone(first.poll())
        self.assertEqual(second.poll().type, "motion_detected")
        json.dumps(event.to_dict(), allow_nan=False)
        bus.close()
        self.assertIsNone(first.poll())

    def test_slow_consumer_drops_oldest_without_blocking(self):
        bus = EventBus(2)
        subscription = bus.subscribe()
        for number in range(1000):
            bus.publish("person_position", {"number": number}, observed_at=1, source="test")
        self.assertEqual(subscription.dropped_count, 998)
        self.assertEqual([e.data["number"] for e in subscription.drain()], [998, 999])
        subscription.close()
        self.assertFalse(bus._subscriptions)
        bus.close()


class StateTests(unittest.TestCase):
    def test_seen_position_multiple_people_and_lost_events(self):
        bus = EventBus()
        subscription = bus.subscribe()
        emitter = SceneEvents(bus)
        state = SceneState()
        state.set_running(True)
        observation = FaceObservation(1, 10, 320, 240,
                                      (Face(10, 10, 40, 40), Face(100, 80, 60, 60)))
        state.update_fast(observation, TrackingTarget("tracking", 0.2, -0.1), None)
        emitter.update(state.snapshot(10.01), 10.01)
        self.assertEqual([e.type for e in subscription.drain()],
                         ["person_seen", "person_position", "multiple_people"])
        emitter.update(state.snapshot(10.02), 10.02)
        self.assertEqual(subscription.drain(), [])
        # Cadru fără fețe: holding nu emite person_lost înainte de expirare.
        state.update_fast(FaceObservation(2, 10.1, 320, 240, ()),
                          TrackingTarget("holding", 0.2, -0.1), None)
        emitter.update(state.snapshot(10.11), 10.11)
        events = subscription.drain()
        self.assertEqual([e.type for e in events], ["multiple_people"])
        self.assertFalse(events[0].data["active"])
        expired_at = 10 + config.FACE_TARGET_HOLD_SECONDS + 0.01
        emitter.update(state.snapshot(expired_at), expired_at)
        self.assertEqual([e.type for e in subscription.drain()], ["person_lost"])
        emitter.update(state.snapshot(expired_at + 1), expired_at + 1)
        self.assertEqual(subscription.drain(), [])
        bus.close()

    def test_person_hold_and_expiry_without_new_updates(self):
        state = SceneState()
        state.set_running(True)
        observation = FaceObservation(1, 10, 320, 240, (Face(100, 80, 60, 60),))
        with patch.object(config, "FACE_INVERT_X", True):
            state.update_fast(observation, TrackingTarget("tracking", 0.2, -0.1), None)
        initial = state.snapshot(10.1)
        self.assertTrue(initial["has_person"])
        self.assertEqual(initial["primary"]["position"]["x"], -0.2)
        self.assertEqual(initial["primary"]["eye_target"]["x"], 0.2)
        held = state.snapshot(10 + config.PERCEPTION_PEOPLE_TTL + 0.01)
        self.assertEqual(held["people"], [])
        self.assertEqual(held["primary"]["state"], "holding")
        self.assertTrue(held["has_person"])
        lost = state.snapshot(10 + config.FACE_TARGET_HOLD_SECONDS + 0.01)
        self.assertFalse(lost["has_person"])
        state.set_running(False)
        self.assertEqual(state.snapshot(10.1)["people"], [])

    def test_slow_expiry_capabilities_and_detached_json(self):
        path = "tests:detector"
        with patch.object(config, "SLOW_ANALYZERS", (path,)):
            state = SceneState()
            state.set_running(True)
            state.update_slow(10, [{"analyzer": path, "capabilities": ["objects"],
                                   "result": {"objects": [{"label": "test", "confidence": 0.9,
                                                           "bbox": [0.1, 0.1, 0.2, 0.2]}]}}])
            initial = state.snapshot(10.1)
            self.assertEqual(initial["capabilities"]["objects"], "fresh")
            self.assertEqual(initial["capabilities"]["gestures"], "not_configured")
            initial["objects"][0]["label"] = "modified"
            self.assertEqual(state.snapshot(10.1)["objects"][0]["label"], "test")
            stale = state.snapshot(10 + config.SLOW_RESULT_TTL + 1)
            self.assertEqual(stale["objects"], [])
            self.assertEqual(stale["slow"][path]["status"], "stale")
            self.assertNotIn("result", stale["slow"][path])
            state.slow_error("failed")
            self.assertEqual(state.snapshot(10.2)["objects"], [])
            self.assertEqual(state.snapshot(10.2)["capabilities"]["objects"], "error")
            json.dumps(stale, allow_nan=False)

    def test_existing_tracker_confirmation_hold_and_loss(self):
        # Fixtures de metadate pentru test, nu sursă de coordonate în runtime.
        with patch.object(config, "FACE_CONFIRM_DETECTIONS", 2):
            tracker = FaceTracker()
        face = Face(100, 80, 60, 60)
        first = FaceObservation(1, 10, 320, 240, (face,))
        second = FaceObservation(2, 10.1, 320, 240, (face,))
        self.assertEqual(tracker.update(first, 10.01).state, "no_target")
        self.assertEqual(tracker.update(first, 10.02).state, "no_target")
        tracked = tracker.update(second, 10.11)
        self.assertEqual(tracked.state, "tracking")
        held = tracker.update(FaceObservation(3, 10.2, 320, 240, ()), 10.21)
        self.assertEqual(held.state, "holding")
        self.assertEqual((held.x, held.y), (tracked.x, tracked.y))
        self.assertEqual(tracker.update(None, 10.1 + tracker.hold_seconds + 0.01).state, "no_target")


class MotionAndAnalysisTests(unittest.TestCase):
    def test_on_demand_inspection_waits_for_new_slow_result(self):
        from threading import Timer
        from vision.perception import PerceptionSystem

        perception = PerceptionSystem()
        perception._state.set_running(True)
        perception.check_health = lambda: None

        class Slow:
            def request(self):
                frame = AIFrame(1, time.monotonic() + 0.01,
                                np.zeros((48, 64, 3), dtype=np.uint8))
                timer = Timer(0.02, perception._slow_results,
                              args=(frame, [{"analyzer": "vision.analyzers:SceneMetricsAnalyzer",
                                             "capabilities": ["scene"],
                                             "result": {"scene": {"brightness": 0.5}}}]))
                timer.start()
                return True

        perception._slow = Slow()
        try:
            result = perception.inspect_scene(timeout=1)
            self.assertEqual(result["status"], "fresh")
            self.assertEqual(result["scene"]["scene_analysis"]["vision.analyzers:SceneMetricsAnalyzer"]["brightness"], 0.5)
        finally:
            perception.events.close()

    def test_on_demand_inspection_reports_unavailable_or_timeout(self):
        from vision.perception import PerceptionSystem

        perception = PerceptionSystem()
        perception.check_health = lambda: None
        try:
            self.assertEqual(perception.inspect_scene(timeout=0.1)["status"], "not_configured")

            class Slow:
                def request(self):
                    return True

            perception._slow = Slow()
            self.assertEqual(perception.inspect_scene(timeout=0.02)["status"], "timeout")
        finally:
            perception.events.close()

    def test_motion_and_return_to_still(self):
        detector = MotionDetector()
        image = np.zeros((240, 320), dtype=np.uint8)
        self.assertFalse(detector.update(CameraFrame(1, 1, image))["active"])
        changed = image.copy()
        changed[40:100, 50:150] = 255
        moving = detector.update(CameraFrame(2, 1.1, changed))
        self.assertTrue(moving["active"])
        self.assertIsNotNone(moving["bbox"])
        self.assertFalse(detector.update(CameraFrame(3, 1.2, changed))["active"])

    def test_scene_metrics_and_invalid_detections(self):
        frame = AIFrame(1, 1, np.zeros((48, 64, 3), dtype=np.uint8))
        result = SceneMetricsAnalyzer().analyze(frame)
        self.assertEqual(validate_result(result, ("scene",))["scene"]["brightness"], 0)
        self.assertFalse(result["scene"]["semantic_analysis"])
        for confidence, box in ((float("nan"), [0, 0, 1, 1]), (0.8, [0.9, 0, 1, 1]), (2, [0, 0, 1, 1])):
            with self.assertRaises(ValueError):
                validate_result({"objects": [{"label": "test", "confidence": confidence, "bbox": box}]}, ("objects",))
        with self.assertRaises(ValueError):
            validate_result({"objects": []}, ("scene",))

    def test_slow_process_success_invalid_result_and_timeout(self):
        frame = AIFrame(1, 1, np.zeros((48, 64, 3), dtype=np.uint8))
        with patch.object(config, "SLOW_ANALYZERS", ("vision.analyzers:SceneMetricsAnalyzer", "tests.slow_analyzers:InvalidAnalyzer")):
            worker = SlowVisionWorker(None, None, None)
        try:
            with patch.object(config, "SLOW_VISION_TIMEOUT", 10):
                result = worker._execute(frame)
            self.assertIn("scene", result[0]["result"])
            self.assertIn("error", result[1])
        finally:
            worker._shutdown_process()
        with patch.object(config, "SLOW_ANALYZERS", ("tests.slow_analyzers:BlockedAnalyzer",)):
            worker = SlowVisionWorker(None, None, None)
        try:
            with patch.object(config, "SLOW_VISION_TIMEOUT", 2):
                with self.assertRaises(TimeoutError):
                    worker._execute(frame)
        finally:
            worker._shutdown_process()
        self.assertIsNone(worker._process)


if __name__ == "__main__":
    unittest.main()
