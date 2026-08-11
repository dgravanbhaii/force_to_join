# JoinGuard Bot — Full Button-Driven UI

Every setting and moderation action now lives behind inline keyboards with
colored-emoji status indicators (🟢 = on / enabled, 🔴 = off / disabled).
Typed commands are just entry points that open a menu — you rarely need to
type anything else.

## Menus and what opens them

| Command | Where | Opens |
|---|---|---|
| `/start` | private chat | Main menu (Help, Rules, My Info, My ID, Owner Panel if you're the owner) |
| `/panel` | private chat, owner only | Owner control panel — Stats, Users (by status), Federations, full command list |
| `/settings` | group, admin only | Group settings — toggle Welcome/Goodbye, adjust Warn Limit, open Locks menu |
| `/admin` (as a **reply** to a user's message) | group, admin only | Moderation menu for that user — Warn, Clear Warns, Mute, Unmute, Kick, Ban, Unban |
| `/fedmenu` | group, admin only | Federation menu — create a federation or view info for the current one |

Approval requests (force-join → owner approval flow) still arrive as a DM to
the owner with 🟢 Approve / 🔴 Reject / 🔄 Reapprove / 🚫 Revoke buttons,
exactly as before — that part already used buttons.

## What changed from the plain-command version

- **Locks** (photo/video/sticker/gif/url/forward/document/voice/poll) are now
  toggle buttons in `/settings → 🔒 Locks`, each showing 🟢/🔴 for its current
  state, instead of typed `/lock <type>` / `/unlock <type>`.
- **Warn limit** is adjusted with ➖ / ➕ buttons instead of `/setwarnlimit N`.
- **Welcome/Goodbye** are toggle buttons instead of `/welcome on|off`.
- **Moderation actions** (warn, mute, kick, ban, etc.) are buttons that appear
  after replying to a user with `/admin`, instead of separate `/warn`,
  `/mute`, `/ban` commands. The menu refreshes in place after each tap so you
  can chain actions (e.g. warn, warn, then ban) without retyping anything.
- **Federations**: `/fedmenu` replaces `/newfed`, `/fedban`, etc. as the entry
  point; creating one is a single button tap using the group's name.

## Setup (same as before)

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in BOT_TOKEN and OWNER_ID
python bot.py
```

Add the bot to your group(s) as **admin** (needs: ban users, delete messages,
restrict members, invite users) for moderation and locks to work. Also make
it admin in the force-join channels listed in `config.py` — update the `id`,
`title`, and `link` for each channel to your real ones before deploying.

## Files

- `bot.py` — all command + button (callback) handlers, single entry point
- `keyboards.py` — every inline keyboard the bot shows, in one place
- `database.py` — SQLite schema and queries
- `config.py` — env vars + force-join channel list
