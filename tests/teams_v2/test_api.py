from pathlib import Path

from eventflow_teams_v2.api import TeamsV2Api
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
