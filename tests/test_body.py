"""Regresii de interpretare, limite, oprire și bus comun. Fără hardware în unit tests."""

import math
from queue import Full
import time
import unittest
from unittest.mock import patch

import config
from core.events import EventBus, RobotEvent
from vision.events import VisionEvent
from vision.perception import PerceptionSystem
from hardware.bno085 import BNO085, IMUSample
from hardware.i2c import SOFTWARE_OVERLAY, open_body_i2c
from body.body_manager import BodyManager
from body.motion import MotionInterpreter
from body.settings import validate_settings
from body.tongue import TongueController


class MotionTests(unittest.TestCase):
    def setUp(self):
        self.motion = MotionInterpreter()
        self.t = 0
        self.events = []
        self.feed(2)
        self.assertTrue(self.motion.snapshot()['ready'])
        self.events.clear()

    def feed(self, duration, gravity=(0, 0, 9.81), linear=(0, 0, 0), gyro=(0, 0, 0)):
        for _ in range(round(duration * 50)):
            self.t += .02
            self.events.extend(name for name, _ in self.motion.update(IMUSample(self.t, gravity, linear, gyro)))

    def test_rest_noise_and_single_impact_do_not_raise_pickup_or_shake(self):
        self.feed(3, linear=(.05, -.03, .02), gyro=(.01, 0, 0))
        self.assertFalse(self.events)
        self.feed(.04, linear=(0, 0, 8))
        self.feed(3)
        self.assertNotIn('picked_up', self.events)
        self.assertNotIn('shaken', self.events)

    def test_all_directions_are_latched_and_rearm_after_neutral(self):
        for name, gravity in [('tilted_left', (6, 0, 7.8)), ('tilted_right', (-6, 0, 7.8)),
                              ('tilted_forward', (0, -6, 7.8)), ('tilted_back', (0, 6, 7.8)),
                              ('upside_down', (0, 0, -9.81))]:
            self.events.clear()
            self.feed(2, gravity=gravity)
            self.assertEqual(self.events.count(name), 1, (name, self.events))
            self.feed(2)
            self.feed(2, gravity=gravity)
            self.assertEqual(self.events.count(name), 2)
            self.feed(2)

    def test_short_tilt_jitter_and_threshold_band_do_not_repeat(self):
        self.feed(.08, gravity=(6, 0, 7.8))
        self.feed(1)
        self.assertNotIn('tilted_left', self.events)
        self.feed(1, gravity=(6, 0, 7.8))
        for _ in range(8):
            self.feed(.2, gravity=(3.7, 0, 9.08))
            self.feed(.2, gravity=(4.5, 0, 8.72))
        self.assertEqual(self.events.count('tilted_left'), 1)

    def test_movement_started_stopped_are_paired(self):
        self.feed(.5, linear=(1, 0, 0))
        self.feed(1.5)
        self.assertEqual(self.events, ['movement_started', 'movement_stopped'])

    def test_shake_requires_alternating_peaks_and_respects_cooldown(self):
        for _ in range(10):
            self.feed(.1, linear=(6, 0, 0))
            self.feed(.1, linear=(-6, 0, 0))
        self.assertEqual(self.events.count('shaken'), 1)
        self.assertNotIn('picked_up', self.events)

    def test_pickup_hold_then_putdown_needs_downward_motion(self):
        self.feed(.2, linear=(0, 0, 1.5))
        self.feed(.2, linear=(0, 0, -1.5))
        self.feed(3)
        self.assertEqual(self.events.count('picked_up'), 1)
        self.assertNotIn('put_down', self.events)
        self.assertEqual(self.motion.snapshot()['support_state'], 'held_estimate')
        self.feed(.2, linear=(0, 0, -1.5))
        self.feed(.2, linear=(0, 0, 1.5))
        self.feed(1.5)
        self.assertEqual(self.events.count('put_down'), 1)

    def test_stale_or_duplicate_samples_cannot_complete_pending_tilt(self):
        sample = IMUSample(self.t, (6, 0, 7.8), (0, 0, 0), (0, 0, 0))
        for _ in range(100):
            self.assertFalse(self.motion.update(sample))
        self.t += 3
        self.feed(.2, gravity=(6, 0, 7.8))
        self.assertFalse(self.motion.snapshot()['ready'])


class RecordingServo:
    def __init__(self):
        self.angles = []
        self.released = False

    def write(self, angle):
        assert config.TONGUE_MIN_ANGLE <= angle <= config.TONGUE_MAX_ANGLE
        self.angles.append(angle)
        self.released = False

    def release(self):
        self.released = True

    def close(self):
        self.release()


class SensorInputTests(unittest.TestCase):
    def test_software_bus_selects_existing_bus_three(self):
        with patch('hardware.i2c.Path') as path, \
                patch('adafruit_blinka.microcontroller.generic_linux.i2c.I2C') as backend:
            path.return_value.read_text.return_value = SOFTWARE_OVERLAY + '\n'
            path.return_value.exists.return_value = True
            bus = open_body_i2c()
            backend.assert_called_once_with(3)
            self.assertTrue(bus.try_lock())
            bus.unlock()
            bus.deinit()

    def test_bad_gravity_is_discarded_and_valid_next_sample_recovers(self):
        class Reports:
            _data_ready = False
            bad_packets = 0

            def __init__(self):
                self.received = {1: (time.monotonic(), (0, 0, 500)),
                                 2: (time.monotonic(), (0, 0, 0)),
                                 3: (time.monotonic(), (0, 0, 0))}

            def discard_packet(self, reason):
                self.bad_packets += 1

        sensor = BNO085.__new__(BNO085)
        sensor._driver = Reports()
        sensor._features = (1, 2, 3)
        sensor._last_stamp = -1
        self.assertIsNone(sensor.read())
        self.assertEqual(sensor.bad_packets, 1)
        sensor._driver.received[1] = (time.monotonic(), (0, 0, 9.81))
        self.assertIsNotNone(sensor.read())


class TongueTests(unittest.TestCase):
    def test_sequences_speed_bounds_and_idle_release(self):
        servo = RecordingServo()
        tongue = TongueController(servo)
        self.assertFalse(servo.angles)  # fără mișcare la construcție
        future = tongue.request('tongue_double_blep')
        events = []
        for tick in range(400):
            events.extend(name for name, _ in tongue.step(tick * .02))
        self.assertEqual(future.result()['position'], 'in')
        self.assertEqual(events, ['tongue_action_started', 'tongue_action_completed'])
        self.assertEqual(servo.angles[0], 175)
        self.assertEqual(servo.angles[-1], 175)
        for a, b in zip(servo.angles, servo.angles[1:]):
            self.assertLessEqual(abs(a - b), config.TONGUE_SPEED_DEG_PER_SECOND * .02 + 1e-6)
        self.assertTrue(servo.released)
        self.assertFalse(tongue.snapshot()['pwm_enabled'])

    def test_out_uses_zero_in_uses_175(self):
        servo = RecordingServo()
        tongue = TongueController(servo)
        out = tongue.request('tongue_out')
        inside = tongue.request('tongue_in')
        for tick in range(300):
            tongue.step(tick * .02)
        self.assertEqual(out.result()['position'], 'out')
        self.assertIn(0, servo.angles)
        self.assertEqual(inside.result()['position'], 'in')
        self.assertEqual(servo.angles[-1], 175)

    def test_queue_limit_cancellation_and_shutdown(self):
        servo = RecordingServo()
        tongue = TongueController(servo)
        cancelled = tongue.request('tongue_out')
        cancelled.cancel()
        tongue.step(0)
        self.assertFalse(servo.angles)
        futures = [tongue.request('tongue_blep') for _ in range(config.TONGUE_ACTION_QUEUE_SIZE)]
        with self.assertRaises(Full):
            tongue.request('tongue_in')
        tongue.step(.02)
        tongue.close()
        self.assertTrue(all(f.done() for f in futures))
        self.assertTrue(servo.released)
        with self.assertRaises(RuntimeError):
            tongue.request('tongue_out')

    def test_invalid_limits_rejected_before_hardware(self):
        with patch.object(config, 'TONGUE_IN_ANGLE', 180):
            with self.assertRaises(ValueError):
                BodyManager()
        with patch.object(config, 'BODY_AXIS_MAP', (1, 1, 3)):
            with self.assertRaises(ValueError):
                validate_settings()


class CommonBusTests(unittest.TestCase):
    def test_imu_timeout_degrades_without_stopping_tongue(self):
        class Bus:
            closed = False

            def deinit(self):
                self.closed = True

        class SilentIMU:
            bad_packets = 0

            def read(self):
                return None

        bus, servo = Bus(), RecordingServo()
        with patch('body.body_manager.open_body_i2c', return_value=bus), \
                patch('body.body_manager.BNO085', return_value=SilentIMU()), \
                patch('body.body_manager.TongueServo', return_value=servo), \
                patch.object(config, 'BODY_SENSOR_TIMEOUT', .08):
            body = BodyManager()
            with self.assertLogs(level='WARNING'):
                body.start()
                time.sleep(.3)
            self.assertTrue(body._thread.is_alive())  # limba/ochii/vocea continuă
            body.check_health()
            self.assertTrue(body.get_state()['stale'])
            body.close()
            self.assertTrue(servo.released)
            self.assertTrue(bus.closed)

    def test_imu_only_timeout_is_fatal(self):
        class Bus:
            def deinit(self):
                pass

        class SilentIMU:
            bad_packets = 0

            def read(self):
                return None

        with patch('body.body_manager.open_body_i2c', return_value=Bus()), \
                patch('body.body_manager.BNO085', return_value=SilentIMU()), \
                patch.object(config, 'BODY_SENSOR_TIMEOUT', .08):
            body = BodyManager(enable_tongue=False)
            events = body.subscribe()
            with self.assertLogs(level='ERROR'):
                body.start()
                deadline = time.monotonic() + 2
                while body._thread.is_alive() and time.monotonic() < deadline:
                    time.sleep(.01)
            self.assertFalse(body._thread.is_alive())
            self.assertIn('body_error', [e.type for e in events.drain()])
            with self.assertRaises(RuntimeError):
                body.check_health()
            body.close()

    def test_vision_and_body_share_bus_without_closing_each_other(self):
        bus = EventBus(extra_types=('brain_request',))
        self.addCleanup(bus.close)
        perception = PerceptionSystem(event_bus=bus)
        body = BodyManager(event_bus=bus)
        all_events, vision, body_events = bus.subscribe(), perception.subscribe(), body.subscribe()
        bus.publish('picked_up', {'inferred': True}, observed_at=1, source='body')
        bus.publish('person_seen', {}, observed_at=1, source='vision')
        self.assertEqual([e.type for e in all_events.drain()], ['picked_up', 'person_seen'])
        self.assertEqual([e.type for e in vision.drain()], ['person_seen'])
        self.assertEqual([e.type for e in body_events.drain()], ['picked_up'])
        body.close()
        perception.close()
        bus.publish('brain_request', {}, observed_at=2, source='brain')
        self.assertEqual(all_events.poll().type, 'brain_request')
        self.assertIs(VisionEvent, RobotEvent)


if __name__ == '__main__':
    unittest.main()
