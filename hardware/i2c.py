"""Aceleași fire SDA/SCL; backend hardware I2C1 sau i2c-gpio configurat."""

from pathlib import Path
from threading import RLock


SOFTWARE_OVERLAY = "dtoverlay=i2c-gpio,bus=3,i2c_gpio_sda=2,i2c_gpio_scl=3,i2c_gpio_delay_us=2"


def open_body_i2c():
    import board
    import busio

    boot = Path('/boot/firmware/config.txt').read_text()
    if SOFTWARE_OVERLAY in boot.splitlines():
        if not Path('/dev/i2c-3').exists():
            raise RuntimeError('Overlay i2c-gpio configurat dar /dev/i2c-3 lipsește: repornește Pi-ul sau verifică boot config')
        if (board.SDA, board.SCL) != (2, 3):
            raise RuntimeError('Pinii SDA/SCL existenți nu coincid cu overlay-ul i2c-gpio')
        from adafruit_blinka.microcontroller.generic_linux.i2c import I2C as LinuxI2C

        class SoftwareI2C(busio.I2C):
            def __init__(self):
                # Interface busio deja folosită de driverele Adafruit; doar
                # selectorul /dev/i2c-N diferă. Kernelul gestionează stretching.
                self._i2c = LinuxI2C(3)
                self._lock = RLock()

        return SoftwareI2C()
    return busio.I2C(board.SCL, board.SDA)
