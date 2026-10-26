#!/usr/bin/python3
"""Poro complet: hardware sigur, ochi realtime și agent AI local recuperabil."""

import argparse
from contextlib import ExitStack
import logging
import math
import os
import signal
from threading import Event
import time

import config
from behavior import BehaviorManager
from body.body_manager import BodyManager
from brain import BrainAgent, LocalLLM
from brain.context import ContextBuilder, MemoryStore
from brain.tool_registry import ToolRegistry
from core.events import EventBus
from display_manager import DisplayManager
from eye_controller import EyeSystem
from eye_renderer import EyeRenderer, load_assets
from mobile import MobileCompanionManager
from poro_runtime import LLMProxy, PerceptionProxy, RecoverySlot, VoiceProxy
from vision.perception import PerceptionSystem
from voice.voice_manager import VoiceManager


def _settings():
    if not math.isfinite(config.FPS) or config.FPS <= 0:
        raise ValueError("FPS trebuie să fie pozitiv și finit")
    for name in ("SYSTEM_HEALTH_INTERVAL_SECONDS", "SYSTEM_RECOVERY_INITIAL_SECONDS",
                 "SYSTEM_RECOVERY_MAX_SECONDS", "SYSTEM_SHUTDOWN_TIMEOUT",
                 "SYSTEM_STATUS_LOG_INTERVAL"):
        value = getattr(config, name)
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} trebuie să fie pozitiv și finit")
    if config.SYSTEM_RECOVERY_MAX_SECONDS < config.SYSTEM_RECOVERY_INITIAL_SECONDS:
        raise ValueError("SYSTEM_RECOVERY_MAX_SECONDS trebuie să fie >= intervalul inițial")


def _llm_health(llm):
    if not llm.running:
        raise RuntimeError("serverul LLM s-a oprit")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=0, help="Secunde; 0 = până la SIGTERM/Ctrl+C")
    parser.add_argument("--text", help="Trimite o comandă inițială pentru diagnostic, fără STT")
    args = parser.parse_args(argv)
    if not math.isfinite(args.duration) or args.duration < 0:
        parser.error("--duration trebuie să fie finit și >= 0")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s",
                        datefmt="%H:%M:%S")
    stop = Event()
    previous = {name: signal.getsignal(name) for name in (signal.SIGINT, signal.SIGTERM)}
    for name in previous:
        signal.signal(name, lambda signum, frame: stop.set())
    try:
        _settings()
        assets = load_assets()
        eyes = EyeSystem(EyeRenderer(assets))
        with ExitStack() as stack:
            displays = stack.enter_context(DisplayManager())
            bus = EventBus(capacity=max(config.BODY_EVENT_CAPACITY, config.PERCEPTION_EVENT_CAPACITY))
            stack.callback(bus.close)
            body = stack.enter_context(BodyManager(event_bus=bus))
            try:
                memory = stack.enter_context(MemoryStore())

                voice_slot = RecoverySlot("audio", lambda stop_event: VoiceManager().start(),
                                          lambda voice: voice.check_health())
                voice = VoiceProxy(voice_slot)
                voice_slot.on_ready = voice.on_ready
                stack.callback(voice_slot.close)
                voice_slot.start()

                vision_slot = RecoverySlot("camera", lambda stop_event: PerceptionSystem(event_bus=bus).start(),
                                           lambda perception: perception.check_health())
                vision = PerceptionProxy(vision_slot)
                stack.callback(vision_slot.close)
                vision_slot.start()

                llm_slot = RecoverySlot("llm", lambda stop_event: LocalLLM().start(stop_event=stop_event),
                                        _llm_health)
                llm = LLMProxy(llm_slot)
                stack.callback(llm_slot.close)
                llm_slot.start()

                def _on_sleep_change(sleeping):
                    if sleeping:
                        logging.info("SLEEP: opresc camera și LLM-ul pentru economisirea energiei")
                        vision_slot.suspend()
                        llm_slot.suspend()
                    else:
                        logging.info("WAKE: reactivez camera și LLM-ul")
                        vision_slot.resume()
                        llm_slot.resume()

                def _subsystems_ready():
                    return (
                        vision_slot.status()["state"] == "ready"
                        and llm_slot.status()["state"] == "ready"
                    )

                behavior = stack.enter_context(BehaviorManager(
                    eyes, perception=vision, body=body, voice=voice, event_bus=bus,
                    on_sleep_change=_on_sleep_change, subsystems_ready=_subsystems_ready))
                context = stack.enter_context(ContextBuilder(
                    perception=vision, body=body, behavior=behavior, memory=memory, event_bus=bus))
                tools = ToolRegistry(behavior=behavior, context=context, perception=vision, memory=memory)
                agent = BrainAgent(llm=llm, context=context, tools=tools, behavior=behavior)
                agent.start(start_llm=False)
                stack.callback(agent.close)
                stack.enter_context(MobileCompanionManager(behavior=behavior, body=body, agent=agent))
                pending_text = args.text

                started = last_frame = log_at = time.monotonic()
                frames = 0
                previous_state = None
                logging.info("Poro pornit. Spune «%s» apoi comanda; Ctrl+C oprește.",
                             config.VOICE_WAKE_WORD)
                while not stop.is_set() and (not args.duration or time.monotonic() - started < args.duration):
                    frame_at = time.monotonic()
                    body.check_health()  # eroarea I2C este critică: PWM se eliberează și ieșim
                    if pending_text and voice_slot.status()["state"] == "ready" and llm.running:
                        agent.submit(pending_text)
                        pending_text = None
                    state = behavior.update(frame_at - last_frame)
                    last_frame = frame_at
                    displays.show_both(*eyes.render())
                    frames += 1
                    if state != previous_state:
                        logging.info("BEHAVIOR %s", state.value)
                        previous_state = state
                    while (utterance := behavior.listen()) is not None:
                        try:
                            agent.submit(utterance)
                        except Exception as error:
                            logging.warning("Brain ocupat; mesaj ignorat: %s", error)
                            behavior.finish_thinking()
                    while (result := agent.poll_result()) is not None:
                        if result.get("reply"):
                            behavior.set_last_text(result["reply"])
                        logging.info("BRAIN RESULT reply=%r actions=%s read_results=%s metrics=%s",
                                     result.get("reply"), result.get("actions"),
                                     result.get("read_results"), result.get("metrics"))
                    if not agent.get_status()["running"]:
                        raise RuntimeError("Worker-ul agentului s-a oprit")
                    if frame_at - log_at >= config.SYSTEM_STATUS_LOG_INTERVAL:
                        logging.info("Ochi %.1f FPS; audio=%s camera=%s llm=%s agent=%s",
                                     frames / (frame_at - log_at), voice_slot.status(),
                                     vision_slot.status(), llm_slot.status(), agent.get_status())
                        frames, log_at = 0, frame_at
                    target_fps = (
                        getattr(config, "SLEEP_FPS", 10)
                        if (state.value == "SLEEP" and not behavior.is_waking)
                        else config.FPS
                    )
                    stop.wait(max(0.0, 1.0 / target_fps - (time.monotonic() - frame_at)))
            finally:
                # Prioritatea #1: nu așteptăm oprirea LLM/camerei înainte de PWM.
                try:
                    body.close()
                except Exception:
                    logging.exception("Body nu s-a închis curat")
        logging.info("Poro oprit; hardware-ul și worker-ele au fost eliberate.")
        return 0
    except KeyboardInterrupt:
        logging.info("Poro oprit prin Ctrl+C")
        return 0
    except Exception:
        logging.exception("Poro nu a putut continua; systemd poate reporni aplicația")
        return 1
    finally:
        for name, handler in previous.items():
            signal.signal(name, handler)


if __name__ == "__main__":
    raise SystemExit(main())
