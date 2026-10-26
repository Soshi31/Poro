"""BLE Advertising + BlueZ Agent/Profile registration for the Android 'Poro Companion' app."""

import logging
import subprocess
from threading import Event, Thread

import config
from .bt_spp import AGENT_PATH, PROFILE_PATH, SPP_CHANNEL, SPP_UUID, ensure_bluetooth_adapter_ready

ADAPTER_PATH = "/org/bluez/hci0"
ADVERTISEMENT_PATH = "/org/poro/ble_advertisement0"
LE_ADVERTISEMENT_IFACE = "org.bluez.LEAdvertisement1"
LE_ADVERTISING_MANAGER_IFACE = "org.bluez.LEAdvertisingManager1"
DBUS_PROP_IFACE = "org.freedesktop.DBus.Properties"


def _configure_hci_ble_advertising():
    """Fallback HCI LE advertising setup for 'Poro' with Dual-Mode (LE + BR/EDR) and TxPower (-59 dBm @ 1m)."""
    name = getattr(config, "MOBILE_BLE_NAME", "Poro")
    name_bytes = name.encode("utf-8")[:20]
    tx_power = int(getattr(config, "MOBILE_BLE_TX_POWER_DBM", -59)) & 0xFF
    # AD structure 1: Flags = 0x1A (LE General Discoverable + Simultaneous LE & BR/EDR Controller/Host)
    # NU folosim 0x06 (BR/EDR Not Supported), altfel Android blochează conectarea Bluetooth Classic SPP!
    # AD structure 2: Tx Power Level (0x0A, signed int8)
    # AD structure 3: Complete Local Name (0x09, UTF-8 bytes)
    ad = bytearray([
        0x02, 0x01, 0x1A,
        0x02, 0x0A, tx_power,
        len(name_bytes) + 1, 0x09, *name_bytes,
    ])
    total_len = len(ad)
    padded = ad + bytearray(31 - total_len)
    hex_bytes = [f"{b:02x}" for b in padded]
    for cmd in (
        ["hcitool", "-i", "hci0", "cmd", "0x08", "0x0008", f"{total_len:02x}", *hex_bytes],
        ["hcitool", "-i", "hci0", "cmd", "0x08", "0x000a", "01"],
    ):
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4, check=False)
        except Exception:
            pass


class BlueZCompanionDaemon:
    """Runs the GLib/D-Bus mainloop registering BLE Advertisement, Auto-Pairing Agent, and SPP Profile."""

    def __init__(self, *, spp_server=None):
        self.spp_server = spp_server
        self._stop = Event()
        self._thread = None
        self._loop = None

    def _run_dbus_loop(self):
        ensure_bluetooth_adapter_ready()
        _configure_hci_ble_advertising()
        try:
            import dbus
            import dbus.mainloop.glib
            import dbus.service
            from gi.repository import GLib

            mainloop = dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
            bus = dbus.SystemBus(mainloop=mainloop, private=True)

            class PoroBLEAdvertisement(dbus.service.Object):
                def __init__(self, conn):
                    super().__init__(conn, ADVERTISEMENT_PATH)

                def get_properties(self):
                    name = getattr(config, "MOBILE_BLE_NAME", "Poro")
                    return {
                        LE_ADVERTISEMENT_IFACE: {
                            "Type": dbus.String("peripheral"),
                            "LocalName": dbus.String(name),
                            "Discoverable": dbus.Boolean(True),
                            "Includes": dbus.Array(["tx-power"], signature="s"),
                        }
                    }

                @dbus.service.method(DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
                def GetAll(self, interface):
                    if interface != LE_ADVERTISEMENT_IFACE:
                        raise dbus.exceptions.DBusException("org.freedesktop.DBus.Error.InvalidArgs")
                    return self.get_properties()[LE_ADVERTISEMENT_IFACE]

                @dbus.service.method(LE_ADVERTISEMENT_IFACE, in_signature="", out_signature="")
                def Release(self):
                    logging.info("BLE Advertisement released by BlueZ")

            def _trust_device(device_path):
                try:
                    dev_props = dbus.Interface(bus.get_object("org.bluez", device_path), DBUS_PROP_IFACE)
                    dev_props.Set("org.bluez.Device1", "Trusted", dbus.Boolean(True))
                except Exception:
                    pass

            class PoroPairingAgent(dbus.service.Object):
                @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
                def Release(self):
                    pass

                @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
                def AuthorizeService(self, device, uuid):
                    logging.info("Bluetooth Agent: authorizing %s for %s", uuid, device)
                    _trust_device(device)

                @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="s")
                def RequestPinCode(self, device):
                    _trust_device(device)
                    return "0000"

                @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="u")
                def RequestPasskey(self, device):
                    _trust_device(device)
                    return dbus.UInt32(0)

                @dbus.service.method("org.bluez.Agent1", in_signature="ouq", out_signature="")
                def DisplayPasskey(self, device, passkey, entered):
                    _trust_device(device)

                @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
                def DisplayPinCode(self, device, pincode):
                    _trust_device(device)

                @dbus.service.method("org.bluez.Agent1", in_signature="ou", out_signature="")
                def RequestConfirmation(self, device, passkey):
                    logging.info("Bluetooth Agent: auto-confirming pairing for %s (passkey %06d)", device, passkey)
                    _trust_device(device)

                @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="")
                def RequestAuthorization(self, device):
                    logging.info("Bluetooth Agent: auto-authorizing %s", device)
                    _trust_device(device)

                @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
                def Cancel(self):
                    pass

            parent = self

            class PoroSPPProfile(dbus.service.Object):
                @dbus.service.method("org.bluez.Profile1", in_signature="", out_signature="")
                def Release(self):
                    pass

                @dbus.service.method("org.bluez.Profile1", in_signature="oha{sv}", out_signature="")
                def NewConnection(self, device, fd, fd_properties):
                    raw_fd = fd.take()
                    logging.info("BlueZ SPP Profile: NewConnection from %s (fd=%d)", device, raw_fd)
                    _trust_device(device)
                    if parent.spp_server is not None:
                        parent.spp_server.handle_fd(raw_fd)

                @dbus.service.method("org.bluez.Profile1", in_signature="o", out_signature="")
                def RequestDisconnection(self, device):
                    logging.info("BlueZ SPP Profile: disconnected %s", device)

            adv = PoroBLEAdvertisement(bus)
            agent = PoroPairingAgent(bus, AGENT_PATH)
            profile = PoroSPPProfile(bus, PROFILE_PATH)

            # 1. Register Auto-Pairing Agent
            try:
                agent_mgr = dbus.Interface(bus.get_object("org.bluez", "/org/bluez"), "org.bluez.AgentManager1")
                agent_mgr.RegisterAgent(AGENT_PATH, "NoInputNoOutput")
                agent_mgr.RequestDefaultAgent(AGENT_PATH)
                logging.info("BlueZ NoInputNoOutput pairing agent active")
            except Exception as error:
                logging.debug("BlueZ AgentManager1 registration notice: %s", error)

            # 2. Register SPP Profile (00001101-0000-1000-8000-00805F9B34FB)
            try:
                profile_mgr = dbus.Interface(bus.get_object("org.bluez", "/org/bluez"), "org.bluez.ProfileManager1")
                opts = {
                    "Name": dbus.String("Poro Wi-Fi Provisioning"),
                    "Role": dbus.String("server"),
                    "Channel": dbus.UInt16(SPP_CHANNEL),
                    "RequireAuthentication": dbus.Boolean(False),
                    "RequireAuthorization": dbus.Boolean(False),
                    "AutoConnect": dbus.Boolean(True),
                }
                profile_mgr.RegisterProfile(PROFILE_PATH, SPP_UUID.lower(), opts)
                logging.info("BlueZ SPP Profile registered on UUID %s", SPP_UUID)
            except Exception as error:
                logging.debug("BlueZ ProfileManager1 registration notice: %s", error)

            # 3. Register BLE Advertisement ("Poro", txPower=-59 dBm)
            try:
                ad_mgr = dbus.Interface(bus.get_object("org.bluez", ADAPTER_PATH), LE_ADVERTISING_MANAGER_IFACE)
                ad_mgr.RegisterAdvertisement(
                    ADVERTISEMENT_PATH,
                    dbus.Dictionary({}, signature="sv"),
                    reply_handler=lambda: logging.info(
                        "BLE Advertising active: name=%r, txPower=%d dBm",
                        getattr(config, "MOBILE_BLE_NAME", "Poro"),
                        getattr(config, "MOBILE_BLE_TX_POWER_DBM", -59),
                    ),
                    error_handler=lambda err: logging.warning("BLE RegisterAdvertisement warning: %s", err),
                )
            except Exception as error:
                logging.warning("BlueZ LEAdvertisingManager1 notice: %s", error)

            self._loop = GLib.MainLoop()
            self._loop.run()
        except Exception as error:
            logging.warning("BlueZ D-Bus companion loop stopped: %s", error)

    def start(self):
        self._thread = Thread(target=self._run_dbus_loop, name="poro-bluez-ble", daemon=True)
        self._thread.start()
        return self

    def close(self):
        self._stop.set()
        if self._loop is not None:
            try:
                self._loop.quit()
            except Exception:
                pass
            self._loop = None
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
