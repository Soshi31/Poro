#!/usr/bin/python3
"""Conversație reală ALSA -> voce -> text -> răspuns local, fără LLM."""

import argparse
import logging
import math
import signal
import time
import unicodedata

from voice.voice_manager import VoiceManager


def reply_to(text):
    normalized = "".join(c for c in unicodedata.normalize("NFD", text.lower()) if not unicodedata.combining(c))
    if "hello" in normalized or "hi" in normalized:
        return "Hello! I am Poro. I can hear you!"
    if "what is your name" in normalized or "who are you" in normalized:
        return "My name is Poro! This is my local voice test."
    if "what time" in normalized:
        return time.strftime("It is %H:%M.")
    return "I heard: " + text[:350]


def _stop(signum, frame):
    raise KeyboardInterrupt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=0, help="Secunde; 0 = până la Ctrl+C")
    parser.add_argument("--no-wakeword", action="store_true", help="Diagnostic STT; orice frază activează transcrierea")
    parser.add_argument("--quiet-start", action="store_true", help="Fără mesaj vocal la pornire")
    args = parser.parse_args(argv)
    if not math.isfinite(args.duration) or args.duration < 0:
        parser.error("Durata trebuie să fie finită și >= 0")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s", datefmt="%H:%M:%S")
    signal.signal(signal.SIGTERM, _stop)
    try:
        with VoiceManager(require_wakeword=not args.no_wakeword) as voice:
            started = log_at = time.monotonic()
            pending = []
            if not args.quiet_start:
                instruction = ("After this message, say Hello or Who are you."
                               if args.no_wakeword else "Say Hey Poro, then your command.")
                pending.append(voice.speak("Hello! I am Poro. " + instruction))
            logging.info("REAL TEST: %s Ctrl+C stops.",
                         "Say «Hello» or «Who are you?»; wake word is disabled."
                         if args.no_wakeword else "Say «Hey Poro», then your command.")
            while not args.duration or time.monotonic() - started < args.duration:
                voice.check_health()
                for future in pending[:]:
                    if future.done():
                        future.result()  # erorile difuzorului nu sunt ascunse
                        pending.remove(future)
                text = voice.listen()
                if text:
                    logging.info("TU: %s", text)
                    answer = reply_to(text)
                    logging.info("PORO: %s", answer)
                    pending.append(voice.speak(answer))
                if time.monotonic() - log_at >= 5:
                    status = voice.get_status()
                    logging.info("VOICE %s | mic %.1f dBFS | STT=%s | wake=%s | texte=%s | cadre pierdute=%s",
                                 status["state"], status["microphone_dbfs"], status["stt_busy"],
                                 status["wake_count"], status["recognized_count"], status["dropped_audio_frames"])
                    log_at = time.monotonic()
                time.sleep(0.02)
        return 0
    except KeyboardInterrupt:
        logging.info("Voice oprit; ALSA și procesele locale eliberate.")
        return 0
    except Exception:
        logging.exception("Testul vocal nu a putut continua")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
