"""PocketSphinx instalat local în proiect, fără venv sau modificări în Python OS."""

from pathlib import Path
import sys


def pocketsphinx():
    vendor = Path(__file__).resolve().parent / "_vendor"
    if vendor.is_dir() and str(vendor) not in sys.path:
        sys.path.insert(0, str(vendor))
    try:
        import pocketsphinx as module
        return module
    except ImportError as error:
        raise RuntimeError("Lipsește PocketSphinx. Rulează bash voice/setup.sh") from error
