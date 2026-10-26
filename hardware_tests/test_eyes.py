import time
import spidev
import gpiod

from gpiod.line import Direction, Value


# ============================================================
# CONFIGURATIE PORO - 2 x GC9A01 240x240
# ============================================================

WIDTH = 240
HEIGHT = 240

# GPIO numbers (BCM), NU numerele fizice
DC = 25       # pin fizic 22
RST = 24      # pin fizic 18

# SPI0
# Display 1 -> CE0 / GPIO8 / pin fizic 24
# Display 2 -> CE1 / GPIO7 / pin fizic 26

SPI_BUS = 0
SPI_LEFT = 0
SPI_RIGHT = 1

SPI_SPEED = 40_000_000


# ============================================================
# GPIO - API NOU gpiod
# ============================================================

gpio = gpiod.request_lines(
    "/dev/gpiochip0",
    consumer="poro_gc9a01",
    config={
        DC: gpiod.LineSettings(
            direction=Direction.OUTPUT,
            output_value=Value.INACTIVE,
        ),
        RST: gpiod.LineSettings(
            direction=Direction.OUTPUT,
            output_value=Value.ACTIVE,
        ),
    },
)


def dc_low():
    gpio.set_value(DC, Value.INACTIVE)


def dc_high():
    gpio.set_value(DC, Value.ACTIVE)


def rst_low():
    gpio.set_value(RST, Value.INACTIVE)


def rst_high():
    gpio.set_value(RST, Value.ACTIVE)


# ============================================================
# SPI
# ============================================================

spi_left = spidev.SpiDev()
spi_left.open(SPI_BUS, SPI_LEFT)
spi_left.max_speed_hz = SPI_SPEED
spi_left.mode = 0

spi_right = spidev.SpiDev()
spi_right.open(SPI_BUS, SPI_RIGHT)
spi_right.max_speed_hz = SPI_SPEED
spi_right.mode = 0


# ============================================================
# GC9A01 LOW LEVEL
# ============================================================

def write_command(spi, command):
    dc_low()
    spi.writebytes([command])


def write_data(spi, data):
    dc_high()

    if isinstance(data, int):
        spi.writebytes([data])
    else:
        # trimitem pe bucati ca sa nu depasim limita SPI
        chunk_size = 4096

        for i in range(0, len(data), chunk_size):
            chunk = data[i:i + chunk_size]

            try:
                spi.writebytes2(chunk)
            except AttributeError:
                spi.xfer2(chunk)


def command(spi, cmd, data=None):
    write_command(spi, cmd)

    if data is not None:
        write_data(spi, data)


# ============================================================
# RESET COMUN
# ============================================================

def hardware_reset():
    print("Reset display-uri...")

    rst_high()
    time.sleep(0.05)

    rst_low()
    time.sleep(0.05)

    rst_high()
    time.sleep(0.15)


# ============================================================
# INITIALIZARE GC9A01
# ============================================================

def init_display(spi):
    command(spi, 0xEF)

    command(spi, 0xEB, [0x14])

    command(spi, 0xFE)
    command(spi, 0xEF)

    command(spi, 0xEB, [0x14])

    command(spi, 0x84, [0x40])
    command(spi, 0x85, [0xFF])
    command(spi, 0x86, [0xFF])
    command(spi, 0x87, [0xFF])
    command(spi, 0x88, [0x0A])
    command(spi, 0x89, [0x21])
    command(spi, 0x8A, [0x00])
    command(spi, 0x8B, [0x80])
    command(spi, 0x8C, [0x01])
    command(spi, 0x8D, [0x01])
    command(spi, 0x8E, [0xFF])
    command(spi, 0x8F, [0xFF])

    command(spi, 0xB6, [0x00, 0x20])

    # Memory Access Control
    command(spi, 0x36, [0x08])

    # RGB565
    command(spi, 0x3A, [0x05])

    command(spi, 0x90, [0x08, 0x08, 0x08, 0x08])

    command(spi, 0xBD, [0x06])
    command(spi, 0xBC, [0x00])

    command(spi, 0xFF, [0x60, 0x01, 0x04])

    command(spi, 0xC3, [0x13])
    command(spi, 0xC4, [0x13])

    command(spi, 0xC9, [0x22])

    command(spi, 0xBE, [0x11])

    command(spi, 0xE1, [0x10, 0x0E])
    command(spi, 0xDF, [0x21, 0x0C, 0x02])

    command(
        spi,
        0xF0,
        [0x45, 0x09, 0x08, 0x08, 0x26, 0x2A]
    )

    command(
        spi,
        0xF1,
        [0x43, 0x70, 0x72, 0x36, 0x37, 0x6F]
    )

    command(
        spi,
        0xF2,
        [0x45, 0x09, 0x08, 0x08, 0x26, 0x2A]
    )

    command(
        spi,
        0xF3,
        [0x43, 0x70, 0x72, 0x36, 0x37, 0x6F]
    )

    command(spi, 0xED, [0x1B, 0x0B])

    command(spi, 0xAE, [0x77])

    command(
        spi,
        0xCD,
        [0x63]
    )

    command(
        spi,
        0x70,
        [0x07, 0x07, 0x04, 0x0E, 0x0F, 0x09, 0x07, 0x08, 0x03]
    )

    command(spi, 0xE8, [0x34])

    command(
        spi,
        0x62,
        [0x18, 0x0D, 0x71, 0xED, 0x70, 0x70, 0x18, 0x0F, 0x71, 0xEF, 0x70, 0x70]
    )

    command(
        spi,
        0x63,
        [0x18, 0x11, 0x71, 0xF1, 0x70, 0x70, 0x18, 0x13, 0x71, 0xF3, 0x70, 0x70]
    )

    command(
        spi,
        0x64,
        [0x28, 0x29, 0xF1, 0x01, 0xF1, 0x00, 0x07]
    )

    command(
        spi,
        0x66,
        [0x3C, 0x00, 0xCD, 0x67, 0x45, 0x45, 0x10, 0x00, 0x00, 0x00]
    )

    command(
        spi,
        0x67,
        [0x00, 0x3C, 0x00, 0x00, 0x00, 0x01, 0x54, 0x10, 0x32, 0x98]
    )

    command(spi, 0x74, [0x10, 0x85, 0x80, 0x00, 0x00, 0x4E, 0x00])

    command(spi, 0x98, [0x3E, 0x07])

    # Sleep Out
    command(spi, 0x11)
    time.sleep(0.12)

    # Display ON
    command(spi, 0x29)
    time.sleep(0.02)


# ============================================================
# DISPLAY WINDOW
# ============================================================

def set_window(spi, x0, y0, x1, y1):
    command(
        spi,
        0x2A,
        [
            (x0 >> 8) & 0xFF,
            x0 & 0xFF,
            (x1 >> 8) & 0xFF,
            x1 & 0xFF,
        ],
    )

    command(
        spi,
        0x2B,
        [
            (y0 >> 8) & 0xFF,
            y0 & 0xFF,
            (y1 >> 8) & 0xFF,
            y1 & 0xFF,
        ],
    )

    write_command(spi, 0x2C)


# ============================================================
# RGB888 -> RGB565
# ============================================================

def rgb565(r, g, b):
    return (
        ((r & 0xF8) << 8)
        | ((g & 0xFC) << 3)
        | (b >> 3)
    )


# ============================================================
# UMPLE ECRANUL CU O CULOARE
# ============================================================

def fill_screen(spi, r, g, b):
    color = rgb565(r, g, b)

    high = (color >> 8) & 0xFF
    low = color & 0xFF

    set_window(
        spi,
        0,
        0,
        WIDTH - 1,
        HEIGHT - 1
    )

    dc_high()

    # ~57k pixeli
    pixels_per_chunk = 2048

    chunk = [high, low] * pixels_per_chunk

    total_pixels = WIDTH * HEIGHT

    full_chunks = total_pixels // pixels_per_chunk
    remaining = total_pixels % pixels_per_chunk

    for _ in range(full_chunks):
        try:
            spi.writebytes2(chunk)
        except AttributeError:
            spi.xfer2(chunk)

    if remaining:
        data = [high, low] * remaining

        try:
            spi.writebytes2(data)
        except AttributeError:
            spi.xfer2(data)


# ============================================================
# TEST
# ============================================================

try:
    print()
    print("==============================")
    print("PORO GC9A01 TEST")
    print("==============================")
    print()

    hardware_reset()

    print("Initializare ochi stang...")
    init_display(spi_left)

    print("Initializare ochi drept...")
    init_display(spi_right)

    print()
    print("TEST 1: stang ROSU / drept ALBASTRU")

    fill_screen(
        spi_left,
        255,
        0,
        0
    )

    fill_screen(
        spi_right,
        0,
        0,
        255
    )

    time.sleep(2)

    print("TEST 2: stang VERDE / drept MOV")

    fill_screen(
        spi_left,
        0,
        255,
        0
    )

    fill_screen(
        spi_right,
        180,
        0,
        255
    )

    time.sleep(2)

    print("TEST 3: ambele ALB")

    fill_screen(
        spi_left,
        255,
        255,
        255
    )

    fill_screen(
        spi_right,
        255,
        255,
        255
    )

    time.sleep(2)

    print("TEST 4: culoarea ochilor PORO")

    fill_screen(
        spi_left,
        0,
        120,
        255
    )

    fill_screen(
        spi_right,
        0,
        120,
        255
    )

    print()
    print("==============================")
    print("TEST TERMINAT")
    print("==============================")
    print()
    print("Daca ambele display-uri sunt albastre:")
    print("GC9A01 LEFT  = OK")
    print("GC9A01 RIGHT = OK")
    print()

except KeyboardInterrupt:
    print("\nTest oprit.")

finally:
    spi_left.close()
    spi_right.close()
    gpio.release()