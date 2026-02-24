# ── PiCam Stream for Raspberry Pi (ARM64) ────────
FROM python:3.11-slim-bookworm

# System deps for OpenCV (minimal set for headless)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6 \
    libjpeg62-turbo \
    libpng16-16 \
    libtiff6 \
    libv4l-dev \
    v4l-utils \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Try picamera2 separately (may fail on non-Pi, that's OK)
RUN pip install --no-cache-dir picamera2 2>/dev/null || \
    echo "picamera2 skipped (not on Pi or missing deps — using OpenCV fallback)"

# Copy application code
COPY . .

EXPOSE 5000

CMD ["python", "app.py"]
