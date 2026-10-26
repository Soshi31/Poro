"""Stare JSON thread-safe, cu expirare la citire și fără imagini brute."""

from copy import deepcopy
from threading import Lock
import time

import config
from .face_tracker import TrackingTarget


class SceneState:
    def __init__(self):
        self._lock = Lock()
        self._state = {
            "schema_version": 1, "clock": "monotonic", "running": False,
            "error": None, "people_observed_at": None, "people": [],
            "primary": None, "motion": None, "slow": {},
        }

    def set_running(self, running, error=None):
        with self._lock:
            self._state["running"] = running
            self._state["error"] = error

    def update_fast(self, observation, target, motion):
        with self._lock:
            state = self._state
            if observation is not None:
                state["people_observed_at"] = observation.captured_at
                width, height = observation.frame_width, observation.frame_height
                state["people"] = [
                    {"detection_index": index, "evidence": "frontal_face",
                     "position": {"x": face.center[0] / width * 2 - 1,
                                  "y": face.center[1] / height * 2 - 1},
                     "bbox": [face.x / width, face.y / height, face.width / width, face.height / height]}
                    for index, face in enumerate(observation.faces)
                ]
            if target.state == "no_target":
                state["primary"] = None
            elif target.state == "tracking" and observation is not None and observation.faces:
                # Camera coordinates pentru agent; corecția montajului rămâne doar la ochi.
                state["primary"] = {
                    "state": target.state, "observed_at": observation.captured_at,
                    "expires_at": observation.captured_at + config.FACE_TARGET_HOLD_SECONDS,
                    "position": {"x": -target.x if config.FACE_INVERT_X else target.x,
                                 "y": -target.y if config.FACE_INVERT_Y else target.y},
                    "eye_target": {"x": target.x, "y": target.y},
                }
            elif state["primary"] is not None:
                state["primary"]["state"] = target.state
            if motion is not None:
                state["motion"] = dict(motion)

    def update_slow(self, captured_at, results):
        with self._lock:
            for item in results:
                old = self._state["slow"].get(item["analyzer"], {})
                self._state["slow"][item["analyzer"]] = {
                    "capabilities": old.get("capabilities", []),
                    **deepcopy(item), "observed_at": captured_at,
                    "expires_at": captured_at + config.SLOW_RESULT_TTL,
                }

    def slow_error(self, message):
        with self._lock:
            for path in config.SLOW_ANALYZERS:
                old = self._state["slow"].get(path, {})
                self._state["slow"][path] = {"analyzer": path, "error": message,
                                             "capabilities": old.get("capabilities", []),
                                             "observed_at": None, "expires_at": 0}

    def snapshot(self, now=None):
        now = time.monotonic() if now is None else now
        with self._lock:
            state = deepcopy(self._state)
        state["sampled_at"] = now
        running = state["running"]
        people_at = state["people_observed_at"]
        state["people_fresh"] = bool(running and people_at is not None
                                     and 0 <= now - people_at <= config.PERCEPTION_PEOPLE_TTL)
        if not state["people_fresh"]:
            state["people"] = []
        primary = state["primary"]
        if primary is not None and (not running or now >= primary["expires_at"]):
            state["primary"] = None
        elif primary is not None and not state["people_fresh"]:
            primary["state"] = "holding"
        state["has_person"] = state["primary"] is not None
        motion = state["motion"]
        state["motion_fresh"] = bool(running and motion is not None
                                     and 0 <= now - motion["observed_at"] <= config.PERCEPTION_PEOPLE_TTL)
        if not state["motion_fresh"]:
            state["motion"] = None
        state["objects"], state["gestures"], state["scene_analysis"] = [], [], {}
        capabilities = {key: "not_configured" for key in ("objects", "gestures", "scene")}
        if any(not state["slow"].get(path, {}).get("capabilities") for path in config.SLOW_ANALYZERS):
            capabilities = dict.fromkeys(capabilities, "unknown")
        for path in config.SLOW_ANALYZERS:
            item = state["slow"].setdefault(path, {"analyzer": path})
            fresh = running and "error" not in item and now < item.get("expires_at", 0)
            item["status"] = ("error" if "error" in item else "fresh" if fresh
                              else "stale" if "result" in item else "pending")
            for capability in item.get("capabilities", []):
                if capabilities[capability] != "fresh":
                    capabilities[capability] = item["status"]
            result = item.pop("result", {})  # nu expunem detecții vechi în alte ramuri JSON
            if fresh:
                for key in ("objects", "gestures"):
                    state[key].extend({**entry, "analyzer": path, "observed_at": item["observed_at"]}
                                      for entry in result.get(key, []))
                if "scene" in result:
                    state["scene_analysis"][path] = result["scene"]
        state["capabilities"] = {"face_tracking": "enabled", "motion": "enabled" if config.MOTION_ENABLED else "disabled",
                                 **capabilities}
        return state

    def tracking_target(self):
        now = time.monotonic()
        with self._lock:
            primary = deepcopy(self._state["primary"])
            running = self._state["running"]
        if primary is None or not running or now >= primary["expires_at"]:
            return TrackingTarget("no_target", None, None)
        if now - primary["observed_at"] > config.PERCEPTION_PEOPLE_TTL:
            primary["state"] = "holding"
        return TrackingTarget(primary["state"], **primary["eye_target"])
