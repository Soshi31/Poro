"""Keyword spotting local pentru o expresie configurabilă, înainte de Whisper."""

from dataclasses import dataclass
import math

import config
from .dependencies import pocketsphinx


@dataclass(frozen=True)
class WakeHit:
    word: str
    end_seconds: float


class WakeWordDetector:
    def __init__(self):
        if not config.VOICE_WAKE_WORD or not config.VOICE_WAKE_PHONEMES:
            raise ValueError("Configurează cuvântul de activare și pronunția lui")
        if not math.isfinite(config.VOICE_WAKE_THRESHOLD) or config.VOICE_WAKE_THRESHOLD <= 0:
            raise ValueError("VOICE_WAKE_THRESHOLD trebuie să fie pozitiv și finit")
        if not math.isfinite(config.VOICE_WAKE_FIRST_THRESHOLD) or config.VOICE_WAKE_FIRST_THRESHOLD <= 0:
            raise ValueError("VOICE_WAKE_FIRST_THRESHOLD trebuie să fie pozitiv și finit")
        if not math.isfinite(config.VOICE_WAKE_MAX_GAP_SECONDS) or config.VOICE_WAKE_MAX_GAP_SECONDS <= 0:
            raise ValueError("VOICE_WAKE_MAX_GAP_SECONDS trebuie să fie pozitiv și finit")
        self.word = " ".join(config.VOICE_WAKE_WORD.casefold().split())
        self._words = self.word.split()
        phonemes = config.VOICE_WAKE_PHONEMES
        # Compatibil și cu configurația veche pentru un singur cuvânt.
        if len(self._words) == 1 and all(isinstance(item, str) for item in phonemes):
            phonemes = (phonemes,)
        if len(self._words) != len(phonemes) or any(not options or isinstance(options, str)
                                                    for options in phonemes):
            raise ValueError("VOICE_WAKE_PHONEMES trebuie să aibă variante pentru fiecare cuvânt")
        self._decoders = []
        for word_index, (token, options) in enumerate(zip(self._words, phonemes)):
            threshold = (config.VOICE_WAKE_FIRST_THRESHOLD if word_index == 0 and len(self._words) > 1
                         else config.VOICE_WAKE_THRESHOLD)
            decoder = pocketsphinx().Decoder(lm=None, samprate=config.VOICE_SAMPLE_RATE,
                                              kws_threshold=threshold, loglevel="ERROR")
            for index, phones in enumerate(options):
                variant = token if index == 0 else f"{token}({index + 1})"
                decoder.add_word(variant, phones)
            decoder.add_keyphrase("wake", token)
            decoder.activate_search("wake")
            self._decoders.append(decoder)

    def find(self, pcm):
        if isinstance(pcm, (bytes, bytearray)) and len(pcm) >= 640 and len(pcm) % 2 == 0:
            import numpy as np
            samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
            peak = float(np.max(np.abs(samples))) / 32768.0
            if peak < 0.015:
                return None
            gain = min(config.VOICE_STT_MAX_GAIN, config.VOICE_STT_NORMALIZE_PEAK / max(peak, 1e-6))
            pcm = np.clip(samples * gain, -32768, 32767).astype("<i2").tobytes()
        sightings = []
        for token, decoder in zip(self._words, self._decoders):
            decoder.start_utt()
            try:
                decoder.process_raw(pcm, False, True)
            finally:
                decoder.end_utt()
            segments = (list(decoder.seg() or ()) if decoder.hyp() is not None else [])
            sightings.append([segment for segment in segments
                              if segment.word.casefold().split("(")[0] == token])
        candidates = [(segment,) for segment in sightings[0]]
        gap_frames = int(config.VOICE_WAKE_MAX_GAP_SECONDS * 100)
        for later in sightings[1:]:
            next_candidates = []
            for chain in candidates:
                first, previous = chain[0], chain[-1]
                # Un singur „Poro” poate produce un fals „Hei” complet suprapus.
                if any(item.start_frame <= first.start_frame + 3 and item.end_frame >= first.end_frame - 3
                       for item in later):
                    continue
                for item in later:
                    gap = item.start_frame - previous.end_frame
                    if -6 <= gap <= gap_frames:
                        next_candidates.append((*chain, item))
            candidates = next_candidates
            if not candidates:
                break
        if candidates:
            end = min(chain[0].start_frame + (chain[-1].end_frame - chain[0].start_frame) for chain in candidates)
            return WakeHit(self.word, (end + 1) / 100)
        # Fallback: în vorbirea naturală, PocketSphinx poate rata „Hei”, dar prinde „Poro”.
        if sightings and sightings[-1]:
            early = [item for item in sightings[-1] if item.start_frame <= 220]
            if early:
                first_hit = min(early, key=lambda item: item.start_frame)
                return WakeHit(self.word, (first_hit.end_frame + 1) / 100)
        return None
