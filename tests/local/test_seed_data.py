from __future__ import annotations

import json
from importlib.resources import files

from event_checklist.units import COMMON_UNITS
from event_checklist.database import Database


def test_seed_has_120_clean_items():
    payload = files("event_checklist").joinpath("resources/master_items.json").read_text(encoding="utf-8")
    items = json.loads(payload)
    assert len(items) == 120
    assert {item["major"] for item in items} == {"시스템", "시설", "행사", "홍보", "운영"}
    assert any(item["name"] == "카메라다이" for item in items)
    assert any(item["name"] == "콘솔다이" for item in items)
    assert '"81"' not in payload
    assert "#NAME?" not in payload
    assert all({"anchor", "start_offset", "due_offset"}.isdisjoint(item) for item in items)


def test_database_is_seeded(db):
    assert db.one("SELECT COUNT(*) count FROM master_items")["count"] == 120
    assert db.one("SELECT COUNT(*) count FROM contacts WHERE kind='PERSON'")["count"] == 9
    assert db.one("SELECT COUNT(*) count FROM master_items WHERE TRIM(unit)='' ")["count"] == 0
    assert db.one("SELECT unit FROM master_items WHERE name='발전차'")["unit"] == "대"
    assert db.one("SELECT unit FROM master_items WHERE name='안전요원'")["unit"] == "명"
    assert {row["unit"] for row in db.query("SELECT DISTINCT unit FROM master_items")} <= set(COMMON_UNITS)
    columns = {row["name"] for row in db.query("PRAGMA table_info(master_items)")}
    assert {"anchor", "start_offset", "due_offset"}.isdisjoint(columns)


def test_contacts_allow_same_name_and_database_reopens(tmp_path):
    path = tmp_path / "same-contact-names.db"
    database = Database(path)
    first_vendor = database.execute("INSERT INTO contacts(kind,name) VALUES ('VENDOR','첫 업체')").lastrowid
    second_vendor = database.execute("INSERT INTO contacts(kind,name) VALUES ('VENDOR','둘째 업체')").lastrowid
    for vendor_id in (first_vendor, second_vendor, second_vendor):
        database.execute(
            "INSERT INTO contacts(kind,name,company_id) VALUES ('PERSON','김담당',?)",
            (vendor_id,),
        )
    database.close()

    reopened = Database(path)
    assert reopened.one(
        "SELECT COUNT(*) count FROM contacts WHERE kind='PERSON' AND name='김담당'"
    )["count"] == 3
    reopened.close()
