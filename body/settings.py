"""Validare înainte de orice acces la servo sau IMU."""

import math
import config


def validate_settings():
    positive = (
        'BODY_POLL_HZ', 'BODY_REPORT_INTERVAL_US', 'BODY_SENSOR_TIMEOUT', 'BODY_WARMUP_SECONDS',
        'BODY_SMOOTHING_SECONDS', 'BODY_GRAVITY_SMOOTHING_SECONDS', 'BODY_TILT_DWELL_SECONDS',
        'BODY_TILT_COOLDOWN_SECONDS', 'BODY_MOVE_START_SECONDS', 'BODY_MOVE_STOP_SECONDS',
        'BODY_SHAKE_ACCEL', 'BODY_SHAKE_WINDOW_SECONDS', 'BODY_SHAKE_COOLDOWN_SECONDS',
        'BODY_LIFT_ACCEL', 'BODY_LIFT_BRAKE_ACCEL', 'BODY_LIFT_MIN_IMPULSE',
        'BODY_LIFT_WINDOW_SECONDS', 'BODY_LIFT_SETTLE_SECONDS', 'BODY_PUT_DOWN_SETTLE_SECONDS',
        'BODY_LIFT_COOLDOWN_SECONDS', 'TONGUE_SPEED_DEG_PER_SECOND',
        'TONGUE_BLEP_HOLD_SECONDS', 'TONGUE_DOUBLE_BLEP_GAP_SECONDS',
    )
    for name in positive:
        if not math.isfinite(getattr(config, name)) or getattr(config, name) <= 0:
            raise ValueError(f'{name} trebuie să fie pozitiv și finit')
    if not math.isfinite(config.BODY_I2C_READ_PAUSE_SECONDS) or not 0 <= config.BODY_I2C_READ_PAUSE_SECONDS <= .01:
        raise ValueError('Pauza I2C trebuie să fie între 0 și 10 ms')
    for name in ('BODY_EVENT_CAPACITY', 'BODY_SHAKE_MIN_PEAKS', 'TONGUE_ACTION_QUEUE_SIZE'):
        if type(getattr(config, name)) is not int or getattr(config, name) < 1:
            raise ValueError(f'{name} trebuie să fie întreg pozitiv')
    if config.BODY_SHAKE_MIN_PEAKS < 3:
        raise ValueError('Scuturarea necesită minimum trei impulsuri alternante')
    if not 0 < config.BODY_TILT_EXIT_DEG < config.BODY_TILT_ENTER_DEG < 90:
        raise ValueError('Praguri tilt invalide')
    if not 90 < config.BODY_UPSIDE_EXIT_DEG < config.BODY_UPSIDE_ENTER_DEG < 180:
        raise ValueError('Praguri upside_down invalide')
    for kind in ('ACCEL', 'GYRO'):
        if not 0 < getattr(config, f'BODY_MOVE_{kind}_EXIT') < getattr(config, f'BODY_MOVE_{kind}_ENTER'):
            raise ValueError('Praguri movement invalide')
    axes = config.BODY_AXIS_MAP
    if len(axes) != 3 or {abs(v) for v in axes} != {1, 2, 3} or any(type(v) is not int for v in axes):
        raise ValueError('BODY_AXIS_MAP trebuie să fie o permutare cu semn a (1, 2, 3)')
    # Matrice de rotație: respinge reflexiile care ar inversa orientarea axelor.
    inversions = sum(abs(axes[i]) > abs(axes[j]) for i in range(3) for j in range(i + 1, 3))
    if (-1) ** inversions * math.prod(1 if v > 0 else -1 for v in axes) != 1:
        raise ValueError('BODY_AXIS_MAP trebuie să păstreze orientarea axelor (determinant +1)')
    for name in ('BODY_IMU_ADDRESS', 'BODY_PCA_ADDRESS'):
        if type(getattr(config, name)) is not int or not 0x08 <= getattr(config, name) <= 0x77:
            raise ValueError('Adresă I2C invalidă')
    if type(config.TONGUE_CHANNEL) is not int or not 0 <= config.TONGUE_CHANNEL < 16:
        raise ValueError('Canal servo invalid')
    if not 0 <= config.TONGUE_MIN_ANGLE < config.TONGUE_MAX_ANGLE <= 180:
        raise ValueError('Limitele servo trebuie să fie între 0 și 180')
    for angle in (config.TONGUE_IN_ANGLE, config.TONGUE_OUT_ANGLE):
        if not config.TONGUE_MIN_ANGLE <= angle <= config.TONGUE_MAX_ANGLE:
            raise ValueError('Pozițiile limbii depășesc limitele configurate')
    if config.TONGUE_IN_ANGLE == config.TONGUE_OUT_ANGLE:
        raise ValueError('Pozițiile in/out trebuie să fie diferite')
    if not 0 < config.TONGUE_BLEP_FRACTION <= 1:
        raise ValueError('Fracția blep trebuie să fie în (0, 1]')
    if not 500 <= config.TONGUE_MIN_PULSE_US < config.TONGUE_MAX_PULSE_US <= 2500:
        raise ValueError('Interval PWM invalid: trebuie calibrat în 500..2500 µs')
    if config.TONGUE_PWM_HZ != 50:
        raise ValueError('Montajul existent folosește PWM 50 Hz')
    release = config.TONGUE_RELEASE_IDLE_SECONDS
    if release is not None and (not math.isfinite(release) or release <= 0):
        raise ValueError('TONGUE_RELEASE_IDLE_SECONDS trebuie să fie pozitiv sau None')
