# Wynncraft Guild Companion

A lightweight Discord slash-command bot for one configured Wynncraft guild. It
fetches public data from the official Wynncraft API on demand and uses only a
short-lived in-memory cache. It does not store guild, player, or command data
between runs.

## Commands

- `/guild info` — guild level, progress, member counts by rank, activity, and season data.
- `/guild members` — paginated directory with rank filtering and username search.
- `/guild member username` — guild-member summary and available public profile stats.
- `/guild leaderboard category` — rank members by total level, contribution, wars, or guild raids.
- `/guild territories` — current territory holdings and available territory details.
- `/guild refresh` — clear the in-memory cache and fetch fresh guild data; requires
  Discord **Manage Server** permission and responds privately.
- `/valt help` — show the bot's command guide and data notes.
- `/item name` — search the Wynncraft item database and show a matching item's
  type, tier, requirements, identifications, base stats, major IDs, restrictions,
  icon metadata, and lore when available. The item title links to the
  [Wynncraft Item Guide](https://wynncraft.com/help/item-guide). If a search is
  ambiguous, the bot asks for a more specific name.
- `/news latest` — show up to five latest visible, published Wynncraft
  announcements, ordered by publication date and including their summaries.

The `/guild info` embed also lists `/item name`, `/news latest`, and `/valt help`
under **Companion tools**.

## World event announcements

Set `WORLD_EVENT_CHANNEL_ID` to the numeric ID of a text channel or thread where
the bot can view and send messages. Enable Discord Developer Mode, right-click
the desired channel, and choose **Copy Channel ID**. The bot polls the Wynncraft
world-events endpoint every 30 seconds and posts an announcement as soon as an
event appears in the upcoming schedule, normally up to 15 minutes before it
starts. Wynncraft's shared API cache can keep the response unchanged for up to
two minutes. The embed shows the local start time, relative countdown, and
location coordinates.

An announcement is deleted only when the API response explicitly confirms a
started/active state (or provides an actual start timestamp). A scheduled time
passing, an event disappearing from the response, or a missing status does not
confirm that it started. The documented Wynncraft world-events response currently
provides schedules but does not guarantee an active-state field, so messages
remain if no reliable start status is returned. If a schedule disappears, an
actual start timestamp must match the stored occurrence; ambiguous updates keep
the message. Events already confirmed as started are not announced. The bot
needs **Manage Messages** in the channel.

Pending announcements and deletion retries are held in memory only, with no
database. Discord deletion failures are logged and retried with exponential
backoff capped at five minutes. Restarting the bot clears this tracking and may
leave a posted message behind.

Use `WORLD_EVENT_EXCLUDED` for a comma-separated list of event names or internal
names that should not be announced. Matching ignores case. Leave it empty to
receive all events. Leave `WORLD_EVENT_CHANNEL_ID` unset to disable announcements.
Upcoming schedules and duplicate protection are kept in memory, so a bot that is
offline for the full schedule visibility window can miss that announcement.

### Command modules and Discord sync

Each slash command has its own module under `commands/`: guild subcommands are
in separate `guild_*.py` files, `/item` is in `item.py`, and `/news latest` is
in `news.py`. Shared guild embeds, menus, and pagination live in `guild.py`.
At startup, the bot discovers modules in `commands/`, runs each module's async
`setup(bot)` when present, then calls `tree.sync()` after registration. Add a
guild subcommand as a `guild_*.py` module attached to the shared guild group;
add a standalone command module with an async `setup(bot)` to register its cog.
Restart the running bot after adding or changing a command; it will discover,
register, and synchronize the changes automatically and log the synced command
count. Global command changes can take a short time to appear in Discord's
autocomplete, so re-inviting the bot is not needed.

Player details follow Wynncraft privacy settings. Missing values display as
`NIL`. Territory regions and total lifetime guild XP are not exposed by the
fields the bot uses. Guild-member wars are global player statistics, not a live
guild war feed.

## Setup

Requires Python 3.11+.

1. Create a Discord application and bot, enable application commands, and invite
   it with the `bot` and `applications.commands` OAuth scopes. The bot needs
   permission to send messages and embeds. No privileged Discord intents are used.
2. Optionally create a Wynncraft API token from the
   [account dashboard](https://wynncraft.com/account/dashboard?section=dev).
   Public-mode tokens are recommended. Enter only the token value; the bot
   applies the required `Bearer` authorization scheme.
3. Configure `DISCORD_TOKEN`, `GUILD_NAME`, and `GUILD_TAG` in your environment
   or a local `.env` file. `.env` is ignored by Git. Set `WYNNCRAFT_API_TOKEN`
   only if using an API token; embed colors can be set with `ACCENT_COLOR` and
   `SUCCESS_COLOR`. For world event alerts, configure `WORLD_EVENT_CHANNEL_ID`
   and optionally `WORLD_EVENT_EXCLUDED`.
4. Install and run on Windows:

   ```powershell
   py -3 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   python main.py
   ```

   On Android Termux, install Python with `pkg install python`, then run
   `python -m venv .venv`, `source .venv/bin/activate`,
   `python -m pip install -r requirements.txt`, and `python main.py`.

Slash commands synchronize during startup. Discord may take a short time to show
new global commands.

## Data and hosting

No database, SQLite, snapshots, or local application data files are used. API
responses are cached only in memory according to the API cache headers; all
cached data disappears when the process exits. The bot can run on a small Python
worker or Termux process. Continuous uptime depends on the host or device, and
the bot requires an active internet connection.

Logging is written to console and a rotating `discord.log`; Discord library
debug-level HTTP logging is disabled to avoid dumping request/response details.
The HTTP session closes on normal shutdown.

## API references

- [Wynncraft API overview and rate limits](https://docs.wynncraft.com/welcome)
- [Guild by name](https://docs.wynncraft.com/modules/guild/get-guild-by-name)
- [Territory list](https://docs.wynncraft.com/modules/guild/list-guild-territories)
- [Player profile](https://docs.wynncraft.com/modules/player/get-player)
- [Item search](https://docs.wynncraft.com/modules/item-recipe/quick-search-items)
- [Published articles](https://docs.wynncraft.com/modules/news/list-publisher-articles)
- [World events](https://docs.wynncraft.com/modules/map/list-world-events)
- [Wynncraft Item Guide](https://wynncraft.com/help/item-guide)
- [API privacy rules](https://docs.wynncraft.com/privacy)
- [Authentication](https://docs.wynncraft.com/authentication)

## Configuration

| Variable | Purpose |
| --- | --- |
| `DISCORD_TOKEN` | Discord bot token (required) |
| `WYNNCRAFT_API_TOKEN` | Optional Wynncraft API token |
| `GUILD_NAME` / `GUILD_TAG` | Guild identity |
| `ACCENT_COLOR` / `SUCCESS_COLOR` | Hex RGB embed colors |
| `WORLD_EVENT_CHANNEL_ID` | Optional Discord text channel or thread ID for world event alerts |
| `WORLD_EVENT_EXCLUDED` | Optional comma-separated event names/internal names to skip |
