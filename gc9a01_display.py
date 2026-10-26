"""Driver GC9A01 real: spidev persistent, libgpiod v2, RGB565 big-endian.

Registrele de inițializare corespund controlerului modulului Waveshare:
https://www.waveshare.com/wiki/1.28inch_LCD_Module
"""

from threading import Event, RLock

import gpiod
from gpiod.line import Direction, Value
import numpy as np
import spidev

import config


# Configurația analogică și gamma a panoului GC9A01 de 240x240.
_INIT_REGISTERS = (
    (0xEF, b""), (0xEB, b"\x14"), (0xFE, b""), (0xEF, b""),
    (0xEB, b"\x14"), (0x84, b"\x40"), (0x85, b"\xff"),
    (0x86, b"\xff"), (0x87, b"\xff"), (0x88, b"\x0a"),
    (0x89, b"\x21"), (0x8A, b"\x00"), (0x8B, b"\x80"),
    (0x8C, b"\x01"), (0x8D, b"\x01"), (0x8E, b"\xff"),
    (0x8F, b"\xff"), (0xB6, b"\x00\x20"), (0x3A, b"\x05"),
    (0x90, b"\x08\x08\x08\x08"), (0xBD, b"\x06"), (0xBC, b"\x00"),
    (0xFF, b"\x60\x01\x04"), (0xC3, b"\x13"), (0xC4, b"\x13"),
    (0xC9, b"\x22"), (0xBE, b"\x11"), (0xE1, b"\x10\x0e"),
    (0xDF, b"\x21\x0c\x02"),
    (0xF0, b"\x45\x09\x08\x08\x26\x2a"),
    (0xF1, b"\x43\x70\x72\x36\x37\x6f"),
    (0xF2, b"\x45\x09\x08\x08\x26\x2a"),
    (0xF3, b"\x43\x70\x72\x36\x37\x6f"),
    (0xED, b"\x1b\x0b"), (0xAE, b"\x77"), (0xCD, b"\x63"),
    (0x70, b"\x07\x07\x04\x0e\x0f\x09\x07\x08\x03"),
    (0xE8, b"\x34"),
    (0x62, b"\x18\x0d\x71\xed\x70\x70\x18\x0f\x71\xef\x70\x70"),
    (0x63, b"\x18\x11\x71\xf1\x70\x70\x18\x13\x71\xf3\x70\x70"),
    (0x64, b"\x28\x29\xf1\x01\xf1\x00\x07"),
    (0x66, b"\x3c\x00\xcd\x67\x45\x45\x10\x00\x00\x00"),
    (0x67, b"\x00\x3c\x00\x00\x00\x01\x54\x10\x32\x98"),
    (0x74, b"\x10\x85\x80\x00\x00\x4e\x00"), (0x98, b"\x3e\x07"),
)


class SharedGPIO:
    """Deține DC/RST și lock-ul întregii magistrale cu DC comun."""

    def __init__(self):
        self.lock = RLock()
        self._reset_done = False
        self._request = gpiod.request_lines(
            config.GPIO_CHIP,
            consumer="poro-eyes",
            config={
                config.DC_PIN: gpiod.LineSettings(
                    direction=Direction.OUTPUT, output_value=Value.INACTIVE
                ),
                config.RST_PIN: gpiod.LineSettings(
                    direction=Direction.OUTPUT, output_value=Value.ACTIVE
                ),
            },
        )

    def set_dc(self, data):
        self._request.set_value(
            config.DC_PIN, Value.ACTIVE if data else Value.INACTIVE
        )

    def hardware_reset(self):
        """Un singur puls comun, înainte de inițializarea ORICĂRUI panou."""
        with self.lock:
            if self._reset_done:
                raise RuntimeError("Resetul comun a fost deja efectuat.")
            # Așteptări electrice doar la startup, fără legătură cu animațiile.
            delay = Event()
            self._request.set_value(config.RST_PIN, Value.ACTIVE)
            delay.wait(config.RESET_HIGH_SECONDS)
            self._request.set_value(config.RST_PIN, Value.INACTIVE)
            delay.wait(config.RESET_LOW_SECONDS)
            self._request.set_value(config.RST_PIN, Value.ACTIVE)
            delay.wait(config.RESET_RECOVERY_SECONDS)
            self._reset_done = True

    def close(self):
        if self._request is not None:
            self._request.release()
            self._request = None


class GC9A01Display:
    """O instanță pentru un CS hardware; nu controlează niciodată RST."""

    def __init__(self, device, gpio, rotation=0):
        if (config.DISPLAY_WIDTH, config.DISPLAY_HEIGHT) != (240, 240):
            raise ValueError("GC9A01 necesită framebuffer 240x240.")
        if rotation not in (0, 90, 180, 270):
            raise ValueError("Rotation trebuie să fie 0, 90, 180 sau 270.")
        if config.COLOR_ORDER not in ("RGB", "BGR"):
            raise ValueError('COLOR_ORDER trebuie să fie "RGB" sau "BGR".')
        self.gpio = gpio
        self.rotation = rotation
        self.initialized = False
        self._spi = spidev.SpiDev()
        try:
            self._spi.open(config.SPI_BUS, device)
            self._spi.max_speed_hz = config.SPI_SPEED_HZ
            self._spi.mode = config.SPI_MODE
            self._spi.bits_per_word = 8
            self._spi.no_cs = False
        except BaseException:
            self.close()
            raise

    def _command(self, command, data=b""):
        # Apelantul deține lock-ul comun pe întreaga operație.
        self.gpio.set_dc(False)
        self._spi.writebytes([command])
        if data:
            self.gpio.set_dc(True)
            self._spi.writebytes2(data)

    def initialize(self):
        with self.gpio.lock:
            if self.initialized:
                return
            if not self.gpio._reset_done:
                raise RuntimeError("Lipsește resetul hardware comun.")
            for command, data in _INIT_REGISTERS:
                self._command(command, data)
            madctl = {0: 0x00, 90: 0x60, 180: 0xC0, 270: 0xA0}[self.rotation]
            if config.COLOR_ORDER == "BGR":
                madctl |= 0x08
            self._command(0x36, bytes([madctl]))
            self._command(0x21 if config.DISPLAY_INVERSION else 0x20)
            self._command(0x11)  # SLPOUT
            Event().wait(config.SLEEP_OUT_SECONDS)
            self._command(0x29)  # DISPON
            Event().wait(config.DISPLAY_ON_SECONDS)
            self.initialized = True

    def _set_window(self, x0, y0, x1, y1):
        if not (0 <= x0 <= x1 < 240 and 0 <= y0 <= y1 < 240):
            raise ValueError("Address window în afara display-ului.")
        self._command(0x2A, bytes([0, x0, 0, x1]))
        self._command(0x2B, bytes([0, y0, 0, y1]))
        self._command(0x2C)  # RAMWR

    @staticmethod
    def rgb565(image):
        """RGB888 -> RGB565, octetul superior primul, fără swap RGB/BGR dublu."""
        if image.mode != "RGB" or image.size != (240, 240):
            raise ValueError("Imaginea trebuie să fie PIL RGB 240x240.")
        rgb = np.asarray(image, dtype=np.uint8)
        packed = np.empty((240, 240, 2), dtype=np.uint8)
        packed[:, :, 0] = (rgb[:, :, 0] & 0xF8) | (rgb[:, :, 1] >> 5)
        packed[:, :, 1] = ((rgb[:, :, 1] & 0x1C) << 3) | (rgb[:, :, 2] >> 3)
        return packed.reshape(-1)

    def show_buffer(self, buffer):
        if not self.initialized or self._spi is None:
            raise RuntimeError("Display-ul nu este inițializat sau este închis.")
        if memoryview(buffer).nbytes != 240 * 240 * 2:
            raise ValueError("Framebuffer RGB565 incomplet.")
        with self.gpio.lock:
            self._set_window(0, 0, 239, 239)
            self.gpio.set_dc(True)
            # writebytes2 folosește buffer protocol și fragmentează în C
            # conform /sys/module/spidev/parameters/bufsiz.
            self._spi.writebytes2(buffer)

    def show(self, image):
        self.show_buffer(self.rgb565(image))

    def clear(self):
        self.show_buffer(bytes(240 * 240 * 2))

    def close(self):
        if self._spi is not None:
            self._spi.close()
            self._spi = None
        self.initialized = False
