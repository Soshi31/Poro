"""HTTP REST API server on port 8000 for the Android 'Poro Companion' app."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import math
from pathlib import Path
from threading import Thread

import config

_VALID_ACTIONS = frozenset({
    "FEED_SNAX",
    "DEVICE_NEARBY",
    "BLEP",
    "WAKE",
    "SLEEP",
    "SET_EMOTION",
    "MUTE",
    "UNMUTE",
})
_VALID_EMOTIONS = frozenset({
    "normal",
    "heart",
    "star",
    "sleepy",
    "dead",
    "dizzy",
})
_THROTTLED_PATHS = (
    Path("/sys/devices/platform/soc/soc:firmware/get_throttled"),
    Path("/sys/devices/platform/scb/fd500000.pcie/pci0000:00/0000:00:00.0/0000:01:00.0/get_throttled"),
)


def check_battery_ok():
    """Return True if Raspberry Pi supply voltage is healthy, False on under-voltage."""
    for path in _THROTTLED_PATHS:
        try:
            if path.is_file():
                raw = path.read_text(encoding="utf-8").strip()
                flags = int(raw, 16) if raw.startswith("0x") else int(raw, 0)
                # Bit 0 = currently under-voltage (< 4.63V)
                return (flags & 0x1) == 0
        except Exception:
            continue
    return True


class MobileHTTPServer:
    """Non-blocking threaded HTTP server exposing /api/action, /api/gaze, /api/chat, /api/telemetry."""

    def __init__(self, *, behavior, body=None, agent=None, host=None, port=None):
        self.behavior = behavior
        self.body = body
        self.agent = agent
        self.host = host or getattr(config, "MOBILE_HTTP_HOST", "0.0.0.0")
        self.port = int(port or getattr(config, "MOBILE_HTTP_PORT", 8000))
        self._httpd = None
        self._thread = None

    def build_telemetry(self):
        snap = self.behavior.get_state() if self.behavior is not None else {}
        status = snap.get("telemetry_status") or snap.get("state") or "IDLE"
        if status not in {"IDLE", "ATTENTIVE", "LISTENING", "THINKING", "SPEAKING", "SLEEP"}:
            status = "ATTENTIVE" if status in {"HAPPY", "CURIOUS", "STARTLED"} else "IDLE"
        last_text = snap.get("last_text") or getattr(self.behavior, "last_text", "") or ""
        body_state = {}
        if self.body is not None:
            try:
                body_state = self.body.get_state() or {}
            except Exception:
                body_state = {}
        roll = float(body_state.get("roll_degrees", 0.0) or 0.0)
        pitch = float(body_state.get("pitch_degrees", 0.0) or 0.0)
        shaken = bool(body_state.get("shaken", False)) or (snap.get("state") == "STARTLED")
        return {
            "status": status,
            "battery_ok": check_battery_ok(),
            "last_text": last_text,
            "bno": {
                "roll": round(roll, 2),
                "pitch": round(pitch, 2),
                "shaken": shaken,
            },
        }

    def handle_action(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("JSON object required")
        action = payload.get("action")
        parameter = payload.get("parameter")
        if action not in _VALID_ACTIONS:
            raise ValueError(f"Unsupported action: {action!r}")

        if action == "FEED_SNAX":
            self.behavior.feed_snax()
        elif action == "DEVICE_NEARBY":
            self.behavior.device_nearby()
        elif action == "BLEP":
            if self.body is not None:
                self.behavior.tongue("blep")
        elif action == "WAKE":
            self.behavior.wake_up()
        elif action == "SLEEP":
            if self.body is not None:
                try:
                    self.behavior.tongue("in")
                except Exception:
                    pass
            self.behavior.sleep()
        elif action == "SET_EMOTION":
            if parameter not in _VALID_EMOTIONS:
                raise ValueError(f"Unsupported emotion parameter: {parameter!r}")
            self.behavior.set_mobile_emotion(parameter)
        elif action == "MUTE":
            self.behavior.set_muted(True)
        elif action == "UNMUTE":
            self.behavior.set_muted(False)

        return {"ok": True, "action": action, "parameter": parameter}

    def handle_gaze(self, payload):
        if not isinstance(payload, dict) or "x" not in payload or "y" not in payload:
            raise ValueError("Fields 'x' and 'y' are required")
        x = float(payload["x"])
        y = float(payload["y"])
        if not (math.isfinite(x) and math.isfinite(y)):
            raise ValueError("Coordinates must be finite numbers")
        # Restrict strictly to unit circle (sqrt(x^2 + y^2) <= 1.0)
        radius = math.hypot(x, y)
        if radius > 1.0:
            x /= radius
            y /= radius
        x = max(-1.0, min(1.0, x))
        y = max(-1.0, min(1.0, y))
        duration = 1.2 if (abs(x) < 1e-4 and abs(y) < 1e-4) else 5.0
        self.behavior.look_at(x, y, duration=duration)
        return {"ok": True, "x": round(x, 3), "y": round(y, 3)}

    def handle_chat(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("JSON object required")
        message = payload.get("message")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("Non-empty 'message' string required")
        text = message.strip()[:config.BRAIN_MAX_USER_CHARS]
        self.behavior.wake_up(silent=True)
        self.behavior.begin_thinking()
        if self.agent is not None:
            self.agent.submit(text)
        return {"ok": True, "status": "THINKING", "message": text}

    def start(self):
        parent = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt, *args):
                # Avoid spamming stdout on 1.5s /api/telemetry polling
                if self.path != "/api/telemetry":
                    logging.info("Mobile HTTP %s: " + fmt, self.address_string(), *args)

            def _send_json(self, status_code, data):
                body = json.dumps(data, ensure_ascii=False).encode("utf-8")
                self.send_response(status_code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.end_headers()
                self.wfile.write(body)

            def _read_json(self):
                length = int(self.headers.get("Content-Length", "0") or "0")
                if length <= 0 or length > 32_768:
                    raise ValueError("Invalid Content-Length")
                raw = self.rfile.read(length)
                return json.loads(raw.decode("utf-8"))

            def do_OPTIONS(self):
                self._send_json(200, {"ok": True})

            def do_GET(self):
                path = self.path.split("?", 1)[0].rstrip("/")
                if path == "/api/telemetry":
                    self._send_json(200, parent.build_telemetry())
                else:
                    self._send_json(404, {"ok": False, "error": "Not found"})

            def do_POST(self):
                path = self.path.split("?", 1)[0].rstrip("/")
                try:
                    payload = self._read_json()
                    if path == "/api/action":
                        self._send_json(200, parent.handle_action(payload))
                    elif path == "/api/gaze":
                        self._send_json(200, parent.handle_gaze(payload))
                    elif path == "/api/chat":
                        self._send_json(200, parent.handle_chat(payload))
                    else:
                        self._send_json(404, {"ok": False, "error": "Not found"})
                except (ValueError, TypeError, json.JSONDecodeError) as error:
                    self._send_json(400, {"ok": False, "error": str(error)})
                except Exception as error:
                    logging.warning("Mobile HTTP %s error: %s", path, error)
                    self._send_json(500, {"ok": False, "error": str(error)[:200]})

        class ReusableThreadingHTTPServer(ThreadingHTTPServer):
            allow_reuse_address = True
            daemon_threads = True

        self._httpd = ReusableThreadingHTTPServer((self.host, self.port), Handler)
        self._thread = Thread(target=self._httpd.serve_forever, name="poro-mobile-http", daemon=True)
        self._thread.start()
        logging.info("Mobile HTTP REST API active on http://%s:%d", self.host, self.port)
        return self

    def close(self):
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception:
                pass
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None

