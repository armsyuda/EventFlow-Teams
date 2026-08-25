from pathlib import Path

from PySide6.QtCore import QCoreApplication

from eventflow_teams_v2.sync_engine import WorkspaceSyncEngine
from eventflow_teams_v2.sync_store import WorkspaceSnapshotStore
from eventflow_teams_v2.workspace import WorkspaceDatabase, workspace_database_path


def _application() -> QCoreApplication:
    return QCoreApplication.instance() or QCoreApplication([])


def _snapshot() -> dict:
    return {"cursor": 1, "vendors": [], "people": [], "master_items": [], "events": [{"id": "event-1", "name": "행사", "start_date": "2026-08-24"}], "event_tasks": [{"id": "task-1", "event_id": "event-1", "major": "운영", "minor": "일반", "name": "업무", "sort_order": 10, "row_version": 1}], "event_vendors": [], "event_freelancers": []}


def test_engine_sends_only_when_local_outbox_has_a_change(tmp_path: Path) -> None:
    _application()
    database = WorkspaceDatabase(workspace_database_path(tmp_path, "user", "org"), user_id="user", organization_id="org")
    WorkspaceSnapshotStore(database).apply_snapshot(_snapshot())
    calls: list[list[dict]] = []
    def send(mutations: list[dict]) -> dict:
        calls.append(mutations)
        mutation = mutations[0]
        return {"cursor": 2, "results": [{"mutation_id": mutation["mutation_id"], "status": "APPLIED", "entity_type": "EVENT_TASK", "entity": {"id": "task-1", "row_version": 2}}]}
    def run(task, done, failed) -> None:
        try:
            done(task())
        except Exception as exc:  # pragma: no cover - assertion aid
            failed(str(exc))
    engine = WorkspaceSyncEngine(database, "org", send, run)
    engine._tick()
    assert calls == []
    database.execute("UPDATE event_tasks SET quantity=? WHERE id=1", (3,))
    engine._tick()
    assert len(calls) == 1
    assert database.pending_outbox() == []
    engine.stop(); database.close()


def test_engine_keeps_failed_mutation_and_enters_waiting_state(tmp_path: Path) -> None:
    _application()
    database = WorkspaceDatabase(workspace_database_path(tmp_path, "user", "org"), user_id="user", organization_id="org")
    WorkspaceSnapshotStore(database).apply_snapshot(_snapshot())
    database.execute("UPDATE event_tasks SET quantity=? WHERE id=1", (3,))
    states: list[str] = []
    def run(task, done, failed) -> None:
        failed("offline")
    engine = WorkspaceSyncEngine(database, "org", lambda _: {}, run)
    engine.state_changed.connect(lambda state, _: states.append(state))
    engine._tick()
    assert database.pending_outbox()
    assert "WAITING" in states
    engine.stop(); database.close()
