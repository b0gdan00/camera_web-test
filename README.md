# 🎥 PiCam Stream

Live camera stream from Raspberry Pi with a web-based control panel.

![Python](https://img.shields.io/badge/Python-3.9+-blue?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.0-green?logo=flask)
![OpenCV](https://img.shields.io/badge/OpenCV-4.8-orange?logo=opencv)
![License](https://img.shields.io/badge/License-MIT-yellow)

## Features

- **Live MJPEG stream** — real-time video in any browser
- **Camera controls** — adjustable JPEG quality, FPS, and image rotation
- **Object detection** — YOLOv4-tiny via OpenCV DNN (80 COCO classes)
- **Face & hand detection** — Haar cascade + skin-color segmentation
- **System monitoring** — CPU, RAM, disk, temperature, uptime
- **Server logs** — live log viewer in the browser
- **Viewer tracking** — see who's watching the stream
- **Snapshot** — download a single frame as JPEG
- **Auto-start** — systemd service with automatic `git pull` on boot

## Project Structure

```
picam-stream/
├── app.py                  # Flask server (routes, API, logs, viewers)
├── camera.py               # Camera abstraction (picamera2 / OpenCV)
├── object_detector.py      # YOLOv4-tiny detection module
├── detectors.py            # Face & hand detectors (pure OpenCV)
├── requirements.txt        # Python dependencies
├── start.sh                # Boot startup script
├── picam-stream.service    # systemd unit file
├── static/
│   ├── css/style.css       # UI styles (dark theme, glassmorphism)
│   └── js/app.js           # Frontend logic
├── templates/
│   ├── base.html           # HTML skeleton
│   ├── index.html          # Main page (assembles components)
│   └── components/
│       ├── header.html     # Header bar with logo, viewers, status
│       ├── video.html      # Video player and action buttons
│       ├── sidebar.html    # Camera settings, rotation, detection
│       ├── login.html      # Name entry overlay
│       ├── logs.html       # Server log panel
│       └── stats.html      # System stats panel
└── models/                 # YOLOv4-tiny weights (auto-downloaded)
    ├── yolov4-tiny.cfg
    ├── yolov4-tiny.weights
    └── coco.names
```

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/your-user/camera_web-test.git
cd camera_web-test
```

### 2. Create a virtual environment

> **Important:** Use `--system-site-packages` so Python can access `libcamera` (required by `picamera2`).

```bash
python3 -m venv --system-site-packages venv
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Run

```bash
python3 app.py
```

Open **http://\<raspberry-pi-ip\>:5000** in your browser.

## Auto-Start on Boot

### Install the systemd service

```bash
chmod +x start.sh
sudo cp picam-stream.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable picam-stream.service
sudo systemctl start picam-stream.service
```

### What happens on boot

1. ⏳ Waits for network connectivity
2. 📥 Runs `git pull` to fetch the latest code
3. 📦 Installs/updates Python dependencies
4. 🎥 Starts the Flask server on port 5000

### Useful commands

| Command                               | Description          |
| ------------------------------------- | -------------------- |
| `sudo systemctl status picam-stream`  | Check service status |
| `sudo journalctl -u picam-stream -f`  | View live logs       |
| `sudo systemctl restart picam-stream` | Restart the service  |
| `sudo systemctl stop picam-stream`    | Stop the service     |
| `sudo systemctl disable picam-stream` | Disable auto-start   |

## API Endpoints

| Method     | Endpoint          | Description                              |
| ---------- | ----------------- | ---------------------------------------- |
| `GET`      | `/`               | Web interface                            |
| `GET`      | `/video_feed`     | MJPEG video stream                       |
| `GET`      | `/snapshot`       | Download a single JPEG frame             |
| `GET/POST` | `/api/settings`   | Camera settings (quality, fps, rotation) |
| `GET/POST` | `/api/detection`  | Object detection settings                |
| `GET`      | `/api/stats`      | System resource usage                    |
| `GET`      | `/api/logs?n=200` | Server log lines                         |
| `GET`      | `/api/viewers`    | Current viewers                          |
| `POST`     | `/api/join`       | Join as viewer `{name: "..."}`           |
| `POST`     | `/api/heartbeat`  | Keep viewer alive `{name: "..."}`        |
| `POST`     | `/api/leave`      | Leave stream `{name: "..."}`             |

## Requirements

- **Hardware:** Raspberry Pi 4 (or newer) with CSI camera
- **OS:** Raspberry Pi OS (64-bit recommended)
- **Python:** 3.9+
- **System packages:** `libcamera` (usually pre-installed)

## Tech Stack

- **Backend:** Python, Flask, OpenCV, picamera2
- **Frontend:** HTML5, CSS3, vanilla JavaScript
- **Templating:** Jinja2
- **Detection:** YOLOv4-tiny, Haar cascades
