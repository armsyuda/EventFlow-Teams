from __future__ import annotations

import sqlite3
from datetime import date

from event_checklist.database import Database
from event_checklist.services import EventService


def test_v1_database_migrates_and_keeps_safety_copy(tmp_path):
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE schema_info(version INTEGER NOT NULL);
        INSERT INTO schema_info VALUES (1);
        CREATE TABLE master_items (
            id INTEGER PRIMARY KEY, major TEXT NOT NULL, minor TEXT NOT NULL, name TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '', anchor TEXT NOT NULL, start_offset INTEGER NOT NULL,
            due_offset INTEGER NOT NULL, priority TEXT NOT NULL DEFAULT '중', quantity REAL,
            unit TEXT NOT NULL DEFAULT '', sort_order INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1
        );
        """
    )
    conn.commit()
    conn.close()
    db = Database(path)
    columns = {row["name"] for row in db.query("PRAGMA table_info(master_items)")}
    assert {"default_vendor_id", "default_assignee_id"} <= columns
    assert db.one("SELECT version FROM schema_info")["version"] == 10
    assert {"pm_vendor_id"} <= {row["name"] for row in db.query("PRAGMA table_info(events)")}
    assert {"event_start_date", "event_end_date"}.isdisjoint({row["name"] for row in db.query("PRAGMA table_info(events)")})
    assert {"pm_assignee_id"} <= {row["name"] for row in db.query("PRAGMA table_info(event_tasks)")}
    assert db.one("SELECT COUNT(*) count FROM master_items")["count"] == 120
    db.close()
    assert (tmp_path / "legacy.pre-v1.db").exists()


def test_v6_dates_are_preserved_and_automatic_schedule_columns_are_removed(tmp_path):
    path = tmp_path / "v6.db"
    db = Database(path)
    service = EventService(db)
    masters = db.query("SELECT id FROM master_items ORDER BY sort_order LIMIT 2")
    event_id = service.create_event(
        "준비 기간 행사", date(2026, 8, 10), date(2026, 10, 2), [row["id"] for row in masters]
    )
    tasks = db.query("SELECT id FROM event_tasks WHERE event_id=? ORDER BY id", (event_id,))
    first_id, second_id = tasks[0]["id"], tasks[1]["id"]
    db.execute("UPDATE event_tasks SET planned_start='2026-08-15',due_date='2026-08-20' WHERE id=?", (first_id,))
    db.execute("UPDATE event_tasks SET planned_start=NULL,due_date=NULL WHERE id=?", (second_id,))
    db.execute("UPDATE schema_info SET version=6")
    db.close()

    migrated = Database(path)
    dated = migrated.one("SELECT planned_start,due_date FROM event_tasks WHERE id=?", (first_id,))
    blank = migrated.one("SELECT planned_start,due_date FROM event_tasks WHERE id=?", (second_id,))
    columns = {row["name"] for row in migrated.query("PRAGMA table_info(event_tasks)")}
    assert tuple(dated) == ("2026-08-15", "2026-08-20")
    assert tuple(blank) == (None, None)
    assert {"schedule_mode", "anchor", "start_offset", "due_offset"}.isdisjoint(columns)
    migrated.close()
    assert (tmp_path / "v6.pre-v6.db").exists()


def test_v3_cost_migrates_to_unit_price_and_keeps_pre_v3_copy(tmp_path):
    path = tmp_path / "event_checklist.db"
    db = Database(path); service = EventService(db)
    master = db.one("SELECT id FROM master_items ORDER BY id LIMIT 1")
    event_id = service.create_event("기존 행사", date(2026, 9, 1), None, [master["id"]])
    db.execute("UPDATE event_tasks SET quantity=4,cost=12000,unit_price=NULL WHERE event_id=?", (event_id,))
    db.execute("UPDATE schema_info SET version=3"); db.close()
    migrated = Database(path)
    assert migrated.one("SELECT unit_price FROM event_tasks WHERE event_id=?", (event_id,))["unit_price"] == 3000
    assert migrated.one("SELECT version FROM schema_info")["version"] == 10
    migrated.close()
    assert (tmp_path / "event_checklist.pre-v3.db").exists()


def test_v7_contacts_gain_blank_job_title_without_losing_existing_values(tmp_path):
    path = tmp_path / "v7-contacts.db"
    db = Database(path)
    contact_id = db.execute(
        "INSERT INTO contacts(kind,name,phone,job_title,role_note) "
        "VALUES ('PERSON','legacy person','010-1234','manager','field operation')"
    ).lastrowid
    db.execute("ALTER TABLE contacts DROP COLUMN job_title")
    db.execute("UPDATE schema_info SET version=7")
    db.close()

    migrated = Database(path)
    columns = {row["name"] for row in migrated.query("PRAGMA table_info(contacts)")}
    contact = migrated.one("SELECT name,phone,job_title,role_note FROM contacts WHERE id=?", (contact_id,))
    assert "job_title" in columns
    assert tuple(contact) == ("legacy person", "010-1234", "", "field operation")
    assert migrated.one("SELECT version FROM schema_info")["version"] == 10
    migrated.close()
    assert (tmp_path / "v7-contacts.pre-v7.db").exists()


def test_v4_blank_units_are_filled_without_overwriting_user_values(tmp_path):
    path = tmp_path / "units.db"
    db = Database(path); service = EventService(db)
    masters = db.query("SELECT id FROM master_items ORDER BY id LIMIT 2")
    event_id = service.create_event("단위 이전", date(2026, 9, 1), None, [row["id"] for row in masters])
    db.execute("UPDATE master_items SET unit='' WHERE id=?", (masters[0]["id"],))
    db.execute("UPDATE master_items SET unit='사용자단위' WHERE id=?", (masters[1]["id"],))
    db.execute("UPDATE event_tasks SET unit='' WHERE master_item_id=?", (masters[0]["id"],))
    db.execute("UPDATE schema_info SET version=4"); db.close()

    migrated = Database(path)
    assert migrated.one("SELECT unit FROM master_items WHERE id=?", (masters[0]["id"],))["unit"] == "식"
    assert migrated.one("SELECT unit FROM master_items WHERE id=?", (masters[1]["id"],))["unit"] == "사용자단위"
    assert migrated.one("SELECT unit FROM event_tasks WHERE event_id=? AND master_item_id=?", (event_id, masters[0]["id"]))["unit"] == "식"
    migrated.close()
    assert (tmp_path / "units.pre-v4.db").exists()
