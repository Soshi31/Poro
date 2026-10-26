"""Analyzere numai pentru testarea izolării proceselor și a erorilor."""

import time


class BlockedAnalyzer:
    capabilities = ("scene",)

    def analyze(self, frame):
        time.sleep(30)
        return {"scene": {}}


class InvalidAnalyzer:
    capabilities = ("objects",)

    def analyze(self, frame):
        return {"objects": [{"label": "invalid", "confidence": 2, "bbox": [0, 0, 1, 1]}]}
