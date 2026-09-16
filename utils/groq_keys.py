# ╔══════════════════════════════════════════════════════════════════╗
# ║   Groq API key rotation / failover manager                       ║
# ║   Drop this file in:  utils/groq_keys.py                         ║
# ╚══════════════════════════════════════════════════════════════════╝
"""
Multi-key Groq rotation.

Reads every Groq API key it can find and rotates through them:

  * round-robin  -> spreads load across all keys
  * cooldown     -> a key that returns 429 / quota-exceeded is parked for a
                    while instead of being hammered again
  * disable      -> a key that is invalid / revoked is dropped for the run
  * clear errors -> instead of a raw traceback the user sees something like
                    "⏳ All AI keys have reached their limit."

Supported .env layouts (all can be mixed):

    # one key per line
    GROQ_API_KEY=gsk_key1
    GROQ_API_KEY_2=gsk_key2
    GROQ_API_KEY_3=gsk_key3

    # or comma separated on a single line
    GROQ_API_KEY=gsk_key1,gsk_key2,gsk_key3

Because python-dotenv keeps only the LAST value of a repeated variable name,
this module also parses the raw .env file itself, so even this works:

    GROQ_API_KEY=gsk_key1
    GROQ_API_KEY=gsk_key2
    GROQ_API_KEY=gsk_key3
"""

from __future__ import annotations

import os
import re
import json
import time
import asyncio
import logging
import threading

logger = logging.getLogger("discord")

# how long a key is parked after a rate-limit / quota error (seconds)
RATE_LIMIT_COOLDOWN = 60          # 429 "too many requests"
QUOTA_COOLDOWN = 60 * 30          # daily / per-day token quota exhausted
SERVER_ERROR_COOLDOWN = 15        # 500/503 from Groq

# lightweight endpoint used by the `health` check (lists models for the key)
GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"

# keys added from Discord are persisted here so they survive a restart and do
# not require editing .env by hand.
STORE_FILE = os.path.join("data", "groq_keys.json")

_KEY_LINE = re.compile(
    r"^\s*(?:export\s+)?(GROQ(?:_API)?_KEY[A-Z0-9_]*)\s*[:=]\s*(.+?)\s*$"
)


# ────────────────────────────────────────────────────────────────────
#  Loading keys
# ────────────────────────────────────────────────────────────────────
def _split(raw: str):
    """Split a value that may hold several keys (comma / space / newline)."""
    if not raw:
        return []
    raw = raw.strip().strip('"').strip("'")
    parts = re.split(r"[,\n;\s]+", raw)
    out = []
    for p in parts:
        p = p.strip().strip('"').strip("'")
        if p and not p.lower().startswith("your_") and p != "KEY_HERE":
            out.append(p)
    return out


def _keys_from_env_file(path: str = ".env"):
    keys = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                m = _KEY_LINE.match(line)
                if m:
                    keys.extend(_split(m.group(2)))
    except OSError:
        pass
    return keys


# ────────────────────────────────────────────────────────────────────
#  Persistent store (keys added live from Discord)
# ────────────────────────────────────────────────────────────────────
def keys_from_store(path: str = STORE_FILE):
    """Keys added through the `aikeys add` command."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    if isinstance(data, dict):
        data = data.get("keys", [])
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if isinstance(item, str):
            out.extend(_split(item))
    return out


def _save_store(keys):
    """Atomically persist the Discord-added keys to ``STORE_FILE``."""
    try:
        os.makedirs(os.path.dirname(STORE_FILE) or ".", exist_ok=True)
        tmp = STORE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"keys": list(keys)}, fh, indent=2)
        os.replace(tmp, STORE_FILE)
        return True
    except OSError as exc:
        logger.warning(f"[Groq] Could not save key store: {exc}")
        return False


def mask_key(key: str) -> str:
    """Non-secret representation of a key: ``gsk_••••abcd``."""
    if not key:
        return "????"
    tail = key[-4:] if len(key) > 4 else key
    if key.startswith("gsk_"):
        return f"gsk_••••{tail}"
    prefix = key[:4] if len(key) > 8 else ""
    return f"{prefix}••••{tail}"


def load_keys():
    """Collect keys from the .env file, the environment, the Discord store
    and config.yml (in that order)."""
    keys = []

    # 1. raw .env file (supports repeated GROQ_API_KEY lines)
    keys.extend(_keys_from_env_file(os.path.join(os.getcwd(), ".env")))

    # 2. environment variables: GROQ_API_KEY, GROQ_API_KEY_2, GROQ_KEY...
    for name, value in os.environ.items():
        if re.fullmatch(r"GROQ(?:_API)?_KEY[A-Z0-9_]*", name):
            keys.extend(_split(value))

    # 3. keys added live from Discord
    keys.extend(keys_from_store())

    # 4. config.yml fallback
    try:
        from utils.config_loader import config  # local import: avoids cycles
        keys.extend(_split(str(config.get("GROQ_API_KEY") or "")))
    except Exception:
        pass

    # de-duplicate, keep order
    seen, unique = set(), []
    for k in keys:
        if k not in seen:
            seen.add(k)
            unique.append(k)
    return unique


# ────────────────────────────────────────────────────────────────────
#  Error classification
# ────────────────────────────────────────────────────────────────────
def classify_error(exc: Exception) -> str:
    """Return one of: quota | rate_limit | invalid | model | safety |
    server | network | unknown"""
    msg = str(getattr(exc, "message", "") or exc).lower()
    status = getattr(exc, "status_code", None) or getattr(
        getattr(exc, "response", None), "status", None
    )
    if status is None:
        code = getattr(exc, "status", None) or getattr(exc, "code", None)
        if isinstance(code, int):
            status = code
    name = type(exc).__name__.lower()

    if status == 429 or "rate_limit" in msg or "rate limit" in msg or "too many requests" in msg or "quota" in msg:
        if "per day" in msg or "daily" in msg or "tpd" in msg or "rpd" in msg or "quota" in msg:
            return "quota"
        return "rate_limit"
    if (
        status in (401, 403)
        or "invalid api key" in msg
        or "invalid_api_key" in msg
        or "unauthorized" in msg
        or "authentication" in msg
        or "expired" in msg
        or "disabled" in msg
    ):
        return "invalid"
    if (
        status == 404
        or "model_not_found" in msg
        or "does not exist" in msg
        or "not found" in msg
        or "decommissioned" in msg
        or "model_terms_required" in msg
        or "is not supported" in msg
    ):
        return "model"
    if "content_filter" in msg or "safety" in msg or "blocked" in msg or "flagged" in msg:
        return "safety"
    if (status is not None and 500 <= int(status) < 600) or "internal error" in msg or "unavailable" in msg or "overloaded" in msg or "over capacity" in msg:
        return "server"
    if "timeout" in name or "timeout" in msg or "timed out" in msg or "connection" in msg or "network" in msg or "ssl" in msg:
        return "network"
    return "unknown"


#: user-facing text for each failure reason
ERROR_MESSAGES = {
    "no_keys": (
        "🔑 **No AI key configured.**\n"
        "Ask the bot owner to add `GROQ_API_KEY=...` lines to the `.env` file "
        "(one key per line). Get free keys at https://console.groq.com/keys"
    ),
    "quota": (
        "⏳ **AI limit reached.** All Groq API keys have used up their daily "
        "quota. Please try again later, or add another key in `.env`."
    ),
    "rate_limit": (
        "🚦 **Too many requests.** Every AI key is rate limited right now. "
        "Give it a minute and try again."
    ),
    "invalid": (
        "🔑 **Invalid AI key.** Every configured Groq key was rejected "
        "(invalid, revoked or expired). The bot owner needs to refresh the keys "
        "in `.env`."
    ),
    "model": (
        "🤖 **Model unavailable.** None of the configured Groq models could be "
        "reached with these keys. Check `MODEL_ID` in `config.yml`."
    ),
    "safety": (
        "🛡️ **Blocked response.** The AI refused to answer that (safety filter). "
        "Try rephrasing your message."
    ),
    "server": (
        "🌐 **Groq's AI servers are having issues** right now. Please try "
        "again in a moment."
    ),
    "network": (
        "📡 **Network error** while contacting the AI. Please try again."
    ),
    "unknown": (
        "⚠️ **The AI request failed.** Please try again in a moment."
    ),
}


def error_message(reason: str) -> str:
    return ERROR_MESSAGES.get(reason, ERROR_MESSAGES["unknown"])


class GroqError(Exception):
    """Raised when every key/model combination failed."""

    def __init__(self, reason: str, original: Exception | None = None):
        self.reason = reason
        self.original = original
        super().__init__(error_message(reason))

    @property
    def user_message(self) -> str:
        return error_message(self.reason)


# ────────────────────────────────────────────────────────────────────
#  The rotator
# ────────────────────────────────────────────────────────────────────
class GroqKeyManager:
    def __init__(self):
        self._lock = threading.Lock()
        self.keys = load_keys()
        self._store_keys = set(keys_from_store())
        self._index = 0
        self._cooldown = {}   # key -> timestamp until usable
        self._disabled = set()
        self._forced = None   # key explicitly selected with set_active()
        self.usage = {}       # key -> successful call count
        if self.keys:
            logger.warning(f"[Groq] Loaded {len(self.keys)} API key(s) for rotation.")
        else:
            logger.warning("[Groq] No GROQ_API_KEY found — AI features disabled.")

    # -- info -------------------------------------------------------
    @property
    def has_keys(self) -> bool:
        return bool(self.keys)

    def is_stored(self, key) -> bool:
        """True when the key was added from Discord (and can be removed)."""
        return key in self._store_keys

    def reload(self):
        with self._lock:
            self.keys = load_keys()
            self._store_keys = set(keys_from_store())
            self._cooldown.clear()
            self._disabled.clear()
            self._forced = None
            self._index = 0
        return len(self.keys)

    def status(self):
        """Human readable status list, handy for an owner command."""
        now = time.time()
        rows = []
        for i, key in enumerate(self.keys, 1):
            if key in self._disabled:
                state = "invalid"
            elif self._cooldown.get(key, 0) > now:
                state = f"cooling down {int(self._cooldown[key] - now)}s"
            else:
                state = "ready"
            forced = " (active)" if key == self._forced else ""
            source = "store" if key in self._store_keys else "env"
            rows.append(
                f"`#{i}` {mask_key(key)} — {state} [{source}]{forced} "
                f"({self.usage.get(key, 0)} calls)"
            )
        return rows

    def info(self):
        """Structured status for the ``aikeys`` command."""
        now = time.time()
        out = []
        for i, key in enumerate(self.keys, 1):
            if key in self._disabled:
                state = "invalid"
            elif self._cooldown.get(key, 0) > now:
                state = f"cooldown:{int(self._cooldown[key] - now)}s"
            else:
                state = "ready"
            out.append({
                "index": i,
                "masked": mask_key(key),
                "state": state,
                "stored": key in self._store_keys,
                "active": key == self._forced,
                "calls": self.usage.get(key, 0),
            })
        return out

    # -- management (used by the `aikeys` command) -------------------
    def add_key(self, raw):
        """Add one or more keys, persist the ones added from Discord and make
        them available immediately (no restart needed). Returns the keys that
        were actually new."""
        added = []
        with self._lock:
            for key in _split(raw or ""):
                if key in self.keys:
                    continue
                self.keys.append(key)
                self._store_keys.add(key)
                added.append(key)
            if added:
                _save_store(self._store_keys)
                self._index = 0
        if added:
            logger.warning(f"[Groq] Added {len(added)} key(s) from Discord.")
        return added

    def remove_key(self, identifier):
        """Remove a key by 1-based index or by its last 4 characters.

        Only keys added from Discord can be removed permanently; a key that
        came from .env / config will simply come back after the next reload.
        """
        ident = str(identifier).strip()
        target = None
        with self._lock:
            if ident.isdigit():
                idx = int(ident)
                if 1 <= idx <= len(self.keys):
                    target = self.keys[idx - 1]
            else:
                tail = ident.lstrip("•").lstrip(".").lower()
                for key in self.keys:
                    if key[-4:].lower() == tail:
                        target = key
                        break
            if target is None:
                return None, False
            self.keys.remove(target)
            stored = target in self._store_keys
            self._store_keys.discard(target)
            self._disabled.discard(target)
            self._cooldown.pop(target, None)
            if self._forced == target:
                self._forced = None
            if stored:
                _save_store(self._store_keys)
        return mask_key(target), stored

    def rotate(self):
        """Advance the rotation index and return (previous, next) keys."""
        with self._lock:
            if not self.keys:
                return None, None
            if self._forced is not None:
                previous = self._forced
                self._forced = None
                try:
                    self._index = (self.keys.index(previous) + 1) % len(self.keys)
                except ValueError:
                    self._index = (self._index + 1) % len(self.keys)
                return previous, self.keys[self._index]
            before = self.keys[self._index % len(self.keys)]
            self._index = (self._index + 1) % len(self.keys)
            after = self.keys[self._index % len(self.keys)]
        return before, after

    def set_active(self, identifier):
        """Force one key to be tried first. Returns its masked form."""
        ident = str(identifier).strip()
        with self._lock:
            if ident.isdigit() and 1 <= int(ident) <= len(self.keys):
                target = self.keys[int(ident) - 1]
            else:
                target = next((k for k in self.keys
                               if k[-4:].lower() == ident.lower()), None)
            if target is None:
                return None
            self._forced = target
            self._disabled.discard(target)
            return mask_key(target)

    def clear_active(self):
        with self._lock:
            self._forced = None

    async def health_check_all(self, timeout=12, concurrency=8):
        """Ping every key with a cheap ``GET /models`` call (in parallel).

        Returns a list of dicts and updates the disabled / cooldown state:
        a key that answers 200 is marked ready, a 401/403 key is disabled.
        """
        import aiohttp

        keys = list(self.keys)
        if not keys:
            return []

        client_timeout = aiohttp.ClientTimeout(total=timeout, connect=8)
        sem = asyncio.Semaphore(concurrency)
        results = [None] * len(keys)

        async def check(i, key):
            entry = {
                "index": i + 1,
                "masked": mask_key(key),
                "ok": False,
                "status": None,
                "ms": None,
                "detail": "",
            }
            start = time.monotonic()
            try:
                async with sem:
                    async with session.get(
                        GROQ_MODELS_URL,
                        headers={"Authorization": f"Bearer {key}"},
                    ) as resp:
                        entry["status"] = resp.status
                        entry["ms"] = int((time.monotonic() - start) * 1000)
                        if resp.status == 200:
                            entry["ok"] = True
                            entry["detail"] = "healthy"
                            with self._lock:
                                self._disabled.discard(key)
                                self._cooldown.pop(key, None)
                        elif resp.status in (401, 403):
                            entry["detail"] = "invalid / revoked"
                            with self._lock:
                                self._disabled.add(key)
                        elif resp.status == 429:
                            entry["detail"] = "rate limited"
                        else:
                            body = (await resp.text())[:120]
                            entry["detail"] = body or f"HTTP {resp.status}"
            except Exception as exc:  # noqa: BLE001 - reported below
                entry["detail"] = f"{type(exc).__name__}: {exc}"[:120]
            results[i] = entry

        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            await asyncio.gather(*(check(i, k) for i, k in enumerate(keys)))
        return [r for r in results if r]

    # -- rotation ---------------------------------------------------
    def available_keys(self):
        now = time.time()
        with self._lock:
            live = [
                k for k in self.keys
                if k not in self._disabled and self._cooldown.get(k, 0) <= now
            ]
            if not live:
                return []
            if self._forced in live:
                others = [k for k in live if k != self._forced]
                if others:
                    start = self._index % len(others)
                    self._index = (self._index + 1) % len(others)
                    return [self._forced] + others[start:] + others[:start]
                return [self._forced]
            start = self._index % len(live)
            self._index = (self._index + 1) % len(live)
        return live[start:] + live[:start]

    def mark_success(self, key):
        with self._lock:
            self.usage[key] = self.usage.get(key, 0) + 1
            self._cooldown.pop(key, None)

    def mark_failure(self, key, reason):
        with self._lock:
            if reason == "invalid":
                self._disabled.add(key)
                logger.warning(f"[Groq] Key ••••{key[-4:]} disabled (invalid).")
            elif reason == "quota":
                self._cooldown[key] = time.time() + QUOTA_COOLDOWN
                logger.warning(f"[Groq] Key ••••{key[-4:]} quota exhausted — rotating.")
            elif reason == "rate_limit":
                self._cooldown[key] = time.time() + RATE_LIMIT_COOLDOWN
                logger.warning(f"[Groq] Key ••••{key[-4:]} rate limited — rotating.")
            elif reason == "server":
                self._cooldown[key] = time.time() + SERVER_ERROR_COOLDOWN

    # -- the workhorse ----------------------------------------------
    async def run(self, func, models=None):
        """Call ``func(key, model)`` (sync or async) rotating keys + models.

        ``func`` must perform ONE Groq request. Raises :class:`GroqError`
        when every combination failed.
        """
        if not self.has_keys:
            raise GroqError("no_keys")

        keys = self.available_keys()
        if not keys:
            # everything is cooling down / disabled: report the strictest reason
            reason = "invalid" if len(self._disabled) == len(self.keys) else "quota"
            raise GroqError(reason)

        models = models or [None]
        last_reason = "unknown"
        last_exc = None

        for key in keys:
            for model in models:
                try:
                    result = func(key, model) if model is not None else func(key)
                    if asyncio.iscoroutine(result):
                        result = await result
                    self.mark_success(key)
                    return result
                except GroqError:
                    raise
                except Exception as e:      # noqa: BLE001 - classified below
                    last_exc = e
                    last_reason = classify_error(e)
                    logger.warning(
                        f"[Groq] key ••••{key[-4:]} model={model} failed "
                        f"({last_reason}): {e}"
                    )
                    if last_reason == "model":
                        continue            # same key, next model
                    if last_reason == "safety":
                        raise GroqError("safety", e)
                    self.mark_failure(key, last_reason)
                    break                   # next key
        raise GroqError(last_reason, last_exc)


class GroqAPIError(Exception):
    """A single failed HTTP call to the Groq API (carries the status code)."""

    def __init__(self, status: int, message: str):
        self.status = status
        self.status_code = status
        self.message = message
        super().__init__(f"[{status}] {message}")


#: shared singleton used everywhere in the bot
key_manager = GroqKeyManager()

# Backwards-compatible aliases (older code imported GeminiError)
GeminiError = GroqError
GeminiKeyManager = GroqKeyManager
