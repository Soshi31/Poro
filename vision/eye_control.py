"""Adaptor subțire către API-ul existent EyeSystem, apelat din bucla ochilor."""

import logging


class EyeTrackingController:
    def __init__(self, eyes):
        self.eyes = eyes
        self._had_target = False

    def update(self, target):
        if target.state == "no_target":
            if self._had_target:
                logging.info("FACE LOST -> no_target; revenire lină spre centru, apoi idle")
                # O singură comandă. Apoi EyeSystem își reia idle-ul automat.
                self.eyes.look_at(0.0, 0.0, tracking=True)
                self._had_target = False
            return
        if not self._had_target:
            logging.info("FACE FOUND x=%+.3f y=%+.3f", target.x, target.y)
        self._had_target = True
        # track_target existent primește coordonate într-un cadru. Folosim un
        # cadru unitar pentru ținta normalizată, păstrând TRACKING_* existente.
        # Reînnoim inclusiv în holding pentru a împiedica pornirea prematură a idle-ului.
        self.eyes.track_target((target.x + 1) / 2, (target.y + 1) / 2, 1, 1)
