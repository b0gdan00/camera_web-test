#!/usr/bin/env python3
"""
Camera connection checker — diagnostics tool.

Performs a comprehensive check of camera availability:
  1. Detects connected camera devices (USB, built-in, CSI)
  2. Tries to open each camera and capture a test frame
  3. Reports resolution, FPS, codec, and backend info
  4. On Raspberry Pi, also checks Picamera2

Usage:
    python check_camera.py               # Full check
    python check_camera.py --index 0     # Check specific camera index
    python check_camera.py --snapshot    # Save a test snapshot to disk
    python check_camera.py --json        # Output results as JSON
"""

import sys
import os
import platform
import subprocess
import time
import json as json_module
import argparse
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("check_camera")

# -- Colors --
RESET  = "\033[0m"
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"

# -- Safe print helper (handles encoding issues) --
def _safe_print(*args, **kwargs):
    """Print with fallback for terminals that don't support unicode."""
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        text = " ".join(str(a) for a in args)
        text = text.encode("ascii", errors="replace").decode("ascii")
        print(text, **{k: v for k, v in kwargs.items() if k != 'end'})

# -- Helper functions --

def _header(title: str):
    _safe_print(f"\n{BOLD}{CYAN}{'-' * 55}{RESET}")
    _safe_print(f"{BOLD}{CYAN}  {title}{RESET}")
    _safe_print(f"{BOLD}{CYAN}{'-' * 55}{RESET}\n")


def _ok(msg: str):
    _safe_print(f"  {GREEN}[OK] {msg}{RESET}")


def _warn(msg: str):
    _safe_print(f"  {YELLOW}[!] {msg}{RESET}")


def _fail(msg: str):
    _safe_print(f"  {RED}[FAIL] {msg}{RESET}")


def _info(msg: str):
    _safe_print(f"  {CYAN}[i] {msg}{RESET}")


def _detail(key: str, value):
    _safe_print(f"     {DIM}{key}:{RESET} {value}")


# ══════════════════════════════════════════════════════════════════════
#  SYSTEM INFO
# ══════════════════════════════════════════════════════════════════════

def check_system_info() -> dict:
    """Collect system information."""
    info = {
        "platform": platform.system(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "node": platform.node(),
    }

    _header("System info")
    _detail("OS", f"{info['platform']} ({info['machine']})")
    _detail("Python", info["python"])
    _detail("Host", info["node"])

    # Check OpenCV
    try:
        import cv2
        info["opencv_version"] = cv2.__version__
        info["opencv_backends"] = []

        # List available backends
        backends = [
            (cv2.CAP_DSHOW, "DirectShow"),
            (cv2.CAP_MSMF, "Media Foundation"),
            (cv2.CAP_V4L2, "V4L2"),
            (cv2.CAP_GSTREAMER, "GStreamer"),
            (cv2.CAP_FFMPEG, "FFmpeg"),
        ]

        available = []
        for backend_id, name in backends:
            try:
                cap = cv2.VideoCapture(0, backend_id)
                if cap is not None:
                    available.append(name)
                    cap.release()
            except Exception:
                pass

        info["opencv_backends"] = available
        _ok(f"OpenCV {cv2.__version__} installed")
        if available:
            _detail("Available backends", ", ".join(available))
    except ImportError:
        info["opencv_version"] = None
        _fail("OpenCV NOT installed -- pip install opencv-python-headless")

    # Check Picamera2 (RPi)
    if info["machine"] in ("aarch64", "armv7l"):
        try:
            from picamera2 import Picamera2
            info["picamera2"] = True
            _ok("Picamera2 available")
        except ImportError:
            info["picamera2"] = False
            _warn("Picamera2 not installed (needed for CSI camera on RPi)")
    else:
        info["picamera2"] = False

    return info


# ══════════════════════════════════════════════════════════════════════
#  DEVICE DETECTION
# ══════════════════════════════════════════════════════════════════════

def detect_camera_devices() -> list[dict]:
    """Detect camera devices on the system."""
    _header("Device detection")
    devices = []

    system = platform.system()

    if system == "Windows":
        devices = _detect_devices_windows()
    elif system == "Linux":
        devices = _detect_devices_linux()
    else:
        _warn(f"Auto-detection for '{system}' is limited")

    if devices:
        _ok(f"Devices found: {len(devices)}")
        for i, dev in enumerate(devices):
            _safe_print(f"\n  {BOLD}Camera #{i + 1}:{RESET}")
            _detail("Name", dev.get("name", "Unknown"))
            _detail("ID", dev.get("device_id", "-"))
            if dev.get("status"):
                _detail("Status", dev["status"])
            if dev.get("manufacturer"):
                _detail("Manufacturer", dev["manufacturer"])
    else:
        _warn("No cameras found via system API")
        _info("This does not necessarily mean no camera -- will check via OpenCV")

    return devices


def _detect_devices_windows() -> list[dict]:
    """Detect cameras on Windows using PowerShell/WMI."""
    devices = []
    try:
        ps_script = r"""
        $cameras = @()
        
        # Method 1: PnP devices with Camera class
        Get-PnpDevice -Class 'Camera','Image' -ErrorAction SilentlyContinue |
            ForEach-Object {
                $cameras += [PSCustomObject]@{
                    Name = $_.FriendlyName
                    DeviceId = $_.InstanceId
                    Status = $_.Status
                    Class = $_.Class
                    Manufacturer = $_.Manufacturer
                }
            }
        
        # Method 2: WMI Win32_PnPEntity for imaging devices
        Get-WmiObject Win32_PnPEntity -ErrorAction SilentlyContinue |
            Where-Object { $_.Caption -match 'camera|webcam|video|imaging' -and $_.Caption -notmatch 'audio' } |
            ForEach-Object {
                $existing = $cameras | Where-Object { $_.DeviceId -eq $_.DeviceID }
                if (-not $existing) {
                    $cameras += [PSCustomObject]@{
                        Name = $_.Caption
                        DeviceId = $_.DeviceID
                        Status = $_.Status
                        Class = $_.PNPClass
                        Manufacturer = $_.Manufacturer
                    }
                }
            }
        
        $cameras | ConvertTo-Json -Compress
        """
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True, text=True, timeout=15,
        )
        output = result.stdout.strip()
        if output and output.startswith(("[", "{")):
            items = json_module.loads(output)
            if isinstance(items, dict):
                items = [items]
            for item in items:
                devices.append({
                    "name": item.get("Name", "Unknown"),
                    "device_id": item.get("DeviceId", ""),
                    "status": item.get("Status", ""),
                    "manufacturer": item.get("Manufacturer", ""),
                    "class": item.get("Class", ""),
                })
    except Exception as e:
        log.debug("Windows device detection error: %s", e)

    return devices


def _detect_devices_linux() -> list[dict]:
    """Detect cameras on Linux via /dev/video* and v4l2-ctl."""
    import glob
    devices = []

    video_devs = sorted(glob.glob("/dev/video*"))
    for dev_path in video_devs:
        dev_info = {"name": dev_path, "device_id": dev_path}

        # Try v4l2-ctl for details
        try:
            result = subprocess.run(
                ["v4l2-ctl", "--device", dev_path, "--info"],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.splitlines():
                if "Card type" in line:
                    dev_info["name"] = line.split(":", 1)[1].strip()
                elif "Driver name" in line:
                    dev_info["driver"] = line.split(":", 1)[1].strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        dev_info["status"] = "Found"
        devices.append(dev_info)

    # Check for Raspberry Pi CSI camera
    try:
        result = subprocess.run(
            ["vcgencmd", "get_camera"],
            capture_output=True, text=True, timeout=5,
        )
        if "detected=1" in result.stdout:
            devices.append({
                "name": "Raspberry Pi CSI Camera",
                "device_id": "CSI",
                "status": "Detected",
            })
    except FileNotFoundError:
        pass

    return devices


# ══════════════════════════════════════════════════════════════════════
#  OPENCV CAMERA TEST
# ══════════════════════════════════════════════════════════════════════

def test_opencv_cameras(specific_index: int | None = None,
                        save_snapshot: bool = False) -> list[dict]:
    """Try to open cameras via OpenCV and capture test frames."""
    _header("OpenCV camera test")

    try:
        import cv2
    except ImportError:
        _fail("OpenCV not installed -- cannot test")
        return []

    results = []
    indices = [specific_index] if specific_index is not None else range(5)

    for idx in indices:
        _safe_print(f"  {BOLD}Checking camera index {idx}...{RESET}")

        cam_result = {
            "index": idx,
            "opened": False,
            "frame_captured": False,
            "width": 0,
            "height": 0,
            "fps": 0,
            "backend": "",
        }

        try:
            cap = cv2.VideoCapture(idx)

            if not cap.isOpened():
                _fail(f"Index {idx}: could not open")
                results.append(cam_result)
                continue

            cam_result["opened"] = True
            cam_result["backend"] = cap.getBackendName() if hasattr(cap, 'getBackendName') else "unknown"
            _ok(f"Index {idx}: camera opened (backend: {cam_result['backend']})")

            # Read properties
            cam_result["width"] = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            cam_result["height"] = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cam_result["fps"] = round(cap.get(cv2.CAP_PROP_FPS), 1)

            _detail("Resolution", f"{cam_result['width']}x{cam_result['height']}")
            _detail("FPS (reported)", cam_result["fps"])

            # Try to capture a frame
            ok, frame = cap.read()
            if ok and frame is not None:
                cam_result["frame_captured"] = True
                cam_result["actual_shape"] = list(frame.shape)
                _ok(f"Frame captured! (shape: {frame.shape})")

                # Measure actual FPS
                t0 = time.monotonic()
                frame_count = 0
                while time.monotonic() - t0 < 2.0:
                    ret, _ = cap.read()
                    if ret:
                        frame_count += 1
                elapsed = time.monotonic() - t0
                actual_fps = round(frame_count / elapsed, 1) if elapsed > 0 else 0
                cam_result["actual_fps"] = actual_fps
                _detail("FPS (actual, ~2s test)", actual_fps)

                # Save snapshot if requested
                if save_snapshot:
                    snap_path = os.path.join(
                        os.path.dirname(os.path.abspath(__file__)),
                        f"camera_test_snapshot_{idx}.jpg"
                    )
                    cv2.imwrite(snap_path, frame)
                    _ok(f"Snapshot saved: {snap_path}")
                    cam_result["snapshot_path"] = snap_path
            else:
                _fail("Camera opened but frame NOT captured")

            cap.release()

        except Exception as e:
            _fail(f"Error testing index {idx}: {e}")
            cam_result["error"] = str(e)

        results.append(cam_result)
        print()

    return results


# ══════════════════════════════════════════════════════════════════════
#  PICAMERA2 TEST (Raspberry Pi)
# ══════════════════════════════════════════════════════════════════════

def test_picamera2() -> dict | None:
    """Test Picamera2 on Raspberry Pi."""
    if platform.machine() not in ("aarch64", "armv7l"):
        return None

    _header("Picamera2 test (Raspberry Pi)")

    try:
        from picamera2 import Picamera2
    except ImportError:
        _warn("Picamera2 not installed -- skipping")
        return None

    result = {
        "available": False,
        "cameras": [],
    }

    try:
        picam = Picamera2()
        cam_info = picam.global_camera_info()
        result["cameras"] = cam_info
        result["available"] = len(cam_info) > 0

        if cam_info:
            _ok(f"Picamera2: found {len(cam_info)} camera(s)")
            for i, cam in enumerate(cam_info):
                _safe_print(f"\n  {BOLD}CSI camera #{i}:{RESET}")
                for k, v in cam.items():
                    _detail(k, v)

            # Try to capture
            config = picam.create_still_configuration()
            picam.configure(config)
            picam.start()
            time.sleep(1)
            frame = picam.capture_array()
            picam.stop()

            if frame is not None:
                _ok(f"Frame captured via Picamera2 (shape: {frame.shape})")
                result["frame_captured"] = True
            else:
                _fail("Picamera2 could not capture frame")
                result["frame_captured"] = False
        else:
            _fail("Picamera2: no cameras found")

        picam.close()
    except Exception as e:
        _fail(f"Picamera2 error: {e}")
        result["error"] = str(e)

    return result


# ══════════════════════════════════════════════════════════════════════
#  PROCESS CHECK
# ══════════════════════════════════════════════════════════════════════

def check_camera_in_use() -> list[dict]:
    """Check if camera is currently being used by other processes."""
    _header("Camera lock check")

    # Import our kill script to reuse the detection logic
    try:
        from kill_camera_processes import find_camera_processes
        procs = find_camera_processes()
        if procs:
            _warn(f"Camera may be blocked by {len(procs)} process(es):")
            for p in procs:
                _detail(f"PID {p['pid']}", f"{p['name']} ({p['method']})")
            _info("Run: python kill_camera_processes.py")
        else:
            _ok("Camera is not blocked by other processes")
        return procs
    except ImportError:
        _warn("Module kill_camera_processes not found -- skipping lock check")
        return []


# ══════════════════════════════════════════════════════════════════════
#  SUMMARY
# ══════════════════════════════════════════════════════════════════════

def print_summary(sys_info: dict, devices: list, opencv_results: list,
                  blocking_procs: list, picam_result: dict | None):
    """Print a final summary."""
    _header("Summary report")

    working_cameras = [r for r in opencv_results if r.get("frame_captured")]
    openable_cameras = [r for r in opencv_results if r.get("opened")]

    if working_cameras:
        best = max(working_cameras, key=lambda r: r.get("actual_fps", 0))
        _safe_print(f"  {GREEN}{BOLD}[OK] CAMERA IS WORKING!{RESET}")
        _safe_print()
        _detail("Best index", best["index"])
        _detail("Resolution", f"{best['width']}x{best['height']}")
        _detail("FPS", best.get("actual_fps", "?"))
        _detail("Backend", best.get("backend", "?"))
        _safe_print()
        _info(f"Use index {best['index']} in camera.py (CAMERA_SRC = {best['index']})")
    elif openable_cameras:
        _safe_print(f"  {YELLOW}{BOLD}[!] Camera opens but frames NOT captured{RESET}")
        _safe_print()
        _info("Possible reasons:")
        _info("  - Camera is used by another process")
        _info("  - Camera driver is malfunctioning")
        _info("  - Try: python kill_camera_processes.py")
    else:
        _safe_print(f"  {RED}{BOLD}[FAIL] CAMERA NOT FOUND / NOT WORKING{RESET}")
        _safe_print()
        _info("Recommendations:")
        _info("  1. Check physical camera connection (USB cable)")
        _info("  2. Check if camera is enabled in OS privacy settings")
        _info("  3. Update camera drivers")
        _info("  4. On Windows: Settings -> Privacy -> Camera -> Enable")
        _info("  5. Try a different USB port")
        if blocking_procs:
            _info(f"  6. Kill blocking processes: python kill_camera_processes.py")

    if picam_result and picam_result.get("available"):
        _safe_print()
        _ok("Picamera2 (Raspberry Pi CSI) is also available")

    _safe_print()


# ══════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Camera connection checker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python check_camera.py                # Full check
  python check_camera.py --index 0      # Only index 0
  python check_camera.py --snapshot     # Save test snapshot
  python check_camera.py --json         # Output as JSON
        """,
    )
    parser.add_argument("--index", "-i", type=int, default=None,
                        help="Check specific camera index")
    parser.add_argument("--snapshot", "-s", action="store_true",
                        help="Save test snapshot")
    parser.add_argument("--json", "-j", action="store_true",
                        help="Output as JSON")
    args = parser.parse_args()

    _safe_print(f"\n{BOLD}{'=' * 55}{RESET}")
    _safe_print(f"{BOLD}  [CAM] Camera Connection Checker{RESET}")
    _safe_print(f"{BOLD}  {time.strftime('%Y-%m-%d %H:%M:%S')}{RESET}")
    _safe_print(f"{BOLD}{'=' * 55}{RESET}")

    # Run all checks
    sys_info = check_system_info()
    devices = detect_camera_devices()
    blocking_procs = check_camera_in_use()
    opencv_results = test_opencv_cameras(
        specific_index=args.index,
        save_snapshot=args.snapshot,
    )
    picam_result = test_picamera2()

    # Summary
    if args.json:
        report = {
            "system": sys_info,
            "devices": devices,
            "blocking_processes": blocking_procs,
            "opencv_tests": opencv_results,
            "picamera2": picam_result,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        print(f"\n{json_module.dumps(report, indent=2, ensure_ascii=False)}")
    else:
        print_summary(sys_info, devices, opencv_results, blocking_procs, picam_result)


if __name__ == "__main__":
    main()
