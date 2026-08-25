from __future__ import annotations

from dataclasses import dataclass
import keyring


SERVICE = "EventFlowTeamsV2"


@dataclass(frozen=True)
class Session:
    access_token: str
    refresh_token: str
    user_id: str
    email: str = ""


class SessionStore:
    """V2 has its own credential namespace and never reuses V1 tokens."""

    def save(self, session: Session) -> None:
        keyring.set_password(SERVICE, "access_token", session.access_token)
        keyring.set_password(SERVICE, "refresh_token", session.refresh_token)
        keyring.set_password(SERVICE, "user_id", session.user_id)
        keyring.set_password(SERVICE, "email", session.email)

    def load(self) -> Session | None:
        values = {name: keyring.get_password(SERVICE, name) for name in ("access_token", "refresh_token", "user_id", "email")}
        if not all(values.values()):
            return None
        return Session(values["access_token"] or "", values["refresh_token"] or "", values["user_id"] or "", values["email"] or "")

    def clear(self) -> None:
        for name in ("access_token", "refresh_token", "user_id", "email"):
            try:
                keyring.delete_password(SERVICE, name)
            except keyring.errors.PasswordDeleteError:
                pass
