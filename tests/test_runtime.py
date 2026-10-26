"""Un modul recuperabil nu ține blocată bucla principală."""

import time
import unittest
from unittest.mock import patch

import config
from poro_runtime import PerceptionProxy, RecoverySlot, VoiceProxy


class Component:
    def __init__(self, number):
        self.number = number
        self.closed = False
        self.suspended = False

    def check_health(self):
        if self.number == 1:
            raise RuntimeError("simulated failure")

    def close(self):
        self.closed = True

    def get_status(self):
        return {"state": "suspended" if self.suspended else "listening", "is_speaking": False}

    def listen(self, timeout=0):
        return None

    def suspend_listening(self):
        self.suspended = True

    def resume_listening(self):
        self.suspended = False


class RuntimeTests(unittest.TestCase):
    def test_voice_recovers_and_preserves_suspension(self):
        components = []

        def factory(stop):
            component = Component(len(components) + 1)
            components.append(component)
            return component

        with patch.object(config, "SYSTEM_HEALTH_INTERVAL_SECONDS", 0.01), \
             patch.object(config, "SYSTEM_RECOVERY_INITIAL_SECONDS", 0.01), \
             patch.object(config, "SYSTEM_RECOVERY_MAX_SECONDS", 0.02):
            slot = RecoverySlot("test-audio", factory, lambda component: component.check_health())
            voice = VoiceProxy(slot)
            slot.on_ready = voice.on_ready
            voice.suspend_listening()  # înainte ca audio să fie disponibil
            slot.start()
            try:
                deadline = time.monotonic() + 2
                while (len(components) < 2 or slot.status()["state"] != "ready") and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertGreaterEqual(len(components), 2)
                self.assertTrue(components[0].closed)
                self.assertTrue(components[1].suspended)
                voice.resume_listening()
                self.assertFalse(components[1].suspended)
            finally:
                slot.close()
            self.assertTrue(components[1].closed)

    def test_perception_proxy_has_safe_state_while_camera_recovers(self):
        slot = RecoverySlot("test-camera", lambda stop: None, lambda component: None)
        proxy = PerceptionProxy(slot)
        self.assertFalse(proxy.get_current_scene_state()["has_person"])
        self.assertEqual(proxy.get_tracking_target().state, "no_target")
        with self.assertRaises(RuntimeError):
            proxy.capture_frame_for_ai()

    def test_recovery_slot_suspend_and_resume_closes_and_restarts_component(self):
        created = []

        class OKComponent:
            def __init__(self, idx):
                self.idx = idx
                self.closed = False

            def check_health(self):
                pass

            def close(self):
                self.closed = True

        def factory(stop):
            comp = OKComponent(len(created) + 1)
            created.append(comp)
            return comp

        with patch.object(config, "SYSTEM_HEALTH_INTERVAL_SECONDS", 0.01):
            slot = RecoverySlot("test-llm", factory, lambda comp: comp.check_health())
            slot.start()
            try:
                deadline = time.monotonic() + 2
                while slot.status()["state"] != "ready" and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertEqual(slot.status()["state"], "ready")
                self.assertEqual(len(created), 1)
                self.assertFalse(created[0].closed)

                # Suspendarea oprește componenta (ex: camera / llama-server)
                slot.suspend()
                deadline = time.monotonic() + 2
                while slot.status()["state"] != "suspended" and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertEqual(slot.status()["state"], "suspended")
                self.assertIsNone(slot.current)
                self.assertTrue(created[0].closed)

                # Reactivarea pornește o instanță nouă
                slot.resume()
                deadline = time.monotonic() + 2
                while slot.status()["state"] != "ready" and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertEqual(slot.status()["state"], "ready")
                self.assertEqual(len(created), 2)
                self.assertFalse(created[1].closed)
            finally:
                slot.close()
            self.assertTrue(created[1].closed)


if __name__ == "__main__":
    unittest.main()
