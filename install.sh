#!/usr/bin/env bash
# Peach installer
# Usage: curl -fsSL https://raw.githubusercontent.com/SkittlesGod-cmd/Peach-Agent/main/install.sh | bash
set -euo pipefail

REPO="https://github.com/SkittlesGod-cmd/Peach-Agent.git"
INSTALL_DIR="${PEACH_INSTALL_DIR:-$HOME/.local/share/peach-agent}"
BIN_DIR="$HOME/.local/bin"
VENV="$INSTALL_DIR/.venv"

# ── Colour helpers ────────────────────────────────────────────────────────────
reset='\033[0m'
bold()  { printf '\033[1m%s'"$reset" "$1"; }
green() { printf '\033[1;92m%s'"$reset" "$1"; }
peach() { printf '\033[38;5;209m%s'"$reset" "$1"; }
dim()   { printf '\033[2m%s'"$reset" "$1"; }
die()   { printf '\033[1;91merror:\033[0m %s\n' "$1" >&2; exit 1; }
step()  { printf '\n  %s %s\n' "$(dim '→')" "$1"; }
ok()    { printf '  %s %s\n' "$(green '✓')" "$1"; }
skip()  { printf '  %s %s\n' "$(dim '–')" "$(dim "$1")"; }

printf '\n%s\n' "$(bold 'Peach')"
printf '%s\n\n' "$(dim 'Research Opportunity Hunter')"

# ── Requirements ──────────────────────────────────────────────────────────────
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
python3 -m venv "$VENV"
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

# ── Quick setup wizard ────────────────────────────────────────────────────────
# Reads from /dev/tty so prompts work even when this script is piped from curl.

_setup_name=""
_setup_grade=""
_setup_email=""
_setup_interests=""

if [ -e /dev/tty ]; then
    printf '\n'
    printf '  %s\n' "$(bold '─────────────────────────────────────────────')"
    printf '  %s   %s\n' "$(bold 'Student profile')" "$(dim 'press Enter to skip any question')"
    printf '  %s\n' "$(dim 'Peach uses this to personalize every outreach email')"
    printf '  %s\n' "$(bold '─────────────────────────────────────────────')"

    # ── Name ─────────────────────────────────────────────────────────────────
    printf '\n'
    printf '  Your name: '
    read -r _setup_name </dev/tty || true
    _setup_name="${_setup_name#"${_setup_name%%[![:space:]]*}"}"
    _setup_name="${_setup_name%"${_setup_name##*[![:space:]]}"}"

    # ── Grade ─────────────────────────────────────────────────────────────────
    printf '  Grade (e.g. 11th grade): '
    read -r _setup_grade </dev/tty || true
    _setup_grade="${_setup_grade#"${_setup_grade%%[![:space:]]*}"}"
    _setup_grade="${_setup_grade%"${_setup_grade##*[![:space:]]}"}"

    # ── Email ─────────────────────────────────────────────────────────────────
    printf '\n'
    printf '  %s  %s\n' "$(peach 'Your email')" "$(dim 'professors reply here')"
    printf '  Email address: '
    read -r _setup_email </dev/tty || true
    _setup_email="${_setup_email#"${_setup_email%%[![:space:]]*}"}"
    _setup_email="${_setup_email%"${_setup_email##*[![:space:]]}"}"

    # ── Interests ────────────────────────────────────────────────────────────
    printf '\n'
    printf '  %s  %s\n' "$(peach 'Research interests')" "$(dim 'optional')"
    printf '  %s\n' "$(dim 'e.g. neurosurgery, brain tumors, computational neuroscience')"
    printf '  Interests: '
    read -r _setup_interests </dev/tty || true
    _setup_interests="${_setup_interests#"${_setup_interests%%[![:space:]]*}"}"
    _setup_interests="${_setup_interests%"${_setup_interests##*[![:space:]]}"}"

    printf '\n'
    printf '  %s\n' "$(bold '─────────────────────────────────────────────')"

    # ── Write answers into peach_config.json ──────────────────────────────────
    if [ -n "$_setup_name" ] || [ -n "$_setup_email" ]; then
        _PEACH_NAME="$_setup_name" \
        _PEACH_GRADE="$_setup_grade" \
        _PEACH_EMAIL="$_setup_email" \
        _PEACH_INTERESTS="$_setup_interests" \
        "$VENV/bin/python3" - "$INSTALL_DIR/peach_config.json" <<'PYWRITE'
import sys, json, os

path = sys.argv[1]
with open(path) as f:
    cfg = json.load(f)

name      = os.environ.get("_PEACH_NAME",      "").strip()
grade     = os.environ.get("_PEACH_GRADE",     "").strip()
mail      = os.environ.get("_PEACH_EMAIL",     "").strip()
interests = os.environ.get("_PEACH_INTERESTS", "").strip()

profile = cfg.get("student_profile", {})
if name:      profile["name"]      = name
if grade:     profile["grade"]     = grade
if interests: profile["interests"] = interests
if mail:      profile["email"]     = mail

if profile:
    cfg["student_profile"] = profile

if mail:
    cfg["email_to"] = mail

with open(path, "w") as f:
    json.dump(cfg, f, indent=2)
    f.write("\n")
PYWRITE
    fi

    # ── Setup summary ─────────────────────────────────────────────────────────
    printf '\n'
    if [ -n "$_setup_name" ]; then
        ok "Student profile saved (name: $_setup_name)"
    else
        skip "Profile skipped — edit student_profile in peach_config.json"
    fi

    if [ -n "$_setup_email" ]; then
        ok "Email configured → $_setup_email"
    else
        skip "Email skipped — add email_to in peach_config.json"
    fi

else
    skip "Non-interactive install — edit student_profile in peach_config.json"
fi

# ── Done ─────────────────────────────────────────────────────────────────────
printf '\n%s\n\n' "$(green '✓ Peach installed')"

export PATH="$BIN_DIR:$PATH"

if ! command -v peach &>/dev/null 2>&1; then
    printf '  %s\n\n' "$(dim 'Add to your shell profile if peach is not found:')"
    printf '  %s\n\n' 'export PATH="$HOME/.local/bin:$PATH"'
fi

printf '  %s\n' "$(bold 'Start the agent and run your first hunt:')"
printf '  %s\n' "$(peach 'peach start')"
printf '  %s\n\n' "$(peach 'peach research hunt --batch 3')"

printf '  %s\n' "$(dim 'Full setup guide → https://peach-agent.vercel.app/install')"
printf '\n'
