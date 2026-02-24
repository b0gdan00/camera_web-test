#!/bin/bash
# ── PiCam Stream — start everything ──────────────
# Starts Flask app (with camera) + ngrok tunnel

set -e

echo "🎥 Starting PiCam Stream..."

# 1. Install Python deps if needed
if ! python3 -c "import flask" 2>/dev/null; then
    echo "📦 Installing Python dependencies..."
    pip3 install -r requirements.txt
fi

# 2. Start ngrok in Docker
echo "🌐 Starting ngrok tunnel..."
docker compose up -d

# 3. Start Flask app in background
echo "🚀 Starting camera server on port 5000..."
python3 app.py &
APP_PID=$!

# Wait for ngrok to be ready, then show URL
sleep 8
echo ""
echo "======================================================="
NGROK_URL=$(curl -s http://localhost:4040/api/tunnels | python3 -c "import sys,json; tunnels=json.load(sys.stdin).get('tunnels',[]); [print(t['public_url']) for t in tunnels if t.get('public_url','').startswith('https://')]" 2>/dev/null || echo "")
if [ -n "$NGROK_URL" ]; then
    echo "  🚀 SITE IS LIVE AT: $NGROK_URL"
else
    echo "  ⚠ Could not get ngrok URL. Check http://localhost:4040"
fi
echo "======================================================="
echo ""
echo "Press Ctrl+C to stop"

# Wait for app to finish (or Ctrl+C)
trap "echo '🛑 Stopping...'; kill $APP_PID 2>/dev/null; docker compose down; exit 0" SIGINT SIGTERM
wait $APP_PID
