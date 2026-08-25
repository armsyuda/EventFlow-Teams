from __future__ import annotations

import os
from pathlib import Path


APP_NAME = "EventFlowTeams"
PRODUCT_NAME = "EventFlow Teams"


def data_root() -> Path:
    override = os.environ.get("EVENT_CHECKLIST_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    return base / APP_NAME


def database_path() -> Path:
    return data_root() / "data" / "event_checklist.db"


def backup_dir() -> Path:
    return data_root() / "backups"


def history_dir() -> Path:
    return data_root() / "history"


def update_dir() -> Path:
    return data_root() / "updates"


def install_dir() -> Path:
    """Return the per-user, stable application installation directory."""
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    return base / "Programs" / PRODUCT_NAME


def ensure_directories() -> None:
    database_path().parent.mkdir(parents=True, exist_ok=True)
    backup_dir().mkdir(parents=True, exist_ok=True)
    history_dir().mkdir(parents=True, exist_ok=True)
    update_dir().mkdir(parents=True, exist_ok=True)
