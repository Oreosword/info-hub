import importlib
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_database_path_can_be_overridden_for_ci(tmp_path):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["INFO_HUB_DB_PATH"] = str(tmp_path / "ci-infohub.db")

    result = subprocess.run(
        [sys.executable, "-c", "import database; print(database.DB_PATH)"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == str(tmp_path / "ci-infohub.db")


def test_smoke_test_base_url_can_be_overridden(monkeypatch):
    monkeypatch.setenv("INFO_HUB_BASE_URL", "http://127.0.0.1:8123")
    import scripts.smoke_test as smoke_test

    importlib.reload(smoke_test)

    assert smoke_test.BASE_URL == "http://127.0.0.1:8123"


def test_main_supports_skip_initial_fetch_flag():
    source = (ROOT / "src" / "main.py").read_text(encoding="utf-8")

    assert "INFO_HUB_SKIP_INITIAL_FETCH" in source
