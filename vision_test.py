#!/usr/bin/python3
"""Test real Camera V3 Wide -> față -> ambii ochi GC9A01, fără preview."""

import argparse
from contextlib import ExitStack
import logging
import json
import math
import signal
import time

import config
from display_manager import DisplayManager
from eye_controller import EMOTIONS, EyeSystem
from eye_renderer import EyeRenderer, load_assets
from vision.eye_control import EyeTrackingController
from vision.perception import PerceptionSystem


def _stop(signum, frame):
    raise KeyboardInterrupt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emotion", choices=EMOTIONS, default="neutral")
    parser.add_argument("--duration", type=float, default=0,
                        help="Durată în secunde; implicit 0 = până la Ctrl+C.")
    parser.add_argument("--events", action="store_true", help="Afișează evenimentele JSON (maximum 4/s pentru poziție).")
    parser.add_argument("--scene", action="store_true", help="Afișează starea structurată la intervalul statisticilor.")
    args = parser.parse_args(argv)
    if not math.isfinite(args.duration) or args.duration < 0:
        parser.error("--duration trebuie să fie finit și >= 0")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s",
                        datefmt="%H:%M:%S")
    signal.signal(signal.SIGTERM, _stop)
    try:
        if not math.isfinite(config.FPS) or config.FPS <= 0:
            raise ValueError("FPS trebuie să fie pozitiv și finit.")
        if not math.isfinite(config.VISION_LOG_INTERVAL) or config.VISION_LOG_INTERVAL <= 0:
            raise ValueError("VISION_LOG_INTERVAL trebuie să fie pozitiv și finit.")
        # Validăm dependențele și PNG-urile înainte să deschidem hardware-ul.
        perception = PerceptionSystem()
        eyes = EyeSystem(EyeRenderer(load_assets()))
        eyes.set_emotion(args.emotion)
        controller = EyeTrackingController(eyes)
        with ExitStack() as stack:
            stream = stack.enter_context(perception.subscribe()) if args.events else None
            stack.enter_context(perception)
            camera, worker = perception.camera, perception.face_worker
            displays = stack.enter_context(DisplayManager())
            logging.info("Tracking activ. Ctrl+C pentru oprire. Emoție: %s", args.emotion)
            started = previous = log_at = time.monotonic()
            eye_frames = 0
            initial_frame = camera.latest_frame()
            camera_count = initial_frame.sequence if initial_frame is not None else 0
            detection_count = worker.count
            period = 1.0 / config.FPS
            while True:
                now = time.monotonic()
                if args.duration and now - started >= args.duration:
                    break
                dt, previous = now - previous, now
                perception.check_health()
                target = perception.get_tracking_target()
                controller.update(target)
                eyes.update(dt)
                displays.show_both(*eyes.render())
                if stream is not None:
                    for event in stream.drain(limit=8):
                        logging.info("EVENT %s", json.dumps(event.to_dict(), ensure_ascii=False))
                eye_frames += 1
                elapsed = now - log_at
                if elapsed >= config.VISION_LOG_INTERVAL:
                    frame = camera.latest_frame()
                    captured = frame.sequence if frame is not None else 0
                    detected = worker.count
                    position = "-" if target.x is None else f"x={target.x:+.3f} y={target.y:+.3f}"
                    logging.info("%s face %s | FPS cameră=%.1f detecție=%.1f ochi=%.1f",
                                 target.state, position, (captured - camera_count) / elapsed,
                                 (detected - detection_count) / elapsed, eye_frames / elapsed)
                    log_at, camera_count, detection_count = now, captured, detected
                    eye_frames = 0
                    if args.scene:
                        logging.info("SCENE %s", json.dumps(perception.get_current_scene_state(), ensure_ascii=False))
                remaining = period - (time.monotonic() - now)
                if remaining > 0:
                    time.sleep(remaining)
        return 0
    except KeyboardInterrupt:
        logging.info("Oprit. Camera, worker-ul, SPI și GPIO eliberate.")
        return 0
    except Exception:
        logging.exception("Trackingul nu a putut continua.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
