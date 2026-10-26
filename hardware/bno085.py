"""Adaptor real cu timestamp-uri și citire limitată per tick.

Hook-uri private izolate pentru driverul Adafruit 1.3.3: getter-ele publice
nu disting rapoartele noi de valori cache rămase după oprirea senzorului.
"""

from dataclasses import dataclass
import math
import logging
import struct
import time

import config


@dataclass(frozen=True)
class IMUSample:
    observed_at: float
    gravity: tuple
    linear_acceleration: tuple
    gyro: tuple


class BNO085:
    def __init__(self, i2c):
        from adafruit_bno08x import (BNO_REPORT_GRAVITY, BNO_REPORT_LINEAR_ACCELERATION,
                                    BNO_REPORT_GYROSCOPE, PacketError, _separate_batch, BNO08X)
        from adafruit_bno08x.i2c import BNO08X_I2C
        from adafruit_bus_device.i2c_device import I2CDevice

        features = (BNO_REPORT_GRAVITY, BNO_REPORT_LINEAR_ACCELERATION, BNO_REPORT_GYROSCOPE)

        class TimedBNO(BNO08X_I2C):
            def __init__(self):
                self.received = {}
                self.report_sequences = {}
                self.bad_packets = 0
                self.last_warning = -math.inf
                # BNO vorbește SHTP: probe-ul generic cu citire de 1 octet poate
                # deranja fluxul. Inițializarea BNO verifică apoi ID-ul real.
                self.bus_device_obj = I2CDevice(i2c, config.BODY_IMU_ADDRESS, probe=False)
                BNO08X.__init__(self)

            def _read(self, requested_read_length):
                # Lasă SH-2 să pregătească payload-ul după citirea antetului.
                time.sleep(config.BODY_I2C_READ_PAUSE_SECONDS)
                return super()._read(requested_read_length)

            def _handle_packet(self, packet):
                slices = []
                try:
                    _separate_batch(packet, slices)
                except (KeyError, IndexError, RuntimeError, struct.error) as error:
                    # Nu publica date parțiale din pachete I2C deteriorate.
                    self.discard_packet(error)
                    return
                # Ordine cronologică; driverul original parcurge lista invers.
                for report_id, report_bytes in slices:
                    self._process_report(report_id, report_bytes)

            def discard_packet(self, error):
                self.bad_packets += 1
                if time.monotonic() - self.last_warning >= 5:
                    logging.warning('BNO085: pachet invalid ignorat (%s); total=%d', error, self.bad_packets)
                    self.last_warning = time.monotonic()

            def _process_report(self, report_id, report_bytes):
                if report_id in features:
                    seq = report_bytes[1]
                    previous = self.report_sequences.get(report_id)
                    if previous is not None and not 0 < (seq - previous) % 256 < 128:
                        return  # duplicate/raport vechi din batch-ul LIFO al driverului
                    self.report_sequences[report_id] = seq
                super()._process_report(report_id, report_bytes)
                if report_id in features:
                    self.received[report_id] = (time.monotonic(), tuple(self._readings[report_id]))

        self._driver = TimedBNO()
        self._features = features
        self._packet_error = PacketError
        self._last_stamp = -1
        for feature in features:
            self._driver.enable_feature(feature, config.BODY_REPORT_INTERVAL_US)

    def read(self):
        deadline = time.monotonic() + 0.008
        for _ in range(12):
            if time.monotonic() >= deadline:
                break
            try:
                if not self._driver._data_ready:
                    break
                packet = self._driver._read_packet()
            except (self._packet_error, IndexError, OSError, struct.error) as error:
                self._driver.discard_packet(error)
                break  # lasă senzorul să livreze următorul pachet; stale timeout rămâne activ
            self._driver._handle_packet(packet)
        reports = [self._driver.received.get(feature) for feature in self._features]
        if any(report is None for report in reports):
            return None
        stamp = min(report[0] for report in reports)
        if stamp <= self._last_stamp or time.monotonic() - stamp > config.BODY_SENSOR_TIMEOUT:
            return None
        vectors = [report[1] for report in reports]
        if any(len(v) != 3 or not all(math.isfinite(x) for x in v) for v in vectors):
            self._driver.discard_packet('vector nevalid')
            return None
        gravity, linear, gyro = vectors
        if not 8.0 < math.sqrt(sum(x * x for x in gravity)) < 11.5:
            self._driver.discard_packet('gravitație în afara intervalului fizic')
            return None
        if math.sqrt(sum(x * x for x in linear)) > 60 or math.sqrt(sum(x * x for x in gyro)) > 15:
            self._driver.discard_packet('accelerație/gyro în afara intervalului fizic')
            return None
        self._last_stamp = stamp
        return IMUSample(stamp, *vectors)

    @property
    def bad_packets(self):
        return self._driver.bad_packets
