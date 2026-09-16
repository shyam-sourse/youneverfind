# ╔══════════════════════════════════════════════════════════════════╗
# ║   Shared core for the AI Staff suite                             ║
# ║   AI AutoMod • AI Tasks • AI Task Checker • AI Staff Activity     ║
# ╚══════════════════════════════════════════════════════════════════╝
"""Small shared layer used by the AI staff cogs.

Everything goes through `utils.ai_utils.ask_ai`, which already rotates every
GROQ_API_KEY found in `.env` (up to 20+ keys) and parks rate limited /
exhausted keys automatically.
"""

from __future__ import annotations

import os
import json
import re
import sqlite3
from datetime import datetime, timedelta


DB_FILE = "db/aistaff.db"
COLOR = 0xFF0000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_automod (
    guild_id TEXT PRIMARY KEY,
    enabled INTEGER DEFAULT 0,
    sensitivity TEXT DEFAULT 'medium',
    action TEXT DEFAULT 'delete',
    log_channel TEXT,
    ignored TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS ai_automod_hits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id TEXT, user_id TEXT, category TEXT, severity INTEGER,
    reason TEXT, content TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS ai_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id TEXT, assigned_to TEXT, created_by TEXT,
    title TEXT, details TEXT, priority TEXT DEFAULT 'medium',
    due_at TEXT, status TEXT DEFAULT 'open',
    proof TEXT, score INTEGER, verdict TEXT, review TEXT,
    created_at TEXT, completed_at TEXT
);
CREATE TABLE IF NOT EXISTS ai_activity (
    guild_id TEXT, user_id TEXT, day TEXT,
    messages INTEGER DEFAULT 0, commands INTEGER DEFAULT 0,
    mod_actions INTEGER DEFAULT 0, last_seen TEXT,
    PRIMARY KEY (guild_id, user_id, day)
);
CREATE TABLE IF NOT EXISTS ai_staff_roles (
    guild_id TEXT, role_id TEXT,
    PRIMARY KEY (guild_id, role_id)
);
CREATE TABLE IF NOT EXISTS ai_support (
    guild_id TEXT PRIMARY KEY,
    enabled INTEGER DEFAULT 0,
    channel TEXT
);
CREATE TABLE IF NOT EXISTS ai_faq (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id TEXT, question TEXT, answer TEXT, keywords TEXT
);
CREATE TABLE IF NOT EXISTS ai_welcome (
    guild_id TEXT PRIMARY KEY,
    enabled INTEGER DEFAULT 0,
    channel TEXT,
    style TEXT DEFAULT 'friendly',
    budget_per_hour INTEGER DEFAULT 5
);
CREATE TABLE IF NOT EXISTS ai_welcome_pool (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id TEXT, style TEXT, message TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS ai_welcome_log (
    guild_id TEXT, hour TEXT, count INTEGER DEFAULT 0,
    PRIMARY KEY (guild_id, hour)
);
CREATE TABLE IF NOT EXISTS ai_insight_activity (
    guild_id TEXT, day TEXT, channel_id TEXT, messages INTEGER DEFAULT 0,
    PRIMARY KEY (guild_id, day, channel_id)
);
CREATE TABLE IF NOT EXISTS ai_insight_members (
    guild_id TEXT, day TEXT, joins INTEGER DEFAULT 0, leaves INTEGER DEFAULT 0,
    PRIMARY KEY (guild_id, day)
);
CREATE TABLE IF NOT EXISTS ai_insight_cfg (
    guild_id TEXT PRIMARY KEY,
    channel TEXT,
    weekday INTEGER DEFAULT 0,
    last_post TEXT
);
"""

_conn = None


def db() -> sqlite3.Connection:
    """Single shared sqlite connection for the whole AI staff suite."""
    global _conn
    if _conn is None:
        os.makedirs("db", exist_ok=True)
        _conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        _conn.executescript(_SCHEMA)
        _conn.commit()
    return _conn


def now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def today() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


def days_ago(n: int) -> str:
    return (datetime.utcnow() - timedelta(days=n)).strftime("%Y-%m-%d")


# ────────────────────────────────────────────────────────────────────
#  Staff detection
# ────────────────────────────────────────────────────────────────────
def staff_role_ids(guild_id) -> list[str]:
    rows = db().execute("SELECT role_id FROM ai_staff_roles WHERE guild_id=?",
                        (str(guild_id),)).fetchall()
    return [r[0] for r in rows]


def is_staff(member) -> bool:
    """A member counts as staff when they hold a registered staff role or any
    of the usual moderation permissions."""
    if member is None or getattr(member, "bot", False):
        return False
    perms = getattr(member, "guild_permissions", None)
    if perms and (perms.manage_messages or perms.kick_members
                  or perms.ban_members or perms.moderate_members
                  or perms.manage_guild):
        return True
    ids = set(staff_role_ids(member.guild.id))
    return any(str(r.id) in ids for r in getattr(member, "roles", []))


# ────────────────────────────────────────────────────────────────────
#  Activity tracking
# ────────────────────────────────────────────────────────────────────
def bump(guild_id, user_id, field="messages", amount=1):
    if field not in ("messages", "commands", "mod_actions"):
        return
    conn = db()
    conn.execute(
        "INSERT OR IGNORE INTO ai_activity (guild_id, user_id, day) VALUES (?,?,?)",
        (str(guild_id), str(user_id), today()))
    conn.execute(
        f"UPDATE ai_activity SET {field}={field}+?, last_seen=? "
        "WHERE guild_id=? AND user_id=? AND day=?",
        (amount, now(), str(guild_id), str(user_id), today()))
    conn.commit()


def activity_totals(guild_id, user_id, days=7):
    row = db().execute(
        "SELECT COALESCE(SUM(messages),0), COALESCE(SUM(commands),0), "
        "COALESCE(SUM(mod_actions),0), MAX(last_seen) FROM ai_activity "
        "WHERE guild_id=? AND user_id=? AND day>=?",
        (str(guild_id), str(user_id), days_ago(days))).fetchone()
    return {"messages": row[0], "commands": row[1],
            "mod_actions": row[2], "last_seen": row[3]}


def activity_board(guild_id, days=7, limit=15):
    return db().execute(
        "SELECT user_id, SUM(messages), SUM(commands), SUM(mod_actions), MAX(last_seen) "
        "FROM ai_activity WHERE guild_id=? AND day>=? GROUP BY user_id "
        "ORDER BY (SUM(messages)+SUM(commands)*2+SUM(mod_actions)*5) DESC LIMIT ?",
        (str(guild_id), days_ago(days), limit)).fetchall()


# ────────────────────────────────────────────────────────────────────
#  AI helpers
# ────────────────────────────────────────────────────────────────────
def extract_json(text: str):
    """Pull the first JSON object/array out of a model reply."""
    if not text:
        return None
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    match = re.search(r"[\{\[].*[\}\]]", text, re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except Exception:
        return None


def _ask():
    """Import lazily so the AI stack is only loaded when actually used."""
    from utils.ai_utils import ask_ai
    return ask_ai


async def ai_json(prompt: str, system: str, retries: int = 1,
                  model: str = None, max_tokens: int = 900):
    """Ask the AI for JSON and parse it. Returns None when it never parses.

    ``model`` and ``max_tokens`` let callers use a cheap/fast model with a
    small token budget (important for the high-volume AutoMod classifier).
    """
    for _ in range(retries + 1):
        reply = await _ask()(
            prompt,
            system=system + "\nReply with raw JSON only. No prose, no markdown.",
            temperature=0.2,
            max_tokens=max_tokens,
            model=model,
        )
        data = extract_json(reply)
        if data is not None:
            return data
    return None


async def ai_text(prompt: str, system: str, max_tokens: int = 700,
                  model: str = None) -> str:
    return await _ask()(prompt, system=system, temperature=0.5,
                        max_tokens=max_tokens, model=model)
