from __future__ import annotations

from event_checklist.supabase_connection import (
    SupabaseConfigurationError,
    SupabaseConnectionError,
    check_supabase_connection,
    load_supabase_settings,
)


def main() -> int:
    try:
        settings = load_supabase_settings()
        payload = check_supabase_connection(settings)
    except (SupabaseConfigurationError, SupabaseConnectionError) as exc:
        print(f"SUPABASE_CONNECTION_FAILED: {exc}")
        return 1

    providers = payload.get("external", {})
    enabled_providers = sorted(
        name for name, enabled in providers.items() if enabled is True
    )
    print("SUPABASE_CONNECTION_OK")
    print(f"URL: {settings.url}")
    print(
        "Enabled external providers: "
        + (", ".join(enabled_providers) if enabled_providers else "none")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
