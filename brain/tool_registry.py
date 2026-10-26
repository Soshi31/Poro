"""Allowlist de tools semantice; niciun handle GPIO/SPI/I2C ajunge la LLM."""

import math
from queue import Full
import sqlite3

import config
from .visual import VisualTools


DESCRIPTIONS = {
    "set_emotion": 'emotion=neutral|happy|curious|sleepy',
    "look_at_person": "",
    "look_at": "x,y=-1..1",
    "tongue": "action=in|out|blep|double_blep",
    "speak": "text",
    "get_vision_state": "",
    "inspect_scene": "",
    "inspect_center_object": "",
    "capture_snapshot": "",
    "answer_visual_question": "question",
    "get_imu_state": "",
    "remember": "text,kind=fact|preference (kind opțional)",
    "recall": "query",
    "get_robot_state": "",
    "sleep": "",
    "wake_up": "",
}

READ_TOOLS = frozenset({"get_vision_state", "inspect_scene", "inspect_center_object",
                        "capture_snapshot", "answer_visual_question", "get_imu_state",
                        "recall", "get_robot_state"})


class ToolRegistry:
    def __init__(self, *, behavior, context, perception=None, memory=None, visual=None):
        self.behavior = behavior
        self.context = context
        self.perception = perception
        self.memory = memory
        self.visual = visual if visual is not None else VisualTools(perception) if perception is not None else None

    @staticmethod
    def _keys(args, required):
        if set(args) != set(required):
            raise ValueError(f"Argumente necesare: {sorted(required)}")

    @staticmethod
    def _text(value, maximum):
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            raise ValueError("Text gol sau prea lung")
        return value.strip()

    def execute(self, name, args):
        """Returnează rezultat JSON. Erorile de validare nu ies din worker."""
        try:
            if name not in DESCRIPTIONS or not isinstance(args, dict):
                raise ValueError("Tool necunoscut sau argumente invalide")
            if name == "set_emotion":
                self._keys(args, {"emotion"})
                if args["emotion"] not in {"neutral", "happy", "curious", "sleepy", "excited", "surprised", "sad"}:
                    raise ValueError("Emoție invalidă")
                self.behavior.set_emotion(args["emotion"])
            elif name == "look_at_person":
                self._keys(args, set())
                self.behavior.look_at_person()
            elif name == "look_at":
                self._keys(args, {"x", "y"})
                x, y = args["x"], args["y"]
                if (isinstance(x, bool) or isinstance(y, bool) or
                        not all(isinstance(v, (int, float)) and math.isfinite(v) and -1 <= v <= 1 for v in (x, y))):
                    raise ValueError("x/y trebuie să fie numere în [-1,1]")
                self.behavior.look_at(x, y)
            elif name == "tongue":
                self._keys(args, {"action"})
                if args["action"] not in {"in", "out", "blep", "double_blep"}:
                    raise ValueError("Acțiune limbă invalidă")
                self.behavior.tongue(args["action"])
            elif name == "speak":
                self._keys(args, {"text"})
                self.behavior.speak(self._text(args["text"], config.BRAIN_MAX_SPEECH_CHARS))
            elif name == "get_vision_state":
                self._keys(args, set())
                return {"ok": True, "result": self.context.vision_state()}
            elif name == "inspect_scene":
                self._keys(args, set())
                if self.visual is None:
                    raise RuntimeError("VisualTools nu este conectat")
                return {"ok": True, "result": self.visual.inspect_scene()}
            elif name == "inspect_center_object":
                self._keys(args, set())
                if self.visual is None:
                    raise RuntimeError("VisualTools nu este conectat")
                return {"ok": True, "result": self.visual.inspect_center_object()}
            elif name == "capture_snapshot":
                self._keys(args, set())
                if self.visual is None:
                    raise RuntimeError("VisualTools nu este conectat")
                return {"ok": True, "result": self.visual.capture_snapshot()}
            elif name == "answer_visual_question":
                self._keys(args, {"question"})
                if self.visual is None:
                    raise RuntimeError("VisualTools nu este conectat")
                question = self._text(args["question"], config.BRAIN_MAX_USER_CHARS)
                return {"ok": True, "result": self.visual.answer_visual_question(question)}
            elif name == "get_imu_state":
                self._keys(args, set())
                return {"ok": True, "result": self.context.imu_state()}
            elif name == "remember":
                if set(args) not in ({"text"}, {"text", "kind"}):
                    raise ValueError("Argumente necesare: text și opțional kind")
                if self.memory is None:
                    raise RuntimeError("Memoria nu este conectată")
                kind = args.get("kind", "fact")
                ident = self.memory.remember(self._text(args["text"], config.BRAIN_MAX_MEMORY_CHARS), kind=kind)
                return {"ok": True, "result": {"id": ident, "kind": kind}}
            elif name == "recall":
                self._keys(args, {"query"})
                if self.memory is None:
                    raise RuntimeError("Memoria nu este conectată")
                return {"ok": True, "result": self.memory.recall(self._text(args["query"], config.BRAIN_MAX_USER_CHARS))}
            elif name == "get_robot_state":
                self._keys(args, set())
                return {"ok": True, "result": self.context.robot_state()}
            elif name == "sleep":
                self._keys(args, set())
                self.behavior.sleep()
            elif name == "wake_up":
                self._keys(args, set())
                self.behavior.wake_up()
            return {"ok": True, "result": {"accepted": True}}
        except (ValueError, TypeError, RuntimeError, OverflowError, Full, sqlite3.Error,
                TimeoutError, OSError, KeyError) as error:
            return {"ok": False, "error": str(error)[:240]}
