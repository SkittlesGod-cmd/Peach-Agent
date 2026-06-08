#!/usr/bin/env bash
# Peach Agent installer
# Usage: curl -fsSL https://raw.githubusercontent.com/SkittlesGod-cmd/Peach-Agent/main/install.sh | bash
set -euo pipefail

REPO="https://github.com/SkittlesGod-cmd/Peach-Agent.git"
INSTALL_DIR="${PEACH_INSTALL_DIR:-$HOME/.local/share/peach-agent}"
BIN_DIR="$HOME/.local/bin"
VENV="$INSTALL_DIR/.venv"

bold()    { printf '\033[1m%s\033[0m' "$1"; }
cyan()    { printf '\033[1;96m%s\033[0m' "$1"; }
green()   { printf '\033[1;92m%s\033[0m' "$1"; }
red()     { printf '\033[1;91m%s\033[0m' "$1"; }
step()    { printf '\n%s %s\n' "$(cyan '==>')" "$(bold "$1")"; }
success() { printf '%s %s\n' "$(green '✓')" "$1"; }
die()     { printf '\n%s %s\n\n' "$(red 'error:')" "$1" >&2; exit 1; }

echo
printf '%s\n' "$(bold 'Peach Installer')"
printf '%s\n' "Pre-market intelligence agent"
echo

# ── Requirements ────────────────────────────────────────────────────────────

step "Checking requirements..."

command -v python3 >/dev/null 2>&1 || die "python3 not found. Install Python 3.9+ from https://python.org"
command -v git >/dev/null 2>&1    || die "git not found. Install git and re-run."

python3 - <<'PYCHECK'
import sys
if sys.version_info < (3, 9):
    print(f"Python 3.9+ required (found {sys.version})", file=sys.stderr)
    sys.exit(1)
PYCHECK
success "Python $(python3 --version | cut -d' ' -f2) and git found."

# ── Clone / update ───────────────────────────────────────────────────────────

step "Installing to $INSTALL_DIR..."

if [ -d "$INSTALL_DIR/.git" ]; then
    git -C "$INSTALL_DIR" pull --ff-only --quiet
    success "Repository updated."
else
    git clone --depth 1 --quiet "$REPO" "$INSTALL_DIR"
    success "Repository cloned."
fi

# ── Virtual environment ──────────────────────────────────────────────────────

step "Creating virtual environment..."

python3 -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r "$INSTALL_DIR/requirements-peach.txt"
"$VENV/bin/pip" install -q "$INSTALL_DIR"
success "Dependencies installed."

# ── Config ───────────────────────────────────────────────────────────────────

if [ ! -f "$INSTALL_DIR/peach_config.json" ]; then
    cp "$INSTALL_DIR/peach_config.example.json" "$INSTALL_DIR/peach_config.json"
    success "Created peach_config.json (edit it to set tickers, schedule, provider)."
else
    success "peach_config.json already exists — skipped."
fi

# ── Wrapper binary ───────────────────────────────────────────────────────────

step "Installing peach command to $BIN_DIR..."

mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/peach" <<WRAPPER
#!/usr/bin/env bash
export PEACH_HOME="${INSTALL_DIR}"
exec "${VENV}/bin/peach" "\$@"
WRAPPER
chmod +x "$BIN_DIR/peach"
success "peach command installed."

# ── Done ─────────────────────────────────────────────────────────────────────

echo
printf '%s\n' "$(green '✓  Peach installed!')"
echo
printf '  %-12s %s\n' "Config:"  "$INSTALL_DIR/peach_config.json"
printf '  %-12s %s\n' "Logs:"    "$INSTALL_DIR/peach.log"
printf '  %-12s %s\n' "Command:" "$BIN_DIR/peach"
echo

if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    printf '%s\n' "$(bold 'Add ~/.local/bin to your PATH (add to ~/.bashrc or ~/.zshrc):')"
    printf '  %s\n' 'export PATH="$HOME/.local/bin:$PATH"'
    echo
fi

printf '%s\n' "$(bold 'Set required credentials (or add them to peach_config.json):')"
cat <<'ENV'
  export SMTP_USERNAME="you@example.com"
  export SMTP_PASSWORD="your-app-password"
  export PEACH_EMAIL_FROM="you@example.com"
  export PEACH_EMAIL_TO="you@example.com"

  # Choose one LLM provider:
  export PEACH_LLM_PROVIDER="openai"
  export OPENAI_API_KEY="sk-..."

  # — or —
  export PEACH_LLM_PROVIDER="ollama"
  export OLLAMA_URL="http://127.0.0.1:11434"
ENV
echo
printf '%s\n' "$(bold 'Then start the agent:')"
printf '  %s\n' "peach start"
printf '  %s\n' "peach status"
printf '  %s\n' "peach stop"
echo
printf '%s\n' "Peach runs at 09:00 ET Monday–Friday. Test immediately:"
printf '  %s\n' "PEACH_RUN_ON_START=true peach start"
echo
