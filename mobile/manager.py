"""Unified lifecycle manager for HTTP REST API (port 8000), Bluetooth SPP, and BLE Advertising."""

import logging

import config
from .ble_advertiser import BlueZCompanionDaemon
from .bt_spp import BluetoothSPPServer
from .http_server import MobileHTTPServer


class MobileCompanionManager:
    """Starts and stops all 3 mobile communication channels inside Poro's runtime."""

    def __init__(self, *, behavior, body=None, agent=None):
        self.behavior = behavior
        self.body = body
        self.agent = agent
        self.http = MobileHTTPServer(behavior=behavior, body=body, agent=agent)
        self.spp = BluetoothSPPServer(behavior=behavior)
        self.ble = BlueZCompanionDaemon(spp_server=self.spp)

    def start(self):
        if not getattr(config, "MOBILE_ENABLED", True):
            return self
        self.http.start()
        self.spp.start()
        self.ble.start()
        logging.info(
            "Mobile Companion ready: HTTP=:%d, BT_SPP=%s, BLE=%r",
            self.http.port,
            config.MOBILE_BT_SPP_UUID,
            config.MOBILE_BLE_NAME,
        )
        return self

    def close(self):
        for component in (self.ble, self.spp, self.http):
            try:
                component.close()
            except Exception:
                logging.exception("Error closing mobile companion component")

    def __enter__(self):
        return self.start()

    def __exit__(self, *args):
        self.close()

