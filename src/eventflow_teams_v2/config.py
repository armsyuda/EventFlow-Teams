from __future__ import annotations

from dataclasses import dataclass
from os import getenv
from pathlib import Path
import sys


@dataclass(frozen=True)
class TeamsV2Config:
    supabase_url: str
    publishable_key: str
    data_root: Path

    @classmethod
    def from_environment(cls) -> "TeamsV2Config":
        values: dict[str, str] = {}
        config_directory = Path(sys.executable).parent
        # The review executable was named EventFlowTeamsV2, while the public
        # installer uses EventFlowTeams.  Accept both names during the
        # transition so installed users always receive their connection values.
        for config_name in ("EventFlowTeamsV2.env", "EventFlowTeams.env"):
            config_path = config_directory / config_name
            if not config_path.exists():
                continue
            for line in config_path.read_text(encoding="utf-8-sig").splitlines():
                if "=" not in line or line.lstrip().startswith("#"):
                    continue
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
        url = (getenv("EVENTFLOW_SUPABASE_URL") or values.get("EVENTFLOW_SUPABASE_URL", "")).rstrip("/")
        key = getenv("EVENTFLOW_SUPABASE_PUBLISHABLE_KEY") or values.get("EVENTFLOW_SUPABASE_PUBLISHABLE_KEY", "")
        if not url or not key or "YOUR_PROJECT" in url or "REPLACE_ME" in key:
            raise RuntimeError("EVENTFLOW_SUPABASE_URL과 EVENTFLOW_SUPABASE_PUBLISHABLE_KEY를 설정해 주세요.")
        local_app_data = Path(getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return cls(url, key, local_app_data / "EventFlowTeamsV2")
