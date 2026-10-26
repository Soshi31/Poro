"""API-ul robotului și animații non-blocking bazate pe time.monotonic().

EyeSystem nu deschide hardware. main.py deține DisplayManager și apelează
update(dt), render(), apoi show_both() în același loop al robotului.
"""

import math
import random
import time

import config
from eye_renderer import EyeRenderer


EMOTIONS = {
    "neutral": ("normal", "open"),
    "happy": ("happy", "open"),
    "love": ("heart", "open"),
    "excited": ("star", "open"),
    "dizzy": ("dizzy", "open"),
    "sleepy": ("normal", "half"),
    "dead": ("x", "open"),
    "sleep": ("normal", "closed"),
}


def _clamp(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("Coordonatele trebuie să fie finite.")
    return max(-1.0, min(1.0, value))


def _smoothing(rate, dt):
    return -math.expm1(-max(0.0, rate) * dt)


class Eye:
    """Starea unui ochi. Comenzile sunt apelate din loop-ul robotului."""

    def __init__(self):
        self.pupil = "normal"
        self.emotion = "neutral"
        self.target_x = self.target_y = 0.0
        self.current_x = self.current_y = 0.0
        self.animation_time = 0.0
        self._base_eyelid = "open"
        self._stages = ()
        self._stage_index = 0
        self._stage_deadline = 0.0
        self._animation_end = 0.0
        self._tracking_target = None
        self._last_target_time = time.monotonic()

    @property
    def sleeping(self):
        return self.emotion == "sleep"

    @property
    def animating(self):
        return bool(self._stages)

    @property
    def eyelid(self):
        if self._stages:
            return self._stages[self._stage_index][0]
        return self._base_eyelid

    def set_pupil(self, name):
        if name not in config.PUPIL_FILES:
            raise ValueError(f"Pupilă necunoscută: {name!r}")
        self.pupil = name
        self.animation_time = 0.0

    def set_emotion(self, name):
        if name not in EMOTIONS:
            raise ValueError(f"Emoție necunoscută: {name!r}")
        self.emotion = name
        self.pupil, self._base_eyelid = EMOTIONS[name]
        self.animation_time = 0.0
        # O comandă explicită nouă are prioritate asupra animației anterioare.
        self._stages = ()
        if self.sleeping:
            self._tracking_target = None
            self.target_x, self.target_y = self.current_x, self.current_y

    def look_at(self, x, y, *, tracking=False):
        """Setează target-ul; tracking=True activează filtrarea suplimentară dt."""
        x, y = _clamp(x), _clamp(y)
        if self.sleeping:
            return
        if tracking:
            self._tracking_target = (x, y)
        else:
            self.target_x, self.target_y = x, y
            self._tracking_target = None
        self._last_target_time = time.monotonic()

    def _start_stages(self, stages, now):
        self._stages = tuple(stages)
        self._stage_index = 0
        self._stage_deadline = now + self._stages[0][1]
        self._animation_end = now + sum(duration for _, duration in self._stages)

    def blink(self):
        return self._blink(time.monotonic())

    def _blink(self, now):
        if self.sleeping or self.animating:
            return False
        stages = []
        if self._base_eyelid == "open":
            stages.append(("open", config.BLINK_OPEN_TO_HALF))
        stages.extend((
            ("half", config.BLINK_HALF_TO_CLOSED),
            ("closed", config.BLINK_CLOSED_HOLD + config.BLINK_CLOSED_TO_HALF),
            ("half", config.BLINK_HALF_TO_OPEN),
        ))
        self._start_stages(stages, now)
        return True

    def sleep(self):
        self.set_emotion("sleep")

    def wake(self):
        self._wake(time.monotonic())

    def _wake(self, now):
        was_sleeping = self.sleeping
        was_sleepy = self.emotion == "sleepy"
        self.set_emotion("neutral")
        self.look_at(0.0, 0.0)
        if was_sleeping:
            self._start_stages((
                ("closed", config.WAKE_CLOSED_HOLD),
                ("half", config.WAKE_HALF_HOLD * 0.55),
                ("closed", config.BLINK_CLOSED_HOLD * 2.5),
                ("half", config.WAKE_HALF_HOLD * 0.45),
            ), now)
        elif was_sleepy:
            self._start_stages((
                ("half", config.WAKE_HALF_HOLD * 0.45),
            ), now)

    def update(self, dt, now):
        # Termene absolute: un frame întârziat nu prelungește clipitul.
        while self._stages and now >= self._stage_deadline:
            self._stage_index += 1
            if self._stage_index == len(self._stages):
                self._stages = ()
            else:
                self._stage_deadline += self._stages[self._stage_index][1]
        if self.sleeping:
            return
        if self._tracking_target is not None:
            alpha = _smoothing(config.TRACKING_SMOOTHING, dt)
            self.target_x += (self._tracking_target[0] - self.target_x) * alpha
            self.target_y += (self._tracking_target[1] - self.target_y) * alpha
        alpha = _smoothing(config.GAZE_SMOOTHING, dt)
        self.current_x += (self.target_x - self.current_x) * alpha
        self.current_y += (self.target_y - self.current_y) * alpha
        self.animation_time += dt


class EyeSystem:
    def __init__(self, renderer=None):
        self.renderer = renderer if renderer is not None else EyeRenderer()
        self.left = Eye()
        self.right = Eye()
        self.auto_blink = config.AUTO_BLINK
        self.idle_enabled = config.IDLE_ENABLED
        self._random = random.Random()
        now = time.monotonic()
        self._last_update = now
        self._next_blink = self._new_blink_deadline(now)
        self._double_blink_at = None
        self._next_idle = now + config.IDLE_TARGET_TIMEOUT
        self._micro_pending = False
        self._idle_anchor = (0.0, 0.0)

    def _new_blink_deadline(self, now):
        return now + self._random.uniform(config.BLINK_MIN_INTERVAL, config.BLINK_MAX_INTERVAL)

    def set_pupil(self, name):
        self.left.set_pupil(name)
        self.right.set_pupil(name)

    def set_emotion(self, name):
        self.left.set_emotion(name)
        self.right.set_emotion(name)
        self._double_blink_at = None
        self._next_blink = self._new_blink_deadline(time.monotonic())

    def look_at(self, x, y, *, tracking=False):
        x, y = _clamp(x), _clamp(y)
        self.left.look_at(x, y, tracking=tracking)
        self.right.look_at(x, y, tracking=tracking)
        self._micro_pending = False

    def blink(self):
        now = time.monotonic()
        left = self.left._blink(now)
        right = self.right._blink(now)
        self._double_blink_at = None
        self._next_blink = self._new_blink_deadline(now)
        return left or right

    def wink_left(self):
        self._double_blink_at = None
        self._next_blink = self._new_blink_deadline(time.monotonic())
        return self.left.blink()

    def wink_right(self):
        self._double_blink_at = None
        self._next_blink = self._new_blink_deadline(time.monotonic())
        return self.right.blink()

    def sleep(self):
        self.set_emotion("sleep")

    def wake(self):
        now = time.monotonic()
        self.left._wake(now)
        self.right._wake(now)
        self._double_blink_at = None
        self._next_blink = self._new_blink_deadline(now)
        self._next_idle = now + config.IDLE_TARGET_TIMEOUT
        self._micro_pending = False

    def track_target(self, face_x, face_y, frame_width, frame_height):
        values = tuple(float(v) for v in (face_x, face_y, frame_width, frame_height))
        if not all(math.isfinite(v) for v in values) or min(values[2:]) <= 0:
            raise ValueError("Coordonate finite și dimensiuni pozitive necesare pentru tracking.")
        x = values[0] / values[2] * 2 - 1
        y = values[1] / values[3] * 2 - 1
        if config.TRACKING_MIRROR_X:
            x = -x

        def mapped(value, sensitivity):
            value = _clamp(value * sensitivity)
            deadzone = config.TRACKING_DEADZONE
            if not 0 <= deadzone < 1:
                raise ValueError("TRACKING_DEADZONE trebuie să fie în [0, 1).")
            if abs(value) <= deadzone:
                return 0.0
            return math.copysign((abs(value) - deadzone) / (1 - deadzone), value)

        x = mapped(x, config.TRACKING_SENSITIVITY_X)
        y = mapped(y, config.TRACKING_SENSITIVITY_Y)
        self.look_at(x, y, tracking=True)
        self._next_idle = time.monotonic() + config.IDLE_TARGET_TIMEOUT

    def _update_idle(self, now):
        if not self.idle_enabled or now < self._next_idle:
            return
        available = [eye for eye in (self.left, self.right) if not eye.sleeping
                     and now - eye._last_target_time >= config.IDLE_TARGET_TIMEOUT]
        if not available:
            self._micro_pending = False
            return
        if self._micro_pending:
            amount = config.IDLE_MICROSACCADE_AMOUNT
            x = self._idle_anchor[0] + self._random.uniform(-amount, amount)
            y = self._idle_anchor[1] + self._random.uniform(-amount, amount)
            self._micro_pending = False
        else:
            if self._random.random() < config.IDLE_CENTER_CHANCE:
                x = y = 0.0
            else:
                x = self._random.uniform(-config.IDLE_GAZE_X, config.IDLE_GAZE_X)
                y = self._random.uniform(-config.IDLE_GAZE_Y, config.IDLE_GAZE_Y)
            self._idle_anchor = (x, y)
            self._micro_pending = self._random.random() < config.IDLE_MICROSACCADE_CHANCE
        for eye in available:
            eye.target_x, eye.target_y = _clamp(x), _clamp(y)
            eye._tracking_target = None
        if self._micro_pending:
            pause = self._random.uniform(
                config.IDLE_MICROSACCADE_PAUSE_MIN, config.IDLE_MICROSACCADE_PAUSE_MAX
            )
        else:
            pause = self._random.uniform(config.IDLE_PAUSE_MIN, config.IDLE_PAUSE_MAX)
        self._next_idle = now + pause

    def _update_auto_blink(self, now):
        if not self.auto_blink:
            self._double_blink_at = None
            self._next_blink = self._new_blink_deadline(now)
            return
        available = [eye for eye in (self.left, self.right) if not eye.sleeping]
        if not available:
            self._double_blink_at = None
            return
        if any(eye.animating for eye in available):
            return
        if self._double_blink_at is not None:
            if now < self._double_blink_at:
                return
            for eye in available:
                eye._blink(now)
            self._double_blink_at = None
            self._next_blink = self._new_blink_deadline(now)
        elif now >= self._next_blink:
            for eye in available:
                eye._blink(now)
            if self._random.random() < config.DOUBLE_BLINK_CHANCE:
                self._double_blink_at = max(eye._animation_end for eye in available) + self._random.uniform(
                    config.DOUBLE_BLINK_PAUSE_MIN, config.DOUBLE_BLINK_PAUSE_MAX
                )
            self._next_blink = self._new_blink_deadline(now)

    def update(self, dt=None):
        now = time.monotonic()
        dt = now - self._last_update if dt is None else float(dt)
        if not math.isfinite(dt) or dt < 0:
            raise ValueError("dt trebuie să fie finit și pozitiv sau zero.")
        self._last_update = now
        self._update_idle(now)
        self.left.update(dt, now)
        self.right.update(dt, now)
        self._update_auto_blink(now)

    def render(self):
        """Returnează două imagini PIL RGB 240x240, gata pentru DisplayManager."""
        return self.renderer.render(self.left), self.renderer.render(self.right)
