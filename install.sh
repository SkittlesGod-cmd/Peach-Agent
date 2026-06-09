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
printf '%s\n\n' "$(dim 'Pre-market intelligence agent')"

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

# ── Quick setup wizard ────────────────────────────────────────────────────────
# Reads from /dev/tty so prompts work even when this script is piped from curl.

_setup_telegram=""
_setup_email=""
_setup_email_pw=""
_setup_email_to=""
_setup_tickers=""
_setup_alpaca_key=""
_setup_alpaca_secret=""

if [ -e /dev/tty ]; then
    printf '\n'
    printf '  %s\n' "$(bold '─────────────────────────────────────────────')"
    printf '  %s   %s\n' "$(bold 'Quick setup')" "$(dim 'press Enter to skip any question')"
    printf '  %s\n' "$(bold '─────────────────────────────────────────────')"

    # ── Telegram ──────────────────────────────────────────────────────────────
    printf '\n'
    printf '  %s  %s\n' "$(peach 'Telegram bot')" "$(dim 'recommended')"
    printf '  %s\n' "$(dim 'Message @BotFather on Telegram → /newbot → copy the token')"
    printf '  Token: '
    read -r _setup_telegram </dev/tty || true
    _setup_telegram="${_setup_telegram#"${_setup_telegram%%[![:space:]]*}"}"
    _setup_telegram="${_setup_telegram%"${_setup_telegram##*[![:space:]]}"}"

    # ── Email ─────────────────────────────────────────────────────────────────
    printf '\n'
    printf '  %s  %s\n' "$(peach 'Email delivery')" "$(dim 'optional')"
    printf '  Gmail address: '
    read -r _setup_email </dev/tty || true
    _setup_email="${_setup_email#"${_setup_email%%[![:space:]]*}"}"
    _setup_email="${_setup_email%"${_setup_email##*[![:space:]]}"}"

    if [ -n "$_setup_email" ]; then
        printf '  App password:  '
        # Disable echo for password input
        stty -echo 2>/dev/tty || true
        read -r _setup_email_pw </dev/tty || true
        stty echo 2>/dev/tty || true
        printf '\n'

        printf '  Send to        %s\n' "$(dim "[Enter = same as above]")"
        printf '  → '
        read -r _setup_email_to </dev/tty || true
        _setup_email_to="${_setup_email_to#"${_setup_email_to%%[![:space:]]*}"}"
        _setup_email_to="${_setup_email_to%"${_setup_email_to##*[![:space:]]}"}"
        [ -z "$_setup_email_to" ] && _setup_email_to="$_setup_email"
    fi

    # ── Tickers ───────────────────────────────────────────────────────────────
    printf '\n'
    printf '  %s  %s\n' "$(peach 'Watchlist')" "$(dim 'optional')"
    printf '  %s\n' "$(dim 'Default: SPY, QQQ, DIA, IWM, AAPL, MSFT, NVDA, TSLA')"
    printf '  Tickers (comma-separated): '
    read -r _setup_tickers </dev/tty || true
    _setup_tickers="${_setup_tickers#"${_setup_tickers%%[![:space:]]*}"}"
    _setup_tickers="${_setup_tickers%"${_setup_tickers##*[![:space:]]}"}"

    printf '\n'
    # ── Alpaca ────────────────────────────────────────────────────────────────
    printf '\n'
    printf '  %s  %s\n' "$(peach 'Alpaca brokerage')" "$(dim 'optional — defaults to paper trading')"
    printf '  %s\n' "$(dim 'alpaca.markets → Paper Trading → API Keys')"
    printf '  API key:    '
    read -r _setup_alpaca_key </dev/tty || true
    _setup_alpaca_key="${_setup_alpaca_key#"${_setup_alpaca_key%%[![:space:]]*}"}"
    _setup_alpaca_key="${_setup_alpaca_key%"${_setup_alpaca_key##*[![:space:]]}"}"

    if [ -n "$_setup_alpaca_key" ]; then
        printf '  API secret: '
        stty -echo 2>/dev/tty || true
        read -r _setup_alpaca_secret </dev/tty || true
        stty echo 2>/dev/tty || true
        printf '\n'
    fi

    printf '\n'
    printf '  %s\n' "$(bold '─────────────────────────────────────────────')"

    # ── Write answers into peach_config.json ──────────────────────────────────
    if [ -n "$_setup_telegram" ] || [ -n "$_setup_email" ] || [ -n "$_setup_tickers" ] || [ -n "$_setup_alpaca_key" ]; then
        _PEACH_TELEGRAM="$_setup_telegram" \
        _PEACH_EMAIL="$_setup_email" \
        _PEACH_EMAIL_PW="$_setup_email_pw" \
        _PEACH_EMAIL_TO="$_setup_email_to" \
        _PEACH_TICKERS="$_setup_tickers" \
        _PEACH_ALPACA_KEY="$_setup_alpaca_key" \
        _PEACH_ALPACA_SECRET="$_setup_alpaca_secret" \
        "$VENV/bin/python3" - "$INSTALL_DIR/peach_config.json" <<'PYWRITE'
import sys, json, os

path = sys.argv[1]
with open(path) as f:
    cfg = json.load(f)

tok            = os.environ.get("_PEACH_TELEGRAM",      "").strip()
mail           = os.environ.get("_PEACH_EMAIL",         "").strip()
pw             = os.environ.get("_PEACH_EMAIL_PW",      "").strip()
to             = os.environ.get("_PEACH_EMAIL_TO",      "").strip()
ticks          = os.environ.get("_PEACH_TICKERS",       "").strip()
alpaca_key     = os.environ.get("_PEACH_ALPACA_KEY",    "").strip()
alpaca_secret  = os.environ.get("_PEACH_ALPACA_SECRET", "").strip()

if tok:
    cfg["telegram_bot_token"] = tok

if mail:
    cfg["smtp_username"] = mail
    cfg["smtp_password"] = pw
    cfg["email_from"]    = mail
    cfg["email_to"]      = to or mail

if ticks:
    parsed = [t.strip().upper() for t in ticks.split(",") if t.strip()]
    if parsed:
        cfg["tickers"] = parsed

if alpaca_key and alpaca_secret:
    cfg["alpaca_api_key"]    = alpaca_key
    cfg["alpaca_secret_key"] = alpaca_secret
    cfg["alpaca_paper"]      = True  # paper by default — change to false for live

with open(path, "w") as f:
    json.dump(cfg, f, indent=2)
    f.write("\n")
PYWRITE
    fi

    # ── Setup summary ─────────────────────────────────────────────────────────
    printf '\n'
    if [ -n "$_setup_telegram" ]; then
        ok "Telegram bot configured"
    else
        skip "Telegram skipped — add later: telegram_bot_token in peach_config.json"
    fi

    if [ -n "$_setup_email" ]; then
        ok "Email delivery configured → $_setup_email_to"
    else
        skip "Email skipped — briefings saved to $INSTALL_DIR/briefing.md"
    fi

    if [ -n "$_setup_tickers" ]; then
        ok "Custom watchlist saved"
    else
        skip "Using default watchlist (SPY, QQQ, DIA, IWM, AAPL, MSFT, NVDA, TSLA)"
    fi

    if [ -n "$_setup_alpaca_key" ]; then
        ok "Alpaca brokerage connected (paper trading — set alpaca_paper: false in config for live)"
    else
        skip "Alpaca skipped — add alpaca_api_key / alpaca_secret_key to config later"
    fi

else
    skip "Non-interactive install — edit $INSTALL_DIR/peach_config.json to configure email and Telegram"
fi

# ── Done ─────────────────────────────────────────────────────────────────────
printf '\n%s\n\n' "$(green '✓ Peach installed')"

export PATH="$BIN_DIR:$PATH"

if ! command -v peach &>/dev/null 2>&1; then
    printf '  %s\n\n' "$(dim 'Add to your shell profile if peach is not found:')"
    printf '  %s\n\n' 'export PATH="$HOME/.local/bin:$PATH"'
fi

printf '  %s\n' "$(bold 'Start the agent:')"
printf '  %s\n\n' "$(peach 'peach start')"

if [ -z "$_setup_telegram" ] && [ -z "$_setup_email" ]; then
    printf '  %s\n' "$(dim 'Briefings land at:')"
    printf '  %s\n\n' "$(dim "$INSTALL_DIR/briefing.md")"
fi

printf '  %s\n' "$(dim 'Full setup guide → https://peach-agent.vercel.app/install')"
printf '\n'
