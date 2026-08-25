from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SUPABASE_URL_ENV = "EVENTFLOW_SUPABASE_URL"
SUPABASE_PUBLISHABLE_KEY_ENV = "EVENTFLOW_SUPABASE_PUBLISHABLE_KEY"


class SupabaseConfigurationError(ValueError):
    """Raised when the local Supabase client configuration is incomplete."""


class SupabaseConnectionError(RuntimeError):
    """Raised when the Supabase project cannot be reached or authenticated."""


@dataclass(frozen=True)
class SupabaseSettings:
    url: str
    publishable_key: str


def load_supabase_settings() -> SupabaseSettings:
    """Load client-safe Supabase settings from the process environment."""
    url = os.environ.get(SUPABASE_URL_ENV, "").strip().rstrip("/")
    publishable_key = os.environ.get(SUPABASE_PUBLISHABLE_KEY_ENV, "").strip()
    missing = []
    if not url:
        missing.append(SUPABASE_URL_ENV)
    if not publishable_key:
        missing.append(SUPABASE_PUBLISHABLE_KEY_ENV)
    if missing:
        raise SupabaseConfigurationError(
            "Supabase 설정이 필요합니다: " + ", ".join(missing)
        )
    if not url.startswith("https://"):
        raise SupabaseConfigurationError("Supabase URL은 https:// 주소여야 합니다.")
    return SupabaseSettings(url=url, publishable_key=publishable_key)


def check_supabase_connection(
    settings: SupabaseSettings, *, timeout_seconds: float = 10.0
) -> dict:
    """Verify that the project URL and publishable key reach Supabase Auth."""
    request = Request(
        f"{settings.url}/auth/v1/settings",
        headers={"apikey": settings.publishable_key},
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            status = response.status
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        raise SupabaseConnectionError(
            f"Supabase가 연결을 거부했습니다. HTTP {exc.code}"
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise SupabaseConnectionError(f"Supabase에 연결할 수 없습니다: {exc}") from exc

    if status != 200:
        raise SupabaseConnectionError(f"예상하지 못한 응답입니다. HTTP {status}")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise SupabaseConnectionError("Supabase 응답이 올바른 JSON이 아닙니다.") from exc
    if not isinstance(payload, dict) or "external" not in payload:
        raise SupabaseConnectionError("Supabase Auth 설정 응답을 확인할 수 없습니다.")
    return payload
