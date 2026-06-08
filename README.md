# Peach

Peach is a pre-market intelligence agent. It runs as a terminal-activated
background daemon, gathers market data and headlines, generates a Markdown
briefing with OpenAI or Ollama, and emails the report before market open.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/SkittlesGod-cmd/Peach-Agent/main/install.sh | bash
```

Requires Python 3.9+ and git. Installs to `~/.local/share/peach-agent/` and
drops a `peach` command in `~/.local/bin/`.

## Configure

```bash
export SMTP_USERNAME="you@example.com"
export SMTP_PASSWORD="your-app-password"
export PEACH_EMAIL_FROM="you@example.com"
export PEACH_EMAIL_TO="you@example.com"
export PEACH_LLM_PROVIDER="openai"   # or "ollama"
export OPENAI_API_KEY="sk-..."
```

## Run

```bash
peach start
peach status
peach stop
```

Peach schedules its briefing at 9:00 AM America/New_York, Monday through Friday.
To run immediately: `PEACH_RUN_ON_START=true peach start`

## Manual Install (from source)

```bash
git clone https://github.com/SkittlesGod-cmd/Peach-Agent.git
cd Peach-Agent
python3 -m venv .venv-peach
source .venv-peach/bin/activate
pip install -r requirements-peach.txt
pip install .
cp peach_config.example.json peach_config.json
```

## Deployment Note

Vercel hosts this repository's project page, but Vercel does not run persistent
background daemons. To run Peach when your laptop is off, install it on an
always-on host such as a VPS, cloud VM, home server, or container.

See [PEACH.md](./PEACH.md) for the full configuration reference.
