"""IMU -> stări și evenimente. Fără I2C, thread-uri, servouri sau callback-uri externe."""

from collections import deque
import math
import time

import config


def norm(vector):
    return math.sqrt(sum(value * value for value in vector))


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


class MotionInterpreter:
    def __init__(self):
        self._last_at = None
        self._gravity = None
        self._accel = self._gyro = 0.0
        self._stable_since = None
        self._pending = {}
        self._sent = {}
        self._latches = {}
        self._moving = False
        self._ready = False
        self._held = False
        self._support = 'unknown'
        self._peaks = deque()
        self._last_peak = None
        self._shaken_at = -math.inf
        self._lift = None
        self._state = {'ready': False, 'moving': False, 'support_state': 'unknown', 'shaken': False}

    def _mapped(self, vector):
        return tuple(vector[abs(axis) - 1] * (1 if axis > 0 else -1) for axis in config.BODY_AXIS_MAP)

    def _dwell(self, key, condition, now, duration):
        if not condition:
            self._pending.pop(key, None)
            return False
        return now - self._pending.setdefault(key, now) >= duration

    def _emit(self, events, name, now, cooldown=0, **data):
        if now - self._sent.get(name, -math.inf) >= cooldown:
            self._sent[name] = now
            events.append((name, data))

    def _orientation(self, events, name, value, enter, leave, now):
        active = self._latches.get(name, False)
        if active and value <= leave:
            self._latches[name] = False
            self._pending.pop(name, None)
        elif not active and self._dwell(name, value >= enter, now, config.BODY_TILT_DWELL_SECONDS):
            self._latches[name] = True
            self._emit(events, name, now, config.BODY_TILT_COOLDOWN_SECONDS, angle_degrees=round(value, 1))

    def update(self, sample):
        now = sample.observed_at
        if self._last_at is not None and now <= self._last_at:
            return []
        dt = 1 / config.BODY_POLL_HZ if self._last_at is None else now - self._last_at
        if dt > config.BODY_SENSOR_TIMEOUT:
            # Nu interpreta revenirea senzorului drept impuls/stop confirmat.
            self.__init__()
            dt = 1 / config.BODY_POLL_HZ
        self._last_at = now
        gravity = self._mapped(sample.gravity)
        linear = self._mapped(sample.linear_acceleration)
        gyro = norm(sample.gyro)
        magnitude = norm(gravity)
        if not 8.0 < magnitude < 11.5:
            self._stable_since = None
            if self._ready:
                raise ValueError('Vector gravitațional BNO085 invalid după stabilizare')
            return []
        alpha = -math.expm1(-dt / config.BODY_SMOOTHING_SECONDS)
        beta = -math.expm1(-dt / config.BODY_GRAVITY_SMOOTHING_SECONDS)
        self._gravity = gravity if self._gravity is None else tuple(a + beta * (b - a) for a, b in zip(self._gravity, gravity))
        self._accel += alpha * (norm(linear) - self._accel)
        self._gyro += alpha * (gyro - self._gyro)
        quiet = self._accel < config.BODY_MOVE_ACCEL_EXIT and self._gyro < config.BODY_MOVE_GYRO_EXIT
        self._stable_since = (now if self._stable_since is None else self._stable_since) if quiet else None
        events = []
        if not self._ready:
            if self._stable_since is None or now - self._stable_since < config.BODY_WARMUP_SECONDS:
                return []
            self._ready = True
            self._support = 'assumed_supported'
            self._emit(events, 'body_ready', now, support_state=self._support)
        gx, gy, gz = self._gravity
        tilt = math.degrees(math.acos(max(-1, min(1, gz / max(norm(self._gravity), 1e-6)))))
        roll = math.degrees(math.atan2(-gx, gz))
        pitch = math.degrees(math.atan2(-gy, math.hypot(gx, gz)))
        self._orientation(events, 'upside_down', tilt, config.BODY_UPSIDE_ENTER_DEG, config.BODY_UPSIDE_EXIT_DEG, now)
        if tilt < 100:
            for name, value in (('tilted_left', -roll), ('tilted_right', roll),
                                ('tilted_forward', pitch), ('tilted_back', -pitch)):
                self._orientation(events, name, value, config.BODY_TILT_ENTER_DEG, config.BODY_TILT_EXIT_DEG, now)
        else:
            for name in ('tilted_left', 'tilted_right', 'tilted_forward', 'tilted_back'):
                self._latches[name] = False
                self._pending.pop(name, None)
        moving = self._accel >= config.BODY_MOVE_ACCEL_ENTER or self._gyro >= config.BODY_MOVE_GYRO_ENTER
        if not self._moving and self._dwell('move_start', moving, now, config.BODY_MOVE_START_SECONDS):
            self._moving = True
            self._pending.pop('move_stop', None)
            self._emit(events, 'movement_started', now)
        elif self._moving and self._dwell('move_stop', quiet, now, config.BODY_MOVE_STOP_SECONDS):
            self._moving = False
            self._pending.pop('move_start', None)
            self._emit(events, 'movement_stopped', now)
        self._shake(events, linear, now)
        if norm(linear) >= 1.1 or gyro >= 0.65 or self._moving:
            self._shaken_at = now
        vertical = dot(linear, gravity) / magnitude
        self._support_motion(events, vertical, tilt, now, dt, quiet)
        self._state = {
            'ready': self._ready, 'observed_at': now, 'moving': self._moving,
            'support_state': self._support, 'support_is_estimate': True,
            'roll_degrees': round(roll, 2), 'pitch_degrees': round(pitch, 2),
            'tilt_degrees': round(tilt, 2), 'orientations': sorted(k for k, v in self._latches.items() if v),
            'linear_acceleration_m_s2': round(self._accel, 3), 'gyro_rad_s': round(self._gyro, 3),
            'vertical_acceleration_m_s2': round(vertical, 3),
            'shaken': (now - self._shaken_at) < 2.0,
        }
        return events

    def _shake(self, events, linear, now):
        while self._peaks and now - self._peaks[0] > config.BODY_SHAKE_WINDOW_SECONDS:
            self._peaks.popleft()
        if norm(linear) < config.BODY_SHAKE_ACCEL:
            return
        # O lovitură izolată nu este shake: sunt necesare schimbări de sens.
        if self._last_peak is not None:
            at, previous = self._last_peak
            if now - at < 0.08:
                return
            if now - at <= config.BODY_SHAKE_WINDOW_SECONDS and dot(linear, previous) >= 0:
                return
        self._last_peak = (now, linear)
        self._peaks.append(now)
        if len(self._peaks) >= config.BODY_SHAKE_MIN_PEAKS:
            self._shaken_at = now
            self._emit(events, 'shaken', now, config.BODY_SHAKE_COOLDOWN_SECONDS,
                       acceleration_m_s2=round(norm(linear), 2), alternating_peaks=len(self._peaks))
            self._peaks.clear()
            self._lift = None

    def _support_motion(self, events, vertical, tilt, now, dt, quiet):
        if tilt > 100 or now - self._sent.get('shaken', -math.inf) < config.BODY_SHAKE_COOLDOWN_SECONDS:
            self._lift = None
            return
        direction = -1 if self._held else 1
        projected = vertical * direction
        if self._lift is None:
            if projected < config.BODY_LIFT_ACCEL:
                return
            self._lift = {'started': now, 'impulse': 0.0, 'braked': False, 'quiet_since': None}
        candidate = self._lift
        if now - candidate['started'] > config.BODY_LIFT_WINDOW_SECONDS:
            self._lift = None
            return
        candidate['impulse'] += max(0, projected) * min(dt, 0.05)
        if projected < -config.BODY_LIFT_BRAKE_ACCEL and candidate['impulse'] >= config.BODY_LIFT_MIN_IMPULSE:
            candidate['braked'] = True
        candidate['quiet_since'] = (candidate['quiet_since'] or now) if quiet else None
        settle = config.BODY_PUT_DOWN_SETTLE_SECONDS if self._held else config.BODY_LIFT_SETTLE_SECONDS
        if (candidate['braked'] and candidate['quiet_since'] is not None
                and now - candidate['quiet_since'] >= settle
                and now - self._sent.get('picked_up', -math.inf) >= config.BODY_LIFT_COOLDOWN_SECONDS
                and now - self._sent.get('put_down', -math.inf) >= config.BODY_LIFT_COOLDOWN_SECONDS):
            name = 'put_down' if self._held else 'picked_up'
            self._held = not self._held
            self._support = 'held_estimate' if self._held else 'supported_estimate'
            self._emit(events, name, now, inferred=True, basis='vertical_impulse_braking_and_settle',
                       impulse_m_s=round(candidate['impulse'], 3))
            self._lift = None

    def snapshot(self):
        return {**self._state, 'orientations': list(self._state.get('orientations', []))}
