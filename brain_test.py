#!/usr/bin/python3
"""Compatibilitate: testul complet folosește același runtime ca main.py."""

from main import main


if __name__ == "__main__":
    raise SystemExit(main())
