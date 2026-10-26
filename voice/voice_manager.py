"""API asincron: listen() -> text/None, speak(text) -> Future; fără LLM."""

from concurrent.futures import CancelledError, Future
from dataclasses import dataclass
import logging
import math
from queue import Empty, Full, Queue
import re
from threading import Event, Lock, Thread
import time
import unicodedata

import config
from .microphone import Microphone
from .stt import SpeechToText
from .tts import TextToSpeech
from .vad import SpeechSegmenter, VoiceActivityDetector
from .wakeword import WakeWordDetector


@dataclass(frozen=True)
class RecognitionJob:
    pcm: bytes
    epoch: int


class VoiceManager:
    """Un singur proprietar al microfonului; toate cozile au capacitate limitată.

    speak() închide poarta audio înainte să întoarcă Future-ul. Nu se permite
    barge-in: vorbirea utilizatorului în timpul TTS este ignorată intenționat.
    """

    def __init__(self, *, require_wakeword=True):
        for name in ("VOICE_CAPTURE_TIMEOUT", "VOICE_MAX_UTTERANCE_SECONDS", "VOICE_END_SILENCE_SECONDS",
                     "VOICE_WAKE_COMMAND_TIMEOUT", "VOICE_STT_TIMEOUT", "VOICE_TTS_TIMEOUT",
                     "VOICE_STT_NORMALIZE_PEAK", "VOICE_STT_MAX_GAIN"):
            if not math.isfinite(getattr(config, name)) or getattr(config, name) <= 0:
                raise ValueError(f"{name} trebuie să fie pozitiv și finit")
        if config.VOICE_STT_NORMALIZE_PEAK > 1:
            raise ValueError("VOICE_STT_NORMALIZE_PEAK trebuie să fie <= 1")
        for name in ("VOICE_PRE_ROLL_SECONDS", "VOICE_ECHO_GUARD_SECONDS", "VOICE_MIN_SPEECH_SECONDS",
                     "VOICE_MIN_COMMAND_SECONDS"):
            if not math.isfinite(getattr(config, name)) or getattr(config, name) < 0:
                raise ValueError(f"{name} trebuie să fie finit și >= 0")
        for name in ("VOICE_START_FRAMES", "VOICE_STT_THREADS", "VOICE_STT_QUEUE_SIZE",
                     "VOICE_TEXT_QUEUE_SIZE", "VOICE_TTS_QUEUE_SIZE"):
            if not isinstance(getattr(config, name), int) or getattr(config, name) < 1:
                raise ValueError(f"{name} trebuie să fie un întreg pozitiv")
        if config.VOICE_STT_AUDIO_CONTEXT and config.VOICE_STT_AUDIO_CONTEXT * 0.02 < config.VOICE_MAX_UTTERANCE_SECONDS:
            raise ValueError("VOICE_STT_AUDIO_CONTEXT este prea scurt pentru limita frazei")
        self.require_wakeword = require_wakeword
        self._lock = Lock()
        self._stop = Event()
        self._running = self._used = False
        self._epoch = 0
        self._speeches = 0
        self._suspended = False
        self._resume_after = 0.0
        self._recognition_cancel = None
        self._tts_cancel = Event()
        self._fatal = None
        self._last_error = None
        self._state = "stopped"
        self._wake_count = self._recognized_count = self._discarded_jobs = 0
        self._ack_future = None  # «Da?» rostit după «Hei Poro» fără comandă
        self._ack_armed_until = 0.0  # fereastra de comandă se redeschide după confirmare
        self._last_stt_seconds = None
        self._stt_busy = False
        self._jobs = Queue(maxsize=config.VOICE_STT_QUEUE_SIZE)
        self._texts = Queue(maxsize=config.VOICE_TEXT_QUEUE_SIZE)
        self._speech_jobs = Queue(maxsize=config.VOICE_TTS_QUEUE_SIZE)
        self._threads = []
        self.microphone = self._stt = self._tts = self._wake = None

    def start(self):
        if self._used:
            raise RuntimeError("Creează un VoiceManager nou pentru o sesiune nouă")
        self._used = True
        try:
            # Toate dependențele/modelul se verifică înainte de captura ALSA.
            self._vad = VoiceActivityDetector()
            self._segmenter = SpeechSegmenter()
            self._wake = WakeWordDetector() if self.require_wakeword else None
            self._stt = SpeechToText()
            self._tts = TextToSpeech() if config.VOICE_OUTPUT_ENABLED else None
            self.microphone = Microphone().start()
            with self._lock:
                self._running = True
                self._state = "waiting_wakeword" if self.require_wakeword else "listening"
            workers = [("poro-voice-audio", self._audio_loop),
                       ("poro-voice-stt", self._stt_loop)]
            if config.VOICE_OUTPUT_ENABLED:
                workers.append(("poro-voice-tts", self._tts_loop))
            for name, target in workers:
                thread = Thread(target=target, name=name, daemon=True)
                thread.start()
                self._threads.append(thread)
        except BaseException:
            self.close()
            raise
        logging.info("Voice activ: wake=%s, STT=%s, TTS=%s, ALSA=%s",
                     config.VOICE_WAKE_WORD if self.require_wakeword else "dezactivat",
                     config.VOICE_STT_LANGUAGE,
                     config.VOICE_TTS_BACKEND if config.VOICE_OUTPUT_ENABLED else "oprit",
                     config.VOICE_CAPTURE_DEVICE)
        return self

    def _muted_locked(self):
        return self._speeches > 0 or time.monotonic() < self._resume_after

    @property
    def is_speaking(self):
        with self._lock:
            return self._running and self._muted_locked()

    @property
    def is_listening(self):
        with self._lock:
            return self._running and self._fatal is None and not self._suspended and not self._muted_locked()

    def suspend_listening(self):
        """Oprește VAD/wake/STT fără a închide ALSA; captura continuă să fie drenată."""
        with self._lock:
            if not self._running:
                raise RuntimeError("VoiceManager nu este pornit")
            self._suspended = True
            self._epoch += 1
            if self._recognition_cancel is not None:
                self._recognition_cancel.set()
            self._drain(self._jobs)
            self._drain(self._texts)
            self._state = "suspended"

    def resume_listening(self):
        with self._lock:
            if not self._running:
                raise RuntimeError("VoiceManager nu este pornit")
            self._suspended = False
            self._epoch += 1
            self._state = "waiting_wakeword" if self.require_wakeword else "listening"

    def set_muted(self, muted):
        """Mute or unmute speaker output and immediately stop any active TTS playback."""
        config.VOICE_OUTPUT_ENABLED = not bool(muted)
        if muted:
            with self._lock:
                self._tts_cancel.set()
                while True:
                    try:
                        _, _, future = self._speech_jobs.get_nowait()
                        future.cancel()
                        self._speeches = max(0, self._speeches - 1)
                    except Empty:
                        break
            if self._tts is not None:
                try:
                    self._tts.stop_current()
                except Exception:
                    pass

    @staticmethod
    def _drain(queue):
        while True:
            try:
                queue.get_nowait()
            except Empty:
                return

    _accepts_emotion = True

    def speak(self, text, emotion=None):
        """Întoarce imediat Future; ridică queue.Full dacă ieșirea este saturată."""
        if not isinstance(text, str) or not text.strip() or len(text) > config.VOICE_TTS_MAX_CHARS:
            raise ValueError(f"Textul trebuie să aibă 1..{config.VOICE_TTS_MAX_CHARS} caractere")
        future = Future()
        if not config.VOICE_OUTPUT_ENABLED:
            with self._lock:
                if not self._running or self._stop.is_set():
                    raise RuntimeError("VoiceManager nu este pornit")
            future.set_result(None)
            return future
        with self._lock:
            if not self._running or self._stop.is_set():
                raise RuntimeError("VoiceManager nu este pornit")
            self._speech_jobs.put_nowait((text, emotion, future))
            self._speeches += 1
            self._epoch += 1  # invalidează audio/STT deja în zbor
            if self._recognition_cancel is not None:
                self._recognition_cancel.set()
            self._drain(self._jobs)
            self._drain(self._texts)
            self._state = "speaking"
        return future

    _WAKE_FILLERS = frozenset({
        "hei", "hai", "hey", "ei", "he", "hi", "hello", "pe", "okay", "ok", "k",
        "poro", "boro", "borro", "pero", "porro", "paul", "borrow", "for", "four",
        "photo", "portal", "polo", "puerto", "plurro", "plural", "pluto",
        "paulo", "pablo", "perro", "burrow", "buro", "paro",
    })
    _WAKE_CORE = frozenset({
        "poro", "boro", "borro", "pero", "porro", "paul", "borrow", "photo", "portal",
        "polo", "puerto", "plurro", "plural", "pluto", "paulo", "pablo",
        "perro", "burrow", "buro", "paro",
    })
    _ACK_ECHOES = frozenset({"yes", "yes yes", "yeah", "yeah yeah", "yep", "ya", "da", "da l", "dal", "dă l", "dăl", "de", "da da"})

    @classmethod
    def _is_bare_wake(cls, text):
        """True dacă textul transcris este doar wake phrase-ul repetat, fără o comandă."""
        plain = "".join(c for c in unicodedata.normalize("NFD", text.casefold())
                        if unicodedata.category(c) != "Mn")
        words = re.findall(r"\w+", plain)
        return (0 < len(words) <= 3 and all(w in cls._WAKE_FILLERS for w in words)
                and words[-1] in cls._WAKE_CORE)

    @classmethod
    def _is_ack_echo(cls, text):
        """True dacă microfonul a prins ecoul propriului «Yes?» / «Da?»."""
        plain = "".join(c for c in unicodedata.normalize("NFD", text.casefold())
                        if unicodedata.category(c) != "Mn")
        key = " ".join(re.findall(r"\w+", plain)).strip()
        return key in cls._ACK_ECHOES

    _WAKE_PREFIX_RE = re.compile(
        r"^\s*(?:"
        r"(?:(?:hei|hai|hey|hi|hello|ei|he|pe|okay|ok|k)[\s,.:;!?-]+)+(?:poro|boro|borro|pero|porro|paul|borrow|for|four|photo|portal|polo|poor|put\s+her|part|puerto|plurro|plural|pluto|paulo|pablo|perro|burrow|buro|paro|bro|pro)\b"
        r"|(?:poro|boro|borro|pero|porro|people|puerto|plurro)\b"
        r")[\s,.:;!?-]*",
        re.IGNORECASE,
    )

    @classmethod
    def _strip_wake_prefix(cls, text):
        """Elimină «Hei Poro» de la începutul unei comenzi rostite dintr-o bucată."""
        plain = "".join(c for c in unicodedata.normalize("NFD", text)
                        if unicodedata.category(c) != "Mn")
        match = cls._WAKE_PREFIX_RE.match(plain)
        if match and match.end() < len(plain):
            # Păstrăm diacriticele din restul textului original
            return text[match.end():].strip()
        return text

    def _acknowledge_wake(self):
        """«Hei Poro» fără comandă: deschide fereastra de comandă imediat."""
        self._ack_armed_until = time.monotonic() + config.VOICE_WAKE_COMMAND_TIMEOUT
        text = getattr(config, "VOICE_WAKE_ACK", "")
        if not text or not config.VOICE_OUTPUT_ENABLED or self._tts is None:
            return
        try:
            self._ack_future = self.speak(text, "curious")
        except Exception as error:
            logging.warning("Confirmarea wake word a eșuat: %s", error)

    def listen(self, timeout=0.0):
        """Text sau None; implicit polling non-blocking pentru brain/eye loop."""
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("timeout trebuie să fie finit și >= 0")
        self.check_health()
        try:
            epoch, text = self._texts.get(timeout=timeout)
        except Empty:
            return None
        with self._lock:
            return text if epoch == self._epoch and not self._suspended and not self._muted_locked() else None

    def get_status(self):
        with self._lock:
            return {"running": self._running, "state": self._state,
                    "output_enabled": config.VOICE_OUTPUT_ENABLED,
                    "is_speaking": self._running and self._muted_locked(),
                    "is_listening": self._running and self._fatal is None and not self._suspended and not self._muted_locked(),
                    "stt_busy": self._stt_busy, "wake_count": self._wake_count,
                    "recognized_count": self._recognized_count, "discarded_jobs": self._discarded_jobs,
                    "last_stt_seconds": self._last_stt_seconds, "last_error": self._last_error,
                    "microphone_dbfs": self.microphone.last_dbfs if self.microphone else None,
                    "dropped_audio_frames": self.microphone.dropped_frames if self.microphone else 0}

    def _tail_has_speech(self, pcm):
        vad = VoiceActivityDetector()
        voiced = sum(vad.is_speech(pcm[offset:offset + vad.frame_bytes])
                     for offset in range(0, len(pcm) - vad.frame_bytes + 1, vad.frame_bytes))
        return voiced * config.VOICE_FRAME_MS / 1000 >= config.VOICE_MIN_COMMAND_SECONDS

    def _audio_loop(self):
        epoch = -1
        previous_sequence = None
        armed_until = 0.0
        command_started = False
        try:
            while not self._stop.is_set():
                frame = self.microphone.read()
                if frame is None:
                    continue
                with self._lock:
                    current_epoch = self._epoch
                    muted = self._suspended or self._muted_locked()
                    cutoff = self._resume_after
                if (current_epoch != epoch or muted
                        or frame.captured_at - config.VOICE_FRAME_MS / 1000 < cutoff
                        or (previous_sequence is not None and frame.sequence != previous_sequence + 1)):
                    self._segmenter.reset()
                    armed_until = 0.0
                    command_started = False
                    if current_epoch != epoch:
                        self._vad = VoiceActivityDetector()
                    epoch = current_epoch
                previous_sequence = frame.sequence
                if muted or frame.captured_at - config.VOICE_FRAME_MS / 1000 < cutoff:
                    continue  # microfonul continuă să fie drenat pe durata TTS + ecou
                armed_until = max(armed_until, self._ack_armed_until)
                speech = self._vad.is_speech(frame.pcm)
                was_active = self._segmenter.active
                utterance = self._segmenter.feed(frame.pcm, speech)
                now = time.monotonic()
                if not was_active and self._segmenter.active:
                    command_started = frame.captured_at < armed_until
                with self._lock:
                    if epoch == self._epoch and not self._suspended and not self._muted_locked():
                        if self._segmenter.active:
                            self._state = ("detecting_wakeword" if self.require_wakeword and not command_started
                                           else "recording")
                        else:
                            self._state = ("listening" if not self.require_wakeword or now < armed_until
                                           else "waiting_wakeword")
                if utterance is None:
                    continue
                pcm = utterance.pcm
                if utterance.truncated:
                    logging.info("Fraza a atins limita de %.1f secunde", config.VOICE_MAX_UTTERANCE_SECONDS)
                if self.require_wakeword and not command_started:
                    hit = self._wake.find(pcm)
                    if hit is None:
                        logging.info("Audio %.2fs ignorat (fără «%s»)",
                                     len(pcm) / (config.VOICE_SAMPLE_RATE * 2), config.VOICE_WAKE_WORD)
                        continue
                    with self._lock:
                        if epoch != self._epoch or self._suspended or self._muted_locked():
                            continue
                        self._wake_count += 1
                        self._state = "listening"
                    logging.info("WAKE WORD: %s — ascult comanda", hit.word)
                    armed_until = now + config.VOICE_WAKE_COMMAND_TIMEOUT
                    offset = max(0, int((hit.end_seconds - 0.06) * config.VOICE_SAMPLE_RATE)) * 2
                    tail = pcm[offset:]
                    if not self._tail_has_speech(tail) and utterance.voiced_seconds < 0.70:
                        self._acknowledge_wake()
                        continue  # wake separat: comanda este următoarea frază
                armed_until = 0.0
                self._ack_armed_until = 0.0
                command_started = False
                with self._lock:
                    if epoch != self._epoch or self._suspended or self._muted_locked():
                        continue
                    try:
                        self._jobs.put_nowait(RecognitionJob(pcm, epoch))
                    except Full:
                        self._discarded_jobs += 1
                        logging.warning("STT ocupat; fraza nouă a fost ignorată")
        except Exception as error:
            if not self._stop.is_set():
                with self._lock:
                    self._fatal = error
                    self._last_error = str(error)
                logging.exception("Captura/VAD/wakeword nu mai pot continua")

    def _stt_loop(self):
        while not self._stop.is_set():
            try:
                job = self._jobs.get(timeout=0.1)
            except Empty:
                continue
            cancel = Event()
            with self._lock:
                if job.epoch != self._epoch or self._suspended or self._muted_locked():
                    continue
                self._recognition_cancel = cancel
                self._stt_busy = True
            started = time.monotonic()
            try:
                text = self._stt.transcribe(job.pcm, cancel=cancel)
                if not text and self.require_wakeword:
                    self._ack_armed_until = time.monotonic() + config.VOICE_WAKE_COMMAND_TIMEOUT
                elif text and self.require_wakeword and self._is_bare_wake(text):
                    logging.info("STT: «%s» este doar wake word; confirm și ascult comanda", text)
                    text = None
                    self._acknowledge_wake()
                elif text and self.require_wakeword and self._is_ack_echo(text):
                    logging.info("STT: «%s» ignorat (ecou confirmare); redeschid fereastra de comandă", text)
                    text = None
                    self._ack_armed_until = time.monotonic() + config.VOICE_WAKE_COMMAND_TIMEOUT
                elif text and self.require_wakeword:
                    text = self._strip_wake_prefix(text)
                with self._lock:
                    if text and job.epoch == self._epoch and not self._suspended and not self._muted_locked() and not self._stop.is_set():
                        try:
                            self._texts.put_nowait((job.epoch, text))
                        except Full:
                            try:
                                self._texts.get_nowait()
                            except Empty:
                                pass  # listen() poate consuma simultan
                            self._texts.put_nowait((job.epoch, text))
                        self._recognized_count += 1
                        logging.info("STT: %s", text)
            except CancelledError:
                pass
            except Exception as error:
                with self._lock:
                    self._last_error = str(error)
                logging.warning("STT a eșuat: %s", error)
            finally:
                with self._lock:
                    self._last_stt_seconds = round(time.monotonic() - started, 2)
                    self._stt_busy = False
                    self._recognition_cancel = None

    def _tts_loop(self):
        while not self._stop.is_set():
            try:
                text, emotion, future = self._speech_jobs.get(timeout=0.1)
            except Empty:
                continue
            error = None
            active = future.set_running_or_notify_cancel()
            try:
                # speak() deține acest lock până când a închis poarta audio.
                with self._lock:
                    stopping = self._stop.is_set()
                    tts_cancel = Event()
                    self._tts_cancel = tts_cancel
                if stopping or not config.VOICE_OUTPUT_ENABLED:
                    raise CancelledError()
                if active:
                    if emotion is not None:
                        self._tts.speak(text, cancel=tts_cancel, emotion=emotion)
                    else:
                        self._tts.speak(text, cancel=tts_cancel)
            except Exception as caught:
                error = caught
                if not isinstance(caught, CancelledError):
                    with self._lock:
                        self._last_error = str(caught)
                    logging.warning("TTS a eșuat: %s", caught)
            finally:
                with self._lock:
                    self._resume_after = time.monotonic() + config.VOICE_ECHO_GUARD_SECONDS
                    if future is self._ack_future:
                        self._ack_future = None
                    self._ack_armed_until = (self._resume_after
                                             + config.VOICE_WAKE_COMMAND_TIMEOUT)
                self._stop.wait(config.VOICE_ECHO_GUARD_SECONDS)
                with self._lock:
                    self._speeches = max(0, self._speeches - 1)
                if active:
                    if error is not None:
                        future.set_exception(error)
                    else:
                        future.set_result(None)

    def check_health(self):
        with self._lock:
            if self._fatal is not None:
                raise RuntimeError("Voice pipeline indisponibil") from self._fatal
            if not self._running or self._stop.is_set():
                raise RuntimeError("VoiceManager nu este pornit")
        self.microphone.check_health()

    def close(self):
        self._stop.set()
        with self._lock:
            self._running = False
            self._epoch += 1
            self._state = "stopped"
            if self._recognition_cancel is not None:
                self._recognition_cancel.set()
        if self._stt is not None:
            self._stt.close()
        if self._tts is not None:
            self._tts.close()
        if self.microphone is not None:
            self.microphone.close()
        for thread in self._threads:
            thread.join(timeout=3)
            if thread.is_alive():
                raise RuntimeError(f"Thread-ul {thread.name} nu s-a oprit")
        while True:
            try:
                *_, future = self._speech_jobs.get_nowait()
                future.cancel()
            except Empty:
                break

    def __enter__(self):
        return self.start()

    def __exit__(self, *args):
        self.close()
