# Shyam bot — Gemini ➜ Groq migration + key rotation

## Files to copy over your bot folder (same paths)
- `utils/groq_keys.py`      (NEW)     — Groq key loader + rotation + error messages
- `utils/ai_utils.py`       (REPLACE) — all AI calls now hit the Groq API
- `utils/gemini_keys.py`    (REPLACE) — thin shim so old imports keep working
- `cogs/commands/ai.py`     (REPLACE) — chat, roleplay and image analysis on Groq
- `config.yml`              (REPLACE) — `MODEL_ID: llama-3.3-70b-versatile`
- `requirements.txt`        (REPLACE) — `google-generativeai` removed
- `.env.example`            (reference for the key format)

Then: `pip install -r requirements.txt` and restart the bot.

## Keys in .env — one per line
```
GROQ_API_KEY=gsk_key1
GROQ_API_KEY_2=gsk_key2
GROQ_API_KEY_3=gsk_key3
GROQ_API_KEY_4=gsk_key4
GROQ_API_KEY_5=gsk_key5
```
Repeating the exact same name (`GROQ_API_KEY=` five times) or comma-separating
on one line works too — the loader reads the raw `.env` file, so
python-dotenv's "last value wins" limitation does not eat your keys.

## Models
Chat rotation order (a model that is missing/decommissioned is skipped):
`MODEL_ID` → `llama-3.3-70b-versatile` → `openai/gpt-oss-120b` →
`openai/gpt-oss-20b` → `llama-4-maverick` → `llama-4-scout` → `llama-3.1-8b-instant`

Image analysis uses Groq vision: `llama-4-scout` → `llama-4-maverick`.

Any leftover `gemini-*` value in `MODEL_ID` is ignored automatically, so the
bot never 404s on an old config.

## How rotation works
1. All keys are loaded once at startup and used round-robin.
2. On `429` / quota → key parked (30 min for daily quota, 60 s for rate limit)
   and the next key is tried immediately.
3. On invalid/revoked key (`401/403`) → key disabled for the run.
4. On "model not found / decommissioned" (`404`) → the same key retries the
   next model in the list.
5. On `5xx` → 15 s cooldown, next key.
6. Only when every key + model fails does the user get a clear message.

## Error messages the user sees
| Situation | Message |
|---|---|
| No key configured | 🔑 **No AI key configured.** … add `GROQ_API_KEY=` lines to `.env` |
| All keys out of quota | ⏳ **AI limit reached.** All Groq API keys have used up their daily quota… |
| All keys rate limited | 🚦 **Too many requests.** Every AI key is rate limited right now… |
| All keys invalid | 🔑 **Invalid AI key.** … refresh the keys in `.env` |
| No model reachable | 🤖 **Model unavailable.** Check `MODEL_ID` in `config.yml` |
| Safety filter | 🛡️ **Blocked response.** Try rephrasing your message. |
| Groq outage | 🌐 **Groq's AI servers are having issues** right now… |
| Network problem | 📡 **Network error** while contacting the AI. |

## Owner key health
`key_manager.status()` returns lines like
`` `#1` ••••a9f2 — ⏳ cooling down 1780s (12 calls) `` — drop it into any
owner-only command; `key_manager.reload()` re-reads `.env` without a restart.
