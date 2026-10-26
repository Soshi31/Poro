"""VAD WebRTC inclus în PocketSphinx și segmentare cu pre-roll/silence timeout."""

from collections import deque
from dataclasses import dataclass
import math

import numpy as np

import config
from .dependencies import pocketsphinx


class VoiceActivityDetector:
    def __init__(self):
        self._vad = pocketsphinx().Vad(mode=config.VOICE_VAD_MODE,
                                      sample_rate=config.VOICE_SAMPLE_RATE,
                                      frame_length=config.VOICE_FRAME_MS / 1000)
        self.frame_bytes = self._vad.frame_bytes

    def is_speech(self, pcm):
        if len(pcm) != self.frame_bytes:
            raise ValueError("Cadru PCM de lungime invalidă pentru VAD")
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
        dbfs = 20 * math.log10(max(float(np.sqrt(np.mean(samples * samples))) / 32768, 1e-6))
        detected = self._vad.is_speech(pcm)
        return detected and dbfs >= config.VOICE_VAD_MIN_DBFS


@dataclass(frozen=True)
class Utterance:
    pcm: bytes
    voiced_seconds: float
    truncated: bool


class SpeechSegmenter:
    def __init__(self):
        self.frame_seconds = config.VOICE_FRAME_MS / 1000
        self._pre = deque(maxlen=max(config.VOICE_START_FRAMES,
                                    math.ceil(config.VOICE_PRE_ROLL_SECONDS / self.frame_seconds)))
        self.reset()

    def reset(self):
        self._pre.clear()
        self._frames = []
        self._consecutive = self._silence = self._voiced = 0

    @property
    def active(self):
        return bool(self._frames)

    def feed(self, pcm, speech):
        if not self._frames:
            self._pre.append((pcm, speech))
            self._consecutive = self._consecutive + 1 if speech else 0
            if self._consecutive < config.VOICE_START_FRAMES:
                return None
            self._frames = [frame for frame, _ in self._pre]
            self._voiced = sum(1 for _, voiced in self._pre if voiced)
        else:
            self._frames.append(pcm)
            self._voiced += bool(speech)
        self._silence = 0 if speech else self._silence + 1
        truncated = len(self._frames) * self.frame_seconds >= config.VOICE_MAX_UTTERANCE_SECONDS
        if not truncated and self._silence * self.frame_seconds < config.VOICE_END_SILENCE_SECONDS:
            return None
        voiced_seconds = self._voiced * self.frame_seconds
        result = Utterance(b"".join(self._frames), voiced_seconds, truncated)
        self.reset()
        return result if voiced_seconds >= config.VOICE_MIN_SPEECH_SECONDS else None
