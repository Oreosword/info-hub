#!/usr/bin/env python3
"""Windows-friendly launcher for the AI daily workbench."""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).parent.resolve()
SRC_DIR = ROOT / "src"
PORT = 8000
HOST = "127.0.0.1"
APP_URL = f"http://{HOST}:{PORT}/"
HEALTH_URL = f"{APP_URL}health"
LOCK_PATH = ROOT / ".infohub.launch.lock"

if sys.platform == "win32":
    VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
else:
    VENV_PYTHON = ROOT / ".venv" / "bin" / "python"

os.environ.setdefault("NO_PROXY", "*")
os.environ.setdefault("no_proxy", "*")


def is_info_hub_running() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return False
    return payload.get("status") == "ok" and payload.get("service") == "Info Hub"


def is_port_in_use() -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    try:
        return sock.connect_ex((HOST, PORT)) == 0
    finally:
        sock.close()


def is_port_listening() -> bool:
    if is_port_in_use():
        return True
    if sys.platform != "win32":
        return False
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"(Get-NetTCPConnection -LocalPort {PORT} -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count",
            ],
            capture_output=True,
            text=True,
            timeout=3,
        )
        return int((result.stdout or "0").strip() or "0") > 0
    except (OSError, subprocess.SubprocessError, ValueError):
        return False


def acquire_launch_lock() -> Optional[int]:
    try:
        return os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_RDWR)
    except FileExistsError:
        return None


def release_launch_lock(lock_fd: Optional[int]) -> None:
    if lock_fd is not None:
        try:
            os.close(lock_fd)
        except OSError:
            pass
    try:
        LOCK_PATH.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def wait_for_running_service(seconds: float = 15) -> bool:
    attempts = max(1, int(seconds / 0.5))
    for _ in range(attempts):
        time.sleep(0.5)
        if is_info_hub_running():
            return True
    return False


def open_app() -> None:
    webbrowser.open(APP_URL)


def main() -> int:
    if is_info_hub_running():
        print("[Info Hub] 服务已在运行，正在打开页面...")
        open_app()
        return 0

    if LOCK_PATH.exists():
        print("[Info Hub] 检测到服务正在启动，稍等后打开页面...")
        if wait_for_running_service():
            open_app()
            return 0
        if not is_port_listening():
            try:
                LOCK_PATH.unlink()
            except OSError:
                pass
        else:
            print("[错误] 服务正在启动或 8000 端口被占用，请稍后再试。")
            return 1

    if is_port_listening():
        print("[错误] 8000 端口已被其他程序占用，无法启动 AI 日报生产台。")
        print("[提示] 请关闭占用 8000 端口的程序后再重新打开。")
        return 1

    if not VENV_PYTHON.exists():
        print("[错误] 未找到项目虚拟环境。")
        print("[提示] 请先在项目目录运行：uv venv && uv pip install -r requirements.txt")
        return 1

    env = os.environ.copy()
    env["INFO_HUB_OPEN_BROWSER"] = "1"
    env.setdefault("NO_PROXY", "*")
    env.setdefault("no_proxy", "*")

    lock_fd = acquire_launch_lock()
    if lock_fd is None:
        print("[Info Hub] 检测到服务正在启动，稍等后打开页面...")
        if wait_for_running_service():
            open_app()
            return 0
        print("[错误] 启动锁仍被占用，请稍后重试。")
        return 1

    try:
        if is_info_hub_running():
            print("[Info Hub] 服务已在运行，正在打开页面...")
            open_app()
            return 0
        if is_port_listening():
            print("[错误] 8000 端口已被其他程序占用，无法启动 AI 日报生产台。")
            print("[提示] 请关闭占用 8000 端口的程序后再重新打开。")
            return 1
        print("[Info Hub] 正在启动 AI 日报生产台...")
        print(f"[Info Hub] 页面地址：{APP_URL}")
        print("-" * 48)
        return subprocess.run([str(VENV_PYTHON), str(SRC_DIR / "main.py")], cwd=str(ROOT), env=env).returncode
    except KeyboardInterrupt:
        print("\n[Info Hub] 服务已停止。")
        return 0
    finally:
        release_launch_lock(lock_fd)


if __name__ == "__main__":
    raise SystemExit(main())
