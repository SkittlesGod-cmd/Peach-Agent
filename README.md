# Peach Agent

Peach is a local AI pre-market briefing agent. It runs as a terminal-activated
background daemon, gathers market data and headlines, generates a Markdown
briefing with OpenAI or Ollama, and emails the report before market open.

## Local Install

```bash
python3 -m venv .venv-peach
source .venv-peach/bin/activate
pip install -r requirements-peach.txt
pip install .
cp peach_config.example.json peach_config.json
```

## Run

```bash
peach start
peach status
peach stop
```

Peach schedules its briefing at 9:00 AM America/New_York, Monday through Friday.

## Important Deployment Note

Vercel can host this repository's project page, but Vercel does not run
persistent 24/7 background daemons. To run Peach while your laptop is off,
install it on an always-on host such as a VPS, cloud VM, home server, or
container host.

See [PEACH.md](./PEACH.md) for full configuration.
