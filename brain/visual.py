"""Adaptor on-demand între agent și vision; niciun frame în promptul LLM."""

from datetime import datetime, timezone
import importlib
import json
import os
from pathlib import Path
import re
import unicodedata
from uuid import uuid4

import config


def visual_intent(text):
    """Câteva solicitări vizuale clare; restul rămân la decizia LLM-ului."""
    plain = ''.join(char for char in unicodedata.normalize("NFD", text.casefold())
                    if unicodedata.category(char) != "Mn")
    plain = re.sub(r"[^a-z0-9 ]+", " ", plain)
    plain = re.sub(r"\s+", " ", plain).strip()
    if re.search(r"\b(nu|dont|do not|never)\b", plain):
        return None
    if re.search(r"\b(what am i holding|what is in my hand|what do i have in my hand|ce am in mana|ce tin in mana|ce obiect tin|ce obiect am in mana)\b", plain):
        return "inspect_scene", {}
    if re.search(r"\b(what is in the center|inspect the center|ce este in centru|ce e in centru|ce obiect este in centru|inspecteaza obiectul din centru)\b", plain):
        return "inspect_center_object", {}
    if re.search(r"\b(take a picture|take a photo|capture a photo|take a snapshot|fa o poza|fa o fotografie|captureaza o poza)\b", plain):
        return "capture_snapshot", {}
    if re.search(r"\b(what do you see|what is in front of you|can you see me|do you see me|ce vezi|ce este in fata ta|ce se vede in camera)\b", plain):
        return "answer_visual_question", {"question": text}
    return None


def visual_fallback(tool_name, tool_result):
    """Răspuns sigur când lipsesc datele vizuale; None lasă LLM-ul să decidă."""
    if not tool_result["ok"]:
        return "I cannot see clearly right now."
    result = tool_result["result"]
    if tool_name == "capture_snapshot":
        return "I took a picture!" if result.get("status") == "saved" else "I could not take a picture."
    analysis = result.get("analysis", {})
    if tool_name == "inspect_scene":
        answer = analysis.get("answer")
        return answer if isinstance(answer, str) and answer.strip() else "Nu pot stabili ce ții în mână, I can only track faces right now."
    if tool_name == "inspect_center_object" and analysis.get("status") != "found":
        return "I cannot identify the object in the center right now."
    if tool_name == "answer_visual_question":
        answer = analysis.get("answer")
        if isinstance(answer, str) and answer.strip():
            return answer
        if analysis.get("status") == "insufficient_evidence":
            people = analysis.get("people_count", 0)
            if people == 1:
                return "I see you right in front of me, friend!"
            if people > 1:
                return f"I see {people} people in front of me!"
            return "I am looking around, but I don't see anyone right now."
    return None


class VisualTools:
    def __init__(self, perception, backend=None):
        self.perception = perception
        if backend is None:
            module_name, class_name = config.BRAIN_VISUAL_BACKEND.split(":", 1)
            backend = getattr(importlib.import_module(module_name), class_name)()
        for method in ("inspect_scene", "inspect_center_object", "answer_visual_question"):
            if not callable(getattr(backend, method, None)):
                raise TypeError(f"Backend-ul vizual nu implementează {method}()")
        self.backend = backend

    @staticmethod
    def _bounded(value):
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        if len(encoded) > config.BRAIN_VISUAL_RESULT_MAX_CHARS:
            raise ValueError("Rezultatul vizual este prea mare pentru agent")
        return json.loads(encoded)  # copie JSON; niciodată numpy/frame

    def _observe(self):
        observation = self.perception.inspect_scene(timeout=config.BRAIN_VISUAL_TIMEOUT)
        frame = (self.perception.capture_frame_for_ai()
                 if getattr(self.backend, "requires_frame", False) else None)
        return observation, frame

    def inspect_scene(self):
        observation, frame = self._observe()
        result = self.backend.inspect_scene(observation["scene"], frame)
        return self._bounded({"status": observation["status"], "analysis": result})

    def inspect_center_object(self):
        observation, frame = self._observe()
        result = self.backend.inspect_center_object(observation["scene"], frame)
        return self._bounded({"status": observation["status"], "analysis": result})

    def answer_visual_question(self, question):
        observation, frame = self._observe()
        result = self.backend.answer_visual_question(question, observation["scene"], frame)
        return self._bounded({"status": observation["status"], "analysis": result})

    def capture_snapshot(self):
        root = Path(config.BRAIN_SNAPSHOT_DIR)
        root.mkdir(parents=True, exist_ok=True)
        if len(list(root.glob("poro-*.jpg"))) >= config.BRAIN_MAX_SNAPSHOTS:
            raise RuntimeError("Limita de fotografii a fost atinsă")
        frame = self.perception.capture_frame_for_ai()
        name = datetime.now(timezone.utc).strftime("poro-%Y%m%dT%H%M%SZ-") + uuid4().hex[:8] + ".jpg"
        path = root / name
        data = frame.jpeg_bytes(quality=config.BRAIN_SNAPSHOT_JPEG_QUALITY)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(data)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return {"status": "saved", "path": str(path), "frame": frame.metadata(),
                "bytes": len(data)}
