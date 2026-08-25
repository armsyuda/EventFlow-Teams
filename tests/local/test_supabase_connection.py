from __future__ import annotations

import io
import json

import pytest

from event_checklist import supabase_connection


def test_load_supabase_settings(monkeypatch):
    monkeypatch.setenv(
        supabase_connection.SUPABASE_URL_ENV,
        "https://project.supabase.co/",
    )
    monkeypatch.setenv(
        supabase_connection.SUPABASE_PUBLISHABLE_KEY_ENV,
        "sb_publishable_test",
    )

    settings = supabase_connection.load_supabase_settings()

    assert settings.url == "https://project.supabase.co"
    assert settings.publishable_key == "sb_publishable_test"


def test_load_supabase_settings_reports_missing_values(monkeypatch):
    monkeypatch.delenv(supabase_connection.SUPABASE_URL_ENV, raising=False)
    monkeypatch.delenv(
        supabase_connection.SUPABASE_PUBLISHABLE_KEY_ENV,
        raising=False,
    )

    with pytest.raises(supabase_connection.SupabaseConfigurationError) as error:
        supabase_connection.load_supabase_settings()

    assert supabase_connection.SUPABASE_URL_ENV in str(error.value)
    assert supabase_connection.SUPABASE_PUBLISHABLE_KEY_ENV in str(error.value)


def test_check_supabase_connection(monkeypatch):
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps({"external": {"email": True}}).encode("utf-8")

    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(supabase_connection, "urlopen", fake_urlopen)
    settings = supabase_connection.SupabaseSettings(
        url="https://project.supabase.co",
        publishable_key="sb_publishable_test",
    )

    payload = supabase_connection.check_supabase_connection(settings)

    assert payload["external"]["email"] is True
    assert captured["request"].full_url.endswith("/auth/v1/settings")
    assert captured["request"].get_header("Apikey") == "sb_publishable_test"
    assert captured["timeout"] == 10.0
