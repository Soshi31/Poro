"""Contract SLOW: fabrică importabilă, capabilities și analyze(AIFrame) -> JSON.

Un analyzer poate publica objects / gestures / scene. Coordonatele bbox sunt
[x, y, width, height] în [0, 1], în imaginea camerei, fără inversarea ochilor.
Obiectele/gesturile sunt detecții, nu identități persistente.
"""

import json
import math

import numpy as np


def validate_result(result, capabilities):
    """Respinge rezultate invalide înainte să intre în starea agentului."""
    if not isinstance(result, dict) or set(result) - set(capabilities):
        raise ValueError("Analyzer-ul a întors chei nedeclarate în capabilities")
    encoded = json.dumps(result, allow_nan=False)
    if len(encoded) > 65536:
        raise ValueError("Rezultat SLOW prea mare: limita este 64 KiB de JSON")
    result = json.loads(encoded)
    for key in ("objects", "gestures"):
        if key not in result:
            continue
        if not isinstance(result[key], list) or len(result[key]) > 100:
            raise ValueError(f"{key} trebuie să fie o listă de maximum 100 detecții")
        for item in result[key]:
            if not isinstance(item, dict) or not isinstance(item.get("label"), str) or not item["label"]:
                raise ValueError("Fiecare detecție necesită label")
            confidence = item.get("confidence")
            if not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
                raise ValueError("confidence trebuie să fie în [0, 1]")
            box = item.get("bbox")
            if key == "objects" or box is not None:
                if (not isinstance(box, list) or len(box) != 4
                        or any(not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1 for v in box)
                        or min(box[2:]) <= 0 or box[0] + box[2] > 1.000001 or box[1] + box[3] > 1.000001):
                    raise ValueError("bbox invalid; folosește [x,y,w,h] normalizat în imagine")
    if "scene" in result and not isinstance(result["scene"], dict):
        raise ValueError("scene trebuie să fie un obiect JSON")
    return result


class SceneMetricsAnalyzer:
    """Statistici ieftine ale imaginii, fără interpretare semantică sau model."""

    capabilities = ("scene",)

    def analyze(self, frame):
        rgb = frame.rgb[::4, ::4].astype(np.float32)
        luminance = rgb[:, :, 0] * 0.299 + rgb[:, :, 1] * 0.587 + rgb[:, :, 2] * 0.114
        return {"scene": {"kind": "image_statistics", "semantic_analysis": False,
                          "brightness": round(float(luminance.mean() / 255), 4),
                          "contrast": round(float(luminance.std() / 255), 4)}}
