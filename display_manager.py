"""Coordonează exclusiv cele două GC9A01 fizice de pe SPI0."""

from contextlib import ExitStack
import logging
import math

from PIL import Image

import config
from gc9a01_display import GC9A01Display, SharedGPIO


class DisplayManager:
    def __init__(self):
        self.left_fine_rotation = float(config.LEFT_FINE_ROTATION)
        self.right_fine_rotation = float(config.RIGHT_FINE_ROTATION)
        if not all(math.isfinite(angle) for angle in (
            self.left_fine_rotation, self.right_fine_rotation,
        )):
            raise ValueError("Corecțiile de rotație trebuie să fie finite.")
        self._resources = ExitStack()
        self._closed = False
        self._last_left = None
        self._last_right = None
        try:
            self.gpio = SharedGPIO()
            self._resources.callback(self.gpio.close)
            self.left_display = GC9A01Display(
                config.LEFT_SPI_DEVICE, self.gpio, config.LEFT_ROTATION
            )
            self._resources.callback(self.left_display.close)
            self.right_display = GC9A01Display(
                config.RIGHT_SPI_DEVICE, self.gpio, config.RIGHT_ROTATION
            )
            self._resources.callback(self.right_display.close)
            self.gpio.hardware_reset()
            self.left_display.initialize()
            self.right_display.initialize()
            self.left_display.clear()
            self.right_display.clear()
        except BaseException:
            self._resources.close()
            self._closed = True
            raise

    @staticmethod
    def _rotate_frame(image, angle):
        if angle % 360 == 0:
            return image
        # Rotim toate straturile împreună, păstrând framebuffer-ul 240x240.
        return image.rotate(
            angle, resample=Image.Resampling.BICUBIC,
            expand=False, fillcolor=(0, 0, 0),
        )

    def show_left(self, image):
        self.left_display.show(self._rotate_frame(image, self.left_fine_rotation))

    def show_right(self, image):
        self.right_display.show(self._rotate_frame(image, self.right_fine_rotation))

    def _buffer_for(self, image, angle):
        cache = getattr(image, "_poro_cache", None)
        if cache is not None and angle in cache:
            return cache[angle]
        buffer = GC9A01Display.rgb565(self._rotate_frame(image, angle))
        if cache is not None:
            cache[angle] = buffer
        return buffer

    def show_both(self, left_image, right_image):
        same_frame = (
            right_image is left_image
            and self.left_fine_rotation == self.right_fine_rotation
        )
        left_buffer = self._buffer_for(left_image, self.left_fine_rotation)
        right_buffer = (
            left_buffer if same_frame
            else self._buffer_for(right_image, self.right_fine_rotation)
        )
        if left_buffer is self._last_left and right_buffer is self._last_right:
            return
        with self.gpio.lock:
            if left_buffer is not self._last_left:
                self.left_display.show_buffer(left_buffer)
                self._last_left = left_buffer
            if right_buffer is not self._last_right:
                self.right_display.show_buffer(right_buffer)
                self._last_right = right_buffer

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if config.CLEAR_ON_EXIT:
                # Chiar dacă un display eșuează, eliberăm toate resursele.
                for display in (self.left_display, self.right_display):
                    try:
                        display.clear()
                    except Exception:
                        logging.exception("Nu s-a putut șterge display-ul la ieșire.")
        finally:
            self._resources.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
