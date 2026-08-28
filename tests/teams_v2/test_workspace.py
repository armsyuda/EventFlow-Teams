from pathlib import Path

from eventflow_teams_v2.workspace import clear_user_workspaces, clear_workspace, workspace_database_path, workspace_root
from eventflow_teams_v2.workspace import WorkspaceDatabase
from eventflow_teams_v2.sync_store import WorkspaceSnapshotStore


def test_workspace_is_isolated_by_user_and_organization(tmp_path: Path) -> None:
    first = workspace_database_path(tmp_path, "user-a", "org-a")
    second = workspace_database_path(tmp_path, "user-a", "org-b")
    third = workspace_database_path(tmp_path, "user-b", "org-a")

    assert first == workspace_root(tmp_path, "user-a", "org-a") / "data" / "event_checklist.db"
    assert first != second
    assert first != third


def test_workspace_metadata_refuses_another_membership(tmp_path: Path) -> None:
    path = workspace_database_path(tmp_path, "user-a", "org-a")
    database = WorkspaceDatabase(path, user_id="user-a", organization_id="org-a")
    assert database.one("SELECT user_id FROM teams_v2_workspace WHERE singleton=1")["user_id"] == "user-a"
    database.close()

    try:
        WorkspaceDatabase(path, user_id="user-b", organization_id="org-a")
    except RuntimeError as exc:
        assert "다른 사용자" in str(exc)
    else:
        raise AssertionError("A workspace must remain isolated by membership")


def test_logout_cleanup_removes_only_the_current_users_workspaces(tmp_path: Path) -> None:
    first = workspace_root(tmp_path, "user-a", "org-a")
    second = workspace_root(tmp_path, "user-a", "org-b")
    other = workspace_root(tmp_path, "user-b", "org-a")
    for item in (first, second, other):
        item.mkdir(parents=True)
        (item / "marker.txt").write_text("workspace", encoding="utf-8")

    clear_user_workspaces(tmp_path, "user-a")

    assert not first.exists()
    assert not second.exists()
    assert other.exists()
    clear_workspace(tmp_path, "user-b", "org-a")
    assert not other.exists()


def test_workspace_saves_non_secret_access_context(tmp_path: Path) -> None:
    database = WorkspaceDatabase(workspace_database_path(tmp_path, "user-a", "org-a"), user_id="user-a", organization_id="org-a")
    database.set_access_context(role="VIEWER", permissions={"events.view", "checklist.view"})
    row = database.one("SELECT role,permissions_json FROM teams_v2_workspace WHERE singleton=1")
    assert row["role"] == "VIEWER"
    assert "checklist.view" in row["permissions_json"]
    database.close()


def test_local_domain_changes_are_captured_without_editing_local_services(tmp_path: Path) -> None:
    database = WorkspaceDatabase(workspace_database_path(tmp_path, "user-a", "org-a"), user_id="user-a", organization_id="org-a")
    # The baseline seeds before V2 triggers are installed.  This edit is a
    # normal Local SQL write and must be available to the later sync worker.
    with database.applying_remote_changes():
        database.execute("INSERT INTO events(name,start_date) VALUES (?,?)", ("기존 행사", "2026-08-24"))
    database.execute("UPDATE events SET name=? WHERE id=1", ("동기화 확인 행사",))
    row = database.pending_outbox()[0]
    assert row["entity_type"] == "EVENT"
    assert row["operation"] == "LOCAL_UPSERT"
    assert '"action":"UPDATE"' in str(row["payload_json"])
    database.close()


def test_remote_apply_does_not_echo_back_into_outbox(tmp_path: Path) -> None:
    database = WorkspaceDatabase(workspace_database_path(tmp_path, "user-a", "org-a"), user_id="user-a", organization_id="org-a")
    with database.applying_remote_changes():
        database.execute("INSERT INTO events(name,start_date) VALUES (?,?)", ("서버 행사", "2026-08-24"))
    assert database.pending_outbox() == []
    control = database.one("SELECT suppress_capture FROM teams_v2_sync_control WHERE singleton=1")
    assert control["suppress_capture"] == 0
    database.close()


def test_snapshot_replaces_baseline_samples_and_maps_server_uuids(tmp_path: Path) -> None:
    database = WorkspaceDatabase(workspace_database_path(tmp_path, "user-a", "org-a"), user_id="user-a", organization_id="org-a")
    snapshot = {
        "cursor": 42,
        "vendors": [{"id": "vendor-1", "name": "협력 업체", "industry": "무대"}],
        "people": [{"id": "person-1", "vendor_id": "vendor-1", "name": "담당자", "phone": "010"}],
        "master_items": [{"id": "master-1", "major": "무대", "minor": "장비", "name": "조명", "sort_order": 10}],
        "events": [{"id": "event-1", "name": "서버 행사", "start_date": "2026-08-24"}],
        "event_tasks": [{"id": "task-1", "event_id": "event-1", "master_item_id": "master-1", "major": "무대", "minor": "장비", "name": "조명", "sort_order": 10, "row_version": 7}],
        "event_vendors": [{"event_id": "event-1", "vendor_id": "vendor-1"}],
        "event_freelancers": [],
    }
    WorkspaceSnapshotStore(database).apply_snapshot(snapshot)
    assert database.one("SELECT COUNT(*) AS count FROM master_items")["count"] == 1
    assert database.one("SELECT name FROM events")["name"] == "서버 행사"
    task = database.one("SELECT vendor_id,master_item_id FROM event_tasks")
    assert task["vendor_id"] is None
    assert task["master_item_id"] is not None
    mapping = database.one("SELECT remote_version FROM teams_v2_entity_map WHERE entity_type='EVENT_TASK' AND remote_id='task-1'")
    assert mapping["remote_version"] == 7
    assert database.one("SELECT remote_cursor FROM teams_v2_workspace WHERE singleton=1")["remote_cursor"] == "42"
    assert database.pending_outbox() == []
    database.close()


def test_changes_merge_task_and_delete_link_without_outbox_echo(tmp_path: Path) -> None:
    database = WorkspaceDatabase(workspace_database_path(tmp_path, "user-a", "org-a"), user_id="user-a", organization_id="org-a")
    snapshot = {
        "cursor": 1, "vendors": [{"id": "vendor-1", "name": "업체"}], "people": [], "master_items": [],
        "events": [{"id": "event-1", "name": "행사", "start_date": "2026-08-24"}],
        "event_tasks": [{"id": "task-1", "event_id": "event-1", "major": "운영", "minor": "일반", "name": "업무", "sort_order": 10, "row_version": 1}],
        "event_vendors": [{"event_id": "event-1", "vendor_id": "vendor-1"}], "event_freelancers": [],
    }
    store = WorkspaceSnapshotStore(database); store.apply_snapshot(snapshot)
    store.apply_changes({"cursor": 4, "changes": [
        {"entity_type": "EVENT_TASK", "operation": "UPSERT", "payload": {"id": "task-1", "event_id": "event-1", "major": "운영", "minor": "일반", "name": "수정 업무", "sort_order": 10, "row_version": 2}},
        {"entity_type": "EVENT_VENDOR", "operation": "DELETE", "entity_key": "event-1:vendor-1", "payload": {"event_id": "event-1", "vendor_id": "vendor-1"}},
    ]})
    assert database.one("SELECT name FROM event_tasks WHERE id=1")["name"] == "수정 업무"
    assert database.one("SELECT COUNT(*) AS count FROM event_vendors")["count"] == 0
    assert database.one("SELECT remote_cursor FROM teams_v2_workspace WHERE singleton=1")["remote_cursor"] == "4"
    assert database.pending_outbox() == []
    database.close()


def test_snapshot_mirrors_staff_and_private_schedule_content(tmp_path: Path) -> None:
    database = WorkspaceDatabase(workspace_database_path(tmp_path, "user-a", "org-a"), user_id="user-a", organization_id="org-a")
    WorkspaceSnapshotStore(database).apply_snapshot({
        "cursor": 2, "events": [], "event_tasks": [], "vendors": [], "people": [], "master_items": [], "event_vendors": [], "event_freelancers": [],
        "staff_members": [{"user_id": "staff-1", "display_name": "직원", "role": "MEMBER", "job_title": "기획", "color_hex": "#A9D9F5", "status": "ACTIVE"}],
        "personal_schedules": [{"id": "schedule-1", "member_user_id": "staff-1", "start_date": "2026-08-25", "end_date": "2026-08-26", "title": "휴가", "private_content": "상세", "can_edit": True}],
    })
    member = database.one("SELECT display_name,color_hex FROM teams_v2_staff_members WHERE user_id='staff-1'")
    schedule = database.one("SELECT title,private_content,can_edit FROM teams_v2_personal_schedules WHERE id='schedule-1'")
    assert member["display_name"] == "직원" and member["color_hex"] == "#A9D9F5"
    assert schedule["title"] == "휴가" and schedule["private_content"] == "상세" and schedule["can_edit"] == 1
    database.close()
