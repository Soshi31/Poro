"""Contract pentru backend-uri vizuale; implicit doar date structurate reale."""

import math


class StructuredVisionBackend:
    """Nu pretinde că statisticile imaginii sunt recunoaștere de obiecte."""

    requires_frame = False

    def inspect_scene(self, scene, frame=None):
        capabilities = scene.get("capabilities", {})
        return {
            "status": "structured_only",
            "people_count": len(scene.get("people", [])),
            "primary_target": scene.get("primary", {}).get("position") if scene.get("primary") else None,
            "motion": bool((scene.get("motion") or {}).get("active")),
            "known_objects": [{"label": item["label"], "confidence": item["confidence"],
                               "bbox": item["bbox"]} for item in scene.get("objects", [])[:5]],
            "object_detection": capabilities.get("objects", "not_configured"),
            "scene_analysis": scene.get("scene_analysis", {}),
        }

    def inspect_center_object(self, scene, frame=None):
        objects = scene.get("objects", [])
        ranked = []
        for item in objects:
            x, y, width, height = item["bbox"]
            cx, cy = x + width / 2, y + height / 2
            distance = math.hypot(cx - 0.5, cy - 0.5)
            if x <= 0.5 <= x + width and y <= 0.5 <= y + height:
                distance = 0
            ranked.append((distance, -item["confidence"], item))
        ranked.sort(key=lambda row: row[:2])
        if ranked and ranked[0][0] <= 0.25:
            item = ranked[0][2]
            return {"status": "found", "object": {"label": item["label"],
                                                   "confidence": item["confidence"],
                                                   "bbox": item["bbox"]}}
        return {"status": "unknown", "object": None,
                "object_detection": scene.get("capabilities", {}).get("objects", "not_configured")}

    def answer_visual_question(self, question, scene, frame=None):
        # Fără model de relații mână-obiect sau VLM nu deducem răspunsuri.
        return {"status": "insufficient_evidence", "answer": None,
                "reason": "Backend-ul actual nu interpretează semantic imagini sau relații între obiecte.",
                "people_count": len(scene.get("people", [])),
                "known_objects": [item["label"] for item in scene.get("objects", [])[:5]],
                "object_detection": scene.get("capabilities", {}).get("objects", "not_configured")}
