# Shyam bot — AI fix + Gemini key rotation

## Files
- `utils/gemini_keys.py`  (NEW) — key loader + rotation manager + error messages
- `utils/ai_utils.py`     (REPLACE) — chat_completion now rotates keys AND models
- `cogs/commands/ai.py`   (REPLACE) — chat, roleplay and image analysis use the rotator
- `.env.example`          (reference for the new key format)

Copy them over the same paths in your bot folder, then restart.

## Keys in .env — one per line
```
GOOGLE_API_KEY=AIza...key1
GOOGLE_API_KEY_2=AIza...key2
GOOGLE_API_KEY_3=AIza...key3
GOOGLE_API_KEY_4=AIza...key4
GOOGLE_API_KEY_5=AIza...key5
```
Repeating the exact same name (`GOOGLE_API_KEY=` five times), using
`GEMINI_API_KEY*` names, or comma-separating on one line all work too —
the loader reads the raw .env file, so python-dotenv's "last value wins"
limitation no longer eats your keys.

Remove the hardcoded keys from `config.yml` once .env is set.

## How rotation works
1. All keys are loaded once at startup and used round-robin.
2. On `429` / quota → that key is parked (30 min for daily quota, 60 s for
   rate limit) and the next key is tried immediately.
3. On invalid/revoked key (`401/403`) → the key is disabled for the run.
4. On "model not found / no access" → the same key retries the next model
   (`MODEL_ID` → gemini-2.0-flash → 2.0-flash-lite → 1.5-flash → 1.5-pro).
5. Only when every key+model fails does the user get a clear message.

## Error messages the user sees
| Situation | Message |
|---|---|
| No key configured | 🔑 **No AI key configured.** … add `GOOGLE_API_KEY=` lines to `.env` |
| All keys out of quota | ⏳ **AI limit reached.** All Gemini API keys have used up their daily quota… |
| All keys rate limited | 🚦 **Too many requests.** Every AI key is rate limited right now… |
| All keys invalid | 🔑 **Invalid AI key.** … refresh the keys in `.env` |
| No model reachable | 🤖 **Model unavailable.** Check `MODEL_ID` in `config.yml` |
| Safety filter | 🛡️ **Blocked response.** Try rephrasing your message. |
| Google outage | 🌐 **Google's AI servers are having issues** right now… |
| Network problem | 📡 **Network error** while contacting the AI. |

## Optional: owner status command
`key_manager.status()` returns lines like
`` `#1` ••••a9f2 — ⏳ cooling down 1780s (12 calls) `` — drop it into any
owner-only command to see live key health, and `key_manager.reload()`
re-reads `.env` without restarting.
