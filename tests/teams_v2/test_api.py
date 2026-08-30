from pathlib import Path

from eventflow_teams_v2.api import TeamsV2Api
from eventflow_teams_v2.api import ApiError
from eventflow_teams_v2.config import TeamsV2Config
from eventflow_teams_v2.session import Session


class _Response:
    ok = True

    def __init__(self, value):
        self.value = value

    def json(self):
        return self.value


def test_v2_company_lookup_refreshes_an_expired_saved_access_token(tmp_path: Path, monkeypatch) -> None:
    expired = _Response([]); expired.ok = False; expired.status_code = 401
    refreshed = _Response({"access_token": "new-access", "refresh_token": "new-refresh", "user": {"id": "user", "email": "user@example.com"}})
    companies = _Response([{"organization_id": "org", "role": "OWNER", "organizations": {"name": "회사"}}])
    get_calls = []

    def get(_url, **kwargs):
        get_calls.append(kwargs["headers"].get("authorization"))
        return expired if len(get_calls) == 1 else companies

    monkeypatch.setattr("eventflow_teams_v2.api.requests.get", get)
    monkeypatch.setattr("eventflow_teams_v2.api.requests.post", lambda *_args, **_kwargs: refreshed)
    api = TeamsV2Api(TeamsV2Config("https://example.supabase.co", "publishable", tmp_path), Session("old-access", "refresh", "user", "user@example.com"))

    assert [(item.id, item.name) for item in api.organizations()] == [("org", "회사")]
    assert get_calls == ["Bearer old-access", "Bearer new-access"]
    assert api.session and api.session.refresh_token == "new-refresh"


def test_v2_permissions_use_the_platform_admin_free_rpc(tmp_path: Path, monkeypatch) -> None:
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs["json"]))
        return _Response(["events.view", "checklist.view"])

    monkeypatch.setattr("eventflow_teams_v2.api.requests.post", post)
    api = TeamsV2Api(TeamsV2Config("https://example.supabase.co", "publishable", tmp_path), Session("token", "refresh", "user"))

    assert api.permissions("org") == {"events.view", "checklist.view"}
    assert calls == [("https://example.supabase.co/rest/v1/rpc/get_my_teams_v2_permissions", {"target_organization_id": "org"})]


def test_v2_workspace_contract_uses_only_dedicated_rpcs(tmp_path: Path, monkeypatch) -> None:
    responses = iter([_Response({"cursor": 4}), _Response({"cursor": 5, "changes": []}), _Response({"results": []})])
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs["json"]))
        return next(responses)

    monkeypatch.setattr("eventflow_teams_v2.api.requests.post", post)
    api = TeamsV2Api(TeamsV2Config("https://example.supabase.co", "publishable", tmp_path), Session("token", "refresh", "user"))

    assert api.workspace_snapshot("org")["cursor"] == 4
    assert api.workspace_changes("org", -2)["cursor"] == 5
    assert api.apply_mutations("org", [{"mutation_id": "x"}]) == {"results": []}
    assert [call[0].rsplit("/", 1)[-1] for call in calls] == [
        "teams_v2_workspace_snapshot", "teams_v2_workspace_changes", "teams_v2_apply_mutations",
    ]


def test_v2_member_colour_reports_unapplied_server_feature(tmp_path: Path, monkeypatch) -> None:
    response = _Response({"message": "function not found"}); response.ok = False; response.status_code = 404
    monkeypatch.setattr("eventflow_teams_v2.api.requests.post", lambda *_args, **_kwargs: response)
    api = TeamsV2Api(TeamsV2Config("https://example.supabase.co", "publishable", tmp_path), Session("token", "refresh", "user"))

    try:
        api.save_member_profile("org", "user", color_hex="#A7D7F1")
    except ApiError as exc:
        assert "서버 업데이트가 아직 적용되지 않았습니다" in str(exc)
    else:
        raise AssertionError("missing feature RPC must raise ApiError")


def test_v2_transfer_and_notifications_use_dedicated_rpcs(tmp_path: Path, monkeypatch) -> None:
    responses = iter([_Response({"id": "task", "assigned_member_user_id": "staff-b"}), _Response([{ "message": "새 업무 수신" }])])
    calls = []
    def post(url, **kwargs):
        calls.append((url, kwargs["json"])); return next(responses)
    monkeypatch.setattr("eventflow_teams_v2.api.requests.post", post)
    api = TeamsV2Api(TeamsV2Config("https://example.supabase.co", "publishable", tmp_path), Session("token", "refresh", "owner"))

    assert api.transfer_task_member("org", "task", "staff-b", 7)["assigned_member_user_id"] == "staff-b"
    assert api.pop_task_transfer_notifications("org") == [{"message": "새 업무 수신"}]
    assert [url.rsplit("/", 1)[-1] for url, _ in calls] == ["teams_v2_transfer_task_member", "teams_v2_pop_task_transfer_notifications"]


def test_v2_company_join_code_uses_administrator_rpc(tmp_path: Path, monkeypatch) -> None:
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs["json"])); return _Response("A2B3C")

    monkeypatch.setattr("eventflow_teams_v2.api.requests.post", post)
    api = TeamsV2Api(TeamsV2Config("https://example.supabase.co", "publishable", tmp_path), Session("token", "refresh", "owner"))

    assert api.company_join_code("org") == "A2B3C"
    assert calls == [("https://example.supabase.co/rest/v1/rpc/teams_v2_company_join_code", {"target_organization_id": "org"})]


def test_v2_company_member_removal_uses_the_access_stop_rpc(tmp_path: Path, monkeypatch) -> None:
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs["json"])); return _Response({"removed": True, "access_status": "SUSPENDED"})

    monkeypatch.setattr("eventflow_teams_v2.api.requests.post", post)
    api = TeamsV2Api(TeamsV2Config("https://example.supabase.co", "publishable", tmp_path), Session("token", "refresh", "owner"))

    api.remove_company_member("org", "former-member")

    assert calls == [("https://example.supabase.co/rest/v1/rpc/teams_v2_remove_company_member", {"target_organization_id": "org", "target_user_id": "former-member"})]


def test_v3_my_space_work_uses_self_owned_rpcs(tmp_path: Path, monkeypatch) -> None:
    responses = iter([
        _Response({"status": "APPLIED", "entity": {"id": "work-a"}}),
        _Response({"status": "APPLIED", "entity": {"id": "work-a", "is_removed": True}}),
        _Response({"status": "APPLIED", "entity": {"id": "work-b"}}),
        _Response({"status": "APPLIED", "entity": {"id": "work-b", "is_removed": True}}),
        _Response({"status": "APPLIED", "entity": {"id": "check-a"}}),
    ])
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs["json"])); return next(responses)

    monkeypatch.setattr("eventflow_teams_v2.api.requests.post", post)
    api = TeamsV2Api(TeamsV2Config("https://example.supabase.co", "publishable", tmp_path), Session("token", "refresh", "user"))

    assert api.save_my_company_work("org", None, None, {"name": "문서 정리"})["entity"]["id"] == "work-a"
    assert api.delete_my_company_work("org", "work-a", 2)["entity"]["is_removed"] is True
    assert api.save_my_project_work("org", None, None, "event-a", {"name": "현장 확인"})["entity"]["id"] == "work-b"
    assert api.delete_my_project_work("org", "work-b", 3)["entity"]["is_removed"] is True
    assert api.claim_my_checklist_work("org", "check-a", 4)["entity"]["id"] == "check-a"
    assert calls == [
        ("https://example.supabase.co/rest/v1/rpc/teams_v3_save_my_company_work", {"target_organization_id": "org", "target_task_id": None, "expected_row_version": None, "work": {"name": "문서 정리"}}),
        ("https://example.supabase.co/rest/v1/rpc/teams_v3_delete_my_company_work", {"target_organization_id": "org", "target_task_id": "work-a", "expected_row_version": 2}),
        ("https://example.supabase.co/rest/v1/rpc/teams_v3_save_my_project_work", {"target_organization_id": "org", "target_task_id": None, "expected_row_version": None, "target_event_id": "event-a", "work": {"name": "현장 확인"}}),
        ("https://example.supabase.co/rest/v1/rpc/teams_v3_delete_my_project_work", {"target_organization_id": "org", "target_task_id": "work-b", "expected_row_version": 3}),
        ("https://example.supabase.co/rest/v1/rpc/teams_v3_claim_my_checklist_work", {"target_organization_id": "org", "target_task_id": "check-a", "expected_row_version": 4}),
    ]
