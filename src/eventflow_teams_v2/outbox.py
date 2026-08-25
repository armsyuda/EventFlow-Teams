"""Permission-preserving encoder and sender for Local V2 outbox rows."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from .workspace import WorkspaceDatabase


class MutationApi(Protocol):
    def apply_mutations(self, organization_id: str, mutations: list[dict[str, Any]]) -> dict[str, Any]: ...


class DeferredMutation(RuntimeError):
    """A Local operation that has no approved server contract yet."""


@dataclass(frozen=True)
class FlushResult:
    applied: int = 0
    conflicts: int = 0
    rejected: int = 0
    deferred: int = 0


class WorkspaceOutbox:
    """Convert a captured Local edit into the narrowly authorized V2 RPC call."""

    def __init__(self, database: WorkspaceDatabase) -> None:
        self.db = database

    def _remote(self, entity_type: str, local_id: int | None) -> tuple[str | None, int, str]:
        if local_id is None:
            return None, 0, ""
        row = self.db.one(
            "SELECT remote_id,remote_version,remote_updated_at FROM teams_v2_entity_map WHERE entity_type=? AND local_id=?",
            (entity_type, local_id),
        )
        return (str(row["remote_id"]), int(row["remote_version"]), str(row["remote_updated_at"])) if row else (None, 0, "")

    def _remote_reference(self, entity_type: str, local_id: Any) -> str | None:
        return self._remote(entity_type, int(local_id) if local_id is not None else None)[0]

    @staticmethod
    def _priority(value: Any) -> int:
        return {"하": -1, "중": 0, "상": 1}.get(str(value), 0)

    def encode(self, entry: dict[str, object]) -> dict[str, Any]:
        entity = str(entry["entity_type"])
        local_id = int(entry["local_id"]) if entry.get("local_id") is not None else None
        operation = str(entry["operation"])
        mutation_id = str(entry["mutation_id"])
        remote_id, version, updated_at = self._remote(entity, local_id)
        payload: dict[str, Any]

        if entity == "EVENT":
            if operation == "LOCAL_DELETE":
                if not remote_id:
                    raise DeferredMutation("아직 서버에 없는 행사입니다.")
                return {"mutation_id": mutation_id, "operation": "EVENT_ARCHIVE", "payload": {"id": remote_id, "expected_updated_at": updated_at}}
            row = self.db.one("SELECT * FROM events WHERE id=?", (local_id,))
            if not row:
                raise DeferredMutation("행사 원본을 찾을 수 없습니다.")
            if not remote_id:
                task_rows = self.db.query("SELECT * FROM event_tasks WHERE event_id=? ORDER BY sort_order,id", (local_id,))
                if not task_rows:
                    raise DeferredMutation("업무가 없는 새 행사는 아직 서버에 보낼 수 없습니다.")
                tasks = [{"master_item_id": self._remote_reference("MASTER_ITEM", task["master_item_id"]), "major": task["major"], "minor": task["minor"], "name": task["name"], "detail": task["detail"], "required": bool(task["required"]), "status": task["status"], "priority": self._priority(task["priority"]), "quantity": task["quantity"], "unit": task["unit"], "assignee_id": self._remote_reference("PERSON", task["assignee_id"]), "pm_assignee_id": self._remote_reference("PERSON", task["pm_assignee_id"]), "vendor_id": self._remote_reference("VENDOR", task["vendor_id"]), "planned_start": task["planned_start"], "due_date": task["due_date"], "unit_price": task["unit_price"], "vat_type": task["vat_type"], "is_removed": bool(task["is_removed"]), "removed_reason": task["removed_reason"], "note": task["note"], "completed_at": task["completed_at"], "sort_order": task["sort_order"]} for task in task_rows]
                vendors = self.db.query("SELECT vendor_id FROM event_vendors WHERE event_id=?", (local_id,))
                freelancers = self.db.query("SELECT person_id FROM event_freelancers WHERE event_id=?", (local_id,))
                return {"mutation_id": mutation_id, "operation": "EVENT_CREATE_WITH_TASKS", "payload": {"name": row["name"], "start_date": row["start_date"], "end_date": row["end_date"], "location": row["location"], "organizer": row["organizer"], "budget": row["budget"], "budget_tax_mode": row["budget_tax_mode"], "pm_vendor_id": self._remote_reference("VENDOR", row["pm_vendor_id"]), "tasks": tasks, "vendor_ids": [item for vendor in vendors if (item := self._remote_reference("VENDOR", vendor["vendor_id"]))], "freelancer_ids": [item for person in freelancers if (item := self._remote_reference("PERSON", person["person_id"]))]}}
            payload = {key: row[key] for key in ("name", "start_date", "end_date", "location", "organizer", "budget", "budget_tax_mode")}
            payload.update({"id": remote_id, "pm_vendor_id": self._remote_reference("VENDOR", row["pm_vendor_id"]), "expected_updated_at": updated_at})
            return {"mutation_id": mutation_id, "operation": "EVENT_PATCH", "payload": payload}

        if entity in {"VENDOR", "PERSON"}:
            if operation == "LOCAL_DELETE":
                if not remote_id:
                    raise DeferredMutation("아직 서버에 없는 주소록 항목입니다.")
                return {"mutation_id": mutation_id, "operation": f"{entity}_DELETE", "payload": {"id": remote_id}}
            row = self.db.one("SELECT * FROM contacts WHERE id=?", (local_id,))
            if not row:
                raise DeferredMutation("주소록 원본을 찾을 수 없습니다.")
            if entity == "VENDOR":
                return {"mutation_id": mutation_id, "operation": "VENDOR_UPSERT", "payload": {"id": remote_id, "name": row["name"], "industry": row["job_title"], "is_active": True, **({"expected_updated_at": updated_at} if remote_id and updated_at else {})}}
            return {"mutation_id": mutation_id, "operation": "PERSON_UPSERT", "payload": {"id": remote_id, "vendor_id": self._remote_reference("VENDOR", row["company_id"]), "name": row["name"], "phone": row["phone"], "job_title": row["job_title"], "role_note": row["role_note"], "is_active": True, **({"expected_updated_at": updated_at} if remote_id and updated_at else {})}}

        if entity == "MASTER_ITEM":
            if operation == "LOCAL_DELETE":
                if not remote_id:
                    raise DeferredMutation("아직 서버에 없는 기본 항목입니다.")
                return {"mutation_id": mutation_id, "operation": "MASTER_ITEM_DELETE", "payload": {"id": remote_id}}
            row = self.db.one("SELECT * FROM master_items WHERE id=?", (local_id,))
            if not row:
                raise DeferredMutation("기본 항목 원본을 찾을 수 없습니다.")
            return {"mutation_id": mutation_id, "operation": "MASTER_ITEM_UPSERT", "payload": {"id": remote_id, "major": row["major"], "minor": row["minor"], "name": row["name"], "detail": row["detail"], "priority": self._priority(row["priority"]), "quantity": row["quantity"], "unit": row["unit"], "base_unit_price": row["base_unit_price"], "default_vat_type": row["default_vat_type"], "default_vendor_id": self._remote_reference("VENDOR", row["default_vendor_id"]), "default_assignee_id": self._remote_reference("PERSON", row["default_assignee_id"]), "sort_order": row["sort_order"], "is_active": bool(row["active"]), **({"expected_updated_at": updated_at} if remote_id and updated_at else {})}}

        if entity == "EVENT_TASK":
            row = self.db.one("SELECT * FROM event_tasks WHERE id=?", (local_id,))
            if operation == "LOCAL_CREATE":
                if not row:
                    raise DeferredMutation("새 업무 원본을 찾을 수 없습니다.")
                event_id = self._remote_reference("EVENT", row["event_id"])
                if not event_id:
                    raise DeferredMutation("서버 행사 생성이 완료된 뒤 업무를 전송합니다.")
                return {"mutation_id": mutation_id, "operation": "TASK_CREATE", "payload": {"event_id": event_id, "major": row["major"], "minor": row["minor"], "name": row["name"], "detail": row["detail"]}}
            if operation == "LOCAL_DELETE":
                raise DeferredMutation("업무 영구 삭제 서버 계약은 아직 연결되지 않았습니다.")
            if not row or not remote_id:
                raise DeferredMutation("서버 업무 연결을 찾을 수 없습니다.")
            basic = {"id": remote_id, "expected_row_version": version}
            if operation == "LOCAL_TASK_PATCH":
                return {"mutation_id": mutation_id, "operation": "TASK_PATCH", "payload": {**basic, **{key: row[key] for key in ("status", "planned_start", "due_date", "note", "required", "is_removed", "removed_reason")}}}
            if operation == "LOCAL_TASK_COST":
                return {"mutation_id": mutation_id, "operation": "TASK_COST", "payload": {**basic, **{key: row[key] for key in ("quantity", "unit", "unit_price", "vat_type")}}}
            if operation == "LOCAL_TASK_CONTENT":
                return {"mutation_id": mutation_id, "operation": "TASK_CONTENT", "payload": {**basic, "name": row["name"], "detail": row["detail"]}}
            if operation == "LOCAL_TASK_ASSIGN":
                return {"mutation_id": mutation_id, "operation": "TASK_ASSIGN", "payload": {**basic, "pm_assignee_id": self._remote_reference("PERSON", row["pm_assignee_id"]), "vendor_id": self._remote_reference("VENDOR", row["vendor_id"]), "assignee_id": self._remote_reference("PERSON", row["assignee_id"])}}
            if operation == "LOCAL_TASK_STRUCTURE":
                event_id = self._remote_reference("EVENT", row["event_id"])
                if not event_id:
                    raise DeferredMutation("서버 행사 생성이 완료된 뒤 업무 구조를 전송합니다.")
                rows = self.db.query("SELECT * FROM event_tasks WHERE event_id=? ORDER BY sort_order,id", (row["event_id"],))
                tasks: list[dict[str, Any]] = []
                for task in rows:
                    remote_task_id, remote_version, _ = self._remote("EVENT_TASK", int(task["id"]))
                    if not remote_task_id:
                        raise DeferredMutation("새 업무 생성이 완료된 뒤 순서 변경을 전송합니다.")
                    tasks.append({"id": remote_task_id, "expected_row_version": remote_version, "major": task["major"], "minor": task["minor"], "sort_order": task["sort_order"]})
                return {"mutation_id": mutation_id, "operation": "TASK_STRUCTURE_SET", "payload": {"event_id": event_id, "tasks": tasks}}
            raise DeferredMutation("지원하지 않는 업무 변경입니다.")

        if entity == "EVENT_PARTICIPANTS":
            event_id = self._remote_reference("EVENT", local_id)
            if not event_id:
                raise DeferredMutation("서버 행사 생성이 완료된 뒤 참여자를 전송합니다.")
            event = self.db.one("SELECT pm_vendor_id FROM events WHERE id=?", (local_id,))
            vendors = self.db.query("SELECT vendor_id FROM event_vendors WHERE event_id=?", (local_id,))
            freelancers = self.db.query("SELECT person_id FROM event_freelancers WHERE event_id=?", (local_id,))
            return {"mutation_id": mutation_id, "operation": "PARTICIPANTS_SET", "payload": {"event_id": event_id, "pm_vendor_id": self._remote_reference("VENDOR", event["pm_vendor_id"] if event else None), "vendor_ids": [item for row in vendors if (item := self._remote_reference("VENDOR", row["vendor_id"]))], "freelancer_ids": [item for row in freelancers if (item := self._remote_reference("PERSON", row["person_id"]))]}}

        raise DeferredMutation(f"지원하지 않는 대기열 항목입니다: {entity}")

    def flush(self, api: MutationApi, organization_id: str, *, limit: int = 25) -> FlushResult:
        result = FlushResult()
        for entry in self.db.pending_outbox()[:max(1, limit)]:
            try:
                mutation = self.encode(entry)
            except DeferredMutation as exc:
                self._record_error(int(entry["id"]), str(exc), status="DEFERRED")
                result = FlushResult(result.applied, result.conflicts, result.rejected, result.deferred + 1)
                continue
            try:
                response = api.apply_mutations(organization_id, [mutation])
                item = next((value for value in response.get("results", []) if isinstance(value, dict)), None)
                if not item:
                    raise RuntimeError("서버 저장 결과가 비어 있습니다.")
            except Exception as exc:
                self._record_error(int(entry["id"]), str(exc), status="PENDING")
                break
            status = str(item.get("status") or "REJECTED")
            if status == "APPLIED":
                self._mark_applied(entry, item, response.get("cursor"))
                result = FlushResult(result.applied + 1, result.conflicts, result.rejected, result.deferred)
            elif status == "CONFLICT":
                self._record_conflict(entry, item)
                result = FlushResult(result.applied, result.conflicts + 1, result.rejected, result.deferred)
            else:
                self._record_error(int(entry["id"]), str(item.get("reason") or "서버에서 변경을 거부했습니다."), status="REJECTED")
                result = FlushResult(result.applied, result.conflicts, result.rejected + 1, result.deferred)
        return result

    def next_mutation(self) -> tuple[dict[str, object], dict[str, Any]] | None:
        """Return one sendable change without touching the network.

        The Qt sync coordinator calls this on the UI thread, then performs the
        HTTP call in a worker thread.  SQLite therefore always remains owned by
        the Local window thread and no modal/loading window is necessary.
        Deferred rows are reconsidered: a preceding event/contact creation may
        have supplied the missing server ID since the previous attempt.
        """
        rows = self.db.query(
            "SELECT * FROM teams_v2_outbox WHERE status IN ('PENDING','DEFERRED') ORDER BY id"
        )
        for row in rows:
            entry = dict(row)
            try:
                return entry, self.encode(entry)
            except DeferredMutation as exc:
                self._record_error(int(entry["id"]), str(exc), status="DEFERRED")
        return None

    def record_transport_failure(self, entry: dict[str, object], error: str) -> None:
        """Keep a local edit queued after an offline or temporary API error."""
        self._record_error(int(entry["id"]), error, status="PENDING")
        self.db.conn.execute(
            "UPDATE teams_v2_workspace SET sync_state='WAITING' WHERE singleton=1"
        )
        self.db.conn.commit()

    def apply_response(self, entry: dict[str, object], response: dict[str, Any]) -> str:
        """Apply a single RPC result on the SQLite-owning thread."""
        item = next((value for value in response.get("results", []) if isinstance(value, dict)), None)
        if not item:
            self.record_transport_failure(entry, "서버 저장 결과가 비어 있습니다.")
            return "WAITING"
        status = str(item.get("status") or "REJECTED")
        if status == "APPLIED":
            self._mark_applied(entry, item, response.get("cursor"))
            return "APPLIED"
        if status == "CONFLICT":
            self._record_conflict(entry, item)
            return "CONFLICT"
        self._record_error(int(entry["id"]), str(item.get("reason") or "서버에서 변경을 거부했습니다."), status="REJECTED")
        return "REJECTED"

    def resolve_conflict(self, conflict_id: int, *, keep_local: bool) -> None:
        """Resolve an explicit user choice without silently overwriting data."""
        conflict = self.db.one("SELECT * FROM teams_v2_conflicts WHERE id=? AND status='OPEN'", (conflict_id,))
        if not conflict:
            return
        entity_type = str(conflict["entity_type"])
        local_id = conflict["local_id"]
        server = json.loads(str(conflict["server_payload_json"] or "{}"))
        outbox = self.db.one(
            "SELECT * FROM teams_v2_outbox WHERE entity_type=? AND local_id=? AND status='CONFLICT' ORDER BY id DESC LIMIT 1",
            (entity_type, local_id),
        )
        if keep_local and outbox and local_id is not None and server.get("id"):
            self.db.conn.execute(
                "INSERT INTO teams_v2_entity_map(entity_type,local_id,remote_id,remote_version,remote_updated_at) VALUES (?,?,?,?,?) "
                "ON CONFLICT(entity_type,local_id) DO UPDATE SET remote_id=excluded.remote_id,remote_version=excluded.remote_version,remote_updated_at=excluded.remote_updated_at",
                (entity_type, int(local_id), str(server["id"]), int(server.get("row_version") or 0), str(server.get("updated_at") or "")),
            )
            self.db.conn.execute(
                "INSERT INTO teams_v2_outbox(mutation_id,entity_type,local_id,operation,payload_json,base_version,status) VALUES (?,?,?,?,?,?, 'PENDING')",
                (str(uuid.uuid4()), entity_type, int(local_id), str(outbox["operation"]), str(outbox["payload_json"]), int(server.get("row_version") or 0)),
            )
        if outbox:
            self.db.conn.execute("UPDATE teams_v2_outbox SET status='DISCARDED',last_error='' WHERE id=?", (int(outbox["id"]),))
        self.db.conn.execute("UPDATE teams_v2_conflicts SET status=? WHERE id=?", ("KEEP_LOCAL" if keep_local else "SERVER", conflict_id))
        self.db.conn.commit()

    def _record_error(self, outbox_id: int, error: str, *, status: str) -> None:
        self.db.conn.execute("UPDATE teams_v2_outbox SET status=?,attempts=attempts+1,last_error=? WHERE id=?", (status, error, outbox_id))
        self.db.conn.commit()

    def _record_conflict(self, entry: dict[str, object], item: dict[str, Any]) -> None:
        self.db.conn.execute("UPDATE teams_v2_outbox SET status='CONFLICT',last_error=? WHERE id=?", (str(item.get("reason") or "동시 수정 충돌"), int(entry["id"])))
        self.db.conn.execute("INSERT INTO teams_v2_conflicts(entity_type,local_id,server_payload_json,local_payload_json) VALUES (?,?,?,?)", (str(entry["entity_type"]), entry.get("local_id"), json.dumps(item.get("entity") or {}, ensure_ascii=False), str(entry.get("payload_json") or "{}")))
        self.db.conn.commit()

    def _mark_applied(self, entry: dict[str, object], item: dict[str, Any], cursor: Any) -> None:
        entity = item.get("entity") if isinstance(item.get("entity"), dict) else None
        if entity and entry.get("local_id") is not None and entity.get("id"):
            entity_type = str(item.get("entity_type") or entry["entity_type"])
            version = int(entity.get("row_version") or 0)
            self.db.conn.execute(
                "INSERT INTO teams_v2_entity_map(entity_type,local_id,remote_id,remote_version,remote_updated_at) VALUES (?,?,?,?,?) "
                "ON CONFLICT(entity_type,local_id) DO UPDATE SET remote_id=excluded.remote_id,remote_version=excluded.remote_version,remote_updated_at=excluded.remote_updated_at",
                (entity_type, int(entry["local_id"]), str(entity["id"]), version, str(entity.get("updated_at") or "")),
            )
        entities = item.get("entities") if isinstance(item.get("entities"), list) else []
        for changed in entities:
            if not isinstance(changed, dict) or not changed.get("id"):
                continue
            self.db.conn.execute(
                "UPDATE teams_v2_entity_map SET remote_version=?,remote_updated_at=? WHERE entity_type='EVENT_TASK' AND remote_id=?",
                (int(changed.get("row_version") or 0), str(changed.get("updated_at") or ""), str(changed["id"])),
            )
        if str(entry.get("operation")) == "LOCAL_TASK_STRUCTURE" and entry.get("local_id") is not None:
            task = self.db.one("SELECT event_id FROM event_tasks WHERE id=?", (int(entry["local_id"]),))
            if task:
                self.db.conn.execute(
                    "UPDATE teams_v2_outbox SET status='APPLIED',last_error='' WHERE status='PENDING' AND operation='LOCAL_TASK_STRUCTURE' AND local_id IN (SELECT id FROM event_tasks WHERE event_id=?)",
                    (int(task["event_id"]),),
                )
        self.db.conn.execute("UPDATE teams_v2_outbox SET status='APPLIED',last_error='' WHERE id=?", (int(entry["id"]),))
        self.db.conn.execute("UPDATE teams_v2_workspace SET remote_cursor=?,last_sync_at=CURRENT_TIMESTAMP,sync_state='SYNCED' WHERE singleton=1", (str(cursor or "0"),))
        self.db.conn.commit()
