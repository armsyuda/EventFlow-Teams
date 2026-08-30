from pathlib import Path

from eventflow_teams_v2.outbox import WorkspaceOutbox
from eventflow_teams_v2.sync_store import WorkspaceSnapshotStore
from eventflow_teams_v2.workspace import WorkspaceDatabase, workspace_database_path


class FakeApi:
    def __init__(self) -> None:
        self.calls: list[list[dict]] = []

    def apply_mutations(self, organization_id: str, mutations: list[dict]) -> dict:
        self.calls.append(mutations)
        mutation = mutations[0]
        return {"cursor": 20, "results": [{"mutation_id": mutation["mutation_id"], "status": "APPLIED", "entity_type": "EVENT_TASK", "entity": {"id": "task-1", "row_version": 8, "updated_at": "2026-08-24T00:00:00Z"}}]}


def _snapshot() -> dict:
    return {
        "cursor": 10,
        "vendors": [], "people": [], "master_items": [],
        "events": [{"id": "event-1", "name": "행사", "start_date": "2026-08-24", "updated_at": "2026-08-24T00:00:00Z"}],
        "event_tasks": [{"id": "task-1", "event_id": "event-1", "major": "운영", "minor": "일반", "name": "업무", "sort_order": 10, "row_version": 7}],
        "event_vendors": [], "event_freelancers": [],
    }


def test_task_outbox_uses_task_permission_operation_and_current_version(tmp_path: Path) -> None:
    database = WorkspaceDatabase(workspace_database_path(tmp_path, "user", "org"), user_id="user", organization_id="org")
    WorkspaceSnapshotStore(database).apply_snapshot(_snapshot())
    database.execute("UPDATE event_tasks SET status=? WHERE id=1", ("진행중",))

    api = FakeApi()
    flushed = WorkspaceOutbox(database).flush(api, "org")

    assert flushed.applied == 1
    request = api.calls[0][0]
    assert request["operation"] == "TASK_PATCH"
    assert request["payload"]["id"] == "task-1"
    assert request["payload"]["expected_row_version"] == 7
    assert request["payload"]["status"] == "진행중"
    assert database.pending_outbox() == []
    mapping = database.one("SELECT remote_version FROM teams_v2_entity_map WHERE entity_type='EVENT_TASK' AND local_id=1")
    assert mapping["remote_version"] == 8
    database.close()


def test_new_local_event_preserves_local_task_rows_for_server_creation(tmp_path: Path) -> None:
    database = WorkspaceDatabase(workspace_database_path(tmp_path, "user", "org"), user_id="user", organization_id="org")
    snapshot = _snapshot() | {"master_items": [{"id": "master-1", "major": "운영", "minor": "일반", "name": "기본 업무", "sort_order": 10}]}
    WorkspaceSnapshotStore(database).apply_snapshot(snapshot)
    with database.applying_remote_changes():
        database.execute("INSERT INTO events(name,start_date) VALUES (?,?)", ("새 행사", "2026-09-01"))
        database.execute("INSERT INTO event_tasks(event_id,master_item_id,major,minor,name,sort_order) VALUES (?,?,?,?,?,?)", (2, 1, "운영", "일반", "기본 업무", 10))
    # The normal Local event insertion itself is what V2 queues.
    database.execute("UPDATE events SET name=? WHERE id=2", ("새 행사 수정",))
    event_entry = next(item for item in database.pending_outbox() if item["entity_type"] == "EVENT")
    encoded = WorkspaceOutbox(database).encode(event_entry)
    assert encoded["operation"] == "EVENT_CREATE_WITH_TASKS"
    assert encoded["payload"]["tasks"][0]["master_item_id"] == "master-1"
    assert encoded["payload"]["tasks"][0]["name"] == "기본 업무"
    database.close()


def test_new_empty_project_is_sent_with_an_empty_task_list(tmp_path: Path) -> None:
    database = WorkspaceDatabase(workspace_database_path(tmp_path, "user", "org"), user_id="user", organization_id="org")
    WorkspaceSnapshotStore(database).apply_snapshot(_snapshot())
    database.execute("INSERT INTO events(name,start_date) VALUES (?,?)", ("빈 프로젝트", "2026-09-01"))

    event_entry = next(item for item in database.pending_outbox() if item["entity_type"] == "EVENT")
    encoded = WorkspaceOutbox(database).encode(event_entry)

    assert encoded["operation"] == "EVENT_CREATE_WITH_TASKS"
    assert encoded["payload"]["name"] == "빈 프로젝트"
    assert encoded["payload"]["tasks"] == []
    database.close()


def test_structure_outbox_sends_one_event_snapshot_with_all_task_versions(tmp_path: Path) -> None:
    database = WorkspaceDatabase(workspace_database_path(tmp_path, "user", "org"), user_id="user", organization_id="org")
    snapshot = _snapshot() | {"event_tasks": [
        {"id": "task-1", "event_id": "event-1", "major": "운영", "minor": "일반", "name": "첫 업무", "sort_order": 10, "row_version": 7},
        {"id": "task-2", "event_id": "event-1", "major": "운영", "minor": "일반", "name": "둘째 업무", "sort_order": 20, "row_version": 3},
    ]}
    WorkspaceSnapshotStore(database).apply_snapshot(snapshot)
    database.execute("UPDATE event_tasks SET sort_order=? WHERE id=?", (30, 1))
    entry = database.pending_outbox()[0]
    assert entry["operation"] == "LOCAL_TASK_STRUCTURE"
    encoded = WorkspaceOutbox(database).encode(entry)
    assert encoded["operation"] == "TASK_STRUCTURE_SET"
    assert encoded["payload"]["event_id"] == "event-1"
    assert {task["id"] for task in encoded["payload"]["tasks"]} == {"task-1", "task-2"}
    assert {task["expected_row_version"] for task in encoded["payload"]["tasks"]} == {7, 3}
    database.close()


def test_conflict_keep_local_creates_fresh_mutation_at_server_version(tmp_path: Path) -> None:
    database = WorkspaceDatabase(workspace_database_path(tmp_path, "user", "org"), user_id="user", organization_id="org")
    WorkspaceSnapshotStore(database).apply_snapshot(_snapshot())
    database.execute("UPDATE event_tasks SET quantity=? WHERE id=1", (3,))
    entry = database.pending_outbox()[0]
    outbox = WorkspaceOutbox(database)
    outbox._record_conflict(entry, {"reason": "stale", "entity": {"id": "task-1", "row_version": 9, "updated_at": "new"}})
    conflict = database.one("SELECT id FROM teams_v2_conflicts WHERE status='OPEN'")
    outbox.resolve_conflict(int(conflict["id"]), keep_local=True)
    fresh = database.pending_outbox()
    assert len(fresh) == 1
    assert fresh[0]["mutation_id"] != entry["mutation_id"]
    mapping = database.one("SELECT remote_version FROM teams_v2_entity_map WHERE entity_type='EVENT_TASK' AND local_id=1")
    assert mapping["remote_version"] == 9
    database.close()
