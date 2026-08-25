from __future__ import annotations

from datetime import date

import pytest

from event_checklist.services import EventService


def test_create_event_only_selected_and_snapshot_is_stable(db):
    service = EventService(db)
    masters = db.query("SELECT * FROM master_items ORDER BY sort_order LIMIT 3")
    event_id = service.create_event("테스트 행사", date(2026, 10, 2), date(2026, 10, 3), [masters[0]["id"], masters[2]["id"]])
    tasks = service.list_tasks(event_id)
    assert len(tasks) == 2
    first_name = tasks[0]["name"]
    db.execute("UPDATE master_items SET name='변경된 기본 항목' WHERE id=?", (masters[0]["id"],))
    assert service.list_tasks(event_id)[0]["name"] == first_name


def test_event_start_and_end_dates_are_validated(db):
    service = EventService(db)
    master = db.one("SELECT id FROM master_items ORDER BY sort_order LIMIT 1")
    event_id = service.create_event(
        "3일 행사", date(2026, 9, 10), date(2026, 9, 12), [master["id"]],
    )
    event = service.get_event(event_id)
    assert (event["start_date"], event["end_date"]) == ("2026-09-10", "2026-09-12")
    with pytest.raises(ValueError, match="행사 마감일"):
        service.update_event(
            event_id, "3일 행사", date(2026, 9, 12), date(2026, 9, 10),
        )


def test_tasks_and_calendar_filter_vendor_and_pm_independently(db):
    service = EventService(db)
    masters = db.query("SELECT id FROM master_items ORDER BY sort_order LIMIT 3")
    event_id = service.create_event(
        "업체 PM 필터", date(2026, 10, 1), date(2026, 10, 31), [row["id"] for row in masters]
    )
    vendor_a = db.execute("INSERT INTO contacts(kind,name) VALUES ('VENDOR','가 업체')").lastrowid
    vendor_b = db.execute("INSERT INTO contacts(kind,name) VALUES ('VENDOR','나 업체')").lastrowid
    pm_a = db.execute("INSERT INTO contacts(kind,name) VALUES ('PERSON','김 PM')").lastrowid
    pm_b = db.execute("INSERT INTO contacts(kind,name) VALUES ('PERSON','이 PM')").lastrowid
    tasks = service.list_tasks(event_id)
    assignments = [
        (vendor_a, pm_a),
        (vendor_b, pm_a),
        (vendor_b, pm_b),
    ]
    for task, (vendor_id, pm_id) in zip(tasks, assignments):
        db.execute(
            """UPDATE event_tasks SET vendor_id=?,pm_assignee_id=?,planned_start='2026-10-01',
               due_date='2026-10-03' WHERE id=?""",
            (vendor_id, pm_id, task["id"]),
        )

    assert {row["id"] for row in service.list_tasks(event_id, vendor_id=vendor_a)} == {tasks[0]["id"]}
    assert {row["id"] for row in service.list_tasks(event_id, pm_assignee_id=pm_a)} == {
        tasks[0]["id"], tasks[1]["id"],
    }
    assert {row["id"] for row in service.list_tasks(
        event_id, vendor_id=vendor_b, pm_assignee_id=pm_b,
    )} == {tasks[2]["id"]}
    assert {row["id"] for row in service.calendar_range(
        date(2026, 10, 1), date(2026, 10, 31), event_id, vendor_id=vendor_b,
    )} == {tasks[1]["id"], tasks[2]["id"]}


def test_create_event_can_copy_previous_items_with_optional_prices(db):
    service = EventService(db)
    masters = db.query("SELECT id FROM master_items ORDER BY sort_order LIMIT 2")
    source_id = service.create_event(
        "복사 원본", date(2026, 8, 1), date(2026, 8, 2), [row["id"] for row in masters]
    )
    source_tasks = service.list_tasks(source_id)
    service.update_task(
        source_tasks[0]["id"], name="수정된 항목", detail="원본 세부내용", quantity=9, unit="식",
        unit_price=123456, vat_type="EXEMPT", status="완료",
        planned_start="2026-07-01", due_date="2026-07-02",
    )
    custom_id = service.add_custom_task(
        source_id, major="운영", minor="현장", name="원본 직접 항목", detail="직접 추가한 내용",
        quantity=4, unit="회", unit_price=76543, vat_type="TAXABLE",
    )
    service.set_task_removed([source_tasks[1]["id"]], True, "이번 행사 제외")
    active_ids = [source_tasks[0]["id"], custom_id]

    item_only_id = service.create_event(
        "항목만 복사", date(2026, 9, 1), None, [], source_event_id=source_id,
        source_task_ids=active_ids, copy_settlement_prices=False,
    )
    item_only = service.list_tasks(item_only_id)
    assert [(row["name"], row["detail"]) for row in item_only] == [
        ("수정된 항목", "원본 세부내용"), ("원본 직접 항목", "직접 추가한 내용")
    ]
    assert {row["quantity"] for row in item_only} == {1}
    assert {row["unit_price"] for row in item_only} == {0}
    assert {row["status"] for row in item_only} == {"미착수"}
    assert {(row["planned_start"], row["due_date"]) for row in item_only} == {(None, None)}
    assert {(row["assignee_id"], row["pm_assignee_id"], row["vendor_id"]) for row in item_only} == {
        (None, None, None)
    }

    with_prices_id = service.create_event(
        "정산도 복사", date(2026, 10, 1), None, [], source_event_id=source_id,
        source_task_ids=active_ids, copy_settlement_prices=True,
    )
    with_prices = service.list_tasks(with_prices_id)
    assert [(row["quantity"], row["unit_price"], row["vat_type"]) for row in with_prices] == [
        (1, 123456, "EXEMPT"), (1, 76543, "TAXABLE")
    ]


def test_previous_event_copy_rejects_removed_or_foreign_tasks(db):
    service = EventService(db)
    master = db.one("SELECT id FROM master_items ORDER BY sort_order LIMIT 1")
    source_id = service.create_event("원본", date(2026, 8, 1), None, [master["id"]])
    other_id = service.create_event("다른 행사", date(2026, 8, 2), None, [master["id"]])
    foreign_task = service.list_tasks(other_id)[0]
    with pytest.raises(ValueError, match="가져올 수 없는"):
        service.create_event(
            "잘못된 복사", date(2026, 9, 1), None, [], source_event_id=source_id,
            source_task_ids=[foreign_task["id"]],
        )


def test_new_event_tasks_start_with_blank_dates_and_can_be_filled_or_cleared(db):
    service = EventService(db)
    masters = db.query("SELECT id FROM master_items ORDER BY sort_order LIMIT 2")
    event_id = service.create_event(
        "빈 일정 행사", date(2026, 10, 2), date(2026, 10, 3), [row["id"] for row in masters]
    )
    tasks = service.list_tasks(event_id)
    assert {(task["planned_start"], task["due_date"]) for task in tasks} == {(None, None)}
    assert service.dashboard(event_id)["urgent"] == []
    assert service.calendar_tasks(date(2026, 10, 2), event_id) == []
    assert service.calendar_range(date(2026, 10, 1), date(2026, 10, 31), event_id) == []
    service.update_task(tasks[0]["id"], planned_start="2026-09-01", due_date="2026-09-05")
    service.update_task(tasks[0]["id"], planned_start=None, due_date=None)
    cleared = db.one("SELECT planned_start,due_date FROM event_tasks WHERE id=?", (tasks[0]["id"],))
    assert tuple(cleared) == (None, None)


def test_legacy_inactive_master_remains_available_without_use_checkbox(db):
    service = EventService(db)
    master = db.one("SELECT id FROM master_items ORDER BY id LIMIT 1")
    db.execute("UPDATE master_items SET active=0 WHERE id=?", (master["id"],))
    event_id = service.create_event("사용 열 제거", date(2026, 10, 2), None, [master["id"]])
    assert db.one("SELECT COUNT(*) count FROM event_tasks WHERE event_id=?", (event_id,))["count"] == 1


def test_event_date_change_preserves_all_manually_managed_task_dates(db):
    service = EventService(db)
    masters = db.query("SELECT * FROM master_items ORDER BY sort_order LIMIT 2")
    event_id = service.create_event("일정 행사", date(2026, 6, 1), None, [row["id"] for row in masters])
    tasks = service.list_tasks(event_id)
    manual_id = tasks[0]["id"]
    other_id = tasks[1]["id"]
    service.update_task(manual_id, planned_start="2026-05-01", due_date="2026-05-15")
    old_other = db.one("SELECT planned_start,due_date FROM event_tasks WHERE id=?", (other_id,))
    service.update_event(event_id, "일정 행사", date(2026, 6, 11), None)
    manual = db.one("SELECT planned_start,due_date FROM event_tasks WHERE id=?", (manual_id,))
    other = db.one("SELECT planned_start,due_date FROM event_tasks WHERE id=?", (other_id,))
    assert tuple(manual) == ("2026-05-01", "2026-05-15")
    assert tuple(other) == tuple(old_other)


def test_progress_excludes_not_applicable(db):
    service = EventService(db)
    ids = [row["id"] for row in db.query("SELECT id FROM master_items ORDER BY id LIMIT 3")]
    event_id = service.create_event("진행률 행사", date.today(), None, ids)
    tasks = service.list_tasks(event_id)
    service.set_completed(tasks[0]["id"], True)
    service.update_task(tasks[1]["id"], status="해당없음")
    result = service.dashboard(event_id)
    assert result["managed"] == 2
    assert result["completed"] == 1
    assert result["progress"] == 0.5


def test_master_defaults_copy_to_new_event(db):
    service = EventService(db)
    master = db.one("SELECT id FROM master_items ORDER BY id LIMIT 1")
    person = db.one("SELECT id FROM contacts WHERE kind='PERSON' ORDER BY id LIMIT 1")
    vendor = db.one("SELECT id FROM contacts WHERE kind='VENDOR' ORDER BY id LIMIT 1")
    db.execute(
        "UPDATE master_items SET quantity=7,unit='대',default_assignee_id=?,default_vendor_id=? WHERE id=?",
        (person["id"], vendor["id"], master["id"]),
    )
    event_id = service.create_event("기본값 행사", date(2026, 9, 1), None, [master["id"]])
    task = db.one("SELECT quantity,unit,assignee_id,vendor_id FROM event_tasks WHERE event_id=?", (event_id,))
    assert (task["quantity"], task["unit"], task["assignee_id"], task["vendor_id"]) == (
        7, "대", person["id"], vendor["id"]
    )


def test_price_vat_snapshot_and_round_half_up(db):
    service = EventService(db)
    master = db.one("SELECT id FROM master_items ORDER BY id LIMIT 1")
    db.execute("UPDATE master_items SET quantity=2.5,base_unit_price=333,default_vat_type='TAXABLE' WHERE id=?", (master["id"],))
    event_id = service.create_event("정산 행사", date(2026, 9, 1), None, [master["id"]], budget=1000, budget_tax_mode="INCLUDED")
    task = service.list_tasks(event_id)[0]
    assert (task["unit_price"], task["vat_type"]) == (333, "TAXABLE")
    assert service.line_amounts(task["quantity"], task["unit_price"], task["vat_type"]) == (833, 83, 916)
    summary = service.settlement_summary(event_id)
    assert (summary["supply"], summary["vat"], summary["total"], summary["difference"]) == (833, 83, 916, 84)
    assert summary["comparison"] == 916
    db.execute("UPDATE events SET budget_tax_mode='EXCLUDED' WHERE id=?", (event_id,))
    excluded = service.settlement_summary(event_id)
    assert (excluded["comparison"], excluded["difference"]) == (833, 167)
    db.execute("UPDATE events SET budget_tax_mode='UNSET' WHERE id=?", (event_id,))
    unset = service.settlement_summary(event_id)
    assert unset["comparison"] is unset["difference"] is None


def test_import_remove_restore_and_custom_task(db):
    service = EventService(db)
    masters = db.query("SELECT id FROM master_items ORDER BY id LIMIT 2")
    event_id = service.create_event("항목 관리", date(2026, 9, 1), None, [masters[0]["id"]])
    added, restored = service.add_master_tasks(event_id, [masters[1]["id"]])
    assert (added, restored) == (1, 0)
    task = db.one("SELECT id FROM event_tasks WHERE event_id=? AND master_item_id=?", (event_id, masters[1]["id"]))
    service.update_task(task["id"], status="진행중", note="보존 기록")
    service.set_task_removed([task["id"]], True, "이번 행사에는 불필요")
    assert db.one("SELECT removed_reason FROM event_tasks WHERE id=?", (task["id"],))["removed_reason"] == "이번 행사에는 불필요"
    assert len(service.list_tasks(event_id)) == 1
    assert service.add_master_tasks(event_id, [masters[1]["id"]]) == (0, 1)
    restored_task = db.one("SELECT status,note,is_removed,removed_reason FROM event_tasks WHERE id=?", (task["id"],))
    assert tuple(restored_task) == ("진행중", "보존 기록", 0, "")
    custom_id = service.add_custom_task(event_id, major="운영", minor="현장", name="일회성",
                                        planned_start=date(2026, 9, 1), due_date=date(2026, 9, 2))
    custom = db.one("SELECT master_item_id,quantity FROM event_tasks WHERE id=?", (custom_id,))
    assert tuple(custom) == (None, 1)


def test_item_management_flow_preserves_details_and_keeps_price_for_settlement_only(db):
    service = EventService(db)
    master = db.one("SELECT id FROM master_items ORDER BY sort_order LIMIT 1")
    event_id = service.create_event("항목 흐름 검증", date(2026, 9, 1), None, [master["id"]])
    custom_id = service.add_custom_task(
        event_id, major="운영", minor="기타", name="직접 추가 항목", detail="현장 확인 세부내용",
        quantity=2, unit="식", unit_price=50000, vat_type="TAXABLE",
    )
    custom = db.one(
        "SELECT name,detail,planned_start,due_date,unit_price,is_removed FROM event_tasks WHERE id=?",
        (custom_id,),
    )
    assert tuple(custom) == ("직접 추가 항목", "현장 확인 세부내용", None, None, 50000, 0)
    service.update_task(custom_id, detail="수정된 세부내용", quantity=3)
    service.set_task_removed([custom_id], True)
    assert service.list_tasks(event_id) and all(row["id"] != custom_id for row in service.list_tasks(event_id))
    service.set_task_removed([custom_id], False)
    restored = next(row for row in service.list_tasks(event_id) if row["id"] == custom_id)
    assert (restored["detail"], restored["quantity"], restored["unit_price"]) == ("수정된 세부내용", 3, 50000)
    settlement = service.settlement_summary(event_id)
    item = next(row for row in settlement["items"] if row["id"] == custom_id)
    assert (item["unit_price"], item["supply"], item["vat"], item["total"]) == (50000, 150000, 15000, 165000)


def test_checklist_keeps_categories_contiguous_and_custom_item_inside_group(db):
    service = EventService(db)
    master_ids = [row["id"] for row in db.query("SELECT id FROM master_items ORDER BY sort_order")]
    event_id = service.create_event("분류 정렬", date(2026, 9, 1), date(2026, 9, 8), master_ids)
    custom_id = service.add_custom_task(
        event_id, major="운영", minor="현장", name="추가 운영 항목",
        planned_start=date(2026, 9, 1), due_date=date(2026, 9, 1),
    )
    db.execute(
        "UPDATE event_tasks SET due_date='2099-12-31' WHERE event_id=? AND major='운영' AND id<>?",
        (event_id, custom_id),
    )

    rows = service.list_tasks(event_id)
    majors = [row["major"] for row in rows]
    for major in set(majors):
        positions = [index for index, value in enumerate(majors) if value == major]
        assert positions == list(range(min(positions), max(positions) + 1))
    custom_position = next(index for index, row in enumerate(rows) if row["id"] == custom_id)
    assert majors[custom_position] == "운영"


def test_event_participants_and_company_assignees(db):
    service = EventService(db)
    vendor = db.one("SELECT id FROM contacts WHERE kind='VENDOR' ORDER BY id LIMIT 1")
    db.execute("INSERT INTO contacts(kind,name,company_id) VALUES ('PERSON','업체 담당자',?)", (vendor["id"],))
    person_id = db.one("SELECT last_insert_rowid() id")["id"]
    freelancer = db.one("SELECT id FROM contacts WHERE kind='PERSON' AND company_id IS NULL ORDER BY id LIMIT 1")
    master = db.one("SELECT id FROM master_items ORDER BY id LIMIT 1")
    event_id = service.create_event("참여자 행사", date(2026, 9, 1), None, [master["id"]],
                                    vendor_ids=[vendor["id"]], freelancer_ids=[freelancer["id"]])
    available = {row["id"] for row in service.available_assignees(event_id, vendor["id"])}
    assert {person_id, freelancer["id"]} <= available


def test_bulk_assignment_updates_selected_tasks_atomically_and_validates_companies(db, tmp_path):
    service = EventService(db)
    pm_vendor = db.execute("INSERT INTO contacts(kind,name) VALUES ('VENDOR','일괄 PM 업체')").lastrowid
    work_vendor = db.execute("INSERT INTO contacts(kind,name) VALUES ('VENDOR','일괄 실행 업체')").lastrowid
    other_vendor = db.execute("INSERT INTO contacts(kind,name) VALUES ('VENDOR','다른 실행 업체')").lastrowid
    pm_person = db.execute(
        "INSERT INTO contacts(kind,name,company_id) VALUES ('PERSON','일괄 PM 담당',?)", (pm_vendor,)
    ).lastrowid
    work_person = db.execute(
        "INSERT INTO contacts(kind,name,company_id) VALUES ('PERSON','일괄 업체담당',?)", (work_vendor,)
    ).lastrowid
    other_person = db.execute(
        "INSERT INTO contacts(kind,name,company_id) VALUES ('PERSON','다른 업체담당',?)", (other_vendor,)
    ).lastrowid
    masters = db.query("SELECT id FROM master_items ORDER BY sort_order LIMIT 3")
    event_id = service.create_event(
        "일괄 지정 행사", date(2026, 10, 1), None,
        [row["id"] for row in masters], pm_vendor_id=pm_vendor,
    )
    task_ids = [row["id"] for row in service.list_tasks(event_id)]
    db.enable_history(tmp_path / "bulk-history")

    changed = service.bulk_assign_tasks(
        event_id, task_ids[:2], pm_assignee_id=pm_person,
        vendor_id=work_vendor, assignee_id=work_person,
    )
    assert changed == 2
    assigned = db.query(
        "SELECT id,pm_assignee_id,vendor_id,assignee_id FROM event_tasks WHERE id IN (?,?) ORDER BY id",
        task_ids[:2],
    )
    assert all(
        (row["pm_assignee_id"], row["vendor_id"], row["assignee_id"])
        == (pm_person, work_vendor, work_person)
        for row in assigned
    )
    assert db.can_undo
    assert db.undo()
    restored = db.query("SELECT pm_assignee_id,vendor_id,assignee_id FROM event_tasks WHERE id IN (?,?)", task_ids[:2])
    assert all(tuple(row) == (None, None, None) for row in restored)

    with pytest.raises(ValueError, match="선택한 업체 소속"):
        service.bulk_assign_tasks(
            event_id, task_ids[:2], vendor_id=work_vendor, assignee_id=other_person,
        )


def test_pm_company_is_saved_and_misc_minor_is_last_in_each_settlement_major(db):
    service = EventService(db)
    pm_vendor = db.execute("INSERT INTO contacts(kind,name) VALUES ('VENDOR','PM 회사')").lastrowid
    masters = db.query("SELECT id FROM master_items ORDER BY sort_order LIMIT 3")
    event_id = service.create_event(
        "PM 행사", date(2026, 9, 1), date(2026, 9, 2), [row["id"] for row in masters],
        pm_vendor_id=pm_vendor,
    )
    assert service.get_event(event_id)["pm_vendor_id"] == pm_vendor
    tasks = db.query("SELECT id FROM event_tasks WHERE event_id=? ORDER BY id", (event_id,))
    db.execute("UPDATE event_tasks SET major='운영',minor='기타' WHERE id=?", (tasks[0]["id"],))
    db.execute("UPDATE event_tasks SET major='운영',minor='현장' WHERE id=?", (tasks[1]["id"],))
    db.execute("UPDATE event_tasks SET major='운영',minor='사전 준비' WHERE id=?", (tasks[2]["id"],))
    minors = [item["minor"] for item in service.settlement_summary(event_id)["items"]]
    assert minors[-1] == "기타"


def test_calendar_hides_completed_bars_but_lists_completed_last(db):
    service = EventService(db)
    masters = db.query("SELECT id FROM master_items ORDER BY id LIMIT 3")
    selected = date.today()
    event_id = service.create_event("달력 상태", selected, selected, [row["id"] for row in masters])
    tasks = service.list_tasks(event_id)
    for task in tasks:
        service.update_task(task["id"], planned_start=selected.isoformat(), due_date=selected.isoformat())
    service.update_task(tasks[0]["id"], status="완료")
    service.update_task(tasks[1]["id"], status="진행중")

    bars = service.calendar_range(selected, selected, event_id)
    listed = service.calendar_tasks(selected, event_id)

    assert tasks[0]["id"] not in {row["id"] for row in bars}
    assert listed[-1]["status"] == "완료"
    assert listed[0]["status"] == "진행중"


def test_reorder_tasks_swaps_order_within_same_minor_and_moves_across_major(db):
    service = EventService(db)
    masters = db.query("SELECT id FROM master_items ORDER BY sort_order LIMIT 4")
    event_id = service.create_event("순서 이동", date(2026, 9, 1), None, [row["id"] for row in masters])
    tasks = service.list_tasks(event_id)
    assert len(tasks) >= 3

    first, second, third = tasks[0], tasks[1], tasks[2]
    assert first["major"] == second["major"] == third["major"]

    # 같은 중분류 내에서 두 번째 항목을 첫 번째 앞으로 이동 → 순서가 뒤바뀐다.
    service.reorder_tasks(event_id, second["id"], first["id"], before=True)
    after = service.list_tasks(event_id)
    ordered_ids = [row["id"] for row in after]
    assert ordered_ids.index(second["id"]) < ordered_ids.index(first["id"])

    # 다른 중분류(다른 major)로 드래그 → new_major/new_minor 로 분류가 바뀌고 위치가 이동한다.
    # 세 번째 항목의 major 를 첫 번째와 다르게 만들기 힘들면 다른 major 를 만들어 이동시킨다.
    target_major = third["major"] + "_이동"
    service.reorder_tasks(event_id, second["id"], third["id"], before=True,
                          new_major=target_major, new_minor="새소분류")
    moved = service.db.one("SELECT id,major,minor FROM event_tasks WHERE id=?", (second["id"],))
    assert moved["major"] == target_major and moved["minor"] == "새소분류"
    after2 = service.list_tasks(event_id)
    # 이동된 항목은 이제 새 분류에 속하므로 그 major 그룹 안에서 반복되어 나타난다.
    moved_rows = [row for row in after2 if row["major"] == target_major]
    assert moved_rows and all(row["id"] == second["id"] for row in moved_rows)


def test_reorder_tasks_noop_when_target_is_self(db):
    service = EventService(db)
    master = db.one("SELECT id FROM master_items ORDER BY id LIMIT 1")
    event_id = service.create_event("순서 유지", date(2026, 9, 1), None, [master["id"]])
    task = service.list_tasks(event_id)[0]
    service.reorder_tasks(event_id, task["id"], task["id"])
    assert service.list_tasks(event_id)[0]["id"] == task["id"]


def test_rename_category_updates_all_contained_tasks_and_keeps_order(db):
    service = EventService(db)
    masters = db.query("SELECT id FROM master_items ORDER BY sort_order LIMIT 3")
    event_id = service.create_event("분류 이름 변경", date(2026, 9, 1), None, [row["id"] for row in masters])
    tasks = service.list_tasks(event_id)
    old_major = tasks[0]["major"]
    old_minor = tasks[0]["minor"]
    contained = [t for t in tasks if t["major"] == old_major]
    assert len(contained) >= 1

    order_before = [t["id"] for t in tasks]
    new_major = old_major + "_새"
    service.rename_category(event_id, old_major=old_major, new_major=new_major)
    after = service.list_tasks(event_id)
    # 같은 major 였던 항목들은 모두 새 major 로 따라간다.
    moved = [t for t in after if t["major"] == new_major]
    assert {t["id"] for t in moved} == {t["id"] for t in contained}
    assert all(t["minor"] == old_minor for t in moved)

    # 중분류 개별 이름 변경
    service.rename_category(event_id, old_major=new_major, old_minor=old_minor, new_minor="새중분류")
    after2 = service.list_tasks(event_id)
    assert all(t["minor"] == "새중분류" for t in after2 if t["major"] == new_major)


def test_move_category_reorders_whole_group(db):
    service = EventService(db)
    masters = db.query("SELECT id FROM master_items ORDER BY sort_order LIMIT 6")
    event_id = service.create_event("분류 이동", date(2026, 9, 1), None, [row["id"] for row in masters])
    tasks = service.list_tasks(event_id)
    majors = list(dict.fromkeys(t["major"] for t in tasks))
    if len(majors) < 2:
        # 중분류가 부족하면 이벤트에 중분류를 넣도록 증설
        for m in ("가분류", "나분류"):
            db.execute(
                "INSERT INTO event_tasks(event_id,major,minor,name,status,sort_order) VALUES (?,?,?,?,?,?)",
                (event_id, m, "소분류", "항목", "미착수", 10000),
            )
        tasks = service.list_tasks(event_id)
        majors = list(dict.fromkeys(t["major"] for t in tasks))
    assert len(majors) >= 2

    first_major_groups = [t for t in tasks if t["major"] == majors[0]]
    second_major_id = next(t["id"] for t in tasks if t["major"] == majors[1])
    # 첫 번째 대분류 전체를 두 번째 대분류 뒤로 이동
    service.move_category(event_id, major=majors[0], target_major=majors[1], before=False)
    after = service.list_tasks(event_id)
    positions = [i for i, t in enumerate(after) if t["major"] == majors[0]]
    second_pos = next(i for i, t in enumerate(after) if t["id"] == second_major_id)
    assert positions and positions[0] > second_pos, "첫 대분류가 두 번째 대분류보다 뒤로 이동해야 한다."


def test_move_category_minor_reorders_within_major_keeping_membership(db):
    """중분류 드래그는 같은 대분류 안에서 중분류 순서만 바꾸고,
    항목의 소속(major/minor)은 그대로 유지된다."""
    service = EventService(db)
    masters = db.query("SELECT id FROM master_items ORDER BY sort_order LIMIT 8")
    event_id = service.create_event("중분류 이동", date(2026, 9, 1), None, [row["id"] for row in masters])
    tasks = service.list_tasks(event_id)

    # 같은 major 안에 서로 다른 minor 가 둘 이상 있는지 확인/준비.
    minors_by_major: dict[str, set[str]] = {}
    for t in tasks:
        minors_by_major.setdefault(t["major"], set()).add(t["minor"])
    eligible = [(m, list(ms)) for m, ms in minors_by_major.items() if len(ms) >= 2]
    if not eligible:
        target = tasks[0]["major"]
        eid = event_id
        for mn in ("기존A", "기존B"):
            db.execute(
                "INSERT INTO event_tasks(event_id,major,minor,name,status,sort_order) VALUES (?,?,?,?,?,?)",
                (eid, target, mn, "항목", "미착수", 20000),
            )
        tasks = service.list_tasks(event_id)
        minors_by_major = {}
        for t in tasks:
            minors_by_major.setdefault(t["major"], set()).add(t["minor"])
        eligible = [(m, list(ms)) for m, ms in minors_by_major.items() if len(ms) >= 2]

    major, minors = eligible[0]
    a, b = minors[0], minors[1]
    # 이동 전 각 중분류 소속 항목들의 (major,minor) 고정 확인
    snapshot_before = {t["id"]: (t["major"], t["minor"]) for t in tasks}

    # b 중분류를 a 앞으로 이동
    service.move_category(event_id, major=major, minor=b, target_major=major, target_minor=a, before=True)
    after = service.list_tasks(event_id)
    a_pos = [i for i, t in enumerate(after) if t["major"] == major and t["minor"] == a]
    b_pos = [i for i, t in enumerate(after) if t["major"] == major and t["minor"] == b]
    assert a_pos and b_pos
    assert b_pos[0] < a_pos[0], "b 중분류가 a 중분류보다 앞으로 이동해야 한다."

    # 항목 소속은 전혀 변하지 않아야 한다.
    after_map = {t["id"]: (t["major"], t["minor"]) for t in after}
    assert after_map == snapshot_before, "중분류 이동은 항목의 major/minor 를 바꾸면 안 된다."


def test_removed_task_sort_order_does_not_pin_category_to_front(db):
    """제거된(is_removed) 항목의 낮은 sort_order 가 분류 정렬의 MIN 으로 잡혀
    해당 중분류가 앞에 고정되는 버그가 없어야 한다. (실제 사용자 DB 재현)"""
    service = EventService(db)
    masters = db.query("SELECT id FROM master_items ORDER BY sort_order LIMIT 6")
    event_id = service.create_event("고정 버그", date(2026, 9, 1), None, [row["id"] for row in masters])
    tasks = service.list_tasks(event_id)

    # 테스트하던 대분류를 잡아 '행사'-같은 단일 대분류 group 으로 만들고, 제거된 낮은 sort 항목 추가.
    major = tasks[0]["major"]
    minor_a, minor_b = tasks[0]["minor"], "중분류B"
    # 중분류B 항목이 없으면 추가
    if not any(t["major"] == major and t["minor"] == minor_b for t in tasks):
        db.execute(
            "INSERT INTO event_tasks(event_id,major,minor,name,status,sort_order) VALUES (?,?,?,?,?,?)",
            (event_id, major, minor_b, "B항목", "미착수", 100000),
        )
        tasks = service.list_tasks(event_id)

    # 제거된(is_removed=1) 항목을 추가하는데 낮은 sort_order(1) 를 준다.
    db.execute(
        "INSERT INTO event_tasks(event_id,major,minor,name,status,sort_order,is_removed,removed_reason) "
        "VALUES (?,?,?,?,?,?,1,?)",
        (event_id, major, minor_b, "삭제된낮은sort", "미착수", 1, "테스트"),
    )
    # 두 중분류 그룹의 표시 순서를 확인
    def cat_seq():
        seq = []
        for t in service.list_tasks(event_id):
            if t["major"] != major:
                continue
            k = t["major"] + ">" + t["minor"]
            if not seq or seq[-1] != k:
                seq.append(k)
        return seq
    before = cat_seq()
    # minor_a 와 minor_b 가 모두 앞쪽에, minor_b 다음에 minor_a 가 나오는지(아직).
    assert any(k.endswith(">" + minor_a) for k in before), "minor_a 가 존재해야 한다."
    # minor_b 를 minor_a 앞으로 이동한다. 제거된 항목의 sort=1 이 MIN 을 오염시키면
    # minor_b 가 앞에 고정돼 이동이 안 된다 → 수정 후엔 이동이 된다.
    service.move_category(event_id, major=major, minor=minor_b,
                          target_major=major, target_minor=minor_a, before=True)
    after = cat_seq()
    idx_b = next(i for i, k in enumerate(after) if k.endswith(">" + minor_b))
    idx_a = next(i for i, k in enumerate(after) if k.endswith(">" + minor_a))
    assert idx_b < idx_a, "제거된 항목 때문에 중분류가 고정되면 안 된다. (is_removed MIN 오염)"


def test_restore_repositions_task_to_end_of_its_minor(db):
    """삭제된 항목을 복원하면 그 major+minor 의 맨 끝에 배치되어, 과거의 낮은
    sort_order 가 분류를 앞으로 고정시키지 않아야 한다."""
    service = EventService(db)
    masters = db.query("SELECT id FROM master_items ORDER BY sort_order LIMIT 3")
    event_id = service.create_event("복원 정렬", date(2026, 9, 1), None, [row["id"] for row in masters])
    tasks = service.list_tasks(event_id)
    major = tasks[0]["major"]; minor = tasks[0]["minor"]
    target = next(t for t in tasks if t["major"] == major and t["minor"] == minor)

    # remove + restore 본 항목: 낮은 sort_order(삭제 상태)를 유지하도록 먼저 is_removed 로 만들고
    # 다시 복원하면 맨 끝(sort가 기존 그룹 max+10)으로 배치된다.
    db.execute("UPDATE event_tasks SET is_removed=1,removed_reason='테스트' WHERE id=?", (target["id"],))
    service.set_task_removed([target["id"]], False)

    row = service.db.one(
        "SELECT sort_order FROM event_tasks WHERE id=?", (target["id"],)
    )
    # 같은 minor 그룹의 최신(max) sort 보다 커야 그룹 맨 끝 배치, 앞 고정 방지
    # (복원된 task 자체는 제외한 그룹 max)
    group_max = service.db.one(
        "SELECT COALESCE(MAX(sort_order),0) m FROM event_tasks "
        "WHERE event_id=? AND major=? AND minor=? AND is_removed=0 AND id<>?",
        (event_id, major, minor, target["id"]),
    )["m"]
    assert row["sort_order"] > group_max, "복원 항목은 그 minor 의 맨 끝에 배치되어야 한다."


def test_restore_into_empty_minor_goes_to_end_of_major(db):
    """활성 항목이 하나도 없는(minor 가 비어있는) 중분류에 항목을 복원하면,
    그 major 의 맨 끝에 배치되어 화면 앞으로 튀지 않아야 한다."""
    service = EventService(db)
    masters = db.query("SELECT id FROM master_items ORDER BY sort_order LIMIT 6")
    event_id = service.create_event("빈 minor 복원", date(2026, 9, 1), None, [row["id"] for row in masters])
    tasks = service.list_tasks(event_id)
    major = tasks[0]["major"]; minor = tasks[0]["minor"]

    # 이 major 에 남은 활성 항목들을 전부 삭제해 "빈 minor" 상태를 만든다.
    activ = [t["id"] for t in service.list_tasks(event_id) if t["major"] == major]
    service.set_task_removed(activ, True)
    assert service.db.one(
        "SELECT COUNT(*) n FROM event_tasks WHERE event_id=? AND major=? AND is_removed=0",
        (event_id, major),
    )["n"] == 0

    # 이 major 의 삭제된 항목 하나를 복원 → major 의 끝에 배치되어야 한다.
    removed = service.db.one(
        "SELECT id FROM event_tasks WHERE event_id=? AND major=? AND is_removed=1 LIMIT 1",
        (event_id, major),
    )
    assert removed is not None, "빈 major 에는 복원할 삭제 항목이 있어야 한다."
    service.set_task_removed([removed["id"]], False)

    restored = service.db.one("SELECT sort_order FROM event_tasks WHERE id=?", (removed["id"],))
    major_max = service.db.one(
        "SELECT COALESCE(MAX(sort_order),0) m FROM event_tasks "
        "WHERE event_id=? AND major=? AND is_removed=0 AND id<>?",
        (event_id, major, removed["id"]),
    )["m"]
    assert restored["sort_order"] > major_max, "빈 minor 복원 항목은 major 의 끝에 배치되어야 한다."
