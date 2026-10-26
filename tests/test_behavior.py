"""Arbitrarea comenzilor și priorităților fără a deschide hardware."""

from concurrent.futures import Future
import unittest
from unittest.mock import patch

import config

from behavior import BehaviorManager, BehaviorState
from core.events import EventBus
from eye_controller import EyeSystem
from vision.face_tracker import TrackingTarget


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class Eyes:
    def __init__(self):
        self.calls = []

    def set_pupil(self, name):
        self.calls.append(("pupil", name))

    def set_emotion(self, name):
        self.calls.append(("emotion", name))

    def look_at(self, x, y, *, tracking=False):
        self.calls.append(("look", x, y, tracking))

    def track_target(self, x, y, width, height):
        self.calls.append(("track", x, y, width, height))

    def blink(self):
        self.calls.append(("blink",))

    def sleep(self):
        self.calls.append(("sleep",))

    def wake(self):
        self.calls.append(("wake",))

    def update(self, dt):
        self.calls.append(("update", dt))


class Perception:
    target = TrackingTarget("no_target", None, None)

    def get_tracking_target(self):
        return self.target


class Voice:
    def __init__(self):
        self.status = {"state": "waiting_wakeword", "is_speaking": False}
        self.texts = []
        self.spoken = []

    def get_status(self):
        return self.status

    def listen(self):
        return self.texts.pop(0) if self.texts else None

    def speak(self, text, emotion=None):
        self.spoken.append(text)
        self.status = {"state": "speaking", "is_speaking": True}
        return Future()

    def suspend_listening(self):
        self.status = {"state": "suspended", "is_speaking": False}

    def resume_listening(self):
        self.status = {"state": "waiting_wakeword", "is_speaking": False}


class Body:
    def tongue_blep(self):
        future = Future()
        future.set_result("blep")
        return future


class BehaviorTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.eyes = Eyes()
        self.perception = Perception()
        self.voice = Voice()
        self.bus = EventBus()
        self.behavior = BehaviorManager(self.eyes, perception=self.perception,
                                        voice=self.voice, body=Body(),
                                        event_bus=self.bus, clock=self.clock)

    def tearDown(self):
        self.behavior.close()
        self.bus.close()

    def tick(self, advance=0.05):
        self.clock.now += advance
        return self.behavior.update(advance)

    def test_camera_gaze_expression_and_manual_priority(self):
        self.assertEqual(self.tick(), BehaviorState.IDLE)
        self.perception.target = TrackingTarget("tracking", .5, -.25)
        self.assertEqual(self.tick(), BehaviorState.ATTENTIVE)
        self.assertTrue(any(call[0] == "track" for call in self.eyes.calls))
        self.behavior.set_emotion("happy")
        self.assertEqual(self.tick(), BehaviorState.HAPPY)
        self.assertIn(("pupil", "happy"), self.eyes.calls)
        self.assertEqual(self.behavior.get_state()["gaze_owner"], "camera")
        self.behavior.look_at(-1, 1, duration=1)
        self.tick()
        self.assertEqual(self.behavior.get_state()["gaze_owner"], "manual")
        self.tick(1.1)
        self.assertEqual(self.behavior.get_state()["gaze_owner"], "camera")
        self.assertEqual(self.behavior.get_state()["blink_owner"], "eye_engine")

    def test_body_reactions_sleep_and_voice_priority(self):
        self.tick()
        self.bus.publish("shaken", {}, observed_at=self.clock.now, source="test")
        self.assertEqual(self.tick(), BehaviorState.STARTLED)
        self.assertEqual(self.behavior.get_state()["gaze_owner"], "reaction")
        self.behavior.sleep()
        with self.assertRaises(RuntimeError):
            self.behavior.speak("Nu vorbi încă")
        self.assertEqual(self.tick(), BehaviorState.SLEEP)
        self.assertIn(("sleep",), self.eyes.calls)
        self.assertEqual(self.voice.status["state"], "waiting_wakeword")
        with self.assertRaises(RuntimeError):
            self.behavior.speak("Nu vorbi")
        self.behavior.wake_up()
        self.assertEqual(self.tick(), BehaviorState.STARTLED)
        self.assertIn(("wake",), self.eyes.calls)
        self.assertEqual(self.tick(2), BehaviorState.IDLE)
        self.voice.status = {"state": "recording", "is_speaking": False}
        self.assertEqual(self.tick(), BehaviorState.LISTENING)
        self.voice.status = {"state": "waiting_wakeword", "is_speaking": False}
        self.voice.texts.append("salut")
        self.assertEqual(self.tick(), BehaviorState.THINKING)
        self.assertEqual(self.behavior.listen(), "salut")
        self.behavior.speak("Bună")
        self.assertEqual(self.tick(), BehaviorState.SPEAKING)
        self.assertEqual(self.voice.spoken, ["Bună"])

    def test_tongue_and_event_staleness(self):
        self.assertEqual(self.behavior.tongue("blep").result(), "blep")
        self.bus.publish("shaken", {}, observed_at=self.clock.now - 10, source="test")
        self.assertEqual(self.tick(), BehaviorState.IDLE)
        with self.assertRaises(ValueError):
            self.behavior.tongue("180")
        with self.assertRaises(ValueError):
            self.behavior.look_at(2, 0)

    def test_brain_thinking_suspends_audio_until_decision(self):
        self.behavior.begin_thinking()
        self.assertEqual(self.tick(), BehaviorState.THINKING)
        self.assertEqual(self.voice.status["state"], "suspended")
        self.behavior.finish_thinking()
        self.assertEqual(self.tick(), BehaviorState.IDLE)
        self.assertEqual(self.voice.status["state"], "waiting_wakeword")

    def test_expression_change_preserves_running_blink(self):
        eyes = EyeSystem(renderer=object())
        with BehaviorManager(eyes) as behavior:
            self.assertTrue(eyes.blink())
            self.assertTrue(eyes.left.animating)
            behavior.set_emotion("happy")
            behavior.update(0.01)
            self.assertEqual(eyes.left.pupil, "happy")
            self.assertTrue(eyes.left.animating)

    def test_wake_phrase_opens_sleeping_eyes_without_suspending_microphone(self):
        self.behavior.sleep()
        self.assertEqual(self.tick(), BehaviorState.SLEEP)
        self.assertEqual(self.voice.status["state"], "waiting_wakeword")
        # Doar wake_count fără comanda „wake up” NU trezește robotul din SLEEP
        self.voice.status = {"state": "listening", "is_speaking": False, "wake_count": 1}
        self.voice.texts.append("what time is it")
        self.assertEqual(self.tick(), BehaviorState.SLEEP)
        # Comanda „wake up” trezește robotul
        self.voice.texts.append("wake up")
        self.voice.status = {"state": "waiting_wakeword", "is_speaking": False, "wake_count": 2}
        self.assertEqual(self.tick(), BehaviorState.ATTENTIVE)
        self.assertIn(("wake",), self.eyes.calls)
        self.assertEqual(self.behavior.get_state()["gaze_owner"], "idle")
        self.assertEqual(self.tick(7), BehaviorState.IDLE)

    def test_auto_sleep_yawn_power_save_and_strict_wake(self):
        sleep_changes = []
        ready_state = [False]
        voice = Voice()
        voice._accepts_emotion = True
        with BehaviorManager(self.eyes, perception=self.perception, voice=voice,
                             body=Body(), event_bus=self.bus, clock=self.clock,
                             on_sleep_change=sleep_changes.append,
                             subsystems_ready=lambda: ready_state[0]) as beh:
            def step(advance=0.05):
                self.clock.now += advance
                return beh.update(advance)

            # După 7 minute (420s) -> SLEEPY + căscat
            self.assertEqual(step(421.0), BehaviorState.SLEEPY)
            self.assertEqual(len(voice.spoken), 1)
            self.assertIn("sleepy", voice.spoken[0].lower())
            voice.status = {"state": "waiting_wakeword", "is_speaking": False}

            # După 10 minute (600s total) -> SLEEP + oprire procese (power_saving=True)
            self.assertEqual(step(185.0), BehaviorState.SLEEP)
            self.assertEqual(sleep_changes, [True])
            self.assertTrue(beh.get_state()["power_saving"])

            # Mișcări minore (ex: tilted_left) NU îl trezesc din SLEEP
            self.bus.publish("tilted_left", {}, observed_at=self.clock.now, source="test")
            self.assertEqual(step(0.1), BehaviorState.SLEEP)

            # Scuturarea („shaken”) îl trezește, reactivează procesele și rulează animația closed -> sleepy -> open
            self.bus.publish("shaken", {}, observed_at=self.clock.now, source="test")
            self.assertEqual(step(0.1), BehaviorState.SLEEP)  # faza 1: ochi închiși (WAKE_CLOSED_HOLD)
            self.assertEqual(sleep_changes, [True, False])
            self.assertEqual(step(0.5), BehaviorState.SLEEPY)  # faza 2: ochi sleepy cât timp procesele pornesc
            self.assertEqual(beh.get_state()["gaze_owner"], "waking")
            ready_state[0] = True
            self.assertEqual(step(2.0), BehaviorState.IDLE)  # faza 3: ochi deschiși după ce procesele sunt gata

    def test_detected_object_can_request_short_gaze_without_direct_eye_access(self):
        self.bus.publish("object_detected", {"label": "cup", "position": {"x": .4, "y": -.3}},
                         observed_at=self.clock.now, source="test")
        self.assertEqual(self.tick(), BehaviorState.CURIOUS)
        self.assertEqual(self.behavior.get_state()["gaze_owner"], "manual")
        self.assertIn(("look", .4, -.3, True), self.eyes.calls)
        self.tick(3)
        self.assertEqual(self.behavior.get_state()["gaze_owner"], "idle")


if __name__ == "__main__":
    unittest.main()
