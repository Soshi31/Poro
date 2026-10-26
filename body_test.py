#!/usr/bin/python3
"""Test real body: evenimente IMU și, opțional, o acțiune semantică a limbii."""

import argparse
import json
import logging
import math
import signal
import time

from body.body_manager import BodyManager
from body.tongue import TongueController


def stop(signum, frame):
    raise KeyboardInterrupt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--duration', type=float, default=0, help='Secunde; 0 = până la Ctrl+C')
    hardware = parser.add_mutually_exclusive_group()
    hardware.add_argument('--imu-only', action='store_true', help='Nu inițializează PCA9685')
    hardware.add_argument('--tongue-only', action='store_true', help='Diagnostic PCA9685 fără BNO085')
    parser.add_argument('--action', choices=sorted(TongueController.ACTIONS), help='Acțiune unică după stabilizarea IMU')
    args = parser.parse_args(argv)
    if not math.isfinite(args.duration) or args.duration < 0:
        parser.error('Durata trebuie să fie finită și >= 0')
    if args.imu_only and args.action:
        parser.error('--action nu se folosește cu --imu-only')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s', datefmt='%H:%M:%S')
    signal.signal(signal.SIGTERM, stop)
    try:
        with BodyManager(enable_tongue=not args.imu_only, enable_imu=not args.tongue_only) as body, body.subscribe() as events:
            started = logged = time.monotonic()
            action = args.action
            pending = None
            logging.info('Body pornit. %s Ctrl+C oprește.',
                         'Diagnostic doar limbă.' if args.tongue_only else 'Așteaptă body_ready cu Poro nemișcat.')
            while not args.duration or time.monotonic() - started < args.duration:
                body.check_health()
                state = body.get_state()
                if action and state['ready']:
                    pending = getattr(body, action)()
                    action = None
                if pending is not None and pending.done():
                    logging.info('ACTION %s', pending.result())
                    pending = None
                for event in events.drain():
                    logging.info('EVENT %s', json.dumps(event.to_dict(), ensure_ascii=False))
                if time.monotonic() - logged >= 2:
                    logging.info('BODY %s', json.dumps(state, ensure_ascii=False))
                    logged = time.monotonic()
                time.sleep(0.02)
            if pending is not None or action is not None:
                logging.warning('Durata s-a terminat înainte de încheierea acțiunii')
        return 0
    except KeyboardInterrupt:
        logging.info('Body oprit; PWM limbă dezactivat.')
        return 0
    except Exception:
        logging.exception('Testul body a eșuat')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
