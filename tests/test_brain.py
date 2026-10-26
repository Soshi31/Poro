"""Contractul JSON și tool allowlist; erorile modelului nu opresc worker-ul."""

from pathlib import Path
import tempfile
import time
import unittest

from brain.agent import BrainAgent
from brain.context import MemoryStore
from brain.intent import direct_command
from brain.prompts import parse_decision
from brain.tool_registry import ToolRegistry


class Behavior:
    def __init__(self):
        self.calls = []

    def speak(self, text):
        self.calls.append(("speak", text))

    def set_emotion(self, value):
        self.calls.append(("emotion", value))

    def look_at(self, x, y):
        self.calls.append(("look", x, y))

    def begin_thinking(self):
        self.calls.append(("begin",))

    def finish_thinking(self):
        self.calls.append(("finish",))


class Context:
    def record_exchange(self, user, reply):
        pass

    def build(self, text):
        return {"user_said": text, "vision": {"has_person": False}, "imu": {},
                "body_events": [], "robot": {"state": "IDLE"}, "relevant_memory": []}

    def vision_state(self):
        return {"has_person": False}

    def imu_state(self):
        return {"ready": True}

    def robot_state(self):
        return {"state": "IDLE"}


class LLM:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.running = False
        self.last_metrics = {"completion_tokens": 10}

    def start(self):
        self.running = True

    def generate(self, messages, *, response_schema):
        return self.outputs.pop(0)

    def generate_stream(self, messages, *, max_tokens=None):
        import json as _json
        try:
            yield _json.loads(self.outputs.pop(0))["reply"]
        except (ValueError, KeyError, TypeError):
            raise RuntimeError("LLM nu a produs JSON valid")

    def close(self):
        self.running = False


class BrainTests(unittest.TestCase):
    def test_only_relevant_tools_are_offered(self):
        self.assertEqual(BrainAgent._relevant_tools("Cum te cheamă?", None), {})
        self.assertIn("tongue", BrainAgent._relevant_tools("Scoate limba", None))

    def test_explicit_command_routes_semantically_without_llm(self):
        self.assertEqual(direct_command("Poro, arată o expresie fericită!")[:2],
                         ("set_emotion", {"emotion": "happy"}))
        self.assertIsNone(direct_command("Salut!"))  # salutul este generat de LLM
        self.assertIsNone(direct_command("Nu fi fericit"))
        self.assertIsNone(direct_command("Ce înseamnă să fii fericit?"))
        behavior = Behavior()
        context = Context()
        llm = LLM([])
        tools = ToolRegistry(behavior=behavior, context=context)
        with BrainAgent(llm=llm, context=context, tools=tools, behavior=behavior) as agent:
            agent.submit("Poro, fii fericit")
            result = None
            deadline = time.monotonic() + 2
            while result is None and time.monotonic() < deadline:
                result = agent.poll_result()
                time.sleep(0.01)
            self.assertTrue(result["direct_command"])
            self.assertEqual(result["actions"][0]["tool"], "set_emotion")
            self.assertIn(("emotion", "happy"), behavior.calls)

    def test_parser_rejects_extra_text_and_malformed_calls(self):
        self.assertEqual(parse_decision('{"reply":"Salut","actions":[]}')["reply"], "Salut")
        self.assertEqual(parse_decision('```json\n{"reply":"Salut","actions":[]}\n```')["reply"], "Salut")
        for raw in ('Salut {"reply":"x"}', '{"reply":"text rostit","actions":[]}',
                    '{"reply":"x","actions":{},"extra":1}',
                    '{"reply":"x","actions":[{"tool":"speak","arguments":[]}]}' ):
            with self.assertRaises(ValueError):
                parse_decision(raw)

    def test_tools_reject_gpio_and_bad_arguments(self):
        behavior = Behavior()
        tools = ToolRegistry(behavior=behavior, context=Context())
        self.assertFalse(tools.execute("gpio_write", {"pin": 1})["ok"])
        self.assertFalse(tools.execute("look_at", {"x": 2, "y": 0})["ok"])
        self.assertFalse(tools.execute("look_at", {"x": True, "y": 0})["ok"])
        self.assertFalse(tools.execute("tongue", {"angle": 180})["ok"])
        self.assertTrue(tools.execute("set_emotion", {"emotion": "happy"})["ok"])
        self.assertEqual(behavior.calls, [("emotion", "happy")])

    def test_memory_persists_and_recalls_relevant_fact(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.sqlite3"
            with MemoryStore(path) as memory:
                memory.remember("Poro iubește merele roșii")
                memory.remember("Camera este montată sus")
            with MemoryStore(path) as memory:
                self.assertIn("merele", memory.recall("Ce merele iubește Poro?")[0]["text"])

    def test_invalid_generation_does_not_stop_next_request(self):
        behavior = Behavior()
        context = Context()
        llm = LLM(["invalid", '{"reply":"Bună!","actions":[]}'])
        tools = ToolRegistry(behavior=behavior, context=context)
        with BrainAgent(llm=llm, context=context, tools=tools, behavior=behavior) as agent:
            agent.submit("Spune-mi o poveste")
            agent.submit("Ce faci astăzi?")
            results = []
            deadline = time.monotonic() + 2
            while len(results) < 2 and time.monotonic() < deadline:
                result = agent.poll_result()
                if result is not None:
                    results.append(result)
                else:
                    time.sleep(0.01)
            self.assertEqual(len(results), 2)
            self.assertIn("error", results[0])
            self.assertEqual(results[1]["reply"], "Bună!")
            self.assertIn(("speak", "Bună!"), behavior.calls)


if __name__ == "__main__":
    unittest.main()
