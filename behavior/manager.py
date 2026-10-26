"""Arbitru unic pentru ochi; consumă stări/evente, nu accesează hardware direct."""

from collections import deque
from enum import Enum
import math
from queue import Empty, Queue
import random
import re
from threading import Lock, get_ident
import time

import config
from vision.eye_control import EyeTrackingController


class BehaviorState(str, Enum):
    IDLE = "IDLE"
    ATTENTIVE = "ATTENTIVE"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"
    HAPPY = "HAPPY"
    CURIOUS = "CURIOUS"
    SLEEPY = "SLEEPY"
    SLEEP = "SLEEP"
    STARTLED = "STARTLED"


_PUPILS = {
    BehaviorState.IDLE: "normal", BehaviorState.ATTENTIVE: "normal",
    BehaviorState.LISTENING: "normal", BehaviorState.THINKING: "star",
    BehaviorState.SPEAKING: "normal", BehaviorState.HAPPY: "happy",
    BehaviorState.CURIOUS: "star", BehaviorState.STARTLED: "dizzy",
}
_MOODS = {"neutral", "happy", "curious", "sleepy", "excited", "surprised", "sad"}
_MOBILE_EMOTION_MAP = {
    "normal": ("neutral", "normal"),
    "heart": ("happy", "heart"),
    "star": ("curious", "star"),
    "sleepy": ("sleepy", None),
    "dead": ("neutral", "x"),
    "dizzy": ("neutral", "dizzy"),
}
_TELEMETRY_STATUS_MAP = {
    BehaviorState.IDLE: "IDLE",
    BehaviorState.SLEEPY: "IDLE",
    BehaviorState.ATTENTIVE: "ATTENTIVE",
    BehaviorState.HAPPY: "ATTENTIVE",
    BehaviorState.CURIOUS: "ATTENTIVE",
    BehaviorState.STARTLED: "ATTENTIVE",
    BehaviorState.LISTENING: "LISTENING",
    BehaviorState.THINKING: "THINKING",
    BehaviorState.SPEAKING: "SPEAKING",
    BehaviorState.SLEEP: "SLEEP",
}
_TONGUE_ACTIONS = {"in": "tongue_in", "out": "tongue_out",
                   "blep": "tongue_blep", "double_blep": "tongue_double_blep"}
_SNAX_VOICELINES = (
    "Yum! Tasty Snax!",
    "Nom nom! So good!",
    "Yay! Poro-Snax!",
    "Mmm, thank you!",
    "Blep! More Snax please!",
)


class BehaviorManager:
    """Apelat o dată per frame în thread-ul EyeSystem/DisplayManager.

    Producătorii (vision/body/voice) nu primesc EyeSystem. Comenzile publice
    pot veni din alt thread; se aplică numai la următorul update().
    """

    def __init__(self, eyes, *, perception=None, voice=None, body=None, event_bus=None,
                 clock=time.monotonic, on_sleep_change=None, subsystems_ready=None):
        for name in ("BEHAVIOR_COMMAND_QUEUE_SIZE", "BEHAVIOR_COMMANDS_PER_TICK",
                     "BEHAVIOR_TEXT_QUEUE_SIZE", "BEHAVIOR_EVENTS_PER_TICK"):
            value = getattr(config, name)
            if not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} trebuie să fie un întreg pozitiv")
        for name in ("BEHAVIOR_EVENT_MAX_AGE", "BEHAVIOR_STARTLED_SECONDS",
                     "BEHAVIOR_CURIOUS_SECONDS", "BEHAVIOR_HAPPY_SECONDS",
                     "BEHAVIOR_THINKING_TIMEOUT"):
            value = getattr(config, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} trebuie să fie pozitiv și finit")
        self.eyes = eyes
        self.perception = perception
        self.voice = voice
        self.body = body
        self._clock = clock
        self._on_sleep_change = on_sleep_change
        self._subsystems_ready = subsystems_ready
        self._events = event_bus.subscribe() if event_bus is not None else None
        self._commands = Queue(maxsize=config.BEHAVIOR_COMMAND_QUEUE_SIZE)
        self._lock = Lock()
        self._texts = deque(maxlen=config.BEHAVIOR_TEXT_QUEUE_SIZE)
        self._loop_thread = None
        self._closed = False
        self._mood = "neutral"
        self._sleeping = False
        self._auto_sleeping = False
        self._sleep_requested = False
        self._power_saving = False
        self._waking = False
        self._wake_closed_until = 0.0
        self._wake_min_until = 0.0
        self._wake_max_until = 0.0
        self._wake_speech_until = 0.0
        self._sleepy_yawned = False
        self._sleepy_yawn_until = 0.0
        self._gaze_mode = "camera"
        self._manual_gaze = (0.0, 0.0)
        self._manual_until = 0.0
        self._startled_until = self._curious_until = self._happy_until = 0.0
        self._thinking_until = 0.0
        self._wake_attention_until = 0.0
        self._last_wake_count = 0
        self._last_presence_at = clock()
        self._brain_thinking = False
        self._brain_voice_paused = False
        self._state = BehaviorState.IDLE
        self._gaze_owner = "idle"
        self._expression_owner = "behavior"
        self._tracking = EyeTrackingController(eyes)
        self._eyelid_mode = "open"
        self._pupil = None
        self._pupil_override = None
        self._pupil_override_until = 0.0
        self._snax_attentive_until = 0.0
        self._last_snax_line = None
        self._snax_rng = random.Random()
        self._last_text = "Blep! Ready to play!"
        self._snapshot = {"state": "IDLE", "mood": "neutral", "gaze_owner": "idle",
                          "expression_owner": "behavior", "blink_owner": "eye_engine",
                          "tongue_owner": "behavior" if body is not None else None,
                          "audio_owner": "voice" if voice is not None else None,
                          "has_person": False, "voice_state": "stopped", "pending_texts": 0}

    def _submit(self, name, *args):
        with self._lock:
            if self._closed:
                raise RuntimeError("BehaviorManager este închis")
            self._commands.put_nowait((name, args))
            if name == "sleep":
                self._sleep_requested = True
            elif name in {"wake", "mood", "mobile_emotion", "feed_snax"}:
                self._sleep_requested = False

    def set_emotion(self, name):
        if name in _MOBILE_EMOTION_MAP and name not in _MOODS:
            return self.set_mobile_emotion(name)
        if name not in _MOODS:
            raise ValueError(f"Emoție necunoscută: {name!r}; alege {sorted(_MOODS)}")
        self._submit("mood", name)

    def set_mobile_emotion(self, parameter):
        if parameter not in _MOBILE_EMOTION_MAP:
            raise ValueError(f"Parametru emoție mobilă necunoscut: {parameter!r}")
        self._submit("mobile_emotion", parameter)

    def set_muted(self, muted):
        import subprocess
        muted = bool(muted)
        config.VOICE_OUTPUT_ENABLED = not muted
        if self.voice is not None and hasattr(self.voice, "set_muted"):
            try:
                self.voice.set_muted(muted)
            except Exception:
                pass
        for control in ("Master", "PCM", "Speaker"):
            try:
                subprocess.run(
                    ["amixer", "-q", "set", control, "mute" if muted else "unmute"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2, check=False,
                )
            except Exception:
                pass
        if muted:
            try:
                subprocess.run(
                    ["pkill", "-TERM", "-f", "aplay.*sndrpigooglevoi"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2, check=False,
                )
            except Exception:
                pass

    def feed_snax(self):
        self._submit("feed_snax")
        with self._lock:
            candidates = [line for line in _SNAX_VOICELINES if line != self._last_snax_line] or list(_SNAX_VOICELINES)
            line = self._snax_rng.choice(candidates)
            self._last_snax_line = line
            self._last_text = line
        if self.body is not None:
            try:
                self.tongue("blep")
            except Exception:
                pass
        if self.voice is not None:
            try:
                self.speak(line, "excited")
            except Exception:
                pass
        return line

    def device_nearby(self):
        with self._lock:
            if self._sleep_requested or self._sleeping:
                return
        self._submit("device_nearby")
        if self.body is not None:
            try:
                self.tongue("blep")
            except Exception:
                pass
        if self.voice is not None:
            try:
                self.speak("Sniff, sniff! Ooh, hello friend!", "curious")
            except Exception:
                pass

    def look_at_person(self):
        self._submit("camera")

    def look_at(self, x, y, *, duration=2.0):
        values = (float(x), float(y), float(duration))
        if not all(math.isfinite(v) for v in values) or not all(-1 <= v <= 1 for v in values[:2]) or values[2] <= 0:
            raise ValueError("Privirea cere x/y în [-1,1] și durată pozitivă finită")
        self._submit("look", *values)

    def release_gaze(self):
        self._submit("idle_gaze")

    def sleep(self):
        self._submit("sleep")

    def wake_up(self, *, silent=False):
        self._submit("wake", bool(silent))

    def blink(self):
        self._submit("blink")

    def finish_thinking(self):
        self._submit("finish_thinking")

    def begin_thinking(self):
        """Brain lucrează; suspendă temporar VAD/STT ca să păstreze CPU pentru ochi."""
        self._submit("begin_thinking")

    def tongue(self, action):
        if action not in _TONGUE_ACTIONS:
            raise ValueError(f"Acțiune limbă necunoscută: {action!r}")
        if self.body is None:
            raise RuntimeError("BodyManager nu este conectat")
        return getattr(self.body, _TONGUE_ACTIONS[action])()

    def speak(self, text, emotion=None):
        if self.voice is None:
            raise RuntimeError("VoiceManager nu este conectat")
        with self._lock:
            if self._closed:
                raise RuntimeError("BehaviorManager este închis")
            if self._sleep_requested:
                raise RuntimeError("Poro doarme; apelează wake_up() înainte de speak()")
            mood = emotion or self._mood
            self._last_text = str(text).strip()
        if getattr(self.voice, "_accepts_emotion", False):
            result = self.voice.speak(text, mood)
        else:
            result = self.voice.speak(text)
        self._submit("finish_thinking")
        return result

    @property
    def last_text(self):
        with self._lock:
            return self._last_text

    def set_last_text(self, text):
        if isinstance(text, str) and text.strip():
            with self._lock:
                self._last_text = text.strip()

    def listen(self):
        """Întoarce următorul text deja transcris, fără a bloca bucla ochilor."""
        with self._lock:
            return self._texts.popleft() if self._texts else None

    _WAKE_COMMANDS = (
        "wake up", "wakeup", "wakey", "good morning", "get up",
        "open your eyes", "trezeste", "scularea", "buna dimineata",
    )

    @classmethod
    def _is_wake_voice_command(cls, text):
        if not isinstance(text, str):
            return False
        norm = re.sub(r"[^a-z0-9 ]+", " ", text.casefold())
        norm = re.sub(r"\s+", " ", norm).strip()
        if norm in {"wake", "awake", "up"}:
            return True
        return any(phrase in norm for phrase in cls._WAKE_COMMANDS)

    @property
    def is_waking(self):
        return self._waking

    def _enter_sleep(self, now, *, auto=False):
        if self._brain_voice_paused and self.voice is not None:
            self.voice.resume_listening()
        self._sleeping = True
        self._auto_sleeping = bool(auto)
        self._waking = False
        self._brain_thinking = False
        self._brain_voice_paused = False
        self._thinking_until = 0.0
        self._pupil_override = None
        self._pupil_override_until = 0.0
        self._snax_attentive_until = 0.0
        self._wake_attention_until = self._curious_until = self._happy_until = 0.0
        if not self._power_saving:
            self._power_saving = True
            if self.body is not None and hasattr(self.body, "set_low_power"):
                try:
                    self.body.set_low_power(True)
                except Exception:
                    pass
            if self._on_sleep_change is not None:
                try:
                    self._on_sleep_change(True)
                except Exception:
                    pass

    def _start_wake_up(self, now, *, play_voiceline=True):
        was_sleeping = self._sleeping or self._power_saving
        self._sleeping = False
        self._auto_sleeping = False
        self._sleep_requested = False
        self._sleepy_yawned = False
        self._sleepy_yawn_until = 0.0
        self._last_presence_at = now
        if self._power_saving:
            self._power_saving = False
            if self.body is not None and hasattr(self.body, "set_low_power"):
                try:
                    self.body.set_low_power(False)
                except Exception:
                    pass
            if self._on_sleep_change is not None:
                try:
                    self._on_sleep_change(False)
                except Exception:
                    pass
        if was_sleeping:
            if self._subsystems_ready is not None:
                self._waking = True
                self._wake_closed_until = now + config.WAKE_CLOSED_HOLD
                self._wake_min_until = now + getattr(config, "BEHAVIOR_WAKE_MIN_SECONDS", 1.8)
                self._wake_max_until = now + getattr(config, "BEHAVIOR_WAKE_MAX_WAIT_SECONDS", 8.0)
            if play_voiceline:
                wake_line = getattr(config, "BEHAVIOR_WAKE_VOICELINE",
                                    "Yaaawn! Good morning! I am awake and ready to play!")
                with self._lock:
                    self._last_text = wake_line
                if self.voice is not None and getattr(self.voice, "_accepts_emotion", False):
                    try:
                        self.voice.speak(wake_line, "happy")
                        self._wake_speech_until = now + 3.5
                    except Exception:
                        pass
                if self.body is not None:
                    try:
                        self.tongue("blep")
                    except Exception:
                        pass

    def _drain_commands(self, now):
        for _ in range(config.BEHAVIOR_COMMANDS_PER_TICK):
            try:
                name, args = self._commands.get_nowait()
            except Empty:
                break
            if name == "mood":
                self._mood = args[0]
                self._pupil_override = None
                self._pupil_override_until = 0.0
                self._start_wake_up(now, play_voiceline=False)
            elif name == "mobile_emotion":
                param = args[0]
                mood, pupil_override = _MOBILE_EMOTION_MAP[param]
                self._mood = mood
                self._pupil_override = None if param == "normal" else pupil_override
                self._pupil_override_until = math.inf if self._pupil_override else 0.0
                self._wake_attention_until = self._curious_until = self._happy_until = 0.0
                self._snax_attentive_until = 0.0
                self._start_wake_up(now, play_voiceline=False)
                if param == "sleepy":
                    self._sleepy_yawn_until = now + 4.0
                    yawn_text = getattr(config, "BEHAVIOR_SLEEPY_YAWN_TEXT", "Yaaawn... I am getting so sleepy...")
                    with self._lock:
                        self._last_text = yawn_text
                    if self.voice is not None and getattr(self.voice, "_accepts_emotion", False):
                        try:
                            self.voice.speak(yawn_text, "sleepy")
                        except Exception:
                            pass
            elif name == "feed_snax":
                self._start_wake_up(now, play_voiceline=False)
                self._mood = "happy"
                self._pupil_override = "heart"
                self._pupil_override_until = now + 8.0
                self._wake_attention_until = now + 8.0
                self._snax_attentive_until = now + 8.0
            elif name == "device_nearby":
                if self._sleeping:
                    continue
                self._mood = "curious"
                self._pupil_override = "star"
                self._pupil_override_until = now + 4.0
                self._curious_until = now + 4.0
                self._gaze_mode = "manual"
                self._manual_gaze = (0.0, -0.45)
                self._manual_until = now + 3.0
                self._last_presence_at = now
                self._sleepy_yawned = False
            elif name == "camera":
                self._gaze_mode = "camera"
                self._manual_until = 0.0
            elif name == "look":
                self._gaze_mode = "manual"
                self._manual_gaze = args[:2]
                self._manual_until = now + args[2]
                self._last_presence_at = now
                self._sleepy_yawned = False
            elif name == "idle_gaze":
                self._gaze_mode = "idle"
            elif name == "sleep":
                self._enter_sleep(now, auto=False)
            elif name == "wake":
                silent = bool(args[0]) if args else False
                self._mood = "neutral"
                self._pupil_override = None
                self._pupil_override_until = 0.0
                self._snax_attentive_until = 0.0
                self._wake_attention_until = self._curious_until = self._happy_until = 0.0
                self._start_wake_up(now, play_voiceline=not silent)
            elif name == "blink":
                if not self._sleeping:
                    self.eyes.blink()
            elif name == "finish_thinking":
                if self._brain_voice_paused and not self._sleeping and self.voice is not None:
                    self.voice.resume_listening()
                self._brain_voice_paused = False
                self._brain_thinking = False
                self._thinking_until = 0.0
            elif name == "begin_thinking":
                if not self._sleeping:
                    self._brain_thinking = True
                    self._thinking_until = now + config.LLM_REQUEST_TIMEOUT + 5
                    if self.voice is not None and not self._brain_voice_paused:
                        self.voice.suspend_listening()
                        self._brain_voice_paused = True

    def _react(self, event, now):
        if now - event.observed_at > config.BEHAVIOR_EVENT_MAX_AGE:
            return
        if self._sleeping:
            # În modul SLEEP, doar scuturarea fizică („shaken”) trezește robotul din IMU.
            if event.type == "shaken":
                self._start_wake_up(now, play_voiceline=True)
                self._startled_until = max(self._startled_until, now + config.BEHAVIOR_STARTLED_SECONDS)
            return
        if event.type in {"shaken", "upside_down", "picked_up", "movement_started",
                          "tilted_left", "tilted_right", "tilted_forward", "tilted_back"}:
            self._last_presence_at = now
            self._sleepy_yawned = False
            self._startled_until = max(self._startled_until, now + config.BEHAVIOR_STARTLED_SECONDS)
        elif event.type == "person_seen":
            self._last_presence_at = now
            self._sleepy_yawned = False
            self._happy_until = max(self._happy_until, now + config.BEHAVIOR_HAPPY_SECONDS)
        elif event.type == "multiple_people" and event.data.get("active"):
            self._last_presence_at = now
            self._sleepy_yawned = False
            self._curious_until = max(self._curious_until, now + config.BEHAVIOR_CURIOUS_SECONDS)
        elif event.type == "object_detected":
            # Numai pentru detectori reali conectați la event bus; nu ghicim obiecte.
            self._curious_until = max(self._curious_until, now + config.BEHAVIOR_CURIOUS_SECONDS)
            position = event.data.get("position")
            if isinstance(position, dict):
                x, y = position.get("x"), position.get("y")
                if (type(x) in (int, float) and type(y) in (int, float)
                        and math.isfinite(x) and math.isfinite(y)
                        and -1 <= x <= 1 and -1 <= y <= 1):
                    self._gaze_mode = "manual"
                    self._manual_gaze = (x, y)
                    self._manual_until = now + config.BEHAVIOR_CURIOUS_SECONDS
        elif event.type == "put_down":
            self._last_presence_at = now
            self._sleepy_yawned = False
            self._happy_until = max(self._happy_until, now + config.BEHAVIOR_HAPPY_SECONDS)

    def _voice_status(self, now):
        if self.voice is None:
            return {"state": "stopped", "is_speaking": False}
        status = self.voice.get_status()
        wake_count = status.get("wake_count", 0)
        if self._sleeping:
            self._last_wake_count = wake_count
            for _ in range(config.BEHAVIOR_TEXT_QUEUE_SIZE):
                text = self.voice.listen()
                if text is None:
                    break
                if self._is_wake_voice_command(text):
                    self._start_wake_up(now, play_voiceline=True)
                    self._mood = "neutral"
                    self._gaze_mode = "camera"
                    self._wake_attention_until = now + config.VOICE_WAKE_COMMAND_TIMEOUT
                    break
            return status
        if wake_count > self._last_wake_count:
            self._sleepy_yawned = False
            self._sleepy_yawn_until = 0.0
            self._mood = "neutral"
            self._gaze_mode = "camera"
            self._wake_attention_until = now + config.VOICE_WAKE_COMMAND_TIMEOUT
            self._last_presence_at = now
        self._last_wake_count = wake_count
        for _ in range(config.BEHAVIOR_TEXT_QUEUE_SIZE):
            text = self.voice.listen()
            if text is None:
                break
            self._last_presence_at = now
            self._sleepy_yawned = False
            with self._lock:
                self._texts.append(text)
            self._thinking_until = now + config.BEHAVIOR_THINKING_TIMEOUT
        return status

    def _choose_state(self, now, voice_status, target):
        if self._sleeping:
            return BehaviorState.SLEEP
        if self._waking:
            if now < self._wake_closed_until:
                return BehaviorState.SLEEP
            ready = self._subsystems_ready() if self._subsystems_ready is not None else True
            if now < self._wake_min_until or (not ready and now < self._wake_max_until):
                return BehaviorState.SLEEPY
            self._waking = False
        if now < self._sleepy_yawn_until:
            return BehaviorState.SLEEPY
        if voice_status["is_speaking"] and now >= self._wake_speech_until:
            return BehaviorState.SPEAKING
        if now < self._startled_until:
            return BehaviorState.STARTLED
        if voice_status["state"] == "recording" or voice_status["state"] == "listening":
            return BehaviorState.LISTENING
        if self._brain_thinking or voice_status.get("stt_busy") or now < self._thinking_until:
            return BehaviorState.THINKING
        if now < self._wake_attention_until:
            return BehaviorState.ATTENTIVE
        if self._mood == "sleepy":
            return BehaviorState.SLEEPY
        if self._mood == "happy" or now < self._happy_until:
            return BehaviorState.HAPPY
        if self._mood == "curious" or now < self._curious_until:
            return BehaviorState.CURIOUS
        if target is not None and target.state != "no_target":
            return BehaviorState.ATTENTIVE
        if now - self._last_presence_at >= config.BEHAVIOR_IDLE_SLEEPY_SECONDS:
            return BehaviorState.SLEEPY
        return BehaviorState.IDLE

    def _apply_expression(self, state, now=0.0):
        if state == BehaviorState.SLEEP:
            if self._eyelid_mode != "sleep":
                self.eyes.sleep()
                self._eyelid_mode = "sleep"
                self._pupil = "normal"
            return
        if state == BehaviorState.SLEEPY:
            if self._eyelid_mode != "sleepy":
                self.eyes.set_emotion("sleepy")
                self._eyelid_mode = "sleepy"
                self._pupil = "normal"
            return
        if self._eyelid_mode == "sleep":
            self.eyes.wake()
            self._pupil = "normal"
        elif self._eyelid_mode == "sleepy":
            self.eyes.wake()
            self._pupil = "normal"
        self._eyelid_mode = "open"
        if self._pupil_override and now >= self._pupil_override_until:
            self._pupil_override = None
            self._pupil_override_until = 0.0
        if self._pupil_override and state not in {BehaviorState.THINKING, BehaviorState.STARTLED}:
            pupil = self._pupil_override
        else:
            pupil = _PUPILS[state]
        if pupil != self._pupil:
            self.eyes.set_pupil(pupil)  # păstrează animația blink în curs
            self._pupil = pupil

    def _apply_gaze(self, state, target, now):
        if state == BehaviorState.SLEEP:
            self._gaze_owner = "sleep"
            return
        if self._waking and state == BehaviorState.SLEEPY:
            # Animație somnoroasă de trezire cât timp se reactivează procesele (camera + LLM).
            phase = now - self._wake_closed_until
            self.eyes.look_at(0.35 * math.sin(phase * 3.0), 0.12, tracking=True)
            self._gaze_owner = "waking"
            return
        if state == BehaviorState.STARTLED:
            if self._gaze_owner != "reaction":
                self.eyes.look_at(0.0, 0.0, tracking=True)
            self._gaze_owner = "reaction"
            return
        if self._gaze_mode == "manual" and now >= self._manual_until:
            self._gaze_mode = "camera"
        if self._gaze_mode == "manual":
            self.eyes.look_at(*self._manual_gaze, tracking=True)
            self._gaze_owner = "manual"
            return
        if self._gaze_mode == "camera" and target is not None:
            if self._gaze_owner not in {"camera", "idle"}:
                self._tracking = EyeTrackingController(self.eyes)
            self._tracking.update(target)
            self._gaze_owner = "camera" if target.state != "no_target" else "idle"
            return
        if self._gaze_owner not in {"idle", "sleep"}:
            self.eyes.look_at(0.0, 0.0, tracking=True)
        self._gaze_owner = "idle"

    def update(self, dt=None):
        """Arbitrează și apoi avansează EyeSystem; cheamă numai din loop-ul ochilor."""
        thread_id = get_ident()
        if self._loop_thread is None:
            self._loop_thread = thread_id
        elif self._loop_thread != thread_id:
            raise RuntimeError("update() trebuie apelat mereu din același thread")
        with self._lock:
            if self._closed:
                raise RuntimeError("BehaviorManager este închis")
        now = self._clock()
        self._drain_commands(now)
        if self._events is not None:
            for event in self._events.drain(limit=config.BEHAVIOR_EVENTS_PER_TICK):
                self._react(event, now)
        voice_status = self._voice_status(now)
        target = (
            self.perception.get_tracking_target()
            if (self.perception is not None and not self._sleeping and not self._waking)
            else None
        )
        if target is not None and target.state != "no_target":
            self._last_presence_at = now
            self._sleepy_yawned = False
        elif (not self._sleeping and not self._waking and not self._brain_thinking
              and voice_status["state"] == "waiting_wakeword"
              and now - self._last_presence_at >= config.BEHAVIOR_IDLE_SLEEP_SECONDS):
            self._enter_sleep(now, auto=True)
        state = self._choose_state(now, voice_status, target)
        if (state == BehaviorState.SLEEPY and not self._waking and not self._sleepy_yawned
                and now - self._last_presence_at >= config.BEHAVIOR_IDLE_SLEEPY_SECONDS):
            self._sleepy_yawned = True
            self._sleepy_yawn_until = now + 4.0
            yawn_text = getattr(config, "BEHAVIOR_SLEEPY_YAWN_TEXT", "Yaaawn... I am getting so sleepy...")
            with self._lock:
                self._last_text = yawn_text
            if self.voice is not None and getattr(self.voice, "_accepts_emotion", False):
                try:
                    self.voice.speak(yawn_text, "sleepy")
                except Exception:
                    pass
        self._apply_expression(state, now)
        self._apply_gaze(state, target, now)
        self.eyes.update(dt)
        self._state = state
        telemetry_status = (
            "ATTENTIVE" if (now < self._snax_attentive_until and state not in {BehaviorState.SLEEP, BehaviorState.THINKING, BehaviorState.LISTENING})
            else _TELEMETRY_STATUS_MAP.get(state, "IDLE")
        )
        with self._lock:
            self._snapshot = {
                "state": state.value, "telemetry_status": telemetry_status,
                "mood": self._mood, "gaze_owner": self._gaze_owner,
                "expression_owner": "behavior", "blink_owner": "eye_engine",
                "tongue_owner": "behavior" if self.body is not None else None,
                "audio_owner": "voice" if self.voice is not None else None,
                "has_person": target is not None and target.state != "no_target",
                "voice_state": voice_status["state"], "pending_texts": len(self._texts),
                "last_text": self._last_text,
                "power_saving": self._power_saving,
                "waking": self._waking,
            }
        return state

    def get_state(self):
        with self._lock:
            return dict(self._snapshot)

    def close(self):
        with self._lock:
            self._closed = True
        if self._events is not None:
            self._events.close()
            self._events = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
