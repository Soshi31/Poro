"""Memorie SQLite locală: conversație scurtă, fapte/preferințe și evenimente."""

import json
from pathlib import Path
import re
import sqlite3
from threading import Lock
import time
import unicodedata

import config


_STOP = {"acum", "aici", "asta", "care", "cand", "cum", "daca", "despre",
         "este", "fost", "imi", "mai", "mine", "pentru", "poro", "sunt",
         "unui", "unde", "vreau", "vrei", "ce", "cu", "de", "din", "eu",
         "la", "ma", "mi", "pe", "sa", "si", "tu", "un", "o"}
_EVENT_ALIASES = {
    "picked_up": "ridicat ridica luat in mana",
    "put_down": "asezat pus jos",
    "shaken": "scuturat zguduit",
    "upside_down": "rasturnat invers",
    "tilted_left": "inclinat stanga",
    "tilted_right": "inclinat dreapta",
    "tilted_forward": "inclinat fata inainte",
    "tilted_back": "inclinat spate inapoi",
    "movement_started": "miscare pornita",
    "movement_stopped": "miscare oprita",
}


def _tokens(text):
    plain = ''.join(char for char in unicodedata.normalize("NFD", text.casefold())
                    if unicodedata.category(char) != "Mn")
    return {word for word in re.findall(r"[a-z0-9]+", plain)
            if len(word) >= 3 and word not in _STOP}


def _relevance(query, candidate):
    words = _tokens(candidate)
    score = 0
    for term in query:
        if term in words:
            score += 3
        elif len(term) >= 4 and any(len(word) >= 4 and term[:4] == word[:4] for word in words):
            score += 1
    return score


class MemoryStore:
    def __init__(self, path=None):
        self.path = Path(path or config.BRAIN_MEMORY_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False, timeout=5)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        with self._db:
            self._db.execute("CREATE TABLE IF NOT EXISTS facts (id INTEGER PRIMARY KEY, created_at REAL NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL)")
            self._db.execute("CREATE TABLE IF NOT EXISTS conversation_turns (id INTEGER PRIMARY KEY, created_at REAL NOT NULL, role TEXT NOT NULL, text TEXT NOT NULL)")
            self._db.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, created_at REAL NOT NULL, event_type TEXT NOT NULL, details TEXT NOT NULL)")
            self._db.execute("CREATE TABLE IF NOT EXISTS memory_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            self._db.execute("CREATE INDEX IF NOT EXISTS idx_facts_kind ON facts(kind, id)")
            self._db.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type, id)")
            self._migrate_legacy()

    def _migrate_legacy(self):
        migrated = self._db.execute("SELECT value FROM memory_meta WHERE key='legacy_migrated'").fetchone()
        if migrated is not None:
            return
        old = self._db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='memories'").fetchone()
        if old is not None:
            self._db.execute("INSERT INTO facts(created_at,kind,text) SELECT created_at,'fact',text FROM memories")
            self._db.execute("DELETE FROM facts WHERE id NOT IN (SELECT id FROM facts ORDER BY id DESC LIMIT ?)",
                             (config.BRAIN_MEMORY_LIMIT,))
        self._db.execute("INSERT INTO memory_meta(key,value) VALUES ('legacy_migrated','1')")

    @staticmethod
    def _text(value, maximum):
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            raise ValueError("Text gol sau prea lung")
        return value.strip()

    @staticmethod
    def _limit(value, maximum):
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
            raise ValueError(f"limit trebuie să fie între 1 și {maximum}")

    def remember(self, text, kind="fact"):
        """Păstrează explicit un fapt sau o preferință, persistentă peste restart."""
        value = self._text(text, config.BRAIN_MAX_MEMORY_CHARS)
        if kind not in {"fact", "preference"}:
            raise ValueError("kind trebuie să fie fact sau preference")
        with self._lock, self._db:
            cursor = self._db.execute("INSERT INTO facts(created_at,kind,text) VALUES (?,?,?)",
                                      (time.time(), kind, value))
            self._db.execute("DELETE FROM facts WHERE id NOT IN (SELECT id FROM facts ORDER BY id DESC LIMIT ?)",
                             (config.BRAIN_MEMORY_LIMIT,))
            return cursor.lastrowid

    def add_turn(self, role, text):
        if role not in {"user", "assistant"}:
            raise ValueError("role trebuie să fie user sau assistant")
        value = self._text(text, config.BRAIN_MAX_USER_CHARS)
        with self._lock, self._db:
            cursor = self._db.execute("INSERT INTO conversation_turns(created_at,role,text) VALUES (?,?,?)",
                                      (time.time(), role, value))
            self._db.execute("DELETE FROM conversation_turns WHERE id NOT IN (SELECT id FROM conversation_turns ORDER BY id DESC LIMIT ?)",
                             (config.BRAIN_CONVERSATION_LIMIT,))
            return cursor.lastrowid

    def recent_conversation(self, limit=None):
        limit = config.BRAIN_HISTORY_TURNS * 2 if limit is None else limit
        self._limit(limit, config.BRAIN_CONVERSATION_LIMIT)
        with self._lock:
            rows = self._db.execute("SELECT role,text FROM conversation_turns ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in reversed(rows)]

    def add_event(self, event_type, details=None):
        """Păstrează un eveniment semantic; niciun frame/audio brut."""
        name = self._text(event_type, 80)
        if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            raise ValueError("Tip de eveniment invalid")
        if details is None:
            details = {}
        if not isinstance(details, dict):
            raise ValueError("details trebuie să fie un obiect JSON")
        try:
            payload = json.dumps(details, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        except (TypeError, ValueError) as error:
            raise ValueError("details nu este JSON valid") from error
        if len(payload) > config.BRAIN_EVENT_MAX_CHARS:
            raise ValueError("Eveniment prea mare")
        with self._lock, self._db:
            cursor = self._db.execute("INSERT INTO events(created_at,event_type,details) VALUES (?,?,?)",
                                      (time.time(), name, payload))
            self._db.execute("DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT ?)",
                             (config.BRAIN_EVENT_MEMORY_LIMIT,))
            return cursor.lastrowid

    def recent_events(self, limit=5):
        self._limit(limit, config.BRAIN_EVENT_MEMORY_LIMIT)
        with self._lock:
            rows = self._db.execute("SELECT id,created_at,event_type,details FROM events ORDER BY id DESC LIMIT ?",
                                    (limit,)).fetchall()
        return [{"id": row["id"], "created_at": row["created_at"],
                 "type": row["event_type"], "details": json.loads(row["details"])} for row in rows]

    def search_memories(self, query, limit=4, kinds=("fact", "preference", "event")):
        """Căutare lexicală bounded; numai rezultate cu termen relevant."""
        self._text(query, config.BRAIN_MAX_USER_CHARS)
        self._limit(limit, 20)
        selected = set(kinds)
        if not selected or not selected <= {"fact", "preference", "event"}:
            raise ValueError("kinds invalid")
        terms = _tokens(query)
        if not terms:
            return []
        with self._lock:
            facts = self._db.execute("SELECT id,created_at,kind,text FROM facts ORDER BY id DESC LIMIT ?",
                                     (config.BRAIN_MEMORY_LIMIT,)).fetchall() if selected & {"fact", "preference"} else []
            events = self._db.execute("SELECT id,created_at,event_type,details FROM events ORDER BY id DESC LIMIT ?",
                                      (config.BRAIN_EVENT_MEMORY_LIMIT,)).fetchall() if "event" in selected else []
        ranked = []
        for row in facts:
            if row["kind"] in selected:
                score = _relevance(terms, row["text"])
                if score:
                    ranked.append((score, row["created_at"], {"id": row["id"], "type": row["kind"], "text": row["text"]}))
        for row in events:
            detail = json.loads(row["details"])
            score = _relevance(terms, row["event_type"] + " " +
                               _EVENT_ALIASES.get(row["event_type"], "") + " " +
                               json.dumps(detail, ensure_ascii=False))
            if score:
                ranked.append((score, row["created_at"], {"id": row["id"], "type": "event",
                                                       "event_type": row["event_type"], "details": detail}))
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [item[2] for item in ranked[:limit]]

    def recall(self, query, limit=4):
        """Compatibil cu tool-ul existent: caută fapte și preferințe."""
        return self.search_memories(query, limit=limit, kinds=("fact", "preference"))

    def close(self):
        with self._lock:
            self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
