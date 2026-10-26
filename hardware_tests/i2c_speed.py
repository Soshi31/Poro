#!/usr/bin/python3
"""Previzualizează/aplică hardware I2C1 sau software I2C pe aceleași fire SDA/SCL."""

import argparse
import difflib
import os
from pathlib import Path
import re
import shutil
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--software', action='store_true', help='Înlocuiește hardware I2C1 cu i2c-gpio pe GPIO2/3, bus 3')
    mode.add_argument('--baudrate', type=int, choices=(100000, 400000), help='Revine la hardware I2C1 cu această frecvență')
    parser.add_argument('--apply', action='store_true', help='Aplică schimbarea; necesită sudo și apoi reboot manual')
    args = parser.parse_args()
    path = Path('/boot/firmware/config.txt')
    original = path.read_text()
    rate_pattern = r'(?m)^dtparam=i2c_arm_baudrate=\d+[ \t]*$'
    arm_pattern = r'(?m)^dtparam=i2c_arm=(?:on|off)[ \t]*$'
    overlay = 'dtoverlay=i2c-gpio,bus=3,i2c_gpio_sda=2,i2c_gpio_scl=3,i2c_gpio_delay_us=2'
    if len(re.findall(rate_pattern, original)) != 1 or len(re.findall(arm_pattern, original)) != 1:
        raise RuntimeError('Configurația nu are exact o linie baudrate simplă; necesită verificare manuală')
    if any(line.startswith('dtoverlay=i2c-gpio') and line != overlay for line in original.splitlines()):
        raise RuntimeError('Există deja un alt overlay i2c-gpio; verifică manual înainte de aplicare')
    if args.software:
        model = Path('/proc/device-tree/model').read_bytes().rstrip(b'\0').decode()
        if not model.startswith('Raspberry Pi 4 Model B'):
            raise RuntimeError(f'Model Raspberry Pi neașteptat: {model}')
        updated = re.sub(arm_pattern, 'dtparam=i2c_arm=off', original)
        if overlay not in updated.splitlines():
            match = re.search(rate_pattern, updated)
            updated = updated[:match.end()] + '\n' + overlay + updated[match.end():]
    else:
        updated = re.sub(arm_pattern, 'dtparam=i2c_arm=on', original)
        updated = re.sub(rate_pattern, f'dtparam=i2c_arm_baudrate={args.baudrate or 100000}', updated)
        updated = updated.replace('\n' + overlay, '')
    if updated == original:
        print('Valoarea cerută este deja în fișier. Modificările de boot necesită repornire.')
        return
    print(''.join(difflib.unified_diff(original.splitlines(True), updated.splitlines(True),
                                     fromfile=str(path), tofile=str(path) + ' (propus)')), end='')
    if not args.apply:
        print('Nu s-a modificat nimic. --apply aplică exact acest diff.')
        return
    if os.geteuid() != 0:
        raise PermissionError('Aplicarea necesită sudo; previzualizarea nu necesită sudo')
    backup = path.with_name(path.name + '.poro-i2c-backup')
    if not backup.exists():
        shutil.copyfile(path, backup)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='.poro-i2c-', delete=False) as output:
            temporary = Path(output.name)
            output.write(updated)
            output.flush()
            os.fsync(output.fileno())
        shutil.copymode(path, temporary)
        temporary.replace(path)
    except BaseException:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise
    print(f'Aplicat. Backup inițial: {backup}. Repornește manual Pi-ul pentru activare.')


if __name__ == '__main__':
    main()
