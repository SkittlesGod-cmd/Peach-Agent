# Peach

Peach is a pre-market intelligence agent. It runs as a background daemon, gathers market data and headlines, and generates a Markdown briefing before the market opens — emailed, written to disk, or sent to your Telegram.

## Install

Two commands. No API keys to configure — the LLM is pre-configured.

```bash
curl -fsSL https://raw.githubusercontent.com/SkittlesGod-cmd/Peach-Agent/main/install.sh | bash
peach start
```

Requires Python 3.9+ and git. Briefings run at 09:00 ET Monday–Friday.

## Add Telegram (recommended)

1. Message [@BotFather](https://t.me/BotFather) on Telegram → `/newbot` → copy the token
2. Edit `~/.local/share/peach-agent/peach_config.json`:

```json
{
  "telegram_bot_token": "YOUR_BOT_TOKEN"
}
```

3. Restart: `peach stop && peach start`
4. Message your bot `/start` — it will save your chat ID automatically

**What you get:**
- `/briefing` — run a briefing on demand
- `/quote AAPL` — live quote
- `/add AAPL 10 150.00` — track a position
- `/portfolio` — P&L on your positions
- `/alert AAPL above 200` — price alerts
- Type anything — the agent will answer using live tools

## Add Email (optional)

```json
{
  "smtp_username": "you@gmail.com",
  "smtp_password": "your-app-password",
  "email_from": "you@gmail.com",
  "email_to": "you@gmail.com"
}
```

## Commands

```bash
peach start                          # start the background daemon
peach status                         # check if it's running
peach stop                           # stop and clean up
PEACH_RUN_ON_START=true peach start  # run a briefing immediately
```

## Deployment Note

Vercel hosts this repository's project page. To run Peach when your laptop is off, install it on an always-on host: VPS, cloud VM, home server, or container.

See [PEACH.md](./PEACH.md) for the full configuration reference.
