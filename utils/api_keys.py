# ╔══════════════════════════════════════════════════════════════════╗
# ║                                                                  ║
# ║   ░█▀▀░█▀█░█▀▄░█▀▀░█░█   ░█▀▄░█▀▀░█░█░█▀▀                     ║
# ║   ░█░░░█░█░█░█░█▀▀░▄▀▄   ░█░█░█▀▀░▀▄▀░▀▀█                     ║
# ║   ░▀▀▀░▀▀▀░▀▀░░▀▀▀░▀░▀   ░▀▀░░▀▀▀░░▀░░▀▀▀                     ║
# ║                                                                  ║
# ║            © 2026 CodeX Devs — All Rights Reserved              ║
# ║                                                                  ║
# ║   discord  ──  https://discord.gg/34thSTQ2Sp                      ║
# ║   youtube  ──  https://youtube.com/@CodeXDevs                   ║
# ║   github   ──  https://github.com/RayExo                        ║
# ║                                                                  ║
# ╚══════════════════════════════════════════════════════════════════╝

"""API key rotation — comma-separated keys are round-robin rotated and
fail over to the next key on auth / rate-limit / server errors."""

import os
import itertools

from utils.config_loader import config


def _parse_keys(raw):
    if not raw:
        return []
    return [key.strip() for key in raw.split(",") if key.strip()]


def get_groq_keys():
    """Return the list of Groq API keys from .env or config.yml."""
    raw = os.getenv("GROQ_API_KEY") or config.get("GROQ_API_KEY") or ""
    return _parse_keys(raw)


class KeyRotator:
    """Round-robin key rotation with failover support."""

    def __init__(self, keys):
        self._keys = list(keys)
        self._cycle = itertools.cycle(range(len(self._keys))) if self._keys else iter(())

    @property
    def keys(self):
        return self._keys

    def next_key(self):
        """Return the next key in the rotation (None if no keys configured)."""
        if not self._keys:
            return None
        return self._keys[next(self._cycle)]


groq_rotator = KeyRotator(get_groq_keys())
