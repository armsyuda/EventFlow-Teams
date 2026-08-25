from __future__ import annotations

import shutil
from datetime import date, datetime
from pathlib import Path

from .database import Database


def create_backup(db: Database, destination: Path) -> Path:
    db.checkpoint()
    destination = Path(destination)
    if destination.suffix.lower() != ".db":
        destination.mkdir(parents=True, exist_ok=True)
        destination = destination / f"event_checklist_{datetime.now():%Y%m%d_%H%M%S}.db"
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(db.path, destination)
    return destination


def create_named_backup(db: Database, directory: Path, prefix: str) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return create_backup(db, directory / f"{prefix}_{timestamp}.db")


def create_manual_backup(db: Database, directory: Path) -> Path:
    """Create a user-requested full backup that rotation never deletes."""
    return create_named_backup(db, directory, "manual_event_flow")


def create_rotating_auto_backup(db: Database, directory: Path, keep: int = 10) -> Path:
    """Create one full automatic backup and retain only the newest files."""
    result = create_named_backup(db, directory, "auto_event_flow")
    backups = sorted(Path(directory).glob("auto_event_flow_*.db"), key=lambda path: path.stat().st_mtime)
    for obsolete in backups[:-max(1, int(keep))]:
        obsolete.unlink(missing_ok=True)
    return result


def automatic_daily_backup(db: Database, directory: Path) -> Path | None:
    today = date.today().isoformat()
    if db.get_setting("last_auto_backup") == today:
        return None
    result = create_backup(db, directory)
    db.set_setting("last_auto_backup", today)
    return result


def restore_backup(db: Database, source: Path) -> None:
    source = Path(source)
    if not source.is_file():
        raise FileNotFoundError(source)
    probe = Database(source)
    try:
        row = probe.one("SELECT version FROM schema_info LIMIT 1")
        if row is None:
            raise ValueError("올바른 백업 데이터베이스가 아닙니다.")
    finally:
        probe.close()
    db.clear_history()
    db.close()
    try:
        shutil.copy2(source, db.path)
    finally:
        db.open()
    db.mark_backed_up()
