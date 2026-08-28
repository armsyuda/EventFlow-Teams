from eventflow_teams_v2.company_workspace import CompanyWorkspace
from eventflow_teams_v2.workspace import WorkspaceDatabase, workspace_database_path


def _database(tmp_path):
    return WorkspaceDatabase(workspace_database_path(tmp_path, "staff", "company"), user_id="staff", organization_id="company")


def test_v3_snapshot_is_separate_from_legacy_project_outbox(tmp_path):
    db = _database(tmp_path)
    v3 = CompanyWorkspace(db)
    db.conn.execute("INSERT INTO teams_v2_outbox(mutation_id,entity_type,operation,payload_json) VALUES('legacy','EVENT_TASK','LOCAL_TASK_PATCH','{}')")
    v3.apply_snapshot({"cursor": 4, "work_items": [{"id": "company-work", "work_scope": "COMPANY", "major": "회사 운영", "minor": "기타", "name": "공용 업무", "status": "진행중", "row_version": 1}], "financial_entries": []})
    assert db.one("SELECT count(*) AS value FROM teams_v2_outbox")["value"] == 1
    assert db.one("SELECT name FROM teams_v3_work_items WHERE remote_id='company-work'")["name"] == "공용 업무"
    assert v3.cursor() == 4
    db.close()


def test_v3_changes_and_outbox_keep_server_uuid_identity(tmp_path):
    db = _database(tmp_path)
    v3 = CompanyWorkspace(db)
    v3.apply_snapshot({"cursor": 1, "work_items": [], "financial_entries": []})
    v3.apply_changes({"cursor": 2, "changes": [{"entity_type": "WORK_ITEM", "entity_key": "project-work", "operation": "UPSERT", "payload": {"id": "project-work", "event_id": "project-a", "work_scope": "PROJECT", "major": "운영", "minor": "현장", "name": "프로젝트 업무", "status": "진행중", "row_version": 3}}]})
    mutation_id = v3.queue("WORK_ASSIGN", {"id": "project-work", "assigned_member_user_id": "staff-b", "expected_row_version": 3})
    entry, mutation = v3.next_mutation() or ({}, {})
    assert mutation["mutation_id"] == mutation_id
    assert mutation["payload"]["id"] == "project-work"
    response = {"cursor": 3, "results": [{"mutation_id": mutation_id, "status": "APPLIED", "entity_type": "WORK_ITEM", "entity": {"id": "project-work", "event_id": "project-a", "work_scope": "PROJECT", "major": "운영", "minor": "현장", "name": "프로젝트 업무", "status": "진행중", "assigned_member_user_id": "staff-b", "row_version": 4}}]}
    assert v3.apply_mutation_response(entry, response) == "APPLIED"
    assert db.one("SELECT assigned_member_user_id,row_version FROM teams_v3_work_items WHERE remote_id='project-work'")["assigned_member_user_id"] == "staff-b"
    assert db.one("SELECT status FROM teams_v3_outbox WHERE mutation_id=?", (mutation_id,))["status"] == "APPLIED"
    db.close()
