# Peach

Peach is a pre-market intelligence agent. It runs as a terminal-activated
background daemon, gathers market data and headlines, generates a Markdown
briefing with OpenAI or Ollama, and emails the report before market open.

## Install

Two commands. No API keys to set — the LLM is pre-configured via OpenRouter.

```bash
curl -fsSL https://raw.githubusercontent.com/SkittlesGod-cmd/Peach-Agent/main/install.sh | bash
peach start
```

Requires Python 3.9+ and git. Briefings run at 09:00 ET Monday–Friday.
If no email is configured, the briefing is written to `~/.local/share/peach-agent/briefing.md`.

## Add Email (optional)

Edit `~/.local/share/peach-agent/peach_config.json`:

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

Vercel hosts this repository's project page, but Vercel does not run persistent
background daemons. To run Peach when your laptop is off, install it on an
always-on host such as a VPS, cloud VM, home server, or container.

See [PEACH.md](./PEACH.md) for the full configuration reference.
