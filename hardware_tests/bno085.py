import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hardware.i2c import open_body_i2c

from adafruit_bno08x import (
    BNO_REPORT_ACCELEROMETER,
    BNO_REPORT_GYROSCOPE,
    BNO_REPORT_ROTATION_VECTOR
)

from adafruit_bno08x.i2c import BNO08X_I2C


i2c = open_body_i2c()


while not i2c.try_lock():
    pass

try:
    devices = i2c.scan()
finally:
    i2c.unlock()


print("I2C:", [hex(x) for x in devices])


address = None

if 0x4A in devices:
    address = 0x4A
elif 0x4B in devices:
    address = 0x4B


if address is None:
    raise RuntimeError("BNO085 nu a fost gasit")


print("BNO085:", hex(address))

bno = BNO08X_I2C(i2c, address=address)

bno.enable_feature(BNO_REPORT_ACCELEROMETER)
bno.enable_feature(BNO_REPORT_GYROSCOPE)
bno.enable_feature(BNO_REPORT_ROTATION_VECTOR)


try:

    while True:

        ax, ay, az = bno.acceleration
        gx, gy, gz = bno.gyro
        qx, qy, qz, qw = bno.quaternion

        print(
            f"ACC: {ax:6.2f} {ay:6.2f} {az:6.2f} | "
            f"GYRO: {gx:6.2f} {gy:6.2f} {gz:6.2f} | "
            f"Q: {qx:.2f} {qy:.2f} {qz:.2f} {qw:.2f}"
        )

        time.sleep(0.2)

except KeyboardInterrupt:
    print("Stop")
finally:
    i2c.deinit()
