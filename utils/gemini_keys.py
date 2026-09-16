# ╔══════════════════════════════════════════════════════════════════╗
# ║   Compatibility shim — the bot now runs on GROQ, not Gemini.     ║
# ║   Everything lives in utils/groq_keys.py; this file only keeps    ║
# ║   old imports (`from utils.gemini_keys import key_manager, ...`)  ║
# ║   working so no other cog needs editing.                          ║
# ╚══════════════════════════════════════════════════════════════════╝

from utils.groq_keys import (  # noqa: F401
    key_manager,
    error_message,
    classify_error,
    load_keys,
    ERROR_MESSAGES,
    GroqError,
    GroqAPIError,
    GroqKeyManager,
)

GeminiError = GroqError
GeminiKeyManager = GroqKeyManager

__all__ = [
    "key_manager",
    "error_message",
    "classify_error",
    "load_keys",
    "ERROR_MESSAGES",
    "GroqError",
    "GroqAPIError",
    "GroqKeyManager",
    "GeminiError",
    "GeminiKeyManager",
]
