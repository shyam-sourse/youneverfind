# AI Staff Suite (ShyamX)

New AI powered modules, all running on Groq with **20-key rotation**.
They show up automatically as three new categories in the bot's `help` menu:
**AI AutoMod**, **AI Tasks**, **AI Staff**.

## Setup

1. Copy `.env.example` to `.env`.
2. Put your bot token in `TOKEN=`.
3. Paste up to 20 Groq keys (`GROQ_API_KEY`, `GROQ_API_KEY_2` … `GROQ_API_KEY_20`).
   Keys are rotated round-robin; a rate-limited / exhausted / invalid key is
   parked automatically and the next one is used.
4. Run `python CodeX.py`.

Owners can check rotation health with `aistaff keys`.

## AI AutoMod — `aiautomod` (alias `aiam`)

Context-aware moderation: the AI judges each message instead of matching words.

| Command | What it does |
|---|---|
| `aiautomod` | Show current configuration |
| `aiautomod enable` / `disable` | Turn AI screening on/off |
| `aiautomod sensitivity <low\|medium\|high>` | How strict the AI is |
| `aiautomod action <delete\|warn\|timeout>` | What happens on a violation |
| `aiautomod log <#channel>` | Where detections are logged |
| `aiautomod ignore <#channel>` / `unignore` | Exclude channels |
| `aiautomod test <text>` | Preview the AI verdict on any text |
| `aiautomod hits` | Last 10 AI detections |

Staff and bots are never screened, and there is a per-user 3s throttle so keys
are never burned by spam.

## AI Tasks & AI Task Checker — `aitask`, `aitaskcheck`

Give AI generated duties to helpers and moderators, then let the AI grade them.

| Command | What it does |
|---|---|
| `aitask generate <@member> <topic>` | AI writes and assigns 3 verifiable duties |
| `aitask create <@member> <title>` | Manual task |
| `aitask list` / `aitask mine` / `aitask view <id>` | Browse tasks |
| `aitask submit <id> <proof>` | Staff submits proof of completion |
| `aitask reassign <id> <@member>` / `aitask delete <id>` | Manage tasks |
| `aitaskcheck <id>` | **AI task checker** — reviews proof, gives verdict + 0-100 score + feedback |
| `aitaskstats [@member]` | Completion rate and average AI score |

## AI Staff — `aistaff`

Activity tracking and AI insight for the whole staff team.

| Command | What it does |
|---|---|
| `aistaff activity [@member]` | 7d / 30d messages, commands, mod actions, last seen |
| `aistaff leaderboard [days]` | Ranked staff activity score |
| `aistaff inactive [days]` | Staff with no recorded activity |
| `aistaff report [@member]` | AI written performance review |
| `aistaff coach [@member]` | AI coaching tips |
| `aistaff summary` | AI weekly summary of the whole team |
| `aistaff suggest <incident>` | AI recommends a fair punishment |
| `aistaff evaluate <@member> <application>` | AI scores a staff applicant |
| `aistaff role add/remove <@role>` | Register which roles count as staff |
| `aistaff keys` | AI key rotation status (owner only) |

Activity is tracked automatically from staff messages, bot command usage and
audit-log moderation actions, and stored in `db/aistaff.db`.
