from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any
import requests

from .config import TeamsV2Config
from .session import Session


class ApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class Organization:
    id: str
    name: str
    role: str

    @property
    def display_role(self) -> str:
        if self.role in {"OWNER", "ADMIN"}:
            return "회사 관리자"
        if self.role == "GUEST":
            return "손님"
        return "회사 직원"


class TeamsV2Api:
    """Small V2-only Auth and membership client; Local UI never calls it directly."""

    def __init__(self, config: TeamsV2Config, session: Session | None = None) -> None:
        self.config = config
        self.session = session

    @property
    def headers(self) -> dict[str, str]:
        headers = {"apikey": self.config.publishable_key, "accept": "application/json"}
        if self.session:
            headers["authorization"] = f"Bearer {self.session.access_token}"
        return headers

    def sign_in(self, email: str, password: str) -> Session:
        response = requests.post(
            f"{self.config.supabase_url}/auth/v1/token?grant_type=password",
            headers={"apikey": self.config.publishable_key, "content-type": "application/json"},
            json={"email": email, "password": password},
            timeout=20,
        )
        if not response.ok:
            raise ApiError("로그인 정보를 확인할 수 없습니다.")
        payload = response.json(); user = payload.get("user") or {}
        if not payload.get("access_token") or not payload.get("refresh_token") or not user.get("id"):
            raise ApiError("로그인 응답이 올바르지 않습니다.")
        self.session = Session(payload["access_token"], payload["refresh_token"], user["id"], str(user.get("email") or email))
        return self.session

    def refresh_session(self) -> Session:
        if not self.session:
            raise ApiError("로그인이 필요합니다.")
        try:
            response = requests.post(
                f"{self.config.supabase_url}/auth/v1/token?grant_type=refresh_token",
                headers={"apikey": self.config.publishable_key, "content-type": "application/json"},
                json={"refresh_token": self.session.refresh_token},
                timeout=20,
            )
        except requests.RequestException as exc:
            raise ApiError("로그인 상태를 다시 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.") from exc
        if not response.ok:
            raise ApiError("로그인 세션이 만료되었습니다.")
        payload = response.json(); user = payload.get("user") or {}
        self.session = Session(payload["access_token"], payload["refresh_token"], user.get("id", self.session.user_id), str(user.get("email") or self.session.email))
        return self.session

    def organizations(self) -> list[Organization]:
        """Load the membership boundary, recovering an expired saved token once.

        Authentication and membership are separate services.  A successful
        password sign-in is therefore not considered a usable Teams session
        until this request has also succeeded.
        """
        if not self.session:
            return []
        refreshed = False
        response = None
        for attempt in range(3):
            try:
                response = requests.get(
                    f"{self.config.supabase_url}/rest/v1/organization_members",
                    params={"select": "organization_id,role,status,organizations(name)", "status": "eq.ACTIVE", "user_id": f"eq.{self.session.user_id}"},
                    headers=self.headers,
                    timeout=20,
                )
            except requests.RequestException as exc:
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise ApiError("회사 서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.") from exc
            if response.ok:
                break
            status = getattr(response, "status_code", 0)
            if status == 401 and not refreshed:
                try:
                    self.refresh_session()
                except ApiError as exc:
                    raise ApiError("로그인 세션이 만료되었습니다. 다시 로그인해 주세요.") from exc
                refreshed = True
                continue
            if status in {408, 429, 500, 502, 503, 504} and attempt < 2:
                time.sleep(0.5 * (attempt + 1))
                continue
            if status in {401, 403}:
                raise ApiError("회사 접근 권한을 확인할 수 없습니다. 계속되면 회사 관리자에게 문의해 주세요.")
            raise ApiError("회사 목록을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.")
        if response is None or not response.ok:
            raise ApiError("회사 서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.")
        priority = {"OWNER": 0, "ADMIN": 1, "PM": 2, "MEMBER": 3, "VIEWER": 4, "GUEST": 5}
        result: dict[str, Organization] = {}
        for row in response.json():
            organization = Organization(row["organization_id"], (row.get("organizations") or {}).get("name", "회사"), row["role"])
            existing = result.get(organization.id)
            if existing is None or priority.get(organization.role, 99) < priority.get(existing.role, 99):
                result[organization.id] = organization
        return sorted(result.values(), key=lambda item: (item.name.casefold(), priority.get(item.role, 99), item.id))

    def permissions(self, organization_id: str) -> set[str]:
        payload = self.rpc("get_my_teams_v2_permissions", {"target_organization_id": organization_id}, "회사 권한을 확인할 수 없습니다.")
        return {item for item in payload if isinstance(item, str)} if isinstance(payload, list) else set()

    def workspace_snapshot(self, organization_id: str) -> dict[str, Any]:
        payload = self.rpc("teams_v2_workspace_snapshot", {"target_organization_id": organization_id}, "회사 작업본을 받을 수 없습니다.")
        if not isinstance(payload, dict):
            raise ApiError("회사 작업본 응답이 올바르지 않습니다.")
        return payload

    def workspace_changes(self, organization_id: str, after_sequence: int) -> dict[str, Any]:
        payload = self.rpc(
            "teams_v2_workspace_changes",
            {"target_organization_id": organization_id, "after_sequence": max(0, int(after_sequence))},
            "서버 변경분을 확인할 수 없습니다.",
        )
        if not isinstance(payload, dict):
            raise ApiError("서버 변경분 응답이 올바르지 않습니다.")
        return payload

    def apply_mutations(self, organization_id: str, mutations: list[dict[str, Any]]) -> dict[str, Any]:
        payload = self.rpc(
            "teams_v2_apply_mutations",
            {"target_organization_id": organization_id, "requested_mutations": mutations},
            "로컬 변경을 서버에 보낼 수 없습니다.",
        )
        if not isinstance(payload, dict):
            raise ApiError("변경 저장 응답이 올바르지 않습니다.")
        return payload

    def create_guest_invitation(self, event_id: str, allow_settlement: bool) -> dict[str, Any]:
        payload = self.rpc("teams_v2_create_guest_invitation", {"target_event_id": event_id, "allow_settlement": allow_settlement}, "게스트 초대를 만들 수 없습니다.")
        if not isinstance(payload, dict) or not payload.get("token"):
            raise ApiError("게스트 초대 응답이 올바르지 않습니다.")
        return payload

    def guest_invitations(self, organization_id: str) -> list[dict[str, Any]]:
        payload = self.rpc("teams_v2_list_guest_invitations", {"target_organization_id": organization_id}, "게스트 초대 목록을 불러올 수 없습니다.")
        return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []

    def revoke_guest_invitation(self, invitation_id: str) -> None:
        self.rpc("teams_v2_revoke_guest_invitation", {"target_invitation_id": invitation_id}, "게스트 초대를 취소할 수 없습니다.")

    def company_members(self, organization_id: str) -> list[dict[str, Any]]:
        payload = self.rpc("teams_v2_company_members", {"target_organization_id": organization_id}, "직원 목록을 불러올 수 없습니다.")
        return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []

    def update_company_member(self, organization_id: str, user_id: str, role: str | None = None, status: str | None = None) -> None:
        self.rpc("teams_v2_update_company_member", {"target_organization_id": organization_id, "target_user_id": user_id, "target_role": role, "target_status": status}, "직원 정보를 바꿀 수 없습니다.")

    def save_member_permission_overrides(self, organization_id: str, user_id: str, overrides: list[dict[str, str]]) -> None:
        self.rpc("teams_v2_save_member_permission_overrides", {"target_organization_id": organization_id, "target_user_id": user_id, "requested_overrides": overrides}, "직원 메뉴 권한을 바꿀 수 없습니다.")

    def rpc(self, name: str, payload: dict[str, Any], error_message: str) -> Any:
        response = requests.post(
            f"{self.config.supabase_url}/rest/v1/rpc/{name}",
            headers={**self.headers, "content-type": "application/json"},
            json=payload,
            timeout=20,
        )
        if not response.ok:
            raise ApiError(error_message)
        return response.json()
