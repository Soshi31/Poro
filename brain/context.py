"""Selectează doar starea și amintirile relevante pentru promptul curent."""

from collections import deque
import json
import logging
import sqlite3
from threading import Event, Lock, Thread
import time

import config
from core.events import BODY_EVENT_TYPES
from .memory import MemoryStore  # import vechi din brain.context rămâne valid
from .poro_lore import relevant_lore


class ContextBuilder:
    def __init__(self, *, perception, body, behavior, memory, event_bus=None):
        self.perception = perception
        self.body = body
        self.behavior = behavior
        self.memory = memory
        self._events = event_bus.subscribe(BODY_EVENT_TYPES) if event_bus is not None else None
        self._recent_events = deque(maxlen=config.BRAIN_EVENT_HISTORY)
        self._event_lock = Lock()
        self._stop = Event()
        self._event_thread = None
        if self._events is not None:
            self._event_thread = Thread(target=self._collect_events, name="poro-memory-events", daemon=True)
            self._event_thread.start()

    def _collect_events(self):
        while not self._stop.is_set():
            event = self._events.poll(timeout=0.5)
            if event is None or time.monotonic() - event.observed_at > 30:
                continue
            with self._event_lock:
                self._recent_events.append({"type": event.type,
                                            "seconds_ago": round(time.monotonic() - event.observed_at, 1),
                                            "data": event.data})
            if event.type not in {"body_ready", "tongue_action_started", "tongue_action_completed"}:
                try:
                    self.memory.add_event(event.type, event.data)
                except (ValueError, sqlite3.Error) as error:
                    logging.warning("Memory: eveniment %s neînregistrat: %s", event.type, error)

    def record_exchange(self, user_text, reply):
        self.memory.add_turn("user", user_text)
        if reply:
            self.memory.add_turn("assistant", reply)

    def vision_state(self):
        if self.perception is None:
            return {"available": False}
        scene = self.perception.get_current_scene_state()
        return {
            "available": scene["running"], "has_person": scene["has_person"],
            "primary": scene["primary"], "people_count": len(scene["people"]),
            "people": [{"position": person["position"], "bbox": person["bbox"]}
                       for person in scene["people"][:3]],
            "objects": scene["objects"][:5], "motion": scene["motion"],
            "scene_analysis": scene["scene_analysis"], "capabilities": scene["capabilities"],
        }

    def imu_state(self):
        if self.body is None:
            return {"available": False}
        state = self.body.get_state()
        return {key: state.get(key) for key in (
            "ready", "stale", "support_state", "support_is_estimate", "moving",
            "roll_degrees", "pitch_degrees", "tilt_degrees", "orientations",
            "linear_acceleration_m_s2", "gyro_rad_s", "tongue")}

    def robot_state(self):
        return self.behavior.get_state()

    def build(self, user_text):
        vision = self.vision_state()
        imu = self.imu_state()
        robot = self.robot_state()
        primary = vision.get("primary")
        motion = vision.get("motion")
        visual_summary = {"person": vision.get("has_person", False),
                          "people": vision.get("people_count", 0)}
        if primary is not None:
            visual_summary["xy"] = primary.get("position")
        objects = [item.get("label", item.get("name", "unknown"))
                   for item in vision.get("objects", [])[:3]]
        if objects:
            visual_summary["objects"] = objects
        if motion and motion.get("active"):
            visual_summary["motion"] = True
        imu_summary = {"moving": imu.get("moving"), "support": imu.get("support_state")}
        if imu.get("tilt_degrees") is not None and abs(imu["tilt_degrees"]) >= 10:
            imu_summary["tilt"] = imu["tilt_degrees"]
        if imu.get("orientations"):
            imu_summary["orientations"] = imu["orientations"]
        with self._event_lock:
            body_events = [event["type"] for event in list(self._recent_events)[-3:]]
        relevant = []
        for item in self.memory.search_memories(user_text, limit=2):
            if item["type"] == "event":
                compact = {"type": "event", "event": item["event_type"]}
                if len(json.dumps(item["details"], ensure_ascii=False)) <= 100:
                    compact["details"] = item["details"]
                relevant.append(compact)
            else:
                relevant.append({"type": item["type"], "text": item["text"]})
        context = {
            "said": user_text,
            "vision": visual_summary,
            "imu": imu_summary,
            "body_events": body_events,
            "emotion": robot.get("mood"), "robot_state": robot.get("state"),
            "memory": relevant,
            "conversation": self.memory.recent_conversation(),
        }
        lore = relevant_lore(user_text, config.BRAIN_LORE_MAX_CHARS)
        if lore:
            context["lore"] = lore
        # Păstrează întâi vorbirea și stările; elimină detalii opționale.
        while len(json.dumps(context, ensure_ascii=False)) > config.BRAIN_CONTEXT_MAX_CHARS:
            if context["body_events"]:
                context["body_events"].pop(0)
            elif context["conversation"]:
                context["conversation"].pop(0)
            elif context["vision"].get("objects"):
                context["vision"]["objects"].pop()
            elif context["memory"]:
                context["memory"].pop()
            elif context.get("lore"):
                context.pop("lore")
            else:
                break
        return context

    def close(self):
        if self._events is not None:
            self._stop.set()
            self._events.close()
            self._event_thread.join(timeout=2)
            self._events = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
