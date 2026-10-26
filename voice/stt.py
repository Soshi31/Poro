"""Whisper.cpp local, numai pentru fraze activate; maximum un proces STT."""

import json
import logging
import math
from pathlib import Path
import re
import tempfile
import unicodedata
import wave
import zlib

import numpy as np

import config
from .process import ProcessRunner


_PHRASE_CORRECTIONS = {
    "who are you": "Who are you?",
    "what is your name": "What is your name?",
    "whats your name": "What is your name?",
    "how are you": "How are you?",
    "stick out your tongue": "Stick out your tongue!",
    "please stick out your tongue": "Stick out your tongue!",
    "take out your tongue": "Stick out your tongue!",
    "please take out your tongue": "Stick out your tongue!",
    "take out your turn": "Stick out your tongue!",
    "please take out your turn": "Stick out your tongue!",
    "stick out your turn": "Stick out your tongue!",
    "show your tongue": "Stick out your tongue!",
    "put your tongue in": "Put your tongue in!",
    "do a blep": "Do a blep!",
}

_STT_PROMPT = "Poro, Freljord, Poro-Snax, stick out your tongue, do a blep, hello, who are you?"


_WORD_REPLACEMENTS = (
    (re.compile(r"\bmikola\s+tesla\b", re.IGNORECASE), "Nikola Tesla"),
    (re.compile(r"\bnicola\s+tesla\b", re.IGNORECASE), "Nikola Tesla"),
    (re.compile(r"\b(?:please\s+)?ask\s+bert\s+einstein\b", re.IGNORECASE), "Who is Albert Einstein"),
    (re.compile(r"\bbert\s+einstein\b", re.IGNORECASE), "Albert Einstein"),
    (re.compile(r"\b(?:speak|take|pick|peek)\s+out\s+your\s+(?:tongue|turn|time|town)\b", re.IGNORECASE), "stick out your tongue"),
    (re.compile(r"\bstick\s+out\s+your\s+(?:turn|time|town)\b", re.IGNORECASE), "stick out your tongue"),
    (re.compile(r"\bput\s+your\s+(?:turn|time|town)\s+in\b", re.IGNORECASE), "put your tongue in"),
)


def clean_transcript(text):
    """Respinge ieșirile goale, adnotările non-vorbire și buclele repetitive."""
    text = re.sub(r"\([^)]*\)|\[[^\]]*\]|\*[^*]*\*", " ", text)
    text = " ".join(text.split()).strip()
    encoded = text.encode("utf-8")
    if not any(char.isalnum() for char in text):
        return ""
    if len(encoded) / len(zlib.compress(encoded)) > 2.4:
        logging.warning("STT: rezultat repetitiv ignorat")
        return ""
    for pattern, replacement in _WORD_REPLACEMENTS:
        text = pattern.sub(replacement, text)
    plain = "".join(char for char in unicodedata.normalize("NFD", text.casefold())
                    if unicodedata.category(char) != "Mn")
    plain_no_apos = re.sub(r"['’`]+", "", plain)
    phrase_key = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", plain_no_apos)).strip()
    if phrase_key in _PHRASE_CORRECTIONS:
        return _PHRASE_CORRECTIONS[phrase_key]
    normalized = re.sub(r"[^a-z]+", "", plain)
    if len(text.split()) == 1 and normalized in config.VOICE_STT_SINGLE_WORD_CORRECTIONS:
        return config.VOICE_STT_SINGLE_WORD_CORRECTIONS[normalized]
    return text


class SpeechToText:
    def __init__(self):
        self.binary = Path(config.VOICE_STT_BINARY)
        self.model = Path(config.VOICE_STT_MODEL)
        if not self.binary.is_file() or not self.model.is_file():
            raise FileNotFoundError("Lipsește whisper-cli/modelul local. Rulează bash voice/setup.sh")
        self._runner = ProcessRunner()

    def transcribe(self, pcm, cancel=None):
        if not pcm or len(pcm) % 2:
            raise ValueError("STT necesită PCM16 mono valid")
        if len(pcm) > (config.VOICE_MAX_UTTERANCE_SECONDS + 0.1) * config.VOICE_SAMPLE_RATE * 2:
            raise ValueError("Fraza depășește limita de durată")
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
        peak = float(np.max(np.abs(samples))) / 32768
        if peak < 0.014:
            return ""
        gain = min(config.VOICE_STT_MAX_GAIN, config.VOICE_STT_NORMALIZE_PEAK / max(peak, 1e-6))
        pcm = np.clip(samples * gain, -32768, 32767).astype("<i2").tobytes()
        duration_sec = len(pcm) / (config.VOICE_SAMPLE_RATE * 2)
        ac = max(128, min(config.VOICE_STT_AUDIO_CONTEXT, int(math.ceil((duration_sec + 0.4) * 50 / 32.0) * 32)))
        with tempfile.TemporaryDirectory(prefix="poro-stt-") as directory:
            audio = Path(directory) / "speech.wav"
            output = Path(directory) / "result"
            with wave.open(str(audio), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(config.VOICE_SAMPLE_RATE)
                wav.writeframes(pcm)
            self._runner.run([
                str(self.binary), "-m", str(self.model), "-f", str(audio),
                "-l", config.VOICE_STT_LANGUAGE, "-t", str(config.VOICE_STT_THREADS),
                "-ac", str(ac), "-bs", "1", "-bo", "1",
                "-mc", "0", "-nth", "0.45", "-lpt", "-0.80", "-et", "2.2", "-ml", "60",
                "-nf", "-ng", "-np", "-nt", "-oj", "-of", str(output),
            ], timeout=config.VOICE_STT_TIMEOUT, cancel=cancel)
            result = json.loads(output.with_suffix(".json").read_text())
            text = " ".join(segment["text"].strip() for segment in result.get("transcription", []))
            return clean_transcript(text)

    def close(self):
        self._runner.close()
