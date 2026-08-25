from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

from event_checklist.database import Database
from event_checklist.services import EventService


root = Path(sys.argv[1])
db = Database(root / "data" / "event_checklist.db")
service = EventService(db)
ids = [row["id"] for row in db.query("SELECT id FROM master_items ORDER BY id LIMIT 14")]
today = date.today()
event_id = service.create_event("UI 검증 행사", today - timedelta(days=20), today + timedelta(days=5), ids)
tasks = service.list_tasks(event_id)
for index, task in enumerate(tasks[:6]):
    service.update_task(
        task["id"],
        planned_start=(today - timedelta(days=2)).isoformat(),
        due_date=(today + timedelta(days=index - 2)).isoformat(),
        status="진행중" if index % 2 else "미착수",
    )
service.update_task(
    tasks[6]["id"],
    planned_start=(today - timedelta(days=2)).isoformat(),
    due_date=today.isoformat(),
    status="완료",
)
db.close()
