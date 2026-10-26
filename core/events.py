"""Evenimente JSON și abonamente independente, cu memorie limitată."""

from collections import deque
from dataclasses import dataclass
import json
import math
from threading import Condition, Lock
import time


VISION_EVENT_TYPES = frozenset({
    "person_seen", "person_lost", "person_position", "multiple_people",
    "motion_detected", "object_detected", "gesture_detected", "scene_updated",
    "perception_error",
})

BODY_EVENT_TYPES = frozenset({
    "picked_up", "put_down", "tilted_left", "tilted_right", "tilted_forward",
    "tilted_back", "shaken", "upside_down", "movement_started", "movement_stopped",
    "body_ready", "body_error", "tongue_action_started", "tongue_action_completed",
})
EVENT_TYPES = VISION_EVENT_TYPES | BODY_EVENT_TYPES


@dataclass(frozen=True)
class RobotEvent:
    sequence: int
    type: str
    emitted_at: float
    observed_at: float
    source: str
    _payload: str

    @property
    def data(self):
        # Fiecare citire primește o copie; consumatorii nu pot altera evenimentul.
        return json.loads(self._payload)

    def to_dict(self):
        return {"schema_version": 1, "sequence": self.sequence, "type": self.type,
                "emitted_at": self.emitted_at, "observed_at": self.observed_at,
                "clock": "monotonic", "source": self.source, "data": self.data}


class Subscription:
    def __init__(self, types, capacity, remove):
        self.types = frozenset(types)
        self._capacity = capacity
        self._remove = remove
        self._queue = deque()
        self._condition = Condition()
        self._closed = False
        self._dropped = 0

    @property
    def dropped_count(self):
        with self._condition:
            return self._dropped

    def _offer(self, event):
        with self._condition:
            if self._closed or event.type not in self.types:
                return
            if len(self._queue) == self._capacity:
                self._queue.popleft()  # păstrăm date recente, nu blocăm producătorul
                self._dropped += 1
            self._queue.append(event)
            self._condition.notify()

    def poll(self, timeout=0.0):
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("timeout trebuie să fie finit și >= 0")
        with self._condition:
            self._condition.wait_for(lambda: self._queue or self._closed, timeout)
            return self._queue.popleft() if self._queue else None

    def drain(self, limit=64):
        if not isinstance(limit, int) or limit < 1:
            raise ValueError("limit trebuie să fie un întreg pozitiv")
        with self._condition:
            return [self._queue.popleft() for _ in range(min(limit, len(self._queue)))]

    def close(self):
        with self._condition:
            self._closed = True
            self._queue.clear()
            self._condition.notify_all()
        self._remove(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class EventBus:
    """Bus comun în același proces; fiecare consumator are coadă proprie limitată."""

    def __init__(self, capacity=64, *, extra_types=()):
        if not isinstance(capacity, int) or capacity < 1:
            raise ValueError("Capacitatea cozii trebuie să fie un întreg pozitiv")
        self._capacity = capacity
        self._lock = Lock()
        self._subscriptions = set()
        self._types = EVENT_TYPES | frozenset(extra_types)
        if not all(isinstance(name, str) and name for name in self._types):
            raise ValueError("Nume de evenimente invalide")
        self._sequence = 0
        self._closed = False

    def subscribe(self, types=None):
        types = self._types if types is None else ({types} if isinstance(types, str) else set(types))
        if not types <= self._types:
            raise ValueError(f"Tipuri de evenimente necunoscute: {types - self._types}")
        with self._lock:
            if self._closed:
                raise RuntimeError("EventBus este închis")
            subscription = Subscription(types, self._capacity, self._remove)
            self._subscriptions.add(subscription)
            return subscription

    def _remove(self, subscription):
        with self._lock:
            self._subscriptions.discard(subscription)

    def publish(self, event_type, data, *, observed_at, source):
        if event_type not in self._types or not math.isfinite(observed_at):
            raise ValueError("Tip/timestamp de eveniment invalid")
        payload = json.dumps(data, allow_nan=False, separators=(",", ":"))
        with self._lock:
            if self._closed:
                return
            self._sequence += 1
            event = RobotEvent(self._sequence, event_type, time.monotonic(),
                                observed_at, source, payload)
            for subscription in self._subscriptions:
                subscription._offer(event)

    def close(self):
        with self._lock:
            self._closed = True
            subscriptions = tuple(self._subscriptions)
            self._subscriptions.clear()
        for subscription in subscriptions:
            subscription.close()
