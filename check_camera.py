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

# ── Цвета ──────────────────────────────────────────────────────────
RESET  = "\033[0m"
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"

# ── Вспомогательные функции ────────────────────────────────────────

def _header(title: str):
    print(f"\n{BOLD}{CYAN}{'─' * 55}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'─' * 55}{RESET}\n")


def _ok(msg: str):
    print(f"  {GREEN}✅ {msg}{RESET}")


def _warn(msg: str):
    print(f"  {YELLOW}⚠️  {msg}{RESET}")


def _fail(msg: str):
    print(f"  {RED}❌ {msg}{RESET}")


def _info(msg: str):
    print(f"  {CYAN}ℹ️  {msg}{RESET}")


def _detail(key: str, value):
    print(f"     {DIM}{key}:{RESET} {value}")


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

    _header("📋 Системная информация")
    _detail("ОС", f"{info['platform']} ({info['machine']})")
    _detail("Python", info["python"])
    _detail("Хост", info["node"])

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
        _ok(f"OpenCV {cv2.__version__} установлен")
        if available:
            _detail("Доступные бэкенды", ", ".join(available))
    except ImportError:
        info["opencv_version"] = None
        _fail("OpenCV НЕ установлен — pip install opencv-python-headless")

    # Check Picamera2 (RPi)
    if info["machine"] in ("aarch64", "armv7l"):
        try:
            from picamera2 import Picamera2
            info["picamera2"] = True
            _ok("Picamera2 доступен")
        except ImportError:
            info["picamera2"] = False
            _warn("Picamera2 не установлен (нужен для CSI камеры на RPi)")
    else:
        info["picamera2"] = False

    return info


# ══════════════════════════════════════════════════════════════════════
#  DEVICE DETECTION
# ══════════════════════════════════════════════════════════════════════

def detect_camera_devices() -> list[dict]:
    """Detect camera devices on the system."""
    _header("🔎 Обнаружение камер")
    devices = []

    system = platform.system()

    if system == "Windows":
        devices = _detect_devices_windows()
    elif system == "Linux":
        devices = _detect_devices_linux()
    else:
        _warn(f"Автоматическое обнаружение для '{system}' ограничено")

    if devices:
        _ok(f"Обнаружено устройств: {len(devices)}")
        for i, dev in enumerate(devices):
            print(f"\n  {BOLD}Камера #{i + 1}:{RESET}")
            _detail("Имя", dev.get("name", "Неизвестно"))
            _detail("ID", dev.get("device_id", "—"))
            if dev.get("status"):
                _detail("Статус", dev["status"])
            if dev.get("manufacturer"):
                _detail("Производитель", dev["manufacturer"])
    else:
        _warn("Камеры не обнаружены через системные API")
        _info("Это не обязательно значит, что камеры нет — проверим через OpenCV")

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
    _header("🎥 Тест камер через OpenCV")

    try:
        import cv2
    except ImportError:
        _fail("OpenCV не установлен — невозможно тестировать")
        return []

    results = []
    indices = [specific_index] if specific_index is not None else range(5)

    for idx in indices:
        print(f"  {BOLD}Проверка камеры с индексом {idx}...{RESET}")

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
                _fail(f"Индекс {idx}: не удалось открыть")
                results.append(cam_result)
                continue

            cam_result["opened"] = True
            cam_result["backend"] = cap.getBackendName() if hasattr(cap, 'getBackendName') else "unknown"
            _ok(f"Индекс {idx}: камера открыта (бэкенд: {cam_result['backend']})")

            # Read properties
            cam_result["width"] = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            cam_result["height"] = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cam_result["fps"] = round(cap.get(cv2.CAP_PROP_FPS), 1)

            _detail("Разрешение", f"{cam_result['width']}x{cam_result['height']}")
            _detail("FPS (заявленный)", cam_result["fps"])

            # Try to capture a frame
            ok, frame = cap.read()
            if ok and frame is not None:
                cam_result["frame_captured"] = True
                cam_result["actual_shape"] = list(frame.shape)
                _ok(f"Кадр захвачен! (shape: {frame.shape})")

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
                _detail("FPS (фактический, ~2с тест)", actual_fps)

                # Save snapshot if requested
                if save_snapshot:
                    snap_path = os.path.join(
                        os.path.dirname(os.path.abspath(__file__)),
                        f"camera_test_snapshot_{idx}.jpg"
                    )
                    cv2.imwrite(snap_path, frame)
                    _ok(f"Снимок сохранён: {snap_path}")
                    cam_result["snapshot_path"] = snap_path
            else:
                _fail("Камера открылась, но кадр НЕ захвачен")

            cap.release()

        except Exception as e:
            _fail(f"Ошибка при тесте индекса {idx}: {e}")
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

    _header("🍓 Тест Picamera2 (Raspberry Pi)")

    try:
        from picamera2 import Picamera2
    except ImportError:
        _warn("Picamera2 не установлен — пропускаем")
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
            _ok(f"Picamera2: найдено {len(cam_info)} камер(а)")
            for i, cam in enumerate(cam_info):
                print(f"\n  {BOLD}CSI камера #{i}:{RESET}")
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
                _ok(f"Кадр захвачен через Picamera2 (shape: {frame.shape})")
                result["frame_captured"] = True
            else:
                _fail("Picamera2 не смогла захватить кадр")
                result["frame_captured"] = False
        else:
            _fail("Picamera2: камеры не найдены")

        picam.close()
    except Exception as e:
        _fail(f"Ошибка Picamera2: {e}")
        result["error"] = str(e)

    return result


# ══════════════════════════════════════════════════════════════════════
#  PROCESS CHECK
# ══════════════════════════════════════════════════════════════════════

def check_camera_in_use() -> list[dict]:
    """Check if camera is currently being used by other processes."""
    _header("🔒 Проверка блокировки камеры")

    # Import our kill script to reuse the detection logic
    try:
        from kill_camera_processes import find_camera_processes
        procs = find_camera_processes()
        if procs:
            _warn(f"Камеру могут блокировать {len(procs)} процесс(ов):")
            for p in procs:
                _detail(f"PID {p['pid']}", f"{p['name']} ({p['method']})")
            _info("Запустите: python kill_camera_processes.py")
        else:
            _ok("Камера не заблокирована другими процессами")
        return procs
    except ImportError:
        _warn("Модуль kill_camera_processes не найден — пропускаем проверку блокировки")
        return []


# ══════════════════════════════════════════════════════════════════════
#  SUMMARY
# ══════════════════════════════════════════════════════════════════════

def print_summary(sys_info: dict, devices: list, opencv_results: list,
                  blocking_procs: list, picam_result: dict | None):
    """Print a final summary."""
    _header("📊 Итоговый отчёт")

    working_cameras = [r for r in opencv_results if r.get("frame_captured")]
    openable_cameras = [r for r in opencv_results if r.get("opened")]

    if working_cameras:
        best = max(working_cameras, key=lambda r: r.get("actual_fps", 0))
        print(f"  {GREEN}{BOLD}✅ КАМЕРА РАБОТАЕТ!{RESET}")
        print()
        _detail("Лучший индекс", best["index"])
        _detail("Разрешение", f"{best['width']}x{best['height']}")
        _detail("FPS", best.get("actual_fps", "?"))
        _detail("Бэкенд", best.get("backend", "?"))
        print()
        _info(f"Используйте индекс {best['index']} в camera.py (CAMERA_SRC = {best['index']})")
    elif openable_cameras:
        print(f"  {YELLOW}{BOLD}⚠️  Камера открывается, но кадры НЕ захватываются{RESET}")
        print()
        _info("Возможные причины:")
        _info("  • Камера используется другим процессом")
        _info("  • Драйвер камеры работает некорректно")
        _info("  • Попробуйте: python kill_camera_processes.py")
    else:
        print(f"  {RED}{BOLD}❌ КАМЕРА НЕ НАЙДЕНА / НЕ РАБОТАЕТ{RESET}")
        print()
        _info("Рекомендации:")
        _info("  1. Проверьте физическое подключение камеры (USB кабель)")
        _info("  2. Проверьте, включена ли камера в настройках конфиденциальности ОС")
        _info("  3. Обновите драйверы камеры")
        _info("  4. На Windows: Параметры → Конфиденциальность → Камера → Включить")
        _info("  5. Попробуйте другой USB-порт")
        if blocking_procs:
            _info(f"  6. Убейте блокирующие процессы: python kill_camera_processes.py")

    if picam_result and picam_result.get("available"):
        print()
        _ok("Picamera2 (Raspberry Pi CSI) тоже доступна")

    print()


# ══════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="🎥 Проверка подключения камеры",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  python check_camera.py                # Полная проверка
  python check_camera.py --index 0      # Только индекс 0
  python check_camera.py --snapshot     # Сохранить тестовый снимок
  python check_camera.py --json         # Вывод в формате JSON
        """,
    )
    parser.add_argument("--index", "-i", type=int, default=None,
                        help="Проверить конкретный индекс камеры")
    parser.add_argument("--snapshot", "-s", action="store_true",
                        help="Сохранить тестовый снимок")
    parser.add_argument("--json", "-j", action="store_true",
                        help="Вывод в формате JSON")
    args = parser.parse_args()

    print(f"\n{BOLD}{'═' * 55}{RESET}")
    print(f"{BOLD}  🎥 Camera Connection Checker{RESET}")
    print(f"{BOLD}  {time.strftime('%Y-%m-%d %H:%M:%S')}{RESET}")
    print(f"{BOLD}{'═' * 55}{RESET}")

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
