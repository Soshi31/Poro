"""Supraveghere și proxy-uri stabile pentru subsistemele recuperabile."""

import logging
from threading import Event, Lock, Thread
import time

import config
from vision.face_tracker import TrackingTarget


_RAISE = object()


class RecoverySlot:
    """Pornește/repornește un modul într-un worker; nu ține bucla ochilor."""

    def __init__(self, name, factory, health, *, on_ready=None):
        self.name = name
        self.factory = factory
        self.health = health
        self.on_ready = on_ready
        self._lock = Lock()
        self._stop = Event()
        self._failed = Event()
        self._suspended = Event()
        self._state_change = Event()
        self._thread = None
        self._current = None
        self._state = "stopped"
        self._attempts = 0
        self._last_error = None

    @property
    def current(self):
        with self._lock:
            return self._current

    def status(self):
        with self._lock:
            return {"state": self._state, "attempts": self._attempts,
                    "last_error": self._last_error}

    def suspend(self):
        """Oprește complet subsistemul în modul SLEEP pentru economisirea energiei."""
        with self._lock:
            if self._suspended.is_set():
                return
            self._suspended.set()
            self._state_change.set()

    def resume(self):
        """Reactivează subsistemul la trezirea din modul SLEEP."""
        with self._lock:
            if not self._suspended.is_set():
                return
            self._suspended.clear()
            self._state_change.set()

    def start(self):
        if self._thread is not None:
            raise RuntimeError(f"{self.name} a fost deja pornit")
        self._thread = Thread(target=self._run, name=f"poro-recover-{self.name}", daemon=True)
        self._thread.start()
        return self

    def _run(self):
        delay = config.SYSTEM_RECOVERY_INITIAL_SECONDS
        while not self._stop.is_set():
            if self._suspended.is_set():
                with self._lock:
                    self._state = "suspended"
                self._state_change.clear()
                while self._suspended.is_set() and not self._stop.is_set():
                    self._state_change.wait(0.25)
                    self._state_change.clear()
                delay = config.SYSTEM_RECOVERY_INITIAL_SECONDS
                continue
            component = None
            ready_at = None
            try:
                with self._lock:
                    self._attempts += 1
                    self._state = "starting"
                component = self.factory(self._stop)
                if self._stop.is_set() or self._suspended.is_set():
                    continue
                with self._lock:
                    self._current = component
                if self.on_ready is not None:
                    self.on_ready(component)
                with self._lock:
                    self._state = "ready"
                    self._last_error = None
                ready_at = time.monotonic()
                self._failed.clear()
                logging.info("%s activ", self.name)
                while not self._stop.is_set() and not self._suspended.is_set():
                    if self._failed.is_set():
                        raise RuntimeError("apelul subsistemului a eșuat")
                    self.health(component)
                    self._state_change.wait(config.SYSTEM_HEALTH_INTERVAL_SECONDS)
                    self._state_change.clear()
                if self._suspended.is_set():
                    logging.info("%s oprit pentru economisire energie (SLEEP)", self.name)
            except Exception as error:
                if not self._stop.is_set() and not self._suspended.is_set():
                    with self._lock:
                        self._last_error = str(error)[:240]
                        self._state = "recovering"
                    logging.warning("%s indisponibil: %s; repornire în %.1f s",
                                    self.name, error, delay)
            finally:
                with self._lock:
                    self._current = None
                    if self._stop.is_set():
                        self._state = "stopped"
                    elif self._suspended.is_set():
                        self._state = "suspended"
                if component is not None:
                    try:
                        component.close()
                    except Exception:
                        logging.exception("Închiderea %s a eșuat", self.name)
            if self._stop.is_set():
                break
            if self._suspended.is_set():
                continue
            if ready_at is not None and time.monotonic() - ready_at >= 30:
                delay = config.SYSTEM_RECOVERY_INITIAL_SECONDS
            self._state_change.wait(delay)
            self._state_change.clear()
            delay = min(delay * 2, config.SYSTEM_RECOVERY_MAX_SECONDS)
        with self._lock:
            self._state = "stopped"

    def call(self, method, *args, fallback=_RAISE, **kwargs):
        component = self.current
        if component is None:
            if fallback is not _RAISE:
                return fallback() if callable(fallback) else fallback
            raise RuntimeError(f"{self.name} nu este disponibil")
        try:
            return getattr(component, method)(*args, **kwargs)
        except Exception:
            self._failed.set()
            if fallback is not _RAISE:
                return fallback() if callable(fallback) else fallback
            raise

    def close(self):
        self._stop.set()
        self._failed.set()
        self._state_change.set()
        if self._thread is not None:
            self._thread.join(timeout=config.SYSTEM_SHUTDOWN_TIMEOUT)
            if self._thread.is_alive():
                raise RuntimeError(f"{self.name} nu s-a oprit în timp util")
            self._thread = None


class PerceptionProxy:
    def __init__(self, slot):
        self.slot = slot

    @staticmethod
    def _unavailable_scene():
        return {"running": False, "has_person": False, "primary": None,
                "people": [], "objects": [], "motion": None,
                "scene_analysis": {}, "capabilities": {"objects": "unavailable"}}

    def get_current_scene_state(self):
        return self.slot.call("get_current_scene_state", fallback=self._unavailable_scene)

    def get_tracking_target(self):
        return self.slot.call("get_tracking_target",
                              fallback=lambda: TrackingTarget("no_target", None, None))

    def inspect_scene(self, timeout=None):
        return self.slot.call("inspect_scene", timeout=timeout)

    def capture_frame_for_ai(self, timeout=None):
        return self.slot.call("capture_frame_for_ai", timeout=timeout)


class VoiceProxy:
    def __init__(self, slot):
        self.slot = slot
        self._lock = Lock()
        self._suspended = False

    def on_ready(self, voice):
        with self._lock:
            if self._suspended:
                voice.suspend_listening()

    def get_status(self):
        return self.slot.call("get_status", fallback={"state": "stopped", "is_speaking": False,
                                                       "is_listening": False, "running": False})

    def listen(self, timeout=0.0):
        return self.slot.call("listen", timeout=timeout, fallback=None)

    _accepts_emotion = True

    def speak(self, text, emotion=None):
        return self.slot.call("speak", text, emotion) if emotion is not None else self.slot.call("speak", text)

    def suspend_listening(self):
        with self._lock:
            self._suspended = True
            self.slot.call("suspend_listening", fallback=None)

    def resume_listening(self):
        with self._lock:
            self._suspended = False
            self.slot.call("resume_listening", fallback=None)

    def set_muted(self, muted):
        config.VOICE_OUTPUT_ENABLED = not bool(muted)
        return self.slot.call("set_muted", bool(muted), fallback=None)


class LLMProxy:
    def __init__(self, slot):
        self.slot = slot

    @property
    def running(self):
        current = self.slot.current
        return current is not None and current.running

    @property
    def last_metrics(self):
        current = self.slot.current
        return current.last_metrics if current is not None else None

    def _ensure_ready(self):
        self.slot.resume()
        state = self.slot.status()["state"]
        if state in {"starting", "suspended", "recovering"}:
            deadline = time.monotonic() + min(getattr(config, "LLM_STARTUP_TIMEOUT", 30.0), 30.0)
            while time.monotonic() < deadline:
                if self.slot.current is not None and self.slot.current.running:
                    break
                if self.slot.status()["state"] == "stopped":
                    break
                time.sleep(0.05)

    def generate(self, messages, *, response_schema):
        self._ensure_ready()
        return self.slot.call("generate", messages, response_schema=response_schema)

    def generate_stream(self, messages, *, max_tokens=None):
        self._ensure_ready()
        component = self.slot.current
        if component is None:
            raise RuntimeError(f"{self.slot.name} nu este disponibil")
        try:
            yield from component.generate_stream(messages, max_tokens=max_tokens)
        except Exception:
            self.slot._failed.set()
            raise

    def start(self):
        self.slot.start()

    def close(self):
        self.slot.close()