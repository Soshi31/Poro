"""Limite electrice/mecanice pentru canalul limbii; detaliu intern hardware."""

import math

import config


class TongueServo:
    def __init__(self, i2c):
        from adafruit_pca9685 import PCA9685
        from adafruit_motor.servo import Servo

        self._pca = PCA9685(i2c, address=config.BODY_PCA_ADDRESS)
        self._channel = self._pca.channels[config.TONGUE_CHANNEL]
        self._channel.duty_cycle = 0
        try:
            self._pca.frequency = config.TONGUE_PWM_HZ
            self._servo = Servo(self._channel, actuation_range=180,
                                min_pulse=config.TONGUE_MIN_PULSE_US,
                                max_pulse=config.TONGUE_MAX_PULSE_US)
        except BaseException:
            self.release()
            raise

    def write(self, angle):
        if not math.isfinite(angle) or not config.TONGUE_MIN_ANGLE <= angle <= config.TONGUE_MAX_ANGLE:
            raise ValueError("Comanda depășește limitele mecanice ale limbii")
        self._servo.angle = angle

    def release(self):
        self._channel.duty_cycle = 0

    def close(self):
        self.release()
