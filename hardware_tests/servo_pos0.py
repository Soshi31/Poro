from adafruit_servokit import ServoKit
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hardware.i2c import open_body_i2c

i2c = open_body_i2c()
kit = ServoKit(channels=16, address=0x40, i2c=i2c)

servo = kit.servo[0]

try:
    while True:
        for angle in range(0, 176, 5):
            servo.angle = angle
            time.sleep(0.05)

        for angle in range(175, -1, -5):
            servo.angle = angle
            time.sleep(0.05)
finally:
    servo.angle = None
    i2c.deinit()
