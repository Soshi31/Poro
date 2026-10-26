"""TTS local configurabil: Piper în proces (încărcat o singură dată) sau eSpeak, apoi ALSA.

Latența mică vine din trei lucruri: modelul Piper rămâne în RAM (nu se mai
pornește un proces/model la fiecare replică), sinteza este transmisă propoziție
cu propoziție către `aplay` (prima propoziție se aude cât timp se sintetizează
restul), iar pitch-ul se obține prin rata de redare (fără SoX).
"""

from concurrent.futures import CancelledError
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
from threading import Event, Lock
import time
import tempfile

import config
from .process import ProcessRunner


def _emotion_profile(emotion):
    profiles = getattr(config, "VOICE_TTS_EMOTIONS", {})
    return profiles.get(emotion or "neutral", profiles.get("neutral", (1.0, 0, 1.0)))


class TextToSpeech:
    def __init__(self):
        self._runner = ProcessRunner()
        self._lock = Lock()
        self._player = None
        self._closed = Event()
        self._voice = None
        self._audio_cache = {}
        if not config.VOICE_OUTPUT_ENABLED:
            return
        self.backend = config.VOICE_TTS_BACKEND
        if self.backend not in ("piper", "espeak"):
            raise ValueError("VOICE_TTS_BACKEND trebuie să fie 'piper' sau 'espeak'")
        if shutil.which("aplay") is None:
            raise RuntimeError("Lipsește aplay. Rulează: sudo apt install alsa-utils")
        if self.backend == "piper":
            import importlib.util
            if importlib.util.find_spec("piper") is None:
                raise RuntimeError("Lipsește Piper. Rulează: /usr/bin/python3 -m pip install --user --break-system-packages piper-tts==1.8.0")
            model = Path(config.VOICE_TTS_MODEL)
            if not model.is_file() or not model.with_suffix(".onnx.json").is_file():
                raise FileNotFoundError(f"Modelul Piper sau configurația .json lipsește: {model}")
            if not 0.5 <= config.VOICE_TTS_LENGTH_SCALE <= 2.0:
                raise ValueError("VOICE_TTS_LENGTH_SCALE trebuie să fie între 0.5 și 2")
            if not -500 <= config.VOICE_TTS_PITCH_CENTS <= 500:
                raise ValueError("VOICE_TTS_PITCH_CENTS trebuie să fie între -500 și 500")
            self._load_piper(model)
        elif shutil.which("espeak-ng") is None:
            raise RuntimeError("Lipsește eSpeak. Rulează: sudo apt install espeak-ng")

    def _synthesize_piper_bytes(self, text, emotion):
        from piper import SynthesisConfig
        length_mult, cents_delta, volume = _emotion_profile(emotion)
        cents = config.VOICE_TTS_PITCH_CENTS + cents_delta
        factor = 2 ** (cents / 1200)
        syn = SynthesisConfig(length_scale=config.VOICE_TTS_LENGTH_SCALE * length_mult * factor,
                              volume=volume)
        chunks = []
        rate = 22050
        for chunk in self._voice.synthesize(text, syn):
            rate = int(chunk.sample_rate * factor)
            chunks.append(chunk.audio_int16_bytes)
        return rate, b"".join(chunks)

    def _load_piper(self, model):
        import json
        import onnxruntime
        from piper import PiperVoice
        from piper.config import PiperConfig
        prev_affinity = None
        if hasattr(os, "sched_setaffinity"):
            try:
                prev_affinity = os.sched_getaffinity(0)
                cpus = set(range(1, os.cpu_count() or 4)) or {0}
                os.sched_setaffinity(0, cpus)
            except OSError:
                prev_affinity = None
        try:
            options = onnxruntime.SessionOptions()
            # Puține thread-uri: ochii/body/camera trebuie să rămână fluide în timpul vorbirii.
            options.intra_op_num_threads = getattr(config, "VOICE_TTS_THREADS", 2)
            options.inter_op_num_threads = 1
            with open(model.with_suffix(".onnx.json"), encoding="utf-8") as handle:
                piper_config = PiperConfig.from_dict(json.load(handle))
            session = onnxruntime.InferenceSession(str(model), sess_options=options,
                                                   providers=["CPUExecutionProvider"])
            self._voice = PiperVoice(config=piper_config, session=session,
                                     espeak_data_dir=Path(sys.modules["piper"].__file__).parent / "espeak-ng-data",
                                     download_dir=Path(tempfile.gettempdir()))
            # Pre-sintetizăm în RAM confirmarea wake word, «Blep!», căscatul, trezirea și replicile de Snax (0.00s latență).
            ack = getattr(config, "VOICE_WAKE_ACK", "")
            yawn_text = getattr(config, "BEHAVIOR_SLEEPY_YAWN_TEXT", "Yaaawn... I am getting so sleepy...")
            wake_text = getattr(config, "BEHAVIOR_WAKE_VOICELINE", "Yaaawn! Good morning! I am awake and ready to play!")
            precached = (
                (ack, "curious"),
                ("Blep!", "happy"),
                (yawn_text, "sleepy"),
                (wake_text, "happy"),
                ("Yum! Tasty Snax!", "excited"),
                ("Nom nom! So good!", "excited"),
                ("Yay! Poro-Snax!", "excited"),
                ("Mmm, thank you!", "excited"),
                ("Blep! More Snax please!", "excited"),
            )
            for phrase, emo in precached:
                if phrase:
                    self._audio_cache[(phrase, emo)] = self._synthesize_piper_bytes(phrase, emo)
        finally:
            if prev_affinity is not None:
                try:
                    os.sched_setaffinity(0, prev_affinity)
                except OSError:
                    pass

    # -- redare -----------------------------------------------------------
    def _start_player(self, rate):
        command = ["aplay", "-q", "-D", config.VOICE_PLAYBACK_DEVICE,
                   "-t", "raw", "-f", "S16_LE", "-c", "1", "-r", str(rate)]
        with self._lock:
            if self._closed.is_set():
                raise CancelledError()
            self._player = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                            stderr=subprocess.PIPE, start_new_session=True)
            return self._player

    def _kill_player(self):
        with self._lock:
            player, self._player = self._player, None
        if player is not None and player.poll() is None:
            try:
                os.killpg(player.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def _speak_piper(self, text, emotion, cancel):
        from piper import SynthesisConfig
        if hasattr(os, "sched_setaffinity"):
            try:
                cpus = set(range(1, os.cpu_count() or 4)) or {0}
                os.sched_setaffinity(0, cpus)
            except OSError:
                pass
        cached = self._audio_cache.get((text, emotion or "neutral"))
        if cached is not None:
            rate, pcm_bytes = cached
            player = None
            try:
                if self._closed.is_set() or (cancel is not None and cancel.is_set()):
                    raise CancelledError()
                player = self._start_player(rate)
                player.stdin.write(pcm_bytes)
                player.stdin.flush()
                player.stdin.close()
                deadline = time.monotonic() + config.VOICE_TTS_TIMEOUT
                while player.poll() is None:
                    if self._closed.is_set() or (cancel is not None and cancel.is_set()):
                        raise CancelledError()
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Timeout la redarea TTS")
                    time.sleep(0.01)
                if player.returncode:
                    raise RuntimeError("aplay: " + player.stderr.read().decode(errors="replace")[-500:])
            finally:
                self._kill_player()
            return
        length_mult, cents_delta, volume = _emotion_profile(emotion)
        cents = config.VOICE_TTS_PITCH_CENTS + cents_delta
        factor = 2 ** (cents / 1200)
        # Redarea mai rapidă ridică tonul; length_scale compensează durata.
        syn = SynthesisConfig(length_scale=config.VOICE_TTS_LENGTH_SCALE * length_mult * factor,
                              volume=volume)
        player = None
        try:
            for chunk in self._voice.synthesize(text, syn):
                if self._closed.is_set() or (cancel is not None and cancel.is_set()):
                    raise CancelledError()
                if player is None:
                    player = self._start_player(int(chunk.sample_rate * factor))
                try:
                    player.stdin.write(chunk.audio_int16_bytes)
                    player.stdin.flush()
                except (BrokenPipeError, ValueError):
                    raise RuntimeError("aplay: " + (player.stderr.read().decode(errors="replace")[-500:]
                                                    if player.stderr else "redare întreruptă"))
            if player is not None:
                player.stdin.close()
                deadline = time.monotonic() + config.VOICE_TTS_TIMEOUT
                while player.poll() is None:
                    if self._closed.is_set() or (cancel is not None and cancel.is_set()):
                        raise CancelledError()
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Timeout la redarea TTS")
                    time.sleep(0.02)
                if player.returncode:
                    raise RuntimeError("aplay: " + player.stderr.read().decode(errors="replace")[-500:])
        finally:
            self._kill_player()

    def speak(self, text, cancel=None, emotion=None):
        if not isinstance(text, str) or not text.strip() or len(text) > config.VOICE_TTS_MAX_CHARS:
            raise ValueError(f"TTS necesită text de 1..{config.VOICE_TTS_MAX_CHARS} caractere")
        if not config.VOICE_OUTPUT_ENABLED:
            return
        if self._closed.is_set() or (cancel is not None and cancel.is_set()):
            raise CancelledError()
        if self.backend == "piper":
            self._speak_piper(text, emotion, cancel)
            return
        with tempfile.TemporaryDirectory(prefix="poro-tts-") as directory:
            output = Path(directory) / "reply.wav"
            self._runner.run([
                "espeak-ng", "-v", config.VOICE_TTS_VOICE, "-s", str(config.VOICE_TTS_SPEED),
                "-a", str(config.VOICE_TTS_AMPLITUDE), "-w", str(output), "--stdin",
            ], timeout=config.VOICE_TTS_TIMEOUT, input_data=text.encode("utf-8"), cancel=cancel)
            self._runner.run(["aplay", "-q", "-D", config.VOICE_PLAYBACK_DEVICE, str(output)],
                             timeout=config.VOICE_TTS_TIMEOUT, cancel=cancel)

    def stop_current(self):
        """Stop any currently playing TTS audio immediately without closing the engine."""
        self._kill_player()

    def close(self):
        self._closed.set()
        self._kill_player()
        self._runner.close()
