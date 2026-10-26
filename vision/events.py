"""Compatibilitate pentru API-ul vision existent; implementarea este comună."""

from core.events import EventBus, RobotEvent, Subscription, VISION_EVENT_TYPES

VisionEvent = RobotEvent
EVENT_TYPES = VISION_EVENT_TYPES
__all__ = ["EventBus", "VisionEvent", "Subscription", "EVENT_TYPES"]
