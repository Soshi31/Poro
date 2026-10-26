"""Bluetooth SPP / RFCOMM server for Wi-Fi provisioning from the Android 'Poro Companion' app."""

import json
import logging
import os
import socket
import subprocess
from threading import Event, Thread
import time

import config

SPP_UUID = getattr(config, "MOBILE_BT_SPP_UUID", "00001101-0000-1000-8000-00805F9B34FB")
SPP_CHANNEL = int(getattr(config, "MOBILE_BT_SPP_CHANNEL", 1))
AGENT_PATH = "/org/poro/bt_agent"
PROFILE_PATH = "/org/poro/spp_profile"


def configure_wifi(ssid, password):
    """Connect wlan0 to the given Wi-Fi SSID and password using NetworkManager (nmcli)."""
    if not isinstance(ssid, str) or not ssid.strip():
        raise ValueError("Wi-Fi SSID cannot be empty")
    ssid = ssid.strip()
    password = "" if password is None else str(password)
    logging.info("Bluetooth SPP: configuring Wi-Fi for SSID=%r", ssid)

    subprocess.run(["nmcli", "dev", "wifi", "rescan", "ifname", "wlan0"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False)
    cmd = ["nmcli", "--wait", "25", "dev", "wifi", "connect", ssid, "ifname", "wlan0"]
    if password:
        cmd.extend(["password", password])
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    if proc.returncode == 0:
        logging.info("Bluetooth SPP: connected wlan0 to %r via nmcli", ssid)
        return True, proc.stdout.strip()

    # Fallback: delete old profile with same name and retry
    subprocess.run(["nmcli", "connection", "delete", ssid],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8, check=False)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    if proc.returncode == 0:
        logging.info("Bluetooth SPP: connected wlan0 to %r after profile reset", ssid)
        return True, proc.stdout.strip()

    error_msg = (proc.stderr or proc.stdout or "nmcli failed").strip()
    logging.warning("Bluetooth SPP: Wi-Fi connection to %r failed: %s", ssid, error_msg)
    return False, error_msg


def ensure_bluetooth_adapter_ready():
    """Unblock rfkill, power on hci0, set alias 'Poro', and enable discoverable + pairable."""
    name = getattr(config, "MOBILE_BLE_NAME", "Poro")
    for cmd in (
        ["rfkill", "unblock", "bluetooth"],
        ["hciconfig", "hci0", "up"],
        ["hciconfig", "hci0", "name", name],
        ["hciconfig", "hci0", "piscan"],
        ["bluetoothctl", "power", "on"],
        ["bluetoothctl", "system-alias", name],
        ["bluetoothctl", "discoverable-timeout", "0"],
        ["bluetoothctl", "discoverable", "on"],
        ["bluetoothctl", "pairable", "on"],
        ["sdptool", "add", f"--channel={SPP_CHANNEL}", "SP"],
    ):
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=False)
        except Exception:
            pass
    try:
        import dbus
        bus = dbus.SystemBus()
        props = dbus.Interface(bus.get_object("org.bluez", "/org/bluez/hci0"),
                               "org.freedesktop.DBus.Properties")
        props.Set("org.bluez.Adapter1", "Powered", dbus.Boolean(True))
        props.Set("org.bluez.Adapter1", "Alias", dbus.String(name))
        props.Set("org.bluez.Adapter1", "DiscoverableTimeout", dbus.UInt32(0))
        props.Set("org.bluez.Adapter1", "Discoverable", dbus.Boolean(True))
        props.Set("org.bluez.Adapter1", "PairableTimeout", dbus.UInt32(0))
        props.Set("org.bluez.Adapter1", "Pairable", dbus.Boolean(True))
    except Exception as error:
        logging.debug("BlueZ Adapter1 D-Bus setup notice: %s", error)


class BluetoothSPPServer:
    """SPP / RFCOMM listener on UUID 00001101-0000-1000-8000-00805F9B34FB for Wi-Fi setup."""

    def __init__(self, *, behavior=None, wifi_handler=configure_wifi):
        self.behavior = behavior
        self.wifi_handler = wifi_handler
        self._stop = Event()
        self._rfcomm_thread = None
        self._server_sock = None

    def handle_packet_line(self, line):
        """Parse a single JSON line {'ssid': '...', 'pass': '...'} and apply Wi-Fi config."""
        payload = json.loads(line.strip())
        if not isinstance(payload, dict) or "ssid" not in payload:
            raise ValueError("JSON packet must contain 'ssid'")
        ssid = str(payload.get("ssid", "")).strip()
        password = str(payload.get("pass", ""))
        ok, detail = self.wifi_handler(ssid, password)
        if self.behavior is not None:
            try:
                if ok:
                    self.behavior.feed_snax()
                    self.behavior.speak(f"Connected to Wi-Fi {ssid}!", "happy")
                else:
                    self.behavior.set_emotion("sad")
                    self.behavior.speak("Could not connect to Wi-Fi.", "sad")
            except Exception:
                pass
        return {"ok": ok, "ssid": ssid, "detail": detail}

    def handle_stream(self, sock):
        """Read newline-delimited JSON from an connected RFCOMM socket/fd."""
        try:
            sock.settimeout(30.0)
            buffer = b""
            while not self._stop.is_set():
                chunk = sock.recv(1024)
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    raw_line, buffer = buffer.split(b"\n", 1)
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        response = self.handle_packet_line(line)
                    except Exception as error:
                        logging.warning("Bluetooth SPP invalid packet: %s", error)
                        response = {"ok": False, "error": str(error)}
                    try:
                        sock.sendall((json.dumps(response) + "\n").encode("utf-8"))
                    except Exception:
                        pass
            # Also handle a JSON payload sent just before socket close without trailing \n
            tail = buffer.decode("utf-8", errors="replace").strip()
            if tail.startswith("{") and tail.endswith("}"):
                try:
                    response = self.handle_packet_line(tail)
                    sock.sendall((json.dumps(response) + "\n").encode("utf-8"))
                except Exception as error:
                    logging.warning("Bluetooth SPP tail packet error: %s", error)
        except Exception as error:
            logging.warning("Bluetooth SPP client error: %s", error)
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def handle_fd(self, fd):
        """Handle a file descriptor passed by BlueZ Profile1.NewConnection."""
        try:
            sock = socket.socket(fileno=fd)
        except Exception:
            sock = socket.fromfd(fd, socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        Thread(target=self.handle_stream, args=(sock,), name="poro-bt-spp-client", daemon=True).start()

    def _rfcomm_accept_loop(self):
        ensure_bluetooth_adapter_ready()
        while not self._stop.is_set():
            try:
                server = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
                server.settimeout(2.0)
                server.bind((socket.BDADDR_ANY, SPP_CHANNEL))
                server.listen(2)
                self._server_sock = server
                logging.info("Bluetooth SPP RFCOMM listening on channel %d (UUID %s)", SPP_CHANNEL, SPP_UUID)
                while not self._stop.is_set():
                    try:
                        client, addr = server.accept()
                    except socket.timeout:
                        continue
                    logging.info("Bluetooth SPP client connected: %s", addr)
                    Thread(target=self.handle_stream, args=(client,), name="poro-bt-spp-client", daemon=True).start()
            except OSError as error:
                # Dacă BlueZ ProfileManager1 deține deja canalul RFCOMM 1, nu mai resetăm adaptorul în buclă.
                if getattr(error, "errno", None) == 98:
                    logging.info("Bluetooth SPP RFCOMM channel %d este gestionat direct de BlueZ Profile1", SPP_CHANNEL)
                    return
                if not self._stop.is_set():
                    logging.debug("Bluetooth RFCOMM socket loop retry: %s", error)
                    self._stop.wait(10.0)
            except Exception as error:
                if not self._stop.is_set():
                    logging.debug("Bluetooth RFCOMM socket loop retry: %s", error)
                    self._stop.wait(10.0)
            finally:
                if self._server_sock is not None:
                    try:
                        self._server_sock.close()
                    except Exception:
                        pass
                    self._server_sock = None

    def start(self):
        self._rfcomm_thread = Thread(target=self._rfcomm_accept_loop, name="poro-bt-rfcomm", daemon=True)
        self._rfcomm_thread.start()
        return self

    def close(self):
        self._stop.set()
        if self._server_sock is not None:
            try:
                self._server_sock.close()
            except Exception:
                pass
            self._server_sock = None
        if self._rfcomm_thread is not None:
            self._rfcomm_thread.join(timeout=3.0)
            self._rfcomm_thread = None

