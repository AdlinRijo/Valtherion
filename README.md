# Wynncraft Guild Companion

A Discord slash-command bot for one configured Wynncraft guild. It uses the
Wynncraft API v3 for live public guild/member/territory data and SQLite snapshots
for history. It does not scrape the game or bypass player privacy settings.

## Commands

- `/guild info` — guild level, progress, membership by rank, activity and season data.
- `/guild members` — paginated directory with rank filtering and username search.
- `/guild member username` — guild-member summary and available public profile stats.
- `/guild leaderboard category` — bot-calculated rankings from available guild member data.
- `/guild territories` — paginated current holdings, acquisition times, HQ, treasury,
  defences and API-provided map bounds.
- `/guild history period` — compare a daily or weekly snapshot to current data.
- `/guild refresh` — manually refresh API data and save a snapshot; requires
  Discord **Manage Server** permission and responds privately.
- `/guild help` — command and data notes.

The bot never invents unavailable values. The API's guild response exposes level
progress (`xpPercent`), not a lifetime guild XP total. Its territory response
provides map bounds but no named region, and it does not expose a live war feed.
Guild-member `wars` are the public global player stat; weekly contribution is
calculated from saved contribution counters rather than an official weekly API
leaderboard. Member statistics and online status may be hidden by Wynncraft
access rules.

## Setup

Requires Python 3.11+.

1. Create a Discord application and bot, enable application commands, and invite
   it with the `bot` and `applications.commands` OAuth scopes. The bot needs
   permission to send messages and embeds. No privileged Discord intents are used.
2. Create a Wynncraft API token from the [account dashboard](https://wynncraft.com/account/dashboard?section=dev).
   A public-mode token is recommended for public bot features. Requests send the
   token in the `Authorization` header; omitting it is also supported for API
   endpoints that allow guests.
3. If `.env` does not already exist, copy `.env.example` to `.env`. Set
   `DISCORD_TOKEN`, the optional `WYNNCRAFT_API_TOKEN`, the exact `GUILD_NAME`,
   and the matching `GUILD_TAG`. Configure the accent colors and database path
   if desired. Do not commit `.env`.
   The bot adds the required `Bearer ` scheme to `WYNNCRAFT_API_TOKEN`
   automatically; enter only the token value.
4. Install dependencies and start the bot:

   ```powershell
   py -3 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   if (-not (Test-Path .env)) { Copy-Item .env.example .env }
   # Add/update values in .env without replacing existing credentials.
   python main.py
   ```

Slash commands synchronize during startup. Discord may take a short time to show
new global commands.

## Storage, tracking and hosting

The default database is `database/guild_history.sqlite3`. The bot captures a
snapshot at startup and about every 24 hours, plus whenever an authorized user
runs `/guild refresh` or `/guild history`. Weekly comparisons require a snapshot
at least seven days old; history is not backfilled. Keep the SQLite file on
persistent storage or history will be lost when a host replaces its instance.

For continuous hosting, use a Python 3.11+ worker/service that keeps a process
running and mounts durable storage at the database path. The bot cannot make a
provider offer uninterrupted uptime or persistent storage; configure restart
on process failure and backups for the SQLite file with the host. Do not run
multiple bot instances against the same SQLite database.

Logging is written to console and a rotating `discord.log`; Discord library
debug-level HTTP logging is disabled to avoid dumping request/response details.
SIGTERM and normal process shutdown close the HTTP and SQLite connections.

## API references

- [Wynncraft API v3 overview, cache and rate limits](https://docs.wynncraft.com/welcome)
- [Guild by name](https://docs.wynncraft.com/modules/guild/get-guild-by-name)
- [Territory list](https://docs.wynncraft.com/modules/guild/list-guild-territories)
- [Player profile](https://docs.wynncraft.com/modules/player/get-player)
- [API privacy rules](https://docs.wynncraft.com/privacy)
- [Authentication](https://docs.wynncraft.com/authentication)

## Configuration

All branding and operational settings are environment variables; the main bot
code does not need edits to switch guilds or colors:

| Variable | Purpose |
| --- | --- |
| `DISCORD_TOKEN` | Discord bot token (required) |
| `WYNNCRAFT_API_TOKEN` | Optional Wynncraft API token |
| `GUILD_NAME` / `GUILD_TAG` | Guild identity |
| `ACCENT_COLOR` / `SUCCESS_COLOR` | Hex RGB embed palette |
| `DATABASE_PATH` | SQLite file path |
