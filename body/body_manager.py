"""API body: un worker I2C, cozi limitate și aceeași magistrală de evenimente ca vision."""

from copy import deepcopy
import logging
from threading import Event, Lock, Thread
import time

import config
from core.events import BODY_EVENT_TYPES, EventBus
from hardware.bno085 import BNO085
from hardware.i2c import open_body_i2c
from hardware.pca9685 import TongueServo
from .motion import MotionInterpreter
from .settings import validate_settings
from .tongue import TongueController


class BodyManager:
    def __init__(self, *, event_bus=None, enable_tongue=True, enable_imu=True):
        validate_settings()
        if not enable_tongue and not enable_imu:
            raise ValueError('Activează cel puțin un dispozitiv body')
        self._owns_events = event_bus is None
        self.events = event_bus if event_bus is not None else EventBus(config.BODY_EVENT_CAPACITY)
        self._enable_tongue = enable_tongue
        self._enable_imu = enable_imu
        self._stop = Event()
        self._initialized = Event()
        self._lock = Lock()
        self._used = self._running = False
        self._thread = None
        self._error = None
        self._tongue = None
        self._low_power = False
        self._release_requested = False
        self._state = {'running': False, 'ready': False, 'error': None}

    def start(self):
        if self._used:
            raise RuntimeError('Folosește o instanță BodyManager nouă pentru repornire')
        self._used = True
        self._thread = Thread(target=self._run, name='poro-body-i2c', daemon=True)
        self._thread.start()
        try:
            if not self._initialized.wait(15):
                raise TimeoutError('Inițializarea body a expirat')
            self.check_health()
        except BaseException:
            self.close()
            raise
        return self

    def _run(self):
        i2c = None
        tongue = None
        try:
            i2c = open_body_i2c()
            imu = BNO085(i2c) if self._enable_imu else None
            if self._enable_tongue:
                tongue = TongueController(TongueServo(i2c))
            motion = MotionInterpreter() if imu else None
            with self._lock:
                self._tongue = tongue
                self._running = True
            self._initialized.set()
            if imu is None:
                self.events.publish('body_ready', {'imu_enabled': False, 'tongue_enabled': True},
                                    observed_at=time.monotonic(), source='body')
            last_sample = time.monotonic()
            imu_retry_at = None
            period = 1 / config.BODY_POLL_HZ
            while not self._stop.is_set():
                now = time.monotonic()
                sample = imu.read() if imu else None
                if sample is not None:
                    last_sample = sample.observed_at
                    for name, payload in motion.update(sample):
                        self.events.publish(name, payload, observed_at=sample.observed_at, source='body.imu')
                if imu and time.monotonic() - last_sample > config.BODY_SENSOR_TIMEOUT:
                    if not tongue:
                        raise TimeoutError('BNO085 nu mai livrează rapoarte noi pentru toate cele trei măsurători')
                    # IMU-ul este opțional: limba, ochii și vocea continuă fără el.
                    logging.warning('BNO085 nu mai livrează rapoarte; continui fără IMU, reîncerc periodic')
                    imu = None
                    imu_retry_at = time.monotonic() + 10.0
                elif imu is None and self._enable_imu and imu_retry_at is not None and time.monotonic() >= imu_retry_at:
                    try:
                        imu = BNO085(i2c)
                        motion = motion or MotionInterpreter()
                        last_sample = time.monotonic()
                        logging.info('BNO085 reinițializat')
                    except Exception as error:
                        imu = None
                        imu_retry_at = time.monotonic() + 10.0
                        logging.warning('BNO085 încă indisponibil: %s', error)
                if tongue is not None:
                    with self._lock:
                        release_req = self._release_requested
                        self._release_requested = False
                    if release_req:
                        tongue.release_now()
                    for name, payload in tongue.step(time.monotonic()):
                        self.events.publish(name, payload, observed_at=time.monotonic(), source='body.tongue')
                state = motion.snapshot() if motion else {'ready': True}
                state.update(running=True, error=None, imu_enabled=imu is not None,
                             sensor_observed_at=last_sample if imu else None,
                             invalid_imu_packets=imu.bad_packets if imu else 0,
                             tongue=tongue.snapshot() if tongue else None)
                with self._lock:
                    self._state = state
                    effective_period = (1 / 20.0) if self._low_power else period
                self._stop.wait(max(0, effective_period - (time.monotonic() - now)))
        except Exception as error:
            with self._lock:
                self._error = error
            logging.exception('Body s-a oprit')
            self.events.publish('body_error', {'message': str(error)}, observed_at=time.monotonic(), source='body')
        finally:
            # Ordine: refuză comenzi noi, dezactivează PWM, apoi închide I2C.
            with self._lock:
                self._running = False
            try:
                if tongue is not None:
                    tongue.close(self._error)
            except Exception as error:
                with self._lock:
                    self._error = self._error or error
                logging.exception('Dezactivarea PWM a eșuat')
            finally:
                try:
                    if i2c is not None:
                        i2c.deinit()
                except Exception as error:
                    with self._lock:
                        self._error = self._error or error
                    logging.exception('Închiderea I2C a eșuat')
                with self._lock:
                    self._state.update(running=False, ready=False,
                                       error=str(self._error) if self._error else None,
                                       tongue=tongue.snapshot() if tongue else None)
                self._initialized.set()

    def _action(self, name):
        with self._lock:
            if self._error is not None:
                raise RuntimeError('Body indisponibil') from self._error
            if not self._running or self._stop.is_set():
                raise RuntimeError('BodyManager nu este pornit')
            if self._tongue is None:
                raise RuntimeError('Limba este dezactivată în această sesiune')
            return self._tongue.request(name)

    def tongue_in(self):
        return self._action('tongue_in')

    def tongue_out(self):
        return self._action('tongue_out')

    def tongue_blep(self):
        return self._action('tongue_blep')

    def tongue_double_blep(self):
        return self._action('tongue_double_blep')

    def set_low_power(self, enabled):
        """Reduce frecvența de citire I2C și oprește PWM-ul limbii în modul SLEEP."""
        with self._lock:
            self._low_power = bool(enabled)
            if enabled:
                self._release_requested = True

    def subscribe(self, event_types=None):
        return self.events.subscribe(BODY_EVENT_TYPES if event_types is None else event_types)

    def get_state(self):
        with self._lock:
            state = deepcopy(self._state)
        observed = state.get('sensor_observed_at')
        state['stale'] = (observed is None or time.monotonic() - observed > config.BODY_SENSOR_TIMEOUT) if self._enable_imu else False
        return state

    def check_health(self):
        with self._lock:
            if self._error is not None:
                raise RuntimeError('Body indisponibil') from self._error
            if not self._running or self._stop.is_set():
                raise RuntimeError('BodyManager nu este pornit')

    def close(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                raise RuntimeError('Worker-ul I2C body nu s-a oprit')
        if self._owns_events:
            self.events.close()

    def __enter__(self):
        return self.start()

    def __exit__(self, *args):
        self.close()
