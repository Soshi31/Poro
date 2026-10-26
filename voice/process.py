"""Subprocese locale anulabile, cu timeout; fără shell și fără preexec în thread-uri."""

from concurrent.futures import CancelledError
import os
import signal
import subprocess
from threading import Event, Lock
import time


class ProcessRunner:
    def __init__(self):
        self._lock = Lock()
        self._closed = Event()
        self._process = None

    @staticmethod
    def _terminate(process):
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def run(self, command, *, timeout, input_data=None, cancel=None):
        with self._lock:
            if self._closed.is_set() or (cancel is not None and cancel.is_set()):
                raise CancelledError()
            if self._process is not None:
                raise RuntimeError("ProcessRunner este deja ocupat")
            env = os.environ.copy()
            env.update(OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
            process = subprocess.Popen(command, stdin=subprocess.PIPE if input_data is not None else subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       start_new_session=True, env=env)
            if hasattr(os, "sched_setaffinity"):
                try:
                    cpus = set(range(1, os.cpu_count() or 4)) or {0}
                    os.sched_setaffinity(process.pid, cpus)
                except OSError:
                    pass
            self._process = process
        deadline = time.monotonic() + timeout
        try:
            pending_input = input_data
            while True:
                if self._closed.is_set() or (cancel is not None and cancel.is_set()):
                    raise CancelledError()
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Timeout pentru {command[0]}")
                try:
                    stdout, stderr = process.communicate(pending_input, timeout=0.1)
                    break
                except subprocess.TimeoutExpired:
                    pending_input = None
            if process.returncode:
                if self._closed.is_set() or (cancel is not None and cancel.is_set()):
                    raise CancelledError()
                raise RuntimeError(f"{command[0]}: {stderr.decode(errors='replace')[-2000:]}")
            return stdout
        finally:
            self._terminate(process)
            try:
                process.communicate(timeout=1)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
            with self._lock:
                self._process = None

    def close(self):
        self._closed.set()
        with self._lock:
            if self._process is not None:
                self._terminate(self._process)
