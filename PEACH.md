# Peach

Peach is a local pre-market AI briefing agent. It starts from the terminal, runs
as a detached background daemon, gathers market data and headlines, generates a
Markdown briefing with OpenAI or Ollama, and emails the report before the market
opens.

## Install

```bash
cd /Users/svanik/Documents/FormLayer
python3 -m venv .venv-peach
source .venv-peach/bin/activate
pip install -r requirements-peach.txt
pip install .
cp peach_config.example.json peach_config.json
```

## Configure

Peach reads environment variables first, then `peach_config.json`.

Required for email:

```bash
export SMTP_USERNAME="you@example.com"
export SMTP_PASSWORD="your-smtp-app-password"
export PEACH_EMAIL_FROM="you@example.com"
export PEACH_EMAIL_TO="you@example.com"
```

Choose one LLM provider.

OpenAI:

```bash
export PEACH_LLM_PROVIDER="openai"
export OPENAI_API_KEY="sk-..."
export PEACH_OPENAI_MODEL="gpt-4o-mini"
```

Ollama:

```bash
export PEACH_LLM_PROVIDER="ollama"
export OLLAMA_URL="http://127.0.0.1:11434"
export PEACH_OLLAMA_MODEL="llama3.1"
```

Optional news providers:

```bash
export ALPHA_VANTAGE_API_KEY="..."
export NEWS_API_KEY="..."
```

If neither news API key is configured, Peach falls back to Yahoo Finance RSS.

## Run

```bash
peach start
peach status
peach stop
```

Runtime files are created in the Peach home directory:

- `.peach.pid`
- `peach.log`
- `peach_config.json`

By default, the Peach home directory is your current directory. You can pin it:

```bash
peach --home /Users/svanik/Documents/FormLayer start
peach --home /Users/svanik/Documents/FormLayer status
peach --home /Users/svanik/Documents/FormLayer stop
```

## Schedule

Peach runs at 9:00 AM America/New_York, Monday through Friday. Override in
`peach_config.json`:

```json
{
  "schedule_hour": 9,
  "schedule_minute": 0,
  "timezone": "America/New_York"
}
```

To test immediately:

```bash
export PEACH_RUN_ON_START=true
peach start
```

## About Running While Your Machine Is Off

A local daemon cannot execute when the machine that hosts it is fully powered
off. To make Peach run while your laptop is off, install it on an always-on
host: a VPS, home server, cloud VM, or scheduled container. The same commands
work there:

```bash
pip install -r requirements-peach.txt
pip install -e .
PEACH_HOME=/opt/peach peach start
```

For a production always-on setup, run Peach under `systemd`, `launchd`, Docker,
or a cloud scheduler so the host restarts it automatically after reboots.
