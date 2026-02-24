# ── Stage: PiCam Stream ──────────────────────────
FROM python:3.11-slim-bookworm

# System deps for OpenCV headless + camera access
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxrender1 \
        libxext6 \
        v4l-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt psutil

# Copy application code
COPY . .

EXPOSE 5000

CMD ["python", "app.py"]
