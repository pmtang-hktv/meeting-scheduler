# Meeting Scheduler Bot

A Telegram bot that manages the executive's calendar. Colleagues send meeting requests; the bot checks Apple Calendar availability, enforces business rules, and auto-confirms or escalates to the owner.

## Requirements

- macOS with Calendar.app (iCloud / Google calendars synced)
- Python 3.11+
- Telegram bot token (from @BotFather)
- Anthropic API key
- Google Maps API key (Distance Matrix)

## Setup

```bash
# 1. Clone and install
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Copy and fill in .env
cp .env.example .env
# Edit .env — set all required values

# 3. Run
python run.py
```

## Environment Variables

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | From @BotFather |
| `OWNER_TELEGRAM_ID` | Your numeric Telegram ID (from @userinfobot) |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `GOOGLE_MAPS_API_KEY` | Google Maps Distance Matrix API key |
| `DEFAULT_CALENDAR_NAME` | Calendar name in Calendar.app (default: `HKTV`) |
| `DB_PATH` | SQLite path (default: `data/bot.db`) |
| `OFFICE_ADDRESS` | Office address for travel time calculation |

## Auto-start on macOS (launchd)

Create `~/Library/LaunchAgents/com.meeting-scheduler.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.meeting-scheduler</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/.venv/bin/python</string>
        <string>/path/to/meeting-scheduler/run.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/path/to/meeting-scheduler</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/meeting-scheduler.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/meeting-scheduler.err</string>
</dict>
</plist>
```

Load it:
```bash
launchctl load ~/Library/LaunchAgents/com.meeting-scheduler.plist
```

## Business Rules

| Rule | Behaviour |
|---|---|
| Mon–Fri, 9:00–18:00 HKT, no HK public holidays | Normal working window |
| 12:30–14:00 | Lunch — always blocked |
| Outside 9:00–18:00 | Owner approval required |
| Duration ≥ 2h | Owner approval required |
| External party (merchant, client, etc.) | Owner approval required |
| VIP conflict | Owner decides |
| Urgent conflict | Owner decides |
| All other cases | Auto-confirmed |

## Location Follow-ups

For external meetings the bot chases the requester for an exact address at **T-12h**, **T-3h**, and **T-15min** before the meeting.
