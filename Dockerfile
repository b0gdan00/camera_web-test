# ── PiCam Stream for Raspberry Pi (ARM64) ────────
FROM python:3.11-slim-bookworm

# System deps for OpenCV + build tools for ARM
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    pkg-config \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6 \
    libjpeg-dev \
    libpng-dev \
    libtiff-dev \
    libavcodec-dev \
    libavformat-dev \
    libswscale-dev \
    libv4l-dev \
    v4l-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps (split to isolate failures)
COPY requirements.txt .

# Install everything except picamera2 first
RUN pip install --no-cache-dir \
    flask>=3.0 \
    opencv-python-headless \
    numpy \
    psutil

# Try picamera2 separately (may fail on non-Pi, that's OK)
RUN pip install --no-cache-dir picamera2 2>/dev/null || \
    echo "⚠ picamera2 skipped (not on Pi or missing deps — using OpenCV fallback)"

# Copy application code
COPY . .

EXPOSE 5000

CMD ["python", "app.py"]
