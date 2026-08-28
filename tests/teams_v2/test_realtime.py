from eventflow_teams_v2.realtime import RealtimeSignalClient


def test_realtime_uses_protected_organization_signal_only() -> None:
    client = RealtimeSignalClient("https://example.supabase.co", "public-key", "token", "org-1")
    assert client.url.startswith("wss://example.supabase.co/realtime/v1/websocket?")
    assert client.topic == "realtime:teams-v2-org-1"
    assert client.organization_id == "org-1"


def test_postgres_change_emits_wakeup_signal() -> None:
    client = RealtimeSignalClient("https://example.supabase.co", "key", "token", "org-1")
    notices: list[bool] = []
    client.changed.connect(lambda: notices.append(True))
    client._handle_message('[null,null,"realtime:teams-v2-org-1","postgres_changes",{}]')
    assert notices == [True]


def test_access_signal_emits_access_refresh_not_workspace_refresh() -> None:
    client = RealtimeSignalClient("https://example.supabase.co", "key", "token", "org-1", "user-1")
    workspace_notices: list[bool] = []
    access_notices: list[bool] = []
    client.changed.connect(lambda: workspace_notices.append(True))
    client.access_changed.connect(lambda: access_notices.append(True))

    client._handle_message('[null,null,"realtime:teams-v2-org-1","postgres_changes",{"data":{"table":"teams_v2_access_signals"}}]')

    assert workspace_notices == []
    assert access_notices == [True]
