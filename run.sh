#!/usr/bin/env bash
# Quick start script for Raspberry Pi
# Usage: bash run.sh

set -e

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "🔧 Creating virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate

echo "📦 Installing dependencies..."
pip install -r requirements.txt

echo ""
echo "🎥 Starting PiCam Stream server..."
echo "   Open http://$(hostname -I | awk '{print $1}'):5000 in your browser"
echo ""

python app.py
