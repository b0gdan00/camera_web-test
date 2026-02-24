#!/bin/bash
# ── PiCam Stream — startup script ────────────────
# Called by systemd on boot. Updates code, then starts everything.

set -e

PROJECT_DIR="/home/rp/camera_web-test-1"
VENV_DIR="$PROJECT_DIR/venv"
LOG_TAG="picam-startup"

log() {
    echo "[$(date '+%H:%M:%S')] $1"
    logger -t "$LOG_TAG" "$1"
}

cd "$PROJECT_DIR"

# ── 1. Wait for network ──────────────────────────
log "Waiting for network..."
for i in $(seq 1 30); do
    if ping -c1 -W2 github.com &>/dev/null; then
        log "Network is up"
        break
    fi
    sleep 2
done

# ── 2. Git pull ──────────────────────────────────
log "Pulling latest code from git..."
if git pull --ff-only 2>&1; then
    log "Git pull successful"
else
    log "Git pull failed (continuing with current version)"
fi

# ── 3. Install/update Python deps ────────────────
if [ ! -d "$VENV_DIR" ]; then
    log "Creating venv..."
    python3 -m venv --system-site-packages "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"
log "Installing Python dependencies..."
pip install --quiet -r requirements.txt 2>&1 || log "pip install had warnings"

# ── 4. Start ngrok via Docker ────────────────────
log "Starting ngrok tunnel..."
docker compose up -d 2>&1 || log "Docker compose failed"

# ── 5. Start Flask app ───────────────────────────
log "Starting PiCam Stream server..."
exec python3 app.py
