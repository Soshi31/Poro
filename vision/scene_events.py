"""Tranziții și limitarea evenimentelor FAST, independente de hardware."""

import config


class SceneEvents:
    def __init__(self, bus):
        self.bus = bus
        self._presence = False
        self._count = 0
        self._motion = False
        self._next_position = self._next_motion = 0.0

    def update(self, state, now):
        presence, primary = state["has_person"], state["primary"]
        if presence != self._presence:
            self.bus.publish("person_seen" if presence else "person_lost",
                             {"scope": "any_person", "primary": primary},
                             observed_at=primary["observed_at"] if presence else now, source="fast_vision")
            self._presence = presence
        if presence and now >= self._next_position:
            self.bus.publish("person_position", primary,
                             observed_at=primary["observed_at"], source="fast_vision")
            self._next_position = now + config.PERSON_POSITION_INTERVAL
        count = len(state["people"])
        if count != self._count and (count > 1 or self._count > 1):
            self.bus.publish("multiple_people", {"count": count, "active": count > 1,
                                                 "evidence": "frontal_faces"},
                             observed_at=state["people_observed_at"] or now, source="fast_vision")
        self._count = count
        motion = state["motion"]
        if motion is not None:
            active = motion["active"]
            if active != self._motion or (active and now >= self._next_motion):
                self.bus.publish("motion_detected", motion,
                                 observed_at=motion["observed_at"], source="fast_vision")
                self._next_motion = now + config.MOTION_EVENT_INTERVAL
            self._motion = active
