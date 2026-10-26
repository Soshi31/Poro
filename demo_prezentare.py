#!/usr/bin/python3
"""Demo complet de prezentare Poro:
1. Salută vocal prin difuzor + mișcă limba (blep)
2. Demonstrează toate tipurile de ochi / pupile / pleoape și mișcări de privire
3. Demonstrează gesturile semantice ale limbii (blep, double_blep, out, in)
4. Intră în modul interactiv live:
   - urmărește fața cu camera (Picamera2 + OpenCV)
   - când este ridicat, înclinat, scuturat sau mișcat (BNO085 IMU), își pune
     imediat ochii DIZZY (spirale rotitoare), scoate limba și reacționează vocal!
"""

import argparse
from contextlib import ExitStack
import logging
import math
from queue import Empty, Queue
import signal
from threading import Event, Thread
import time

import config
from body.body_manager import BodyManager
from core.events import EventBus
from display_manager import DisplayManager
from eye_controller import EyeSystem
from eye_renderer import EyeRenderer, load_assets
from poro_runtime import PerceptionProxy, RecoverySlot
from vision.eye_control import EyeTrackingController
from vision.perception import PerceptionSystem
from voice.tts import TextToSpeech


DIZZY_EVENTS = {
    "picked_up", "movement_started", "shaken", "upside_down",
    "tilted_left", "tilted_right", "tilted_forward", "tilted_back",
}


class AsyncSpeaker:
    """Redă vocea lui Poro într-un thread separat fără a bloca animația ochilor la 30 FPS."""

    def __init__(self, enabled=True):
        self.enabled = enabled and config.VOICE_OUTPUT_ENABLED
        self._tts = TextToSpeech() if self.enabled else None
        self._queue = Queue(maxsize=8)
        self._stop = Event()
        self._busy = Event()
        self._thread = Thread(target=self._run, name="poro-demo-tts", daemon=True)
        self._thread.start()

    @property
    def speaking(self):
        return self._busy.is_set() or not self._queue.empty()

    def say(self, text, emotion="happy"):
        logging.info("VOCE [%s]: %s", emotion, text)
        if not self.enabled:
            return
        try:
            self._queue.put_nowait((text, emotion))
        except Exception:
            pass

    def _run(self):
        while not self._stop.is_set():
            try:
                text, emotion = self._queue.get(timeout=0.1)
            except Empty:
                continue
            self._busy.set()
            try:
                self._tts.speak(text, cancel=self._stop, emotion=emotion)
            except Exception as error:
                if not self._stop.is_set():
                    logging.warning("Eroare TTS: %s", error)
            finally:
                self._busy.clear()

    def close(self):
        self._stop.set()
        if self._tts is not None:
            self._tts.close()
        self._thread.join(timeout=2.0)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def _safe_tongue(body, action):
    if body is None:
        return
    try:
        logging.info("LIMBĂ: %s", action)
        getattr(body, f"tongue_{action}")()
    except Exception as error:
        logging.warning("Limbă indisponibilă pentru %s: %s", action, error)


def _release_running_poro():
    """Oprește curat (SIGTERM -> cod 0) o instanță anterioară ca să elibereze GPIO/camera."""
    import os
    import subprocess
    my_pid = os.getpid()
    try:
        out = subprocess.check_output(["pgrep", "-f", "Poro/(main|demo_prezentare)\\.py"], text=True)
    except subprocess.CalledProcessError:
        return
    pids = [int(line) for line in out.splitlines() if line.strip().isdigit() and int(line) != my_pid]
    if not pids:
        return
    logging.info("Opresc instanța anterioară (PID %s) pentru a elibera hardware-ul...", pids)
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        if not any(os.path.exists(f"/proc/{pid}") for pid in pids):
            time.sleep(0.5)
            return
        time.sleep(0.2)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=0,
                        help="Secunde totale (0 = rulează continuu până la Ctrl+C)")
    parser.add_argument("--skip-showcase", action="store_true",
                        help="Sare direct la modul interactiv (cameră + IMU dizzy)")
    parser.add_argument("--no-voice", action="store_true", help="Fără sunet în difuzor")
    parser.add_argument("--no-camera", action="store_true", help="Fără cameră")
    parser.add_argument("--no-body", action="store_true", help="Fără BNO085 / servo limbă")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s",
                        datefmt="%H:%M:%S")
    stop = Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda signum, frame: stop.set())

    _release_running_poro()
    assets = load_assets()
    eyes = EyeSystem(EyeRenderer(assets))
    tracking = EyeTrackingController(eyes)
    period = 1.0 / config.FPS

    # Secvența de prezentare: salută vocal DOAR la început, apoi arată fluent toate expresiile și limba.
    showcase_steps = []
    if not args.skip_showcase:
        showcase_steps = [
            ("SALUT", 3.0, "happy",
             "Hello! I am Poro!",
             lambda: (eyes.set_emotion("happy"), eyes.look_at(0.0, 0.0), _safe_tongue(body, "blep"))),
            ("PRIVIRE & WINK (normal)", 4.0, "neutral", None,
             lambda: (eyes.set_emotion("neutral"), eyes.look_at(-0.85, 0.0))),
            ("OCHII VESELI (happy)", 2.5, "happy", None,
             lambda: (eyes.set_emotion("happy"), eyes.look_at(0.0, 0.0), _safe_tongue(body, "blep"))),
            ("OCHII INIMIOARE (love / heart)", 3.0, "excited", None,
             lambda: (eyes.set_emotion("love"), eyes.look_at(0.0, 0.0))),
            ("OCHII STELUȚE (excited / star)", 3.0, "curious", None,
             lambda: (eyes.set_emotion("excited"), eyes.look_at(0.0, -0.2))),
            ("OCHII AMEȚIȚI (dizzy / spiral)", 3.2, "surprised", None,
             lambda: (eyes.set_emotion("dizzy"), eyes.look_at(0.0, 0.0))),
            ("OCHII X (dead / x)", 2.5, "sad", None,
             lambda: (eyes.set_emotion("dead"), eyes.look_at(0.0, 0.0))),
            ("SOMNOROS & SOMN (sleepy -> sleep -> wake)", 4.2, "sleepy", None,
             lambda: (eyes.set_emotion("sleepy"), eyes.look_at(0.0, 0.2))),
            ("LIMBA JUCĂUȘĂ (blep / double_blep / out / in)", 4.2, "happy", None,
             lambda: (eyes.set_emotion("love"), _safe_tongue(body, "double_blep"))),
            ("MOD INTERACTIV (cameră + BNO085 dizzy)", 1.0, "happy", None,
             lambda: (eyes.set_emotion("neutral"), _safe_tongue(body, "in"))),
        ]

    with ExitStack() as stack:
        displays = stack.enter_context(DisplayManager())
        # Încărcăm Piper ONNX ÎNAINTE de BNO085 și cameră ca să nu le blocheze timeout-urile de 1s/3s!
        speaker = stack.enter_context(AsyncSpeaker(enabled=not args.no_voice))
        bus = EventBus(capacity=max(config.BODY_EVENT_CAPACITY, config.PERCEPTION_EVENT_CAPACITY))
        stack.callback(bus.close)
        body = stack.enter_context(BodyManager(event_bus=bus)) if not args.no_body else None
        if body is not None:
            stack.callback(body.close)
        perception = None
        if not args.no_camera:
            vision_slot = RecoverySlot("camera", lambda stop_event: PerceptionSystem(event_bus=bus).start(),
                                       lambda p: p.check_health())
            perception = PerceptionProxy(vision_slot)
            stack.callback(vision_slot.close)
            vision_slot.start()
        events = bus.subscribe()
        stack.callback(events.close)

        started = last_frame = time.monotonic()
        step_index = -1
        step_started = 0.0
        sub_action_done = set()
        dizzy_until = 0.0
        last_dizzy_blep_at = 0.0
        was_person_visible = False

        logging.info("=== DEMO PREZENTARE PORO PORNIT (Ctrl+C pentru oprire) ===")

        while not stop.is_set() and (not args.duration or time.monotonic() - started < args.duration):
            now = time.monotonic()
            dt = now - last_frame
            last_frame = now

            if body is not None:
                body.check_health()

            # 1. Verificăm evenimentele și starea BNO085: ridicare / mișcare -> DIZZY imediat!
            motion_trigger = None
            for event in events.drain(limit=32):
                if event.type in DIZZY_EVENTS and now - event.observed_at <= 2.0:
                    motion_trigger = event.type
            if body is not None:
                bstate = body.get_state()
                if bstate.get("ready") and not bstate.get("stale"):
                    if bstate.get("moving") or bstate.get("support_state") == "picked_up":
                        motion_trigger = motion_trigger or ("picked_up" if bstate.get("support_state") == "picked_up" else "moving")
                    elif bstate.get("tilt_degrees") is not None and abs(bstate["tilt_degrees"]) >= 22.0:
                        motion_trigger = motion_trigger or "tilted"

            # Activăm reacția DIZZY la mișcare (imediat după salutul inițial sau oricând în modul interactiv).
            if motion_trigger is not None and (step_index >= len(showcase_steps) or step_index >= 1):
                if now >= dizzy_until:
                    logging.info("REACȚIE IMU [%s] -> OCHI DIZZY!", motion_trigger)
                dizzy_until = max(dizzy_until, now + 2.2)
                if eyes.left.pupil != "dizzy" or eyes.left.sleeping:
                    eyes.set_emotion("dizzy")
                    eyes.look_at(0.0, 0.0)
                if now - last_dizzy_blep_at >= 3.0:
                    _safe_tongue(body, "blep")
                    last_dizzy_blep_at = now

            # 2. Dacă nu este amețit de la ridicare/mișcare, rulăm fie showcase-ul, fie modul interactiv.
            if now < dizzy_until:
                pass  # păstrăm animația dizzy activă
            elif step_index + 1 < len(showcase_steps):
                if step_index == -1 or (now - step_started >= showcase_steps[step_index][1] and not speaker.speaking):
                    step_index += 1
                    step_started = now
                    sub_action_done.clear()
                    title, _, voice_emotion, line, action = showcase_steps[step_index]
                    logging.info(">>> ETAPA %d/%d: %s", step_index + 1, len(showcase_steps), title)
                    action()
                    if line:
                        speaker.say(line, emotion=voice_emotion)
                else:
                    elapsed = now - step_started
                    title = showcase_steps[step_index][0]
                    # Sub-animații în cadrul etapei curente:
                    if title.startswith("PRIVIRE"):
                        if elapsed > 1.0 and "right" not in sub_action_done:
                            sub_action_done.add("right")
                            eyes.look_at(0.85, 0.0)
                        elif elapsed > 2.0 and "up" not in sub_action_done:
                            sub_action_done.add("up")
                            eyes.look_at(0.0, -0.8)
                        elif elapsed > 2.8 and "wink_l" not in sub_action_done:
                            sub_action_done.add("wink_l")
                            eyes.look_at(0.0, 0.0)
                            eyes.wink_left()
                        elif elapsed > 3.6 and "wink_r" not in sub_action_done:
                            sub_action_done.add("wink_r")
                            eyes.wink_right()
                    elif title.startswith("SOMNOROS"):
                        if elapsed > 1.5 and "sleep" not in sub_action_done:
                            sub_action_done.add("sleep")
                            eyes.sleep()
                        elif elapsed > 3.2 and "wake" not in sub_action_done:
                            sub_action_done.add("wake")
                            eyes.wake()
                            eyes.set_emotion("happy")
                    elif title.startswith("LIMBA"):
                        if elapsed > 2.0 and "out" not in sub_action_done:
                            sub_action_done.add("out")
                            eyes.set_emotion("happy")
                            _safe_tongue(body, "out")
                        elif elapsed > 3.6 and "in" not in sub_action_done:
                            sub_action_done.add("in")
                            _safe_tongue(body, "in")
            else:
                if step_index < len(showcase_steps):
                    step_index = len(showcase_steps)
                    logging.info(">>> MOD INTERACTIV ACTIV: Urmărire față + Reacție DIZZY la ridicare/mișcare!")
                # Revenim din dizzy în expresia normală/happy
                if eyes.left.pupil == "dizzy":
                    eyes.set_emotion("neutral")
                if perception is not None:
                    target = perception.get_tracking_target()
                    tracking.update(target)
                    person_visible = target.state != "no_target"
                    if person_visible and not was_person_visible:
                        logging.info("PERSOANĂ DETECTATĂ -> Ochi HAPPY!")
                        eyes.set_pupil("happy")
                    elif not person_visible and was_person_visible:
                        eyes.set_pupil("normal")
                    was_person_visible = person_visible

            eyes.update(dt)
            displays.show_both(*eyes.render())
            stop.wait(max(0.0, period - (time.monotonic() - now)))

    logging.info("Demo oprit curat; hardware-ul a fost eliberat.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
