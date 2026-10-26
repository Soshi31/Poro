"""Captură ALSA reală, continuă, cu coadă limitată; selectează canalul INMP441."""

from dataclasses import dataclass
import math
import os
from queue import Empty, Full, Queue
import selectors
import shutil
import subprocess
import tempfile
from threading import Event, Thread
import time

import numpy as np

import config


@dataclass(frozen=True)
class AudioFrame:
    sequence: int
    captured_at: float  # sfârșitul aproximativ al cadrului, monotonic
    pcm: bytes  # mono PCM signed 16-bit little-endian, 16 kHz


class Microphone:
    def __init__(self):
        if shutil.which("arecord") is None:
            raise RuntimeError("Lipsește arecord: sudo apt install alsa-utils")
        if config.VOICE_SAMPLE_RATE != 16000 or config.VOICE_FRAME_MS not in (10, 20, 30):
            raise ValueError("Voice necesită 16 kHz și cadre de 10/20/30 ms")
        if not 0 <= config.VOICE_MIC_CHANNEL < config.VOICE_CAPTURE_CHANNELS:
            raise ValueError("VOICE_MIC_CHANNEL nu există în captura configurată")
        if not math.isfinite(config.VOICE_MIC_GAIN) or config.VOICE_MIC_GAIN <= 0:
            raise ValueError("VOICE_MIC_GAIN trebuie să fie pozitiv și finit")
        if config.VOICE_AUDIO_QUEUE_FRAMES < 1:
            raise ValueError("VOICE_AUDIO_QUEUE_FRAMES trebuie să fie pozitiv")
        self.frames = Queue(maxsize=config.VOICE_AUDIO_QUEUE_FRAMES)
        self._stop = Event()
        self._thread = self._process = self._stderr = None
        self._error = None
        self._last_frame_at = None
        self.dropped_frames = 0
        self.last_dbfs = -120.0

    def start(self):
        if self._process is not None:
            raise RuntimeError("Microfonul este deja pornit")
        samples = config.VOICE_SAMPLE_RATE * config.VOICE_FRAME_MS // 1000
        self._stderr = tempfile.TemporaryFile()
        try:
            self._process = subprocess.Popen([
                "arecord", "-q", "-D", config.VOICE_CAPTURE_DEVICE,
                "-t", "raw", "-f", "S16_LE", "-r", str(config.VOICE_SAMPLE_RATE),
                "-c", str(config.VOICE_CAPTURE_CHANNELS),
                "--period-size", str(samples), "--buffer-size", str(samples * 4),
            ], stdout=subprocess.PIPE, stderr=self._stderr, stdin=subprocess.DEVNULL)
            os.set_blocking(self._process.stdout.fileno(), False)
            self._last_frame_at = time.monotonic()
            self._thread = Thread(target=self._capture, name="poro-microphone", daemon=True)
            self._thread.start()
        except BaseException:
            self.close()
            raise
        return self

    def _capture(self):
        samples = config.VOICE_SAMPLE_RATE * config.VOICE_FRAME_MS // 1000
        frame_bytes = samples * config.VOICE_CAPTURE_CHANNELS * 2
        pending = bytearray()
        sequence = 0
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(self._process.stdout, selectors.EVENT_READ)
                while not self._stop.is_set():
                    if not selector.select(timeout=0.1):
                        if time.monotonic() - self._last_frame_at > config.VOICE_CAPTURE_TIMEOUT:
                            raise TimeoutError("Microfonul nu mai livrează PCM")
                        continue
                    chunk = os.read(self._process.stdout.fileno(), frame_bytes * 8)
                    if not chunk:
                        self._stderr.seek(0)
                        detail = self._stderr.read().decode(errors="replace")[-2000:]
                        raise RuntimeError(f"Captura ALSA s-a oprit: {detail}")
                    pending.extend(chunk)
                    now = time.monotonic()
                    while len(pending) >= frame_bytes:
                        raw = bytes(pending[:frame_bytes])
                        del pending[:frame_bytes]
                        stereo = np.frombuffer(raw, dtype="<i2").reshape(-1, config.VOICE_CAPTURE_CHANNELS)
                        mono = stereo[:, config.VOICE_MIC_CHANNEL].astype(np.float32)
                        mono = np.clip(mono * config.VOICE_MIC_GAIN, -32768, 32767)
                        rms = float(np.sqrt(np.mean(mono * mono))) / 32768
                        self.last_dbfs = 20 * math.log10(max(rms, 1e-6))
                        sequence += 1
                        stamp = now - len(pending) / (config.VOICE_SAMPLE_RATE * config.VOICE_CAPTURE_CHANNELS * 2)
                        frame = AudioFrame(sequence, stamp, mono.astype("<i2").tobytes())
                        try:
                            self.frames.put_nowait(frame)
                        except Full:
                            try:
                                self.frames.get_nowait()
                            except Empty:
                                pass
                            self.dropped_frames += 1
                            self.frames.put_nowait(frame)
                        self._last_frame_at = now
        except Exception as error:
            if not self._stop.is_set():
                self._error = error

    def read(self, timeout=0.1):
        self.check_health()
        try:
            return self.frames.get(timeout=timeout)
        except Empty:
            return None

    def check_health(self):
        if self._error is not None:
            raise RuntimeError("Microfon indisponibil") from self._error

    def close(self):
        self._stop.set()
        if self._process is not None:
            if self._process.poll() is None:
                self._process.terminate()
            try:
                self._process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()
        if self._thread is not None:
            self._thread.join(timeout=2)
        if self._process is not None:
            self._process.stdout.close()
        if self._stderr is not None:
            self._stderr.close()

    def __enter__(self):
        return self.start()

    def __exit__(self, *args):
        self.close()
