"""SLOW în proces separat: un singur job, timeout, cereri manuale coalescente."""

import importlib
import multiprocessing
import os
import signal
from threading import Event, Thread
import time

import config
from .analyzers import validate_result


def _analyzer_process(connection, factories):
    # Aplicația părinte gestionează Ctrl+C și închide acest proces ordonat.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    # Prioritate mică și OpenCV pe un singur fir, numai în procesul SLOW.
    os.nice(10)
    import cv2
    cv2.setNumThreads(1)
    analyzers = {}
    try:
        connection.send("ready")
        while True:
            frame = connection.recv()
            results = []
            for path in factories:
                try:
                    if path not in analyzers:
                        module, name = path.split(":", 1)
                        analyzers[path] = getattr(importlib.import_module(module), name)()
                    analyzer = analyzers[path]
                    capabilities = tuple(analyzer.capabilities)
                    if not capabilities or set(capabilities) - {"objects", "gestures", "scene"}:
                        raise ValueError("capabilities trebuie să conțină objects, gestures sau scene")
                    result = validate_result(analyzer.analyze(frame), capabilities)
                    results.append({"analyzer": path, "capabilities": list(capabilities), "result": result})
                except Exception as error:
                    results.append({"analyzer": path, "error": f"{type(error).__name__}: {error}"})
            connection.send(results)
    except (EOFError, BrokenPipeError):
        pass
    finally:
        connection.close()


class SlowVisionWorker:
    def __init__(self, camera, on_result, on_error):
        self.camera = camera
        self.on_result = on_result
        self.on_error = on_error
        self.factories = tuple(config.SLOW_ANALYZERS)
        if len(set(self.factories)) != len(self.factories) or any(":" not in path for path in self.factories):
            raise ValueError("SLOW_ANALYZERS trebuie să conțină fabrici module:Class distincte")
        self._stop = Event()
        self._request = Event()
        self._thread = None
        self._process = self._connection = None

    def start(self):
        self._thread = Thread(target=self._run, name="poro-slow-scheduler", daemon=True)
        self._thread.start()
        return self

    def request(self):
        if not self.factories or self._stop.is_set() or self._thread is None:
            return False
        self._request.set()  # maximum o cerere în așteptare, chiar dacă agentul insistă
        return True

    def _shutdown_process(self):
        if self._process is not None:
            self._process.terminate()
            self._process.join(timeout=1)
            if self._process.is_alive():
                self._process.kill()
                self._process.join(timeout=1)
            self._process.close()
            self._process = None
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _execute(self, frame):
        if self._process is None:
            context = multiprocessing.get_context("spawn")
            self._connection, child = context.Pipe()
            self._process = context.Process(target=_analyzer_process,
                                            args=(child, self.factories), daemon=True,
                                            name="poro-slow-vision")
            self._process.start()
            child.close()
            # Nu scriem un frame mare într-un pipe înainte ca procesul să citească.
            if self._receive(time.monotonic() + config.SLOW_STARTUP_TIMEOUT) != "ready":
                return None
        self._connection.send(frame)
        return self._receive(time.monotonic() + config.SLOW_VISION_TIMEOUT)

    def _receive(self, deadline):
        while not self._stop.is_set():
            if self._connection.poll(0.05):
                return self._connection.recv()
            if time.monotonic() >= deadline:
                raise TimeoutError("Analiza SLOW a depășit SLOW_VISION_TIMEOUT")
            if not self._process.is_alive():
                raise RuntimeError("Procesul SLOW s-a oprit neașteptat")
        return None

    def _run(self):
        next_run = time.monotonic()
        try:
            while not self._stop.is_set():
                periodic = config.SLOW_VISION_INTERVAL > 0 and time.monotonic() >= next_run
                if not self.factories or not (periodic or self._request.is_set()):
                    self._stop.wait(0.05)
                    continue
                self._request.clear()
                try:
                    frame = self.camera.capture_frame_for_ai()
                    results = self._execute(frame)
                    if results is not None and not self._stop.is_set():
                        self.on_result(frame, results)
                except Exception as error:
                    if not self._stop.is_set():
                        self.on_error(error)
                    self._shutdown_process()
                next_run = time.monotonic() + config.SLOW_VISION_INTERVAL
        finally:
            self._shutdown_process()

    def close(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=config.AI_FRAME_TIMEOUT + 4)
            if self._thread.is_alive():
                raise RuntimeError("Scheduler-ul SLOW nu s-a oprit")
            self._thread = None
