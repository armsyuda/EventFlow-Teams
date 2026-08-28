"""Independent local mirror for the additive Teams Workspace V3 contract.

The legacy V2 SQLite tables/outbox remain untouched.  V3 rows use server UUIDs
as their identity so a company-wide list and a selected-project list always
refer to the same work item.
"""

from __future__ import annotations

import json
import uuid
from typing import Any


def _items(value: object) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


class CompanyWorkspace:
    def __init__(self, database) -> None:
        self.db = database
        self.db.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS teams_v3_workspace (
              singleton INTEGER PRIMARY KEY CHECK(singleton=1), remote_cursor INTEGER NOT NULL DEFAULT 0,
              last_sync_at TEXT, sync_state TEXT NOT NULL DEFAULT 'LOCAL_ONLY'
            );
            CREATE TABLE IF NOT EXISTS teams_v3_work_items (
              remote_id TEXT PRIMARY KEY, event_id TEXT, work_scope TEXT NOT NULL,
              major TEXT NOT NULL, minor TEXT NOT NULL, name TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL, planned_start TEXT, due_date TEXT, is_removed INTEGER NOT NULL DEFAULT 0,
              assigned_member_user_id TEXT, sort_order INTEGER NOT NULL DEFAULT 0, row_version INTEGER NOT NULL DEFAULT 1,
              updated_at TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS teams_v3_work_scope_idx ON teams_v3_work_items(work_scope,event_id,status,due_date);
            CREATE TABLE IF NOT EXISTS teams_v3_financial_entries (
              remote_id TEXT PRIMARY KEY, event_id TEXT, event_task_id TEXT, vendor_id TEXT, title TEXT NOT NULL,
              entry_kind TEXT NOT NULL, settlement_status TEXT NOT NULL, supply_amount INTEGER NOT NULL,
              vat_type TEXT NOT NULL, vat_amount INTEGER NOT NULL, total_amount INTEGER NOT NULL,
              planned_date TEXT, settled_date TEXT, note TEXT NOT NULL DEFAULT '', row_version INTEGER NOT NULL DEFAULT 1,
              updated_at TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS teams_v3_finance_project_idx ON teams_v3_financial_entries(event_id,planned_date);
            CREATE TABLE IF NOT EXISTS teams_v3_outbox (
              id INTEGER PRIMARY KEY AUTOINCREMENT, mutation_id TEXT NOT NULL UNIQUE, operation TEXT NOT NULL,
              payload_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING', attempts INTEGER NOT NULL DEFAULT 0,
              last_error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS teams_v3_conflicts (
              id INTEGER PRIMARY KEY AUTOINCREMENT, entity_type TEXT NOT NULL, remote_id TEXT,
              server_payload_json TEXT NOT NULL, local_payload_json TEXT NOT NULL,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT OR IGNORE INTO teams_v3_workspace(singleton) VALUES(1);
            """
        )
        self.db.conn.commit()

    def cursor(self) -> int:
        row = self.db.one("SELECT remote_cursor FROM teams_v3_workspace WHERE singleton=1")
        return int(row["remote_cursor"] or 0) if row else 0

    def apply_snapshot(self, snapshot: dict[str, Any]) -> None:
        with self.db.applying_remote_changes():
            self.db.conn.execute("DELETE FROM teams_v3_work_items")
            self.db.conn.execute("DELETE FROM teams_v3_financial_entries")
            for item in _items(snapshot.get("work_items")):
                self._upsert_work(item)
            for item in _items(snapshot.get("financial_entries")):
                self._upsert_finance(item)
            self.db.conn.execute("UPDATE teams_v3_workspace SET remote_cursor=?,last_sync_at=CURRENT_TIMESTAMP,sync_state='SYNCED' WHERE singleton=1", (int(snapshot.get("cursor") or 0),))
        self.db.conn.commit()

    def apply_changes(self, changes: dict[str, Any]) -> None:
        with self.db.applying_remote_changes():
            for change in _items(changes.get("changes")):
                entity = str(change.get("entity_type") or "")
                remote_id = str(change.get("entity_key") or "")
                if not remote_id:
                    continue
                if str(change.get("operation")) == "DELETE":
                    table = "teams_v3_work_items" if entity == "WORK_ITEM" else "teams_v3_financial_entries" if entity == "FINANCIAL_ENTRY" else ""
                    if table:
                        self.db.conn.execute(f"DELETE FROM {table} WHERE remote_id=?", (remote_id,))
                elif entity == "WORK_ITEM":
                    self._upsert_work(change.get("payload") if isinstance(change.get("payload"), dict) else {})
                elif entity == "FINANCIAL_ENTRY":
                    self._upsert_finance(change.get("payload") if isinstance(change.get("payload"), dict) else {})
            self.db.conn.execute("UPDATE teams_v3_workspace SET remote_cursor=?,last_sync_at=CURRENT_TIMESTAMP,sync_state='SYNCED' WHERE singleton=1", (int(changes.get("cursor") or self.cursor()),))
        self.db.conn.commit()

    def queue(self, operation: str, payload: dict[str, Any]) -> str:
        mutation_id = str(uuid.uuid4())
        self.db.conn.execute("INSERT INTO teams_v3_outbox(mutation_id,operation,payload_json) VALUES(?,?,?)", (mutation_id, operation, json.dumps(payload, ensure_ascii=False)))
        self.db.conn.commit()
        return mutation_id

    def next_mutation(self) -> tuple[dict[str, Any], dict[str, Any]] | None:
        row = self.db.one("SELECT * FROM teams_v3_outbox WHERE status='PENDING' ORDER BY id LIMIT 1")
        if not row:
            return None
        entry = dict(row)
        return entry, {"mutation_id": entry["mutation_id"], "operation": entry["operation"], "payload": json.loads(entry["payload_json"])}

    def apply_mutation_response(self, entry: dict[str, Any], response: dict[str, Any]) -> str:
        result = next((item for item in _items(response.get("results")) if item.get("mutation_id") == entry["mutation_id"]), None)
        if not result:
            self._fail(entry, "서버 저장 결과가 비어 있습니다.")
            return "WAITING"
        status = str(result.get("status") or "REJECTED")
        if status == "APPLIED":
            entity = result.get("entity")
            if isinstance(entity, dict):
                (self._upsert_work(entity) if result.get("entity_type") == "WORK_ITEM" else self._upsert_finance(entity))
            self.db.conn.execute("UPDATE teams_v3_outbox SET status='APPLIED',last_error='' WHERE id=?", (entry["id"],))
            self.db.conn.execute("UPDATE teams_v3_workspace SET remote_cursor=?,last_sync_at=CURRENT_TIMESTAMP WHERE singleton=1", (int(response.get("cursor") or self.cursor()),))
            self.db.conn.commit(); return "APPLIED"
        if status == "CONFLICT":
            self.db.conn.execute("UPDATE teams_v3_outbox SET status='CONFLICT',last_error='동시 수정 충돌' WHERE id=?", (entry["id"],))
            self.db.conn.execute("INSERT INTO teams_v3_conflicts(entity_type,remote_id,server_payload_json,local_payload_json) VALUES(?,?,?,?)", (str(result.get("entity_type") or ""), str((result.get("entity") or {}).get("id") or ""), json.dumps(result.get("entity") or {}, ensure_ascii=False), entry["payload_json"]))
            self.db.conn.commit(); return "CONFLICT"
        self._fail(entry, str(result.get("reason") or "서버에서 변경을 거부했습니다.")); return "REJECTED"

    def record_transport_failure(self, entry: dict[str, Any], message: str) -> None:
        """Keep the V3 row pending; the UI timer retries without touching V2."""
        self.db.conn.execute("UPDATE teams_v3_outbox SET attempts=attempts+1,last_error=? WHERE id=?", (message, entry["id"]))
        self.db.conn.execute("UPDATE teams_v3_workspace SET sync_state='WAITING' WHERE singleton=1")
        self.db.conn.commit()

    def _fail(self, entry: dict[str, Any], message: str) -> None:
        self.db.conn.execute("UPDATE teams_v3_outbox SET attempts=attempts+1,last_error=? WHERE id=?", (message, entry["id"])); self.db.conn.commit()

    def _upsert_work(self, item: dict[str, Any]) -> None:
        if not item.get("id"):
            return
        values = (str(item["id"]), item.get("event_id"), str(item.get("work_scope") or "PROJECT"), str(item.get("major") or "기타"), str(item.get("minor") or "일반"), str(item.get("name") or ""), str(item.get("detail") or ""), str(item.get("status") or "미착수"), item.get("planned_start"), item.get("due_date"), int(bool(item.get("is_removed"))), item.get("assigned_member_user_id"), int(item.get("sort_order") or 0), int(item.get("row_version") or 1), str(item.get("updated_at") or ""))
        self.db.conn.execute("INSERT INTO teams_v3_work_items(remote_id,event_id,work_scope,major,minor,name,detail,status,planned_start,due_date,is_removed,assigned_member_user_id,sort_order,row_version,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(remote_id) DO UPDATE SET event_id=excluded.event_id,work_scope=excluded.work_scope,major=excluded.major,minor=excluded.minor,name=excluded.name,detail=excluded.detail,status=excluded.status,planned_start=excluded.planned_start,due_date=excluded.due_date,is_removed=excluded.is_removed,assigned_member_user_id=excluded.assigned_member_user_id,sort_order=excluded.sort_order,row_version=excluded.row_version,updated_at=excluded.updated_at", values)

    def _upsert_finance(self, item: dict[str, Any]) -> None:
        if not item.get("id"):
            return
        values = (str(item["id"]), item.get("event_id"), item.get("event_task_id"), item.get("vendor_id"), str(item.get("title") or ""), str(item.get("entry_kind") or "EXPENSE"), str(item.get("settlement_status") or "PLANNED"), int(item.get("supply_amount") or 0), str(item.get("vat_type") or "TAXABLE"), int(item.get("vat_amount") or 0), int(item.get("total_amount") or 0), item.get("planned_date"), item.get("settled_date"), str(item.get("note") or ""), int(item.get("row_version") or 1), str(item.get("updated_at") or ""))
        self.db.conn.execute("INSERT INTO teams_v3_financial_entries(remote_id,event_id,event_task_id,vendor_id,title,entry_kind,settlement_status,supply_amount,vat_type,vat_amount,total_amount,planned_date,settled_date,note,row_version,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(remote_id) DO UPDATE SET event_id=excluded.event_id,event_task_id=excluded.event_task_id,vendor_id=excluded.vendor_id,title=excluded.title,entry_kind=excluded.entry_kind,settlement_status=excluded.settlement_status,supply_amount=excluded.supply_amount,vat_type=excluded.vat_type,vat_amount=excluded.vat_amount,total_amount=excluded.total_amount,planned_date=excluded.planned_date,settled_date=excluded.settled_date,note=excluded.note,row_version=excluded.row_version,updated_at=excluded.updated_at", values)
