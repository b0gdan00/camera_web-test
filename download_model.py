#!/usr/bin/env python3
"""
Download YOLOv4-tiny model files for object detection.

Downloads:
  - yolov4-tiny.cfg      (network config)
  - yolov4-tiny.weights   (pre-trained on COCO, ~23 MB)
  - coco.names            (80 class labels)

Usage:
    python download_model.py
"""

import os
import sys
import urllib.request
import hashlib

MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")

FILES = [
    {
        "name": "yolov4-tiny.weights",
        "url": "https://github.com/AlexeyAB/darknet/releases/download/yolov4/yolov4-tiny.weights",
        "size_mb": 23.1,
        "md5": "55c7fadc6b25a2f4a1642d1af29d0757",
    },
    {
        "name": "yolov4-tiny.cfg",
        "url": "https://raw.githubusercontent.com/AlexeyAB/darknet/master/cfg/yolov4-tiny.cfg",
        "size_mb": 0.003,
    },
    {
        "name": "coco.names",
        "url": "https://raw.githubusercontent.com/AlexeyAB/darknet/master/data/coco.names",
        "size_mb": 0.001,
    },
]


def _progress(block_num, block_size, total_size):
    downloaded = block_num * block_size
    if total_size > 0:
        pct = min(100, downloaded * 100 // total_size)
        mb = downloaded / (1024 * 1024)
        total_mb = total_size / (1024 * 1024)
        sys.stdout.write(f"\r    [{pct:3d}%] {mb:.1f} / {total_mb:.1f} MB")
    else:
        mb = downloaded / (1024 * 1024)
        sys.stdout.write(f"\r    {mb:.1f} MB downloaded")
    sys.stdout.flush()


def download_models(force: bool = False):
    """Download all model files."""
    os.makedirs(MODEL_DIR, exist_ok=True)

    print(f"\n  Model directory: {MODEL_DIR}\n")

    for f in FILES:
        path = os.path.join(MODEL_DIR, f["name"])

        if os.path.exists(path) and not force:
            size_mb = os.path.getsize(path) / (1024 * 1024)
            print(f"  [OK] {f['name']} ({size_mb:.1f} MB) -- already exists")
            continue

        print(f"  Downloading {f['name']} ({f['size_mb']:.1f} MB)...")
        try:
            urllib.request.urlretrieve(f["url"], path, reporthook=_progress)
            print()  # newline after progress
            size_mb = os.path.getsize(path) / (1024 * 1024)
            print(f"  [OK] {f['name']} ({size_mb:.1f} MB)")
        except Exception as e:
            print(f"\n  [FAIL] Could not download {f['name']}: {e}")
            if os.path.exists(path):
                os.remove(path)
            return False

    print(f"\n  All model files ready in: {MODEL_DIR}\n")
    return True


if __name__ == "__main__":
    print("\n  ==============================")
    print("  YOLOv4-tiny Model Downloader")
    print("  ==============================")

    force = "--force" in sys.argv
    ok = download_models(force=force)
    sys.exit(0 if ok else 1)
