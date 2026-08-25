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
