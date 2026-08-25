"""V2-only bridge between the server workspace contract and Local SQLite.

This module owns ID translation.  The Local baseline continues to use integer
IDs while the server uses UUIDs, and neither side leaks its identifier format
into the Local screens.
"""

from __future__ import annotations

from typing import Any, Iterable

from .workspace import WorkspaceDatabase


def _items(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _priority(value: Any) -> str:
    if value in ("상", "중", "하"):
        return str(value)
    return "상" if isinstance(value, int) and value > 0 else "중"


class WorkspaceSnapshotStore:
    """Apply a permission-filtered server snapshot without generating local writes."""

    def __init__(self, database: WorkspaceDatabase) -> None:
        self.db = database

    def _remote_id(self, entity_type: str, local_id: int | None) -> str | None:
        if local_id is None:
            return None
        row = self.db.one(
            "SELECT remote_id FROM teams_v2_entity_map WHERE entity_type=? AND local_id=?",
            (entity_type, int(local_id)),
        )
        return str(row["remote_id"]) if row else None

    def _map(self, entity_type: str, local_id: int, remote_id: str, version: int = 0, updated_at: str = "") -> None:
        self.db.conn.execute(
            "INSERT INTO teams_v2_entity_map(entity_type,local_id,remote_id,remote_version,remote_updated_at) VALUES (?,?,?,?,?) "
            "ON CONFLICT(entity_type,local_id) DO UPDATE SET remote_id=excluded.remote_id,remote_version=excluded.remote_version,remote_updated_at=excluded.remote_updated_at",
            (entity_type, local_id, remote_id, max(0, version), updated_at),
        )

    def apply_snapshot(self, snapshot: dict[str, Any]) -> None:
        """Replace only the synchronized work domain with a complete snapshot.

        A first V2 workspace contains Local sample data because the baseline
        database seeds itself.  It is deliberately removed here, under capture
        suppression, before any server records are imported.
        """
        events = _items(snapshot.get("events"))
        vendors = _items(snapshot.get("vendors"))
        people = _items(snapshot.get("people"))
        master_items = _items(snapshot.get("master_items"))
        tasks = _items(snapshot.get("event_tasks"))
        with self.db.applying_remote_changes():
            conn = self.db.conn
            conn.execute("DELETE FROM event_vendors")
            conn.execute("DELETE FROM event_freelancers")
            conn.execute("DELETE FROM event_tasks")
            conn.execute("DELETE FROM events")
            conn.execute("DELETE FROM master_items")
            conn.execute("DELETE FROM contacts")
            conn.execute("DELETE FROM teams_v2_entity_map")
            conn.execute("DELETE FROM teams_v2_tombstones")

            for vendor in vendors:
                cursor = conn.execute(
                    "INSERT INTO contacts(kind,name,phone,job_title,role_note) VALUES ('VENDOR',?,?,?,?)",
                    (str(vendor.get("name") or "업체"), "", str(vendor.get("industry") or ""), "",),
                )
                self._map("VENDOR", int(cursor.lastrowid), str(vendor["id"]), updated_at=str(vendor.get("updated_at") or ""))
            for person in people:
                company_id = self._local_id("VENDOR", person.get("vendor_id"))
                cursor = conn.execute(
                    "INSERT INTO contacts(kind,name,phone,job_title,role_note,company_id) VALUES ('PERSON',?,?,?,?,?)",
                    (str(person.get("name") or "담당자"), str(person.get("phone") or ""), str(person.get("job_title") or ""), str(person.get("role_note") or ""), company_id),
                )
                self._map("PERSON", int(cursor.lastrowid), str(person["id"]), updated_at=str(person.get("updated_at") or ""))
            for item in master_items:
                cursor = conn.execute(
                    "INSERT INTO master_items(major,minor,name,detail,priority,quantity,unit,base_unit_price,default_vat_type,default_vendor_id,default_assignee_id,sort_order,active) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (str(item.get("major") or "기본"), str(item.get("minor") or "기타"), str(item.get("name") or "항목"), str(item.get("detail") or ""), _priority(item.get("priority")), item.get("quantity"), str(item.get("unit") or ""), item.get("base_unit_price"), str(item.get("default_vat_type") or "TAXABLE"), self._local_id("VENDOR", item.get("default_vendor_id")), self._local_id("PERSON", item.get("default_assignee_id")), int(item.get("sort_order") or 0), 1 if item.get("is_active", True) else 0),
                )
                self._map("MASTER_ITEM", int(cursor.lastrowid), str(item["id"]), updated_at=str(item.get("updated_at") or ""))
            for event in events:
                cursor = conn.execute(
                    "INSERT INTO events(name,start_date,end_date,location,organizer,budget,budget_tax_mode,pm_vendor_id) VALUES (?,?,?,?,?,?,?,?)",
                    (str(event.get("name") or "행사"), str(event.get("start_date") or "1970-01-01"), event.get("end_date"), str(event.get("location") or ""), str(event.get("organizer") or ""), event.get("budget"), str(event.get("budget_tax_mode") or "UNSET"), self._local_id("VENDOR", event.get("pm_vendor_id"))),
                )
                self._map("EVENT", int(cursor.lastrowid), str(event["id"]), updated_at=str(event.get("updated_at") or ""))
            for task in tasks:
                cursor = conn.execute(
                    "INSERT INTO event_tasks(event_id,master_item_id,major,minor,name,detail,required,status,priority,quantity,unit,assignee_id,pm_assignee_id,vendor_id,planned_start,due_date,unit_price,vat_type,is_removed,removed_reason,note,completed_at,sort_order) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (self._local_id("EVENT", task.get("event_id")), self._local_id("MASTER_ITEM", task.get("master_item_id")), str(task.get("major") or "기본"), str(task.get("minor") or "기타"), str(task.get("name") or "항목"), str(task.get("detail") or ""), 1 if task.get("required", True) else 0, str(task.get("status") or "미착수"), _priority(task.get("priority")), task.get("quantity"), str(task.get("unit") or ""), self._local_id("PERSON", task.get("assignee_id")), self._local_id("PERSON", task.get("pm_assignee_id")), self._local_id("VENDOR", task.get("vendor_id")), task.get("planned_start"), task.get("due_date"), task.get("unit_price"), str(task.get("vat_type") or "TAXABLE"), 1 if task.get("is_removed", False) else 0, str(task.get("removed_reason") or ""), str(task.get("note") or ""), task.get("completed_at"), int(task.get("sort_order") or 0)),
                )
                self._map("EVENT_TASK", int(cursor.lastrowid), str(task["id"]), int(task.get("row_version") or 0), str(task.get("updated_at") or ""))
            self._apply_links(_items(snapshot.get("event_vendors")), "event_vendors", "vendor_id", "VENDOR")
            self._apply_links(_items(snapshot.get("event_freelancers")), "event_freelancers", "person_id", "PERSON")
            conn.execute(
                "UPDATE teams_v2_workspace SET remote_cursor=?, last_sync_at=CURRENT_TIMESTAMP, sync_state='SYNCED' WHERE singleton=1",
                (str(snapshot.get("cursor") or "0"),),
            )

    def apply_changes(self, response: dict[str, Any]) -> int:
        """Merge a server changes response without replacing the Local workspace.

        This is deliberately data-only.  Realtime notification, UI highlights,
        and conflict decisions are later-stage concerns; this method merely
        guarantees that a received authorized change cannot create an outbox
        echo or cross-company reference.
        """
        changes = _items(response.get("changes"))
        with self.db.applying_remote_changes():
            for change in changes:
                entity_type = str(change.get("entity_type") or "")
                payload = change.get("payload") if isinstance(change.get("payload"), dict) else {}
                if str(change.get("operation")) == "DELETE":
                    self._delete_remote(entity_type, str(change.get("entity_key") or payload.get("id") or ""), payload)
                    continue
                if entity_type == "VENDOR": self._upsert_vendor(payload)
                elif entity_type == "PERSON": self._upsert_person(payload)
                elif entity_type == "MASTER_ITEM": self._upsert_master(payload)
                elif entity_type == "EVENT": self._upsert_event(payload)
                elif entity_type == "EVENT_TASK": self._upsert_task(payload)
                elif entity_type == "EVENT_VENDOR": self._upsert_link(payload, "event_vendors", "vendor_id", "VENDOR")
                elif entity_type == "EVENT_FREELANCER": self._upsert_link(payload, "event_freelancers", "person_id", "PERSON")
            self.db.conn.execute(
                "UPDATE teams_v2_workspace SET remote_cursor=?,last_sync_at=CURRENT_TIMESTAMP,sync_state='SYNCED' WHERE singleton=1",
                (str(response.get("cursor") or "0"),),
            )
        return len(changes)

    def _mapped_local(self, entity_type: str, remote_id: Any) -> int | None:
        return self._local_id(entity_type, remote_id)

    def _delete_remote(self, entity_type: str, remote_id: str, payload: dict[str, Any]) -> None:
        if not remote_id:
            return
        if entity_type == "EVENT_VENDOR":
            event_id = self._local_id("EVENT", payload.get("event_id")); vendor_id = self._local_id("VENDOR", payload.get("vendor_id"))
            if event_id is not None and vendor_id is not None: self.db.conn.execute("DELETE FROM event_vendors WHERE event_id=? AND vendor_id=?", (event_id, vendor_id))
            return
        if entity_type == "EVENT_FREELANCER":
            event_id = self._local_id("EVENT", payload.get("event_id")); person_id = self._local_id("PERSON", payload.get("person_id"))
            if event_id is not None and person_id is not None: self.db.conn.execute("DELETE FROM event_freelancers WHERE event_id=? AND person_id=?", (event_id, person_id))
            return
        local_id = self._mapped_local(entity_type, remote_id)
        tables = {"VENDOR": "contacts", "PERSON": "contacts", "MASTER_ITEM": "master_items", "EVENT": "events", "EVENT_TASK": "event_tasks"}
        if local_id is not None and entity_type in tables:
            self.db.conn.execute(f"DELETE FROM {tables[entity_type]} WHERE id=?", (local_id,))
        self.db.conn.execute("DELETE FROM teams_v2_entity_map WHERE entity_type=? AND remote_id=?", (entity_type, remote_id))
        self.db.conn.execute("INSERT OR REPLACE INTO teams_v2_tombstones(entity_type,remote_id) VALUES (?,?)", (entity_type, remote_id))

    def _upsert_vendor(self, item: dict[str, Any]) -> None:
        remote_id = str(item.get("id") or "")
        if not remote_id: return
        local_id = self._mapped_local("VENDOR", remote_id)
        values = (str(item.get("name") or "업체"), str(item.get("industry") or ""), local_id)
        if local_id is None:
            cursor = self.db.conn.execute("INSERT INTO contacts(kind,name,phone,job_title,role_note) VALUES ('VENDOR',?,?,?,?)", (values[0], "", values[1], "")); local_id = int(cursor.lastrowid)
        else: self.db.conn.execute("UPDATE contacts SET name=?,job_title=? WHERE id=?", values)
        self._map("VENDOR", local_id, remote_id, updated_at=str(item.get("updated_at") or ""))

    def _upsert_person(self, item: dict[str, Any]) -> None:
        remote_id = str(item.get("id") or "")
        if not remote_id: return
        local_id = self._mapped_local("PERSON", remote_id); vendor_id = self._local_id("VENDOR", item.get("vendor_id"))
        values = (str(item.get("name") or "담당자"), str(item.get("phone") or ""), str(item.get("job_title") or ""), str(item.get("role_note") or ""), vendor_id)
        if local_id is None:
            cursor = self.db.conn.execute("INSERT INTO contacts(kind,name,phone,job_title,role_note,company_id) VALUES ('PERSON',?,?,?,?,?)", values); local_id = int(cursor.lastrowid)
        else: self.db.conn.execute("UPDATE contacts SET name=?,phone=?,job_title=?,role_note=?,company_id=? WHERE id=?", (*values, local_id))
        self._map("PERSON", local_id, remote_id, updated_at=str(item.get("updated_at") or ""))

    def _upsert_master(self, item: dict[str, Any]) -> None:
        remote_id = str(item.get("id") or "")
        if not remote_id: return
        local_id = self._mapped_local("MASTER_ITEM", remote_id)
        values = (str(item.get("major") or "기본"), str(item.get("minor") or "기타"), str(item.get("name") or "항목"), str(item.get("detail") or ""), _priority(item.get("priority")), item.get("quantity"), str(item.get("unit") or ""), item.get("base_unit_price"), str(item.get("default_vat_type") or "TAXABLE"), self._local_id("VENDOR", item.get("default_vendor_id")), self._local_id("PERSON", item.get("default_assignee_id")), int(item.get("sort_order") or 0), 1 if item.get("is_active", True) else 0)
        if local_id is None:
            cursor = self.db.conn.execute("INSERT INTO master_items(major,minor,name,detail,priority,quantity,unit,base_unit_price,default_vat_type,default_vendor_id,default_assignee_id,sort_order,active) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", values); local_id = int(cursor.lastrowid)
        else: self.db.conn.execute("UPDATE master_items SET major=?,minor=?,name=?,detail=?,priority=?,quantity=?,unit=?,base_unit_price=?,default_vat_type=?,default_vendor_id=?,default_assignee_id=?,sort_order=?,active=? WHERE id=?", (*values, local_id))
        self._map("MASTER_ITEM", local_id, remote_id, updated_at=str(item.get("updated_at") or ""))

    def _upsert_event(self, item: dict[str, Any]) -> None:
        remote_id = str(item.get("id") or "")
        if not remote_id: return
        local_id = self._mapped_local("EVENT", remote_id)
        values = (str(item.get("name") or "행사"), str(item.get("start_date") or "1970-01-01"), item.get("end_date"), str(item.get("location") or ""), str(item.get("organizer") or ""), item.get("budget"), str(item.get("budget_tax_mode") or "UNSET"), self._local_id("VENDOR", item.get("pm_vendor_id")))
        if local_id is None:
            cursor = self.db.conn.execute("INSERT INTO events(name,start_date,end_date,location,organizer,budget,budget_tax_mode,pm_vendor_id) VALUES (?,?,?,?,?,?,?,?)", values); local_id = int(cursor.lastrowid)
        else: self.db.conn.execute("UPDATE events SET name=?,start_date=?,end_date=?,location=?,organizer=?,budget=?,budget_tax_mode=?,pm_vendor_id=? WHERE id=?", (*values, local_id))
        self._map("EVENT", local_id, remote_id, updated_at=str(item.get("updated_at") or ""))

    def _upsert_task(self, item: dict[str, Any]) -> None:
        remote_id = str(item.get("id") or "")
        if not remote_id: return
        local_id = self._mapped_local("EVENT_TASK", remote_id); event_id = self._local_id("EVENT", item.get("event_id"))
        if event_id is None: return
        values = (event_id, self._local_id("MASTER_ITEM", item.get("master_item_id")), str(item.get("major") or "기본"), str(item.get("minor") or "기타"), str(item.get("name") or "항목"), str(item.get("detail") or ""), 1 if item.get("required", True) else 0, str(item.get("status") or "미착수"), _priority(item.get("priority")), item.get("quantity"), str(item.get("unit") or ""), self._local_id("PERSON", item.get("assignee_id")), self._local_id("PERSON", item.get("pm_assignee_id")), self._local_id("VENDOR", item.get("vendor_id")), item.get("planned_start"), item.get("due_date"), item.get("unit_price"), str(item.get("vat_type") or "TAXABLE"), 1 if item.get("is_removed", False) else 0, str(item.get("removed_reason") or ""), str(item.get("note") or ""), item.get("completed_at"), int(item.get("sort_order") or 0))
        columns = "event_id,master_item_id,major,minor,name,detail,required,status,priority,quantity,unit,assignee_id,pm_assignee_id,vendor_id,planned_start,due_date,unit_price,vat_type,is_removed,removed_reason,note,completed_at,sort_order"
        if local_id is None:
            cursor = self.db.conn.execute(f"INSERT INTO event_tasks({columns}) VALUES ({','.join('?' for _ in values)})", values); local_id = int(cursor.lastrowid)
        else: self.db.conn.execute("UPDATE event_tasks SET event_id=?,master_item_id=?,major=?,minor=?,name=?,detail=?,required=?,status=?,priority=?,quantity=?,unit=?,assignee_id=?,pm_assignee_id=?,vendor_id=?,planned_start=?,due_date=?,unit_price=?,vat_type=?,is_removed=?,removed_reason=?,note=?,completed_at=?,sort_order=? WHERE id=?", (*values, local_id))
        self._map("EVENT_TASK", local_id, remote_id, int(item.get("row_version") or 0), str(item.get("updated_at") or ""))

    def _upsert_link(self, item: dict[str, Any], table: str, column: str, entity_type: str) -> None:
        event_id = self._local_id("EVENT", item.get("event_id")); reference_id = self._local_id(entity_type, item.get(column))
        if event_id is not None and reference_id is not None:
            self.db.conn.execute(f"INSERT OR IGNORE INTO {table}(event_id,{column}) VALUES (?,?)", (event_id, reference_id))

    def _local_id(self, entity_type: str, remote_id: Any) -> int | None:
        if not remote_id:
            return None
        row = self.db.one("SELECT local_id FROM teams_v2_entity_map WHERE entity_type=? AND remote_id=?", (entity_type, str(remote_id)))
        return int(row["local_id"]) if row else None

    def _apply_links(self, links: Iterable[dict[str, Any]], table: str, column: str, entity_type: str) -> None:
        for link in links:
            event_id = self._local_id("EVENT", link.get("event_id"))
            reference_id = self._local_id(entity_type, link.get(column))
            if event_id is not None and reference_id is not None:
                self.db.conn.execute(f"INSERT OR IGNORE INTO {table}(event_id,{column}) VALUES (?,?)", (event_id, reference_id))
