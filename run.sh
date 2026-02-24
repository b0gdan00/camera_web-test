#!/usr/bin/env bash
# Quick start script for Raspberry Pi
# Usage: bash run.sh
#
# Starts Flask server + Cloudflare Tunnel for public access.
# The tunnel URL will be printed to the console.

set -e

# ── Cleanup on exit ──────────────────────────────
cleanup() {
    echo ""
    echo "🛑 Shutting down..."
    # Kill background processes
    if [ -n "$FLASK_PID" ]; then kill $FLASK_PID 2>/dev/null; fi
    if [ -n "$TUNNEL_PID" ]; then kill $TUNNEL_PID 2>/dev/null; fi
    wait 2>/dev/null
    echo "✅ Done."
}
trap cleanup EXIT INT TERM

# ── Virtual environment ──────────────────────────
if [ ! -d "venv" ]; then
    echo "🔧 Creating virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate

echo "📦 Installing dependencies..."
pip install -q -r requirements.txt

# ── Make cloudflared executable ──────────────────
if [ -f "./cloudflared" ]; then
    chmod +x ./cloudflared
fi

# ── Start Flask ──────────────────────────────────
LOCAL_URL="http://localhost:5000"

echo ""
echo "🎥 Starting PiCam Stream server..."
echo "   Local:  $LOCAL_URL"
echo ""

python app.py &
FLASK_PID=$!

# Wait for Flask to start
sleep 2

# ── Start Cloudflare Tunnel ──────────────────────
if [ -f "./cloudflared" ]; then
    echo "🌐 Starting Cloudflare Tunnel..."
    echo "   Waiting for public URL..."
    echo ""

    # Start tunnel and capture the URL from stderr
    ./cloudflared tunnel --url $LOCAL_URL 2>&1 | while IFS= read -r line; do
        # Look for the tunnel URL in the output
        if echo "$line" | grep -qo 'https://.*trycloudflare.com'; then
            URL=$(echo "$line" | grep -o 'https://.*trycloudflare.com')
            echo "════════════════════════════════════════════"
            echo "🔗 PUBLIC URL: $URL"
            echo "════════════════════════════════════════════"
            echo ""
        fi
    done &
    TUNNEL_PID=$!
else
    echo "⚠️  cloudflared not found — running locally only"
    echo "   Download: https://github.com/cloudflare/cloudflared/releases"
fi

# Wait for Flask process
wait $FLASK_PID
