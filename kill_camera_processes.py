#!/usr/bin/env python3
"""
Kill all processes that are blocking the camera.

Supports:
  - Windows:  uses PowerShell + WMI to find processes that have a handle
              on camera / video-capture related devices.
  - Linux:    uses `fuser` / `lsof` on /dev/video* devices.

Usage:
    python kill_camera_processes.py          # interactive — asks before killing
    python kill_camera_processes.py --force  # kill without asking
    python kill_camera_processes.py --dry    # only list, don't kill anything
"""

import sys
import os
import platform
import subprocess
import signal
import logging
import argparse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("kill_camera")

# ── Safe print helper (handles encoding issues) ───────────────────
def _safe_print(*args, **kwargs):
    """Print with fallback for terminals that don't support unicode."""
    import io
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        text = " ".join(str(a) for a in args)
        text = text.encode("ascii", errors="replace").decode("ascii")
        print(text, **{k: v for k, v in kwargs.items() if k != 'end'})

# ── Цвета для консоли ──────────────────────────────────────────────
RESET  = "\033[0m"
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"

# Процессы, которые НИКОГДА не трогаем
SAFE_PROCESSES = {
    "system", "svchost.exe", "csrss.exe", "lsass.exe",
    "winlogon.exe", "services.exe", "smss.exe", "wininit.exe",
    "dwm.exe", "explorer.exe", "taskhostw.exe",
    "systemd", "init", "kernel",
}

# Известные программы, которые часто блокируют камеру
KNOWN_CAMERA_APPS = {
    # Windows
    "obs64.exe", "obs32.exe", "obs.exe",
    "skype.exe", "teams.exe", "zoom.exe", "discord.exe",
    "windowscamera.exe", "microsoftteams.exe",
    "googledrivesync.exe", "webex.exe",
    "snap camera.exe", "manycam.exe",
    "python.exe", "pythonw.exe", "python3.exe",
    "ffmpeg.exe", "vlc.exe",
    # Linux
    "obs", "skype", "zoom", "discord", "teams",
    "cheese", "guvcview", "vlc", "ffmpeg", "python", "python3",
}


def _run_ps(script: str) -> str:
    """Run a PowerShell script and return stdout."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=30,
        )
        return result.stdout.strip()
    except Exception as e:
        log.error("PowerShell error: %s", e)
        return ""


# ══════════════════════════════════════════════════════════════════════
#  WINDOWS
# ══════════════════════════════════════════════════════════════════════

def _find_camera_processes_windows() -> list[dict]:
    """
    Find processes that are likely holding the camera on Windows.
    
    Uses multiple detection methods:
      1. WMI query for Win32_PnPEntity matching camera/video devices
      2. Known camera-using application names
      3. Processes that have handles to video device paths
    """
    processes = {}

    # ── Метод 1: PowerShell — Get-Process with camera device handles ──
    ps_script = r"""
    # Find camera device instance paths
    $cameraDevices = Get-PnpDevice -Class 'Camera','Image' -Status 'OK' -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty InstanceId

    # Find processes accessing webcam via Win32_Process with command line analysis
    $procs = Get-Process | Where-Object {
        $_.MainWindowHandle -ne 0 -or $_.Modules.Count -gt 0
    } | ForEach-Object {
        try {
            $p = $_
            $modules = $p.Modules | Select-Object -ExpandProperty ModuleName -ErrorAction SilentlyContinue
            $hasVideoModule = $modules | Where-Object { 
                $_ -match 'mfplat|mf\.dll|mfreadwrite|vidcap|ksproxy|wmvcore|d3d11|dxgi|avicap|msvfw32|qedit|quartz' 
            }
            if ($hasVideoModule) {
                [PSCustomObject]@{
                    PID  = $p.Id
                    Name = $p.ProcessName
                    Path = $p.Path
                    Method = 'module_scan'
                }
            }
        } catch {}
    }
    $procs | ConvertTo-Json -Compress
    """
    output = _run_ps(ps_script)
    if output and output.startswith(("[", "{")):
        import json
        try:
            items = json.loads(output)
            if isinstance(items, dict):
                items = [items]
            for item in items:
                pid = item.get("PID")
                name = item.get("Name", "unknown")
                path = item.get("Path", "")
                if name.lower() not in SAFE_PROCESSES and pid:
                    processes[pid] = {
                        "pid": pid,
                        "name": name,
                        "path": path,
                        "method": item.get("Method", "wmi"),
                    }
        except json.JSONDecodeError:
            pass

    # ── Метод 2: Ищем известные программы камеры ──
    ps_known = "Get-Process | Select-Object Id, ProcessName, Path | ConvertTo-Json -Compress"
    output2 = _run_ps(ps_known)
    if output2 and output2.startswith(("[", "{")):
        import json
        try:
            items = json.loads(output2)
            if isinstance(items, dict):
                items = [items]
            for item in items:
                pname = (item.get("ProcessName") or "").lower()
                pid = item.get("Id")
                # Check against known camera apps
                if any(pname == app.replace(".exe", "") for app in KNOWN_CAMERA_APPS):
                    # Don't add our own process
                    if pid != os.getpid():
                        if pid not in processes:
                            processes[pid] = {
                                "pid": pid,
                                "name": item.get("ProcessName", "unknown"),
                                "path": item.get("Path", ""),
                                "method": "known_app",
                            }
        except json.JSONDecodeError:
            pass

    # ── Метод 3: handle.exe от Sysinternals (если установлен) ──
    try:
        result = subprocess.run(
            ["handle.exe", "-accepteula", "-a", "-p", "video"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 3 and parts[1].strip().isdigit():
                    pid = int(parts[1].strip())
                    name = parts[0].strip()
                    if name.lower() not in SAFE_PROCESSES and pid != os.getpid():
                        if pid not in processes:
                            processes[pid] = {
                                "pid": pid,
                                "name": name,
                                "path": "",
                                "method": "handle.exe",
                            }
    except FileNotFoundError:
        pass  # handle.exe not installed
    except Exception:
        pass

    return list(processes.values())


def _kill_process_windows(pid: int, name: str) -> bool:
    """Kill a process on Windows by PID."""
    try:
        result = subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            log.info("%s[OK] Ubit process: %s (PID %d)%s", GREEN, name, pid, RESET)
            return True
        else:
            log.warning("%s[!] Ne udalos ubit %s (PID %d): %s%s",
                        YELLOW, name, pid, result.stderr.strip(), RESET)
            return False
    except Exception as e:
        log.error("Ошибка при убийстве процесса %d: %s", pid, e)
        return False


# ══════════════════════════════════════════════════════════════════════
#  LINUX
# ══════════════════════════════════════════════════════════════════════

def _find_camera_processes_linux() -> list[dict]:
    """Find processes accessing /dev/video* on Linux."""
    processes = {}

    # Find all video devices
    import glob
    video_devices = glob.glob("/dev/video*")
    if not video_devices:
        log.info("Не найдено устройств /dev/video*")
        return []

    for dev in video_devices:
        # Try fuser first
        try:
            result = subprocess.run(
                ["fuser", dev],
                capture_output=True, text=True, timeout=5,
            )
            pids_str = result.stdout.strip() + " " + result.stderr.strip()
            for token in pids_str.split():
                token = token.strip().rstrip("m").rstrip("e").rstrip("f")
                if token.isdigit():
                    pid = int(token)
                    if pid != os.getpid():
                        # Get process name
                        name = _get_process_name_linux(pid)
                        if name.lower() not in SAFE_PROCESSES:
                            processes[pid] = {
                                "pid": pid,
                                "name": name,
                                "path": f"/proc/{pid}/exe",
                                "method": f"fuser({dev})",
                            }
        except FileNotFoundError:
            pass

        # Try lsof as fallback
        try:
            result = subprocess.run(
                ["lsof", dev],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 2:
                    name = parts[0]
                    pid = int(parts[1])
                    if pid != os.getpid() and name.lower() not in SAFE_PROCESSES:
                        processes[pid] = {
                            "pid": pid,
                            "name": name,
                            "path": "",
                            "method": f"lsof({dev})",
                        }
        except (FileNotFoundError, ValueError):
            pass

    return list(processes.values())


def _get_process_name_linux(pid: int) -> str:
    """Get process name from /proc on Linux."""
    try:
        with open(f"/proc/{pid}/comm", "r") as f:
            return f.read().strip()
    except Exception:
        return f"PID-{pid}"


def _kill_process_linux(pid: int, name: str) -> bool:
    """Kill a process on Linux."""
    try:
        os.kill(pid, signal.SIGTERM)
        log.info("%s[OK] Otpravlen SIGTERM: %s (PID %d)%s", GREEN, name, pid, RESET)
        
        # Wait a bit and check if still alive
        import time
        time.sleep(1)
        try:
            os.kill(pid, 0)  # Check if still alive
            # Still alive — send SIGKILL
            os.kill(pid, signal.SIGKILL)
            log.info("%s[KILL] Otpravlen SIGKILL: %s (PID %d)%s", RED, name, pid, RESET)
        except ProcessLookupError:
            pass  # Process already dead
        return True
    except PermissionError:
        log.warning("%s[!] Net prav dlya ubiystva %s (PID %d) -- poprobujte sudo%s",
                    YELLOW, name, pid, RESET)
        return False
    except ProcessLookupError:
        log.info("Процесс %s (PID %d) уже не существует", name, pid)
        return True
    except Exception as e:
        log.error("Ошибка: %s", e)
        return False


# ══════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════

def find_camera_processes() -> list[dict]:
    """Find processes blocking the camera (cross-platform)."""
    system = platform.system()
    if system == "Windows":
        return _find_camera_processes_windows()
    elif system == "Linux":
        return _find_camera_processes_linux()
    else:
        log.warning("[!] Platforma '%s' ne podderzhivaetsya polnostyu", system)
        return []


def kill_camera_processes(force: bool = False, dry_run: bool = False) -> int:
    """
    Find and kill processes blocking the camera.
    
    Returns the number of killed processes.
    """
    _safe_print(f"\n{BOLD}{CYAN}[SEARCH] Poisk processov, blokiruyushchikh kameru...{RESET}\n")

    procs = find_camera_processes()

    if not procs:
        _safe_print(f"{GREEN}[OK] Ne najdeno processov, blokiruyushchikh kameru.{RESET}")
        _safe_print(f"{CYAN}   Kamera dolzhna byt svobodna!{RESET}\n")
        return 0

    # Display found processes
    _safe_print(f"{YELLOW}[!] Najdeno {len(procs)} process(ov), potencialno blokiruyushchikh kameru:{RESET}\n")
    _safe_print(f"  {'PID':>8}  {'Process name':<25}  {'Detection method':<20}  Path")
    _safe_print(f"  {'-' * 8}  {'-' * 25}  {'-' * 20}  {'-' * 30}")
    for p in procs:
        path_display = p.get("path", "") or "-"
        if len(path_display) > 50:
            path_display = "..." + path_display[-47:]
        _safe_print(f"  {p['pid']:>8}  {p['name']:<25}  {p['method']:<20}  {path_display}")
    _safe_print()

    if dry_run:
        _safe_print(f"{CYAN}[i] Rezhim --dry: processy NE byli ubity.{RESET}\n")
        return 0

    # Confirm
    if not force:
        try:
            answer = input(f"{BOLD}Kill all these processes? [y/N]: {RESET}").strip().lower()
            if answer not in ("y", "yes", "d", "da"):
                _safe_print(f"{CYAN}Cancelled.{RESET}\n")
                return 0
        except (KeyboardInterrupt, EOFError):
            _safe_print(f"\n{CYAN}Cancelled.{RESET}\n")
            return 0

    # Kill
    killed = 0
    system = platform.system()
    for p in procs:
        if system == "Windows":
            if _kill_process_windows(p["pid"], p["name"]):
                killed += 1
        else:
            if _kill_process_linux(p["pid"], p["name"]):
                killed += 1

    _safe_print(f"\n{GREEN}{'=' * 50}{RESET}")
    _safe_print(f"{GREEN}[OK] Killed processes: {killed} of {len(procs)}{RESET}")
    _safe_print(f"{GREEN}{'=' * 50}{RESET}\n")

    if killed > 0:
        _safe_print(f"{CYAN}[*] Wait 1-2 seconds, then start the camera app.{RESET}\n")

    return killed


def main():
    parser = argparse.ArgumentParser(
        description="Kill all processes blocking the camera",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python kill_camera_processes.py          # Interactive mode
  python kill_camera_processes.py --force  # Kill without confirmation
  python kill_camera_processes.py --dry    # Only list, don't kill
        """,
    )
    parser.add_argument("--force", "-f", action="store_true",
                        help="Kill without confirmation")
    parser.add_argument("--dry", "-d", action="store_true",
                        help="Only list processes, don't kill")
    args = parser.parse_args()

    _safe_print(f"\n{BOLD}{'=' * 50}{RESET}")
    _safe_print(f"{BOLD}  [CAM] Camera Process Killer{RESET}")
    _safe_print(f"{BOLD}  Platform: {platform.system()} ({platform.machine()}){RESET}")
    _safe_print(f"{BOLD}{'=' * 50}{RESET}")

    killed = kill_camera_processes(force=args.force, dry_run=args.dry)
    sys.exit(0 if killed >= 0 else 1)


if __name__ == "__main__":
    main()
