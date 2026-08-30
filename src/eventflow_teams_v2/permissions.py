from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QAbstractItemView, QPushButton, QTabWidget, QWidget


ROLE_LABELS = {
    "OWNER": "회사 관리자",
    "ADMIN": "회사 관리자",
    "PM": "회사 직원",
    "MEMBER": "회사 직원",
    "VIEWER": "회사 직원 · 조회 전용",
    "GUEST": "손님",
}


class _ReadOnlyFilter(QObject):
    """Stops Local's double-click editors without changing Local source."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        if event.type() in {
            QEvent.Type.MouseButtonDblClick,
            QEvent.Type.KeyPress,
            QEvent.Type.InputMethod,
            QEvent.Type.FocusIn,
        }:
            return True
        return super().eventFilter(watched, event)


class TeamsPermissionController:
    """Applies server-granted capability codes to the untouched Local widgets."""

    def __init__(self, window: QWidget, permissions: Iterable[str], role: str) -> None:
        self.window = window
        self.permissions = set(permissions)
        self.role = role
        self._filters: list[_ReadOnlyFilter] = []

    @property
    def role_label(self) -> str:
        return ROLE_LABELS.get(self.role, "회사 직원")

    def allows(self, code: str) -> bool:
        return code in self.permissions

    def apply(self) -> None:
        local = self.window
        self._set_button_text(local.dashboard, "+ 프로젝트 생성", self.allows("events.create"), "프로젝트 만들기 권한이 없습니다.")
        self._set_button_text(local.dashboard, "프로젝트 정보 수정", self.allows("events.edit"), "프로젝트 수정 권한이 없습니다.")
        self._set_button_text(local.dashboard, "프로젝트 삭제", self.allows("events.archive"), "프로젝트 보관 권한이 없습니다.")

        self._set_button(local.events.import_button, self.allows("checklist.structure"), "체크리스트 구조 변경 권한이 없습니다.")
        self._set_button(local.events.edit_event_button, self.allows("events.edit"), "프로젝트 수정 권한이 없습니다.")
        self._set_button(local.events.add_button, self.allows("checklist.structure"), "체크리스트 구조 변경 권한이 없습니다.")
        self._set_button(local.events.remove_button, self.allows("checklist.structure"), "체크리스트 구조 변경 권한이 없습니다.")
        self._set_button(local.events.removed_toggle, self.allows("checklist.structure"), "체크리스트 구조 변경 권한이 없습니다.")
        self._set_button(local.events.bulk_assign_button, self.allows("checklist.assign"), "담당 지정 권한이 없습니다.")
        self._set_table_editable(local.events.table, self.allows("checklist.edit"), "체크리스트 편집 권한이 없습니다.")

        self._set_button(local.settlement.bulk_assign_button, self.allows("checklist.assign"), "담당 지정 권한이 없습니다.")
        self._set_widget(local.settlement.budget, self.allows("settlement.edit"), "정산 편집 권한이 없습니다.")
        self._set_widget(local.settlement.tax_mode, self.allows("settlement.edit"), "정산 편집 권한이 없습니다.")
        self._set_table_editable(local.settlement.table, self.allows("settlement.edit"), "정산 편집 권한이 없습니다.")

        self._apply_settings(local)
        # In Teams V2 this Local control becomes the company switcher.  It is
        # navigation, not a backup action, and must stay available to every
        # active member regardless of backup permission.
        if not local.save_button.property("teamsCompanySwitch"):
            self._set_button(local.save_button, self.allows("backup.create"), "백업 생성 권한이 없습니다.")

    def _apply_settings(self, local: QWidget) -> None:
        settings = local.settings
        tabs: QTabWidget = settings.tabs
        self._set_tab(tabs, 0, self.allows("master_items.view"), "기본 항목 보기 권한이 없습니다.")
        self._set_tab(tabs, 1, self.allows("contacts.view"), "업체·담당자 보기 권한이 없습니다.")
        self._set_tab(tabs, 2, self.allows("backup.create") or self.allows("exports.use"), "데이터 관리 권한이 없습니다.")

        editable_master = self.allows("master_items.edit")
        for name in ("add_button", "edit_button", "delete_button"):
            self._set_button(getattr(settings.master_page, name), editable_master, "기본 항목 편집 권한이 없습니다.")
        editable_contacts = self.allows("contacts.edit")
        for button in settings.contacts_page.findChildren(QPushButton):
            text = button.text()
            if any(token in text for token in ("추가", "삭제")):
                self._set_button(button, editable_contacts, "업체·담당자 편집 권한이 없습니다.")
        for table in (settings.contacts_page.vendor_table, settings.contacts_page.company_people, settings.contacts_page.freelancer_table):
            self._set_table_editable(table, editable_contacts, "업체·담당자 편집 권한이 없습니다.")

        for button in settings.findChildren(QPushButton):
            if button.text() == "지금 백업":
                self._set_button(button, self.allows("backup.create"), "백업 생성 권한이 없습니다.")
            elif button.text() == "백업에서 복원":
                self._set_button(button, self.allows("backup.restore"), "회사 관리자만 복원할 수 있습니다.")
            elif button.text() == "Excel 내보내기":
                self._set_button(button, self.allows("exports.use"), "출력 권한이 없습니다.")

    @staticmethod
    def _set_tab(tabs: QTabWidget, index: int, allowed: bool, reason: str) -> None:
        tabs.setTabEnabled(index, allowed)
        tabs.setTabToolTip(index, "" if allowed else reason)

    @staticmethod
    def _set_button(button: QPushButton, allowed: bool, reason: str) -> None:
        button.setEnabled(allowed)
        button.setToolTip("" if allowed else reason)

    def _set_button_text(self, parent: QWidget, text: str, allowed: bool, reason: str) -> None:
        for button in parent.findChildren(QPushButton):
            if button.text() == text:
                self._set_button(button, allowed, reason)

    @staticmethod
    def _set_widget(widget: QWidget, allowed: bool, reason: str) -> None:
        widget.setEnabled(allowed)
        widget.setToolTip("" if allowed else reason)

    def _set_table_editable(self, table: QAbstractItemView, allowed: bool, reason: str) -> None:
        table.setToolTip("" if allowed else reason)
        if allowed:
            return
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        event_filter = _ReadOnlyFilter(table)
        table.installEventFilter(event_filter)
        table.viewport().installEventFilter(event_filter)
        self._filters.append(event_filter)
