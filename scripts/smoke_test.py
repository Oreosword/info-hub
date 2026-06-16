#!/usr/bin/env python3
"""Smoke-test a running Info Hub service without extra test dependencies."""

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Tuple


BASE_URL = os.environ.get("INFO_HUB_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def fetch(path: str) -> Tuple[int, str]:
    url = f"{BASE_URL}{path}"
    with urllib.request.urlopen(url, timeout=10) as response:
        return response.status, response.read().decode("utf-8", errors="replace")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    try:
        status, body = fetch("/health")
        require(status == 200, "health status must be 200")
        health = json.loads(body)
        require(health.get("status") == "ok", "health status must be ok")
        require(health.get("service") == "Info Hub", "health service must be Info Hub")
        require(bool(health.get("version")), "health must include version")

        status, html = fetch("/")
        require(status == 200, "home status must be 200")
        for text in ("AI 日报生产台", "信息流", "筛选台", "日报生成"):
            require(text in html, f"home page must contain {text}")

        for path in ("/api/items?limit=1", "/api/sources", "/api/deepseek/settings"):
            status, body = fetch(path)
            require(status == 200, f"{path} status must be 200")
            json.loads(body)

    except (AssertionError, OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"[smoke] FAILED: {exc}")
        return 1

    print("[smoke] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
