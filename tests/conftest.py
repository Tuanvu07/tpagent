"""Pytest setup: make the project root importable and isolate the cwd."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    """Run the test inside an empty temp dir so file tools see it as cwd."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def config(workdir):
    from tpagent.config import Config

    cfg = Config(sessions_dir=workdir / "sessions", max_turns=10)
    cfg.tiers = {t: "fake" for t in cfg.tiers}
    cfg.default_provider = "fake"
    return cfg
