"""Memoria rămâne locală, bounded și nu trimite arhiva în prompt."""

from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

import config
from brain.context import ContextBuilder
from brain.memory import MemoryStore
from core.events import EventBus


class Behavior:
    def get_state(self):
        return {"state": "IDLE", "mood": "neutral"}


class MemoryTests(unittest.TestCase):
    def test_legacy_migration_persistent_categories_and_relevance(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.sqlite3"
            old = sqlite3.connect(path)
            old.execute("CREATE TABLE memories (id INTEGER PRIMARY KEY, created_at REAL NOT NULL, text TEXT NOT NULL)")
            old.execute("INSERT INTO memories(created_at,text) VALUES (?,?)", (time.time(), "Îmi plac merele roșii"))
            old.commit()
            old.close()
            with MemoryStore(path) as memory:
                memory.remember("Prefer ceai de mentă", kind="preference")
                memory.remember("Camera este sus")
                memory.add_turn("user", "Salut")
                memory.add_turn("assistant", "Bună")
                memory.add_event("picked_up", {"strength": "gentle"})
            with MemoryStore(path) as memory:
                self.assertEqual(len(memory.recall("mere roșii")), 1)
                self.assertEqual(memory.recall("Ceaiul meu preferat?")[0]["type"], "preference")
                self.assertEqual(memory.recent_conversation(), [
                    {"role": "user", "text": "Salut"}, {"role": "assistant", "text": "Bună"}])
                self.assertEqual(memory.recent_events()[0]["type"], "picked_up")
                self.assertEqual(memory.search_memories("Când m-ai ridicat?")[0]["type"], "event")
                self.assertEqual(memory.search_memories("banana"), [])
                self.assertEqual(len(memory.search_memories("mere roșii")), 1)  # fără migrare duplicată

    def test_bounded_tables_and_invalid_payload(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(config, "BRAIN_MEMORY_LIMIT", 2), \
             patch.object(config, "BRAIN_CONVERSATION_LIMIT", 2), \
             patch.object(config, "BRAIN_EVENT_MEMORY_LIMIT", 2):
            with MemoryStore(Path(directory) / "m.db") as memory:
                for index in range(3):
                    memory.remember(f"fapt {index}")
                    memory.add_turn("user", f"replica {index}")
                    memory.add_event("picked_up", {"index": index})
                self.assertEqual(len(memory.recall("fapt", limit=2)), 2)
                self.assertEqual(len(memory.recent_conversation(limit=2)), 2)
                self.assertEqual(len(memory.recent_events(limit=2)), 2)
                with self.assertRaises(ValueError):
                    memory.add_event("picked_up", {"bad": float("nan")})
                with self.assertRaises(ValueError):
                    memory.remember("x", kind="event")

    def test_event_bus_persists_between_prompts_and_context_stays_small(self):
        with tempfile.TemporaryDirectory() as directory:
            with MemoryStore(Path(directory) / "m.db") as memory:
                memory.remember("Poro preferă merele", kind="preference")
                memory.remember("Pisica are un nume")
                memory.add_turn("user", "Salut")
                memory.add_turn("assistant", "Bună")
                bus = EventBus()
                try:
                    with ContextBuilder(perception=None, body=None, behavior=Behavior(),
                                        memory=memory, event_bus=bus) as context:
                        bus.publish("picked_up", {"direction": "up"},
                                    observed_at=time.monotonic(), source="bno085")
                        deadline = time.monotonic() + 2
                        while not memory.recent_events() and time.monotonic() < deadline:
                            time.sleep(0.01)
                        self.assertEqual(memory.recent_events()[0]["type"], "picked_up")
                        prompt = context.build("Îți plac merele?")
                        self.assertIn({"type": "preference", "text": "Poro preferă merele"}, prompt["memory"])
                        self.assertNotIn({"type": "fact", "text": "Pisica are un nume"}, prompt["memory"])
                        self.assertEqual(prompt["conversation"][-1]["text"], "Bună")
                        self.assertNotIn("lore", prompt)
                        lore_prompt = context.build("Ce este un Poro?")
                        self.assertIn("Freljord", lore_prompt["lore"])
                        self.assertLessEqual(len(lore_prompt["lore"]), config.BRAIN_LORE_MAX_CHARS)
                        context.record_exchange("Îți plac merele?", "Da")
                        self.assertEqual(memory.recent_conversation()[-1]["text"], "Da")
                finally:
                    bus.close()


if __name__ == "__main__":
    unittest.main()
