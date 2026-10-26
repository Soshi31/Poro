"""Unit tests for the Android 'Poro Companion' mobile protocol (HTTP REST, BT SPP, BLE)."""

import json
import math
import unittest
from urllib.request import Request, urlopen

from behavior.manager import BehaviorManager
from mobile.bt_spp import BluetoothSPPServer
from mobile.http_server import MobileHTTPServer


class DummyEyes:
    def __init__(self):
        self.pupil = "normal"
        self.emotion = "neutral"
        self.gaze = (0.0, 0.0)
        self.sleeping = False

    def set_pupil(self, name):
        self.pupil = name

    def set_emotion(self, name):
        self.emotion = name
        if name in {"sleepy", "neutral", "sleep"}:
            self.pupil = "normal"

    def look_at(self, x, y, *, tracking=False):
        self.gaze = (x, y)

    def sleep(self):
        self.sleeping = True
        self.pupil = "normal"

    def wake(self):
        self.sleeping = False
        self.pupil = "normal"

    def blink(self):
        return True

    def update(self, dt=None):
        pass


class DummyBody:
    def __init__(self):
        self.actions = []
        self.low_power = False
        self.state = {"roll_degrees": 1.25, "pitch_degrees": -0.50, "shaken": False}

    def tongue_in(self):
        self.actions.append("in")

    def tongue_out(self):
        self.actions.append("out")

    def tongue_blep(self):
        self.actions.append("blep")

    def tongue_double_blep(self):
        self.actions.append("double_blep")

    def set_low_power(self, enabled):
        self.low_power = bool(enabled)

    def get_state(self):
        return dict(self.state)


class DummyVoice:
    _accepts_emotion = True

    def __init__(self):
        self.spoken = []
        self.suspended = False

    def speak(self, text, emotion=None):
        self.spoken.append((text, emotion))

    def listen(self):
        return None

    def get_status(self):
        return {"state": "waiting_wakeword", "is_speaking": False, "wake_count": 0}

    def suspend_listening(self):
        self.suspended = True

    def resume_listening(self):
        self.suspended = False


class DummyAgent:
    def __init__(self):
        self.submitted = []

    def submit(self, text):
        self.submitted.append(text)


class MobileProtocolTests(unittest.TestCase):
    def setUp(self):
        self.eyes = DummyEyes()
        self.body = DummyBody()
        self.voice = DummyVoice()
        self.agent = DummyAgent()
        self.behavior = BehaviorManager(self.eyes, body=self.body, voice=self.voice)
        self.behavior.update(0.03)
        self.http = MobileHTTPServer(behavior=self.behavior, body=self.body, agent=self.agent,
                                     host="127.0.0.1", port=0)

    def test_actions_and_emotions(self):
        # 1. FEED_SNAX (including non-repeating random voicelines)
        previous_line = None
        for _ in range(15):
            res = self.http.handle_action({"action": "FEED_SNAX", "parameter": None})
            self.assertTrue(res["ok"])
            current_line = self.behavior.last_text
            self.assertNotEqual(current_line, previous_line)
            previous_line = current_line
        self.behavior.update(0.03)
        self.assertEqual(self.eyes.pupil, "heart")
        self.assertIn("blep", self.body.actions)
        self.assertEqual(self.http.build_telemetry()["status"], "ATTENTIVE")

        # 2. DEVICE_NEARBY
        self.http.handle_action({"action": "DEVICE_NEARBY", "parameter": None})
        self.behavior.update(0.03)
        self.assertEqual(self.eyes.pupil, "star")
        self.assertAlmostEqual(self.eyes.gaze[1], -0.45, places=2)

        # 3. BLEP
        self.body.actions.clear()
        self.http.handle_action({"action": "BLEP", "parameter": None})
        self.assertEqual(self.body.actions, ["blep"])

        # 4. SLEEP & WAKE
        self.http.handle_action({"action": "SLEEP", "parameter": None})
        self.behavior.update(0.03)
        self.assertEqual(self.http.build_telemetry()["status"], "SLEEP")
        self.assertTrue(self.eyes.sleeping)

        self.http.handle_action({"action": "WAKE", "parameter": None})
        self.behavior.update(0.03)
        self.assertEqual(self.http.build_telemetry()["status"], "IDLE")
        self.assertFalse(self.eyes.sleeping)

        # 5. SET_EMOTION for all 6 parameters
        expected_pupils = {
            "normal": "normal",
            "heart": "heart",
            "star": "star",
            "sleepy": "normal",
            "dead": "x",
            "dizzy": "dizzy",
        }
        for param, expected_pupil in expected_pupils.items():
            self.http.handle_action({"action": "SET_EMOTION", "parameter": param})
            self.behavior.update(0.03)
            self.assertEqual(self.eyes.pupil, expected_pupil)

        # 6. MUTE & UNMUTE
        import config
        self.http.handle_action({"action": "MUTE", "parameter": None})
        self.assertFalse(config.VOICE_OUTPUT_ENABLED)
        self.http.handle_action({"action": "UNMUTE", "parameter": None})
        self.assertTrue(config.VOICE_OUTPUT_ENABLED)

    def test_gaze_clamping_and_telemetry(self):
        res = self.http.handle_gaze({"x": 3.0, "y": 4.0})
        self.assertAlmostEqual(math.hypot(res["x"], res["y"]), 1.0, places=2)
        self.behavior.update(0.03)
        self.assertAlmostEqual(self.eyes.gaze[0], 0.6, places=2)
        self.assertAlmostEqual(self.eyes.gaze[1], 0.8, places=2)

        # Release finger -> (0.0, 0.0)
        self.http.handle_gaze({"x": 0.0, "y": 0.0})
        self.behavior.update(0.03)
        self.assertEqual(self.eyes.gaze, (0.0, 0.0))

        # Telemetry format
        self.body.state["shaken"] = True
        telemetry = self.http.build_telemetry()
        self.assertEqual(set(telemetry.keys()), {"status", "battery_ok", "last_text", "bno"})
        self.assertEqual(telemetry["bno"], {"roll": 1.25, "pitch": -0.50, "shaken": True})

    def test_chat_sets_thinking_and_submits_to_llm(self):
        res = self.http.handle_chat({"message": "Salut Poro, ce mai faci?"})
        self.assertEqual(res["status"], "THINKING")
        self.assertEqual(self.agent.submitted, ["Salut Poro, ce mai faci?"])
        self.behavior.update(0.03)
        self.assertEqual(self.http.build_telemetry()["status"], "THINKING")

    def test_bt_spp_wifi_packet(self):
        calls = []
        spp = BluetoothSPPServer(
            behavior=self.behavior,
            wifi_handler=lambda ssid, pw: (calls.append((ssid, pw)) or True, "connected"),
        )
        res = spp.handle_packet_line('{"ssid": "MyHomeWiFi", "pass": "secret123"}\n')
        self.assertTrue(res["ok"])
        self.assertEqual(calls, [("MyHomeWiFi", "secret123")])

    def test_mobile_sleep_wake_and_sleepy_yawn_integration(self):
        sleep_events = []
        ready = [False]
        now = [100.0]
        beh = BehaviorManager(
            self.eyes, body=self.body, voice=self.voice, clock=lambda: now[0],
            on_sleep_change=sleep_events.append, subsystems_ready=lambda: ready[0],
        )
        http = MobileHTTPServer(behavior=beh, body=self.body, agent=self.agent, host="127.0.0.1", port=0)

        # 1. Butonul Sleepy din aplicație -> ochi sleepy + sunet de căscat
        self.voice.spoken.clear()
        http.handle_action({"action": "SET_EMOTION", "parameter": "sleepy"})
        beh.update(0.03)
        self.assertEqual(self.eyes.emotion, "sleepy")
        self.assertTrue(any("sleepy" in text.lower() and emo == "sleepy" for text, emo in self.voice.spoken))

        # 2. Butonul SLEEP din aplicație -> oprește procesele (camera + LLM) și activează low-power
        http.handle_action({"action": "SLEEP", "parameter": None})
        beh.update(0.03)
        self.assertEqual(http.build_telemetry()["status"], "SLEEP")
        self.assertEqual(sleep_events, [True])
        self.assertTrue(self.body.low_power)

        # Proximitatea pasivă BLE (DEVICE_NEARBY) NU îl trezește din SLEEP
        http.handle_action({"action": "DEVICE_NEARBY", "parameter": None})
        beh.update(0.03)
        self.assertEqual(http.build_telemetry()["status"], "SLEEP")

        # 3. Butonul WAKE din aplicație -> reactivează procesele, rulează animația closed -> sleepy -> open + voiceline
        self.voice.spoken.clear()
        http.handle_action({"action": "WAKE", "parameter": None})
        now[0] += 0.1
        beh.update(0.1)
        self.assertEqual(sleep_events, [True, False])
        self.assertFalse(self.body.low_power)
        self.assertTrue(any("awake" in text.lower() for text, _ in self.voice.spoken))
        # După 0.6s trece din ochi închiși în ochi sleepy cât timp procesele repornesc
        now[0] += 0.6
        beh.update(0.6)
        self.assertEqual(self.eyes.emotion, "sleepy")
        # Când procesele sunt gata, deschide ochii complet
        ready[0] = True
        now[0] += 2.0
        beh.update(2.0)
        self.assertEqual(http.build_telemetry()["status"], "IDLE")
        self.assertFalse(self.eyes.sleeping)


if __name__ == "__main__":
    unittest.main()
