from __future__ import annotations

import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from event_checklist.database import Database
from event_checklist.services import EventService
from event_checklist.ui.events_page import EventsPage


def main() -> int:
    root = Path(sys.argv[1])
    db = Database(root / "data" / "event_checklist.db")
    service = EventService(db)
    event = service.list_events()
    if event:
        event_id = int(event[0]["id"])
    else:
        ids = [row["id"] for row in db.query("SELECT id FROM master_items ORDER BY sort_order")]
        event_id = service.create_event(
            "체크리스트 성능 검증", date.today(), date.today() + timedelta(days=7), ids
        )
    app = QApplication.instance() or QApplication([])
    page = EventsPage(service, db)
    started = time.perf_counter()
    page.set_event(event_id)
    app.processEvents()
    elapsed_ms = (time.perf_counter() - started) * 1000
    print(f"rows={page.table.rowCount()} load_ms={elapsed_ms:.1f}")
    page.close()
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
