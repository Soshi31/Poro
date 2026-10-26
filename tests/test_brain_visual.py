"""Tools vizuale: cerere explicită, fără pixeli în context sau hallucinații."""

from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np

import config
from brain.agent import BrainAgent
from brain.tool_registry import ToolRegistry
from brain.visual import VisualTools, visual_intent
from vision.camera import AIFrame


class Perception:
    def __init__(self):
        self.requests = 0
        self.captures = 0
        self.scene = {"people": [], "primary": None, "motion": None, "objects": [],
                      "scene_analysis": {}, "capabilities": {"objects": "not_configured"}}

    def inspect_scene(self, timeout=None):
        self.requests += 1
        return {"status": "fresh", "scene": self.scene}

    def capture_frame_for_ai(self):
        self.captures += 1
        return AIFrame(self.captures, time.monotonic(), np.zeros((48, 64, 3), dtype=np.uint8))


class Behavior:
    def __init__(self):
        self.spoken = []

    def begin_thinking(self):
        pass

    def finish_thinking(self):
        pass

    def speak(self, text):
        self.spoken.append(text)


class Context:
    def __init__(self):
        self.exchanges = []

    def build(self, text):
        return {"said": text, "vision": {"objects": [], "object_detection": "not_configured"}}

    def record_exchange(self, user, reply):
        self.exchanges.append((user, reply))


class LLM:
    def __init__(self):
        self.running = False
        self.last_metrics = None
        self.calls = 0

    def start(self):
        self.running = True

    def generate(self, messages, *, response_schema):
        self.calls += 1
        raise AssertionError("LLM nu trebuie să ghicească fără backend vizual")

    def close(self):
        self.running = False


class FutureBackend:
    requires_frame = True

    def inspect_scene(self, scene, frame=None):
        return {"status": "analyzed", "answer": "Ții o cană.", "sequence": frame.sequence}

    def inspect_center_object(self, scene, frame=None):
        return {"status": "found", "object": {"label": "cană"}}

    def answer_visual_question(self, question, scene, frame=None):
        return {"status": "answered", "answer": "Ții o cană.", "sequence": frame.sequence}


class VisualTests(unittest.TestCase):
    def test_structured_default_and_snapshot_only_on_request(self):
        perception = Perception()
        visual = VisualTools(perception)
        self.assertEqual(visual.inspect_scene()["analysis"]["object_detection"], "not_configured")
        self.assertEqual(visual.inspect_center_object()["analysis"]["status"], "unknown")
        self.assertEqual(perception.captures, 0)
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(config, "BRAIN_SNAPSHOT_DIR", Path(directory)), \
             patch.object(config, "BRAIN_MAX_SNAPSHOTS", 1):
            result = visual.capture_snapshot()
            path = Path(result["path"])
            self.assertTrue(path.is_file())
            self.assertEqual(path.read_bytes()[:2], b"\xff\xd8")
            self.assertEqual(perception.captures, 1)
            with self.assertRaises(RuntimeError):
                visual.capture_snapshot()
            self.assertEqual(perception.captures, 1)  # fără captură când limita este atinsă

    def test_backend_can_be_swapped_without_agent_changes(self):
        perception = Perception()
        visual = VisualTools(perception, backend=FutureBackend())
        self.assertEqual(visual.answer_visual_question("Ce am în mână?")["analysis"]["answer"], "Ții o cană.")
        self.assertEqual(perception.requests, 1)
        self.assertEqual(perception.captures, 1)

    def test_hand_question_inspects_scene_and_refuses_to_guess(self):
        self.assertEqual(visual_intent("Poro, ce am în mână?")[0], "inspect_scene")
        self.assertIsNone(visual_intent("Poro, nu fă o poză"))
        behavior = Behavior()
        context = Context()
        llm = LLM()
        perception = Perception()
        tools = ToolRegistry(behavior=behavior, context=context, perception=perception)
        with BrainAgent(llm=llm, context=context, tools=tools, behavior=behavior) as agent:
            agent.submit("Ce am în mână?")
            deadline = time.monotonic() + 2
            result = None
            while result is None and time.monotonic() < deadline:
                result = agent.poll_result()
                time.sleep(0.01)
            self.assertTrue(result["visual_preflight"])
            self.assertEqual(result["read_results"][0]["tool"], "inspect_scene")
            self.assertIn("Nu pot stabili", result["reply"])
            self.assertEqual(llm.calls, 0)
            self.assertEqual(perception.captures, 0)

    def test_hand_question_uses_replacement_backend_answer(self):
        behavior = Behavior()
        context = Context()
        llm = LLM()
        perception = Perception()
        tools = ToolRegistry(behavior=behavior, context=context, perception=perception,
                             visual=VisualTools(perception, backend=FutureBackend()))
        with BrainAgent(llm=llm, context=context, tools=tools, behavior=behavior) as agent:
            agent.submit("Ce am în mână?")
            deadline = time.monotonic() + 2
            result = None
            while result is None and time.monotonic() < deadline:
                result = agent.poll_result()
                time.sleep(0.01)
            self.assertEqual(result["reply"], "Ții o cană.")
            self.assertEqual(perception.captures, 1)
            self.assertEqual(llm.calls, 0)


if __name__ == "__main__":
    unittest.main()
