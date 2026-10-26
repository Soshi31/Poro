"""Backend local GGUF prin llama-server pe loopback; fără SDK/cloud."""

import json
import math
import os
from pathlib import Path
import signal
import shutil
import socket
import subprocess
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import config


class LocalLLM:
    def __init__(self):
        if config.LLM_HOST != "127.0.0.1":
            raise ValueError("LLM trebuie să asculte exclusiv pe 127.0.0.1")
        for name in ("LLM_CONTEXT_SIZE", "LLM_THREADS", "LLM_BATCH_SIZE", "LLM_MAX_TOKENS",
                     "LLM_MAX_RESPONSE_BYTES"):
            value = getattr(config, name)
            if not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} trebuie să fie un întreg pozitiv")
        for name in ("LLM_TOP_P", "LLM_REPEAT_PENALTY",
                     "LLM_STARTUP_TIMEOUT", "LLM_REQUEST_TIMEOUT"):
            value = getattr(config, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} trebuie să fie pozitiv și finit")
        if not math.isfinite(config.LLM_TEMPERATURE) or config.LLM_TEMPERATURE < 0:
            raise ValueError("LLM_TEMPERATURE trebuie să fie finit și >= 0")
        if not 0 < config.LLM_TOP_P <= 1 or not 1 <= config.LLM_PORT <= 65535:
            raise ValueError("LLM_TOP_P sau LLM_PORT invalid")
        affinity = config.LLM_CPU_AFFINITY
        if isinstance(config.LLM_NICE, bool) or not isinstance(config.LLM_NICE, int) or not 0 <= config.LLM_NICE <= 19:
            raise ValueError("LLM_NICE trebuie să fie întreg în [0,19]")
        if config.LLM_NICE and shutil.which("nice") is None:
            raise FileNotFoundError("Comanda nice lipsește")
        if affinity is not None:
            total_cpus = os.cpu_count() or 1
            if (not isinstance(affinity, (tuple, list)) or not affinity
                    or any(not isinstance(cpu, int) or not 0 <= cpu < total_cpus for cpu in affinity)
                    or config.LLM_THREADS > len(set(affinity))):
                raise ValueError("LLM_CPU_AFFINITY invalid pentru acest sistem")
            if shutil.which("taskset") is None:
                raise FileNotFoundError("taskset lipsește; instalează util-linux sau setează LLM_CPU_AFFINITY=None")
        self.model_path = Path(config.LLM_MODEL_PATH)
        self.binary = Path(config.LLM_SERVER_BINARY)
        self._process = None
        self._log = None
        self.last_metrics = None

    @property
    def running(self):
        return self._process is not None and self._process.poll() is None

    @staticmethod
    def _peak_ram_mib(pid):
        try:
            for line in Path(f"/proc/{pid}/status").read_text().splitlines():
                if line.startswith("VmHWM:"):
                    return round(int(line.split()[1]) / 1024, 1)
        except (OSError, ValueError, IndexError):
            pass
        return None

    def _url(self, path):
        return f"http://127.0.0.1:{config.LLM_PORT}{path}"

    def _request(self, path, payload=None, *, timeout):
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(self._url(path), data=data,
                          headers={"Content-Type": "application/json"} if data is not None else {})
        try:
            with urlopen(request, timeout=timeout) as response:
                content = response.read(config.LLM_MAX_RESPONSE_BYTES + 1)
        except HTTPError as error:
            detail = error.read(1200).decode("utf-8", errors="replace")
            raise RuntimeError(f"llama-server HTTP {error.code}: {detail}") from error
        if len(content) > config.LLM_MAX_RESPONSE_BYTES:
            raise RuntimeError("Răspuns LLM prea mare")
        return json.loads(content)

    def start(self, stop_event=None):
        if self._process is not None:
            raise RuntimeError("LocalLLM a fost deja pornit")
        if not self.binary.is_file():
            raise FileNotFoundError(f"llama-server lipsește: {self.binary}")
        if not self.model_path.is_file() or self.model_path.stat().st_size < 1_000_000:
            raise FileNotFoundError(f"Model GGUF lipsește/incomplet: {self.model_path}")
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", config.LLM_PORT)) == 0:
                raise RuntimeError(f"Portul LLM {config.LLM_PORT} este ocupat")
        self._log = tempfile.TemporaryFile(mode="w+b")
        command = [str(self.binary), "--model", str(self.model_path),
                   "--host", "127.0.0.1", "--port", str(config.LLM_PORT),
                   "--ctx-size", str(config.LLM_CONTEXT_SIZE), "--threads", str(config.LLM_THREADS),
                   "--threads-batch", str(config.LLM_THREADS), "--batch-size", str(config.LLM_BATCH_SIZE),
                   "--parallel", "1", "--n-gpu-layers", "0", "--no-webui"]
        if config.LLM_CPU_AFFINITY is not None:
            command = ["taskset", "--cpu-list", ",".join(map(str, config.LLM_CPU_AFFINITY))] + command
        if config.LLM_NICE:
            command = ["nice", "-n", str(config.LLM_NICE)] + command
        env = os.environ.copy()
        env["OPENBLAS_NUM_THREADS"] = "1"
        env["OMP_NUM_THREADS"] = str(config.LLM_THREADS)
        self._process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=self._log,
                                         stderr=subprocess.STDOUT, start_new_session=True, env=env)
        deadline = time.monotonic() + config.LLM_STARTUP_TIMEOUT
        try:
            while time.monotonic() < deadline:
                if stop_event is not None and stop_event.is_set():
                    raise RuntimeError("Pornirea LLM a fost anulată")
                if self._process.poll() is not None:
                    self._log.seek(0)
                    raise RuntimeError("llama-server s-a oprit: " +
                                       self._log.read()[-2000:].decode(errors="replace"))
                try:
                    self._request("/health", timeout=1.0)
                    if stop_event is None or not stop_event.is_set():
                        try:
                            from .prompts import plain_system_prompt
                            self.generate([{"role": "system", "content": plain_system_prompt()},
                                           {"role": "user", "content": "Salut"}], max_tokens=1)
                            self.last_metrics = None
                        except Exception:
                            pass
                    return self
                except (URLError, TimeoutError, RuntimeError):
                    if stop_event is not None:
                        stop_event.wait(0.25)
                    else:
                        time.sleep(0.25)
            raise TimeoutError("Încărcarea GGUF a depășit LLM_STARTUP_TIMEOUT")
        except BaseException:
            self.close()
            raise

    def generate(self, messages, *, response_schema=None, max_tokens=None):
        if not self.running:
            raise RuntimeError("LLM local nu este pornit")
        if not isinstance(messages, list) or not messages:
            raise ValueError("messages trebuie să fie o listă nevidă")
        if max_tokens is not None and (not isinstance(max_tokens, int) or max_tokens < 1):
            raise ValueError("max_tokens trebuie să fie un întreg pozitiv")
        top_p = 1.0 if config.LLM_TEMPERATURE == 0 else config.LLM_TOP_P
        payload = {"model": self.model_path.name, "messages": messages,
                   "stream": False, "max_tokens": max_tokens or config.LLM_MAX_TOKENS,
                   "temperature": config.LLM_TEMPERATURE, "top_p": top_p,
                   "top_k": 1 if config.LLM_TEMPERATURE == 0 else 40,
                   "repeat_penalty": config.LLM_REPEAT_PENALTY, "cache_prompt": True}
        if response_schema is not None:
            payload["response_format"] = {"type": "json_schema",
                                          "json_schema": {"name": "poro_decision", "schema": response_schema}}
        started = time.monotonic()
        result = self._request("/v1/chat/completions", payload, timeout=config.LLM_REQUEST_TIMEOUT)
        elapsed = time.monotonic() - started
        try:
            text = result["choices"][0]["message"]["content"]
            usage = result.get("usage", {})
            tokens = usage.get("completion_tokens")
            if not isinstance(text, str):
                raise TypeError("content nu este text")
        except (KeyError, IndexError, TypeError) as error:
            raise RuntimeError("Răspuns llama-server incomplet") from error
        self.last_metrics = {
            "elapsed_seconds": round(elapsed, 2),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": tokens,
            "effective_tokens_per_second": round(tokens / elapsed, 2) if isinstance(tokens, int) and elapsed > 0 else None,
            "server_peak_ram_mib": self._peak_ram_mib(self._process.pid),
            "model": self.model_path.name,
        }
        return text

    def generate_stream(self, messages, *, max_tokens=None):
        """Generator de fragmente de text (SSE llama-server); actualizează last_metrics la final."""
        if not self.running:
            raise RuntimeError("LLM local nu este pornit")
        if not isinstance(messages, list) or not messages:
            raise ValueError("messages trebuie să fie o listă nevidă")
        top_p = 1.0 if config.LLM_TEMPERATURE == 0 else config.LLM_TOP_P
        payload = {"model": self.model_path.name, "messages": messages, "stream": True,
                   "max_tokens": max_tokens or config.LLM_MAX_TOKENS,
                   "temperature": config.LLM_TEMPERATURE, "top_p": top_p,
                   "top_k": 1 if config.LLM_TEMPERATURE == 0 else 40,
                   "repeat_penalty": config.LLM_REPEAT_PENALTY, "cache_prompt": True}
        request = Request(self._url("/v1/chat/completions"),
                          data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                          headers={"Content-Type": "application/json"})
        started = time.monotonic()
        first = None
        chunks = 0
        total = 0
        try:
            with urlopen(request, timeout=config.LLM_REQUEST_TIMEOUT) as response:
                for line in response:
                    line = line.strip()
                    if not line.startswith(b"data:"):
                        continue
                    data = line[5:].strip()
                    if data == b"[DONE]":
                        break
                    try:
                        delta = json.loads(data)["choices"][0]["delta"].get("content")
                    except (KeyError, IndexError, ValueError):
                        continue
                    if delta:
                        total += len(delta)
                        if total > config.LLM_MAX_RESPONSE_BYTES:
                            raise RuntimeError("Răspuns LLM prea mare")
                        if first is None:
                            first = time.monotonic() - started
                        chunks += 1
                        yield delta
        except HTTPError as error:
            raise RuntimeError(f"llama-server HTTP {error.code}: {error.read(1200).decode('utf-8', errors='replace')}") from error
        finally:
            elapsed = time.monotonic() - started
            self.last_metrics = {
                "elapsed_seconds": round(elapsed, 2),
                "first_token_seconds": round(first, 2) if first is not None else None,
                "completion_tokens": chunks,
                "effective_tokens_per_second": round(chunks / elapsed, 2) if chunks and elapsed > 0 else None,
                "server_peak_ram_mib": self._peak_ram_mib(self._process.pid) if self._process else None,
                "model": self.model_path.name, "streamed": True,
            }

    def close(self):
        if self._process is not None:
            process = self._process
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
            self._process = None
        if self._log is not None:
            self._log.close()
            self._log = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *args):
        self.close()
