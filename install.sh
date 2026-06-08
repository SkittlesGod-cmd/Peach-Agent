#!/usr/bin/env bash
# Peach installer — zero configuration required
# Usage: curl -fsSL https://raw.githubusercontent.com/SkittlesGod-cmd/Peach-Agent/main/install.sh | bash
set -euo pipefail

REPO="https://github.com/SkittlesGod-cmd/Peach-Agent.git"
INSTALL_DIR="${PEACH_INSTALL_DIR:-$HOME/.local/share/peach-agent}"
BIN_DIR="$HOME/.local/bin"
VENV="$INSTALL_DIR/.venv"

# ── Helpers ──────────────────────────────────────────────────────────────────
bold()  { printf '\033[1m%s\033[0m' "$1"; }
green() { printf '\033[1;92m%s\033[0m' "$1"; }
dim()   { printf '\033[2m%s\033[0m' "$1"; }
die()   { printf '\033[1;91merror:\033[0m %s\n' "$1" >&2; exit 1; }
step()  { printf '\n  %s %s\n' "$(dim '→')" "$1"; }

printf '\n%s\n' "$(bold 'Peach')"
printf '%s\n\n' "$(dim 'Pre-market intelligence agent')"

# ── Requirements ─────────────────────────────────────────────────────────────
command -v python3 >/dev/null 2>&1 || die "python3 not found. Install Python 3.9+ from https://python.org"
command -v git     >/dev/null 2>&1 || die "git not found."

python3 - <<'PYCHECK'
import sys
if sys.version_info < (3, 9):
    print(f"Python 3.9+ required (found {sys.version})", file=sys.stderr)
    sys.exit(1)
PYCHECK

# ── Install ───────────────────────────────────────────────────────────────────
step "Downloading Peach..."
if [ -d "$INSTALL_DIR/.git" ]; then
    git -C "$INSTALL_DIR" pull --ff-only --quiet
else
    git clone --depth 1 --quiet "$REPO" "$INSTALL_DIR"
fi

step "Installing dependencies..."
python3 -m venv "$VENV" --quiet
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r "$INSTALL_DIR/requirements-peach.txt"
"$VENV/bin/pip" install -q "$INSTALL_DIR"

step "Writing config..."
if [ ! -f "$INSTALL_DIR/peach_config.json" ]; then
    cp "$INSTALL_DIR/peach_config.example.json" "$INSTALL_DIR/peach_config.json"
fi

step "Adding peach command..."
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/peach" <<WRAPPER
#!/usr/bin/env bash
export PEACH_HOME="${INSTALL_DIR}"
exec "${VENV}/bin/peach" "\$@"
WRAPPER
chmod +x "$BIN_DIR/peach"

# ── Done ─────────────────────────────────────────────────────────────────────
printf '\n%s\n\n' "$(green '✓ Peach installed')"

# Ensure ~/.local/bin is on PATH for this session
export PATH="$BIN_DIR:$PATH"

if [[ ":${PATH_BEFORE:-}:" != *":$BIN_DIR:"* ]] 2>/dev/null || ! command -v peach &>/dev/null; then
    printf '  %s\n\n' "$(dim "Add to your shell profile if peach isn't found:")"
    printf '  %s\n\n' 'export PATH="$HOME/.local/bin:$PATH"'
fi

printf '  %s\n' "$(bold 'Run the agent:')"
printf '  %s\n\n' 'peach start'

printf '  %s\n' "$(dim 'Briefings run at 09:00 ET Mon–Fri. No email? Find your briefing at:')"
printf '  %s\n\n' "$(dim "$INSTALL_DIR/briefing.md")"

printf '  %s\n' "$(dim 'To add email delivery, edit:')"
printf '  %s\n\n' "$(dim "$INSTALL_DIR/peach_config.json")"
