"""Regresii de concurență și segmentare. Dublurile există numai în teste."""

from concurrent.futures import CancelledError
from queue import Full
import sys
from threading import Event, Thread
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import config
from voice.process import ProcessRunner
from voice.microphone import AudioFrame
from voice.stt import clean_transcript
from voice.vad import SpeechSegmenter, Utterance
from voice.voice_manager import RecognitionJob, VoiceManager
from voice.wakeword import WakeHit, WakeWordDetector


class WakePhraseTests(unittest.TestCase):
    def test_phrase_ends_after_poro_and_preserves_following_command(self):
        class Decoder:
            def __init__(self, token):
                self.token = token
                self.words = []
                self.keyphrase = None

            def add_word(self, word, phones):
                self.words.append((word, phones))

            def add_keyphrase(self, name, phrase):
                self.keyphrase = phrase

            def activate_search(self, name):
                pass

            def start_utt(self):
                pass

            def process_raw(self, pcm, a, b):
                pass

            def end_utt(self):
                pass

            def hyp(self):
                return SimpleNamespace(hypstr=self.token)

            def seg(self):
                return [SimpleNamespace(word=self.token, start_frame=5 if self.token == "hei" else 45,
                                        end_frame=32 if self.token == "hei" else 83)]

        decoders = [Decoder("hei"), Decoder("poro")]
        with patch('voice.wakeword.pocketsphinx', return_value=SimpleNamespace(
                Decoder=lambda **kw: decoders.pop(0))):
            detector = WakeWordDetector()
        self.assertEqual([decoder.keyphrase for decoder in detector._decoders], ["hei", "poro"])
        self.assertEqual(sum(len(decoder.words) for decoder in detector._decoders),
                         sum(len(opts) for opts in config.VOICE_WAKE_PHONEMES))
        self.assertEqual(detector.find(b'audio'), WakeHit("hei poro", 0.84))



class SegmentTests(unittest.TestCase):
    def test_hallucinated_repetitions_and_punctuation_are_rejected(self):
        self.assertEqual(clean_transcript('... ' * 80), '')
        self.assertEqual(clean_transcript('Nu-' * 80), '')
        self.assertEqual(clean_transcript('[BLANK_AUDIO]'), '')
        self.assertEqual(clean_transcript(' Salut,  Poro! '), 'Salut, Poro!')
        self.assertEqual(clean_transcript('Sarut!'), 'Salut!')

    def test_preroll_and_silence_end(self):
        s = SpeechSegmenter()
        for _ in range(10):
            self.assertIsNone(s.feed(b'quiet', False))
        for _ in range(12):
            self.assertIsNone(s.feed(b'voice', True))
        self.assertTrue(s.active)
        result = None
        for _ in range(22):
            result = result or s.feed(b'end', False)
        self.assertIsNotNone(result)
        self.assertTrue(result.pcm.startswith(b'quiet'))
        self.assertIn(b'voice', result.pcm)
        self.assertFalse(result.truncated)
        self.assertFalse(s.active)

    def test_noise_rejected_and_long_speech_bounded(self):
        s = SpeechSegmenter()
        s.feed(b'click', True)
        for _ in range(50):
            self.assertIsNone(s.feed(b'quiet', False))
        s.reset()
        result = None
        for _ in range(300):
            result = s.feed(b'x', True)
            if result:
                break
        self.assertTrue(result.truncated)
        self.assertLessEqual(len(result.pcm), 267)


class VoiceConcurrencyTests(unittest.TestCase):
    def manager(self):
        enabled = patch.object(config, 'VOICE_OUTPUT_ENABLED', True)
        enabled.start()
        self.addCleanup(enabled.stop)
        manager = VoiceManager(require_wakeword=False)
        manager._running = True
        self.addCleanup(manager.close)
        return manager

    def test_silent_mode_keeps_listening_and_skips_tts(self):
        v = self.manager()
        with patch.object(config, 'VOICE_OUTPUT_ENABLED', False):
            future = v.speak('Salut')
            self.assertTrue(future.done())
            self.assertTrue(v.is_listening)
            self.assertFalse(v.is_speaking)
            self.assertTrue(v._speech_jobs.empty())

    def test_command_started_before_deadline_can_finish_after_it(self):
        v = self.manager()
        v.require_wakeword = True
        clock = [1.0]
        frames = iter([(1, 1.0), (2, 6.0), (3, 9.0)])

        class Mic:
            def read(self):
                try:
                    seq, at = next(frames)
                except StopIteration:
                    v._stop.set()
                    return None
                clock[0] = at
                return AudioFrame(seq, at, b'pcm')

            def close(self):
                pass

        class Segmenter:
            active = False
            count = 0

            def reset(self):
                self.active = False

            def feed(self, pcm, speech):
                self.count += 1
                self.active = self.count == 2
                return None if self.active else Utterance(b'command', .5, False)

        v.microphone = Mic()
        v._segmenter = Segmenter()
        with patch('voice.voice_manager.VoiceActivityDetector'), \
                patch('voice.voice_manager.time.monotonic', side_effect=lambda: clock[0]), \
                patch.object(v, '_tail_has_speech', return_value=False), \
                patch('voice.voice_manager.WakeWordDetector') as wake:
            v._wake = wake.return_value
            v._wake.find.return_value = WakeHit('poro', 0)
            v._audio_loop()
            self.assertEqual(v._wake.find.call_count, 1)
        self.assertEqual(v._jobs.get_nowait().pcm, b'command')

    def test_speak_immediately_gates_and_invalidates_audio(self):
        v = self.manager()
        v._recognition_cancel = Event()
        v._jobs.put(RecognitionJob(b'old', 0))
        v._texts.put((0, 'old'))
        future = v.speak('Salut')
        self.assertTrue(v.is_speaking)
        self.assertFalse(v.is_listening)
        self.assertTrue(v._recognition_cancel.is_set())
        self.assertTrue(v._jobs.empty())
        self.assertTrue(v._texts.empty())
        self.assertEqual(v._epoch, 1)
        v.close()
        self.assertTrue(future.cancelled())

    def test_suspend_discards_pending_audio_and_resume_rearms(self):
        v = self.manager()
        class Mic:
            last_dbfs = None
            dropped_frames = 0

            def check_health(self):
                pass

            def close(self):
                pass

        v.microphone = Mic()
        v._jobs.put(RecognitionJob(b'old', 0))
        v._texts.put((0, 'old'))
        v.suspend_listening()
        self.assertFalse(v.is_listening)
        self.assertFalse(v.is_speaking)
        self.assertEqual(v.get_status()['state'], 'suspended')
        self.assertTrue(v._jobs.empty())
        self.assertIsNone(v.listen())
        v.resume_listening()
        self.assertTrue(v.is_listening)
        self.assertEqual(v.get_status()['state'], 'listening')

    def test_tts_queue_overflow_does_not_change_gate_state(self):
        v = self.manager()
        for _ in range(config.VOICE_TTS_QUEUE_SIZE):
            v.speak('Salut')
        epoch = v._epoch
        with self.assertRaises(Full):
            v.speak('Prea multe')
        self.assertEqual(v._epoch, epoch)
        self.assertEqual(v._speeches, config.VOICE_TTS_QUEUE_SIZE)

    def test_late_stt_result_after_speak_is_discarded(self):
        v = self.manager()
        entered, release = Event(), Event()

        class DelayedSTT:
            def transcribe(self, pcm, cancel):
                entered.set()
                release.wait(2)
                return 'vocea veche'

            def close(self):
                release.set()

        v._stt = DelayedSTT()
        v._jobs.put(RecognitionJob(b'pcm', 0))
        worker = Thread(target=v._stt_loop)
        v._threads.append(worker)
        worker.start()
        self.assertTrue(entered.wait(1))
        v.speak('Răspuns')
        release.set()
        v.close()
        self.assertTrue(v._texts.empty())

    def test_playback_cannot_start_before_gate_is_closed(self):
        v = self.manager()
        entered = Event()
        gate = []

        class TTS:
            def speak(self, text, cancel):
                gate.append((v.is_speaking, v.is_listening))
                entered.set()

            def close(self):
                pass

        v._tts = TTS()
        worker = Thread(target=v._tts_loop)
        v._threads.append(worker)
        worker.start()
        with patch.object(config, 'VOICE_ECHO_GUARD_SECONDS', 0.01):
            future = v.speak('Salut')
            self.assertTrue(entered.wait(1))
            future.result(timeout=1)
        self.assertEqual(gate, [(True, False)])
        self.assertTrue(v.is_listening)


class ProcessTests(unittest.TestCase):
    def test_timeout_reaps_child_and_allows_reuse(self):
        runner = ProcessRunner()
        self.addCleanup(runner.close)
        with self.assertRaises(TimeoutError):
            runner.run([sys.executable, '-c', 'import time; time.sleep(10)'], timeout=0.15)
        self.assertIsNone(runner._process)
        self.assertEqual(runner.run([sys.executable, '-c', 'print(42)'], timeout=2).strip(), b'42')

    def test_cancelled_command_never_starts(self):
        runner = ProcessRunner()
        cancelled = Event()
        cancelled.set()
        with self.assertRaises(CancelledError):
            runner.run(['/nonexistent-command'], timeout=1, cancel=cancelled)
        self.assertIsNone(runner._process)
        runner.close()


if __name__ == '__main__':
    unittest.main()
