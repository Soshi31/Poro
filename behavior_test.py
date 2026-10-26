#!/usr/bin/python3
"""Test real: cameră + ochi + voice + IMU/limbă, arbitrate într-un singur loop."""

import argparse
from contextlib import ExitStack
import logging
import math
import select
import signal
import sys
import time

import config
from behavior import BehaviorManager
from body.body_manager import BodyManager
from core.events import EventBus
from display_manager import DisplayManager
from eye_controller import EyeSystem
from eye_renderer import EyeRenderer, load_assets
from vision.perception import PerceptionSystem
from voice.voice_manager import VoiceManager


def _stop(signum, frame):
    raise KeyboardInterrupt


def _command(line, behavior):
    words = line.strip().split()
    if not words:
        return True
    command = words[0].lower()
    if command in {"quit", "exit"}:
        return False
    if command in {"neutral", "happy", "curious", "sleepy"}:
        behavior.set_emotion(command)
    elif command == "sleep":
        behavior.sleep()
    elif command == "wake":
        behavior.wake_up()
    elif command == "person":
        behavior.look_at_person()
    elif command == "idle":
        behavior.release_gaze()
    elif command == "look" and len(words) == 3:
        behavior.look_at(float(words[1]), float(words[2]), duration=3.0)
    elif command == "blink":
        behavior.blink()
    elif command == "tongue" and len(words) == 2:
        behavior.tongue(words[1])
    elif command == "say" and len(words) > 1:
        behavior.speak(line.strip()[len(words[0]):].strip())
    else:
        logging.warning("Comandă necunoscută: %s", line.strip())
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=0, help="Secunde; 0 = până la Ctrl+C")
    parser.add_argument("--no-voice", action="store_true", help="Diagnostic fără ALSA/STT/TTS")
    parser.add_argument("--no-body", action="store_true", help="Diagnostic fără BNO085/PCA9685")
    parser.add_argument("--echo-voice", action="store_true", help="Repetă textul STT prin TTS, fără LLM")
    args = parser.parse_args(argv)
    if not math.isfinite(args.duration) or args.duration < 0:
        parser.error("--duration trebuie să fie finit și >= 0")
    if args.echo_voice and args.no_voice:
        parser.error("--echo-voice necesită voice")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s",
                        datefmt="%H:%M:%S")
    signal.signal(signal.SIGTERM, _stop)
    try:
        assets = load_assets()
        eyes = EyeSystem(EyeRenderer(assets))
        period = 1.0 / config.FPS
        with ExitStack() as stack:
            bus = EventBus(capacity=max(config.BODY_EVENT_CAPACITY, config.PERCEPTION_EVENT_CAPACITY))
            stack.callback(bus.close)
            perception = stack.enter_context(PerceptionSystem(event_bus=bus))
            body = stack.enter_context(BodyManager(event_bus=bus)) if not args.no_body else None
            voice = stack.enter_context(VoiceManager()) if not args.no_voice else None
            displays = stack.enter_context(DisplayManager())
            behavior = stack.enter_context(BehaviorManager(
                eyes, perception=perception, body=body, voice=voice, event_bus=bus))
            started = previous = time.monotonic()
            previous_state = None
            stdin_open = sys.stdin.isatty()
            logging.info("Behavior activ. Comenzi: happy/curious/sleepy/neutral, sleep/wake, "
                         "person/idle/look x y, blink, tongue blep, say TEXT, quit")
            while not args.duration or time.monotonic() - started < args.duration:
                now = time.monotonic()
                perception.check_health()
                if body is not None:
                    body.check_health()
                if voice is not None:
                    voice.check_health()
                state = behavior.update(now - previous)
                previous = now
                displays.show_both(*eyes.render())
                if state != previous_state:
                    logging.info("BEHAVIOR %s %s", state.value, behavior.get_state())
                    previous_state = state
                while (recognized := behavior.listen()) is not None:
                    logging.info("USER %s", recognized)
                    if args.echo_voice:
                        behavior.speak("Am auzit: " + recognized[:config.VOICE_TTS_MAX_CHARS - 10])
                    else:
                        behavior.finish_thinking()
                if stdin_open and select.select([sys.stdin], [], [], 0)[0]:
                    line = sys.stdin.readline()
                    if not line:
                        stdin_open = False
                    else:
                        try:
                            if not _command(line, behavior):
                                break
                        except (ValueError, RuntimeError) as error:
                            logging.warning("Comandă refuzată: %s", error)
                remaining = period - (time.monotonic() - now)
                if remaining > 0:
                    time.sleep(remaining)
        return 0
    except KeyboardInterrupt:
        logging.info("Oprit; resursele hardware sunt eliberate.")
        return 0
    except Exception:
        logging.exception("Behavior test s-a oprit")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
