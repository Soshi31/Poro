"""Secvențe ale limbii executate incremental, niciun sleep în acțiuni."""

from collections import deque
from concurrent.futures import CancelledError, Future
from queue import Empty, Queue
from threading import Lock

import config


class TongueController:
    ACTIONS = frozenset({'tongue_in', 'tongue_out', 'tongue_blep', 'tongue_double_blep'})

    def __init__(self, servo):
        self._servo = servo
        self._queue = Queue(config.TONGUE_ACTION_QUEUE_SIZE)
        self._lock = Lock()
        self._closed = False
        self._current = None
        self._phases = deque()
        self._angle = None
        self._arrived_at = None
        self._last_at = None
        self._idle_since = None
        self._enabled = False
        self._position = 'unknown'

    def request(self, action):
        if action not in self.ACTIONS:
            raise ValueError('Acțiune limbă necunoscută')
        future = Future()
        with self._lock:
            if self._closed:
                raise RuntimeError('Controller-ul limbii este oprit')
            self._queue.put_nowait((action, future))
        return future

    def _sequence(self, action):
        inside, outside = config.TONGUE_IN_ANGLE, config.TONGUE_OUT_ANGLE
        blep = inside + config.TONGUE_BLEP_FRACTION * (outside - inside)
        if action == 'tongue_in':
            return [(inside, 0)]
        if action == 'tongue_out':
            return [(outside, 0)]
        one = [(blep, config.TONGUE_BLEP_HOLD_SECONDS), (inside, 0)]
        if action == 'tongue_blep':
            return one
        return [(blep, config.TONGUE_BLEP_HOLD_SECONDS), (inside, config.TONGUE_DOUBLE_BLEP_GAP_SECONDS)] + one

    def step(self, now):
        events = []
        dt = 0 if self._last_at is None else min(max(now - self._last_at, 0), 0.05)
        self._last_at = now
        if self._current is None:
            try:
                action, future = self._queue.get_nowait()
            except Empty:
                if (self._enabled and self._idle_since is not None
                        and config.TONGUE_RELEASE_IDLE_SECONDS is not None
                        and now - self._idle_since >= config.TONGUE_RELEASE_IDLE_SECONDS):
                    self._servo.release()
                    self._enabled = False
                    self._angle = None  # fără feedback, poziția nu mai este cunoscută
                return events
            if not future.set_running_or_notify_cancel():
                return events
            self._current = (action, future)
            self._phases = deque(self._sequence(action))
            self._arrived_at = None
            self._idle_since = None
            if self._angle is None:
                # Servo fără encoder: primul semnal merge la capătul sigur de retragere.
                # Așteptăm cursa maximă înainte de a începe animația.
                self._servo.write(config.TONGUE_IN_ANGLE)
                self._angle = config.TONGUE_IN_ANGLE
                self._phases.appendleft((self._angle, (config.TONGUE_MAX_ANGLE - config.TONGUE_MIN_ANGLE)
                                        / config.TONGUE_SPEED_DEG_PER_SECOND))
                self._arrived_at = now
            self._enabled = True
            events.append(('tongue_action_started', {'action': action}))
        target, hold = self._phases[0]
        if self._angle != target:
            distance = config.TONGUE_SPEED_DEG_PER_SECOND * dt
            angle = self._angle + max(-distance, min(distance, target - self._angle))
            self._servo.write(angle)
            self._angle = angle
            self._arrived_at = now if angle == target else None
        elif self._arrived_at is None:
            self._arrived_at = now
        if self._arrived_at is not None and now - self._arrived_at >= hold:
            self._phases.popleft()
            self._arrived_at = None
            if not self._phases:
                action, future = self._current
                self._current = None
                self._position = 'out' if action == 'tongue_out' else 'in'
                self._idle_since = now
                future.set_result({'action': action, 'position': self._position, 'open_loop': True})
                events.append(('tongue_action_completed', {'action': action, 'position': self._position}))
        return events

    def snapshot(self):
        return {'action': self._current[0] if self._current else None,
                'last_commanded_position': self._position, 'pwm_enabled': self._enabled,
                'queued_actions': self._queue.qsize(), 'position_feedback': False}

    def release_now(self):
        """Oprește imediat PWM-ul servo-ului pentru economisirea energiei în modul SLEEP."""
        if self._enabled:
            try:
                self._servo.release()
            except Exception:
                pass
            self._enabled = False
            self._angle = None

    def close(self, error=None):
        with self._lock:
            self._closed = True
        try:
            self._servo.close()
        finally:
            self._enabled = False
            if self._current is not None:
                _, future = self._current
                if not future.done():
                    future.set_exception(error if error is not None else CancelledError('Body oprit'))
                self._current = None
            while True:
                try:
                    _, future = self._queue.get_nowait()
                except Empty:
                    break
                future.cancel()
