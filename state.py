"""Estado persistente: posiciones abiertas y cooldowns de señales."""
from __future__ import annotations

import json
import logging
import os

log = logging.getLogger("state")


class State:
    def __init__(self, path: str):
        self.path = path
        self.positions: dict = {}
        self.last_signal: dict = {}
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                self.positions = data.get("positions", {})
                self.last_signal = data.get("last_signal", {})
            except Exception:
                log.exception("Estado corrupto en %s; se guarda copia en .bak", path)
                os.replace(path, path + ".bak")

    def save(self):
        folder = os.path.dirname(self.path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(
                {"positions": self.positions, "last_signal": self.last_signal},
                f,
                indent=2,
            )
        os.replace(tmp, self.path)
