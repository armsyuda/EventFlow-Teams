from __future__ import annotations

import argparse
from ctypes import wintypes
import os
import sys
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QThread, Signal, Qt, QTimer
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import QApplication, QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton, QScrollArea, QStackedWidget, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget

from event_checklist import __version__
from event_checklist.install_service import is_packaged_app
from event_checklist.theme import application_stylesheet
from event_checklist.update_service import UpdateInfo, download_update, fetch_latest_release, launch_installer, version_tuple
from event_checklist.ui.main_window import MainWindow
from event_checklist.ui.startup_splash import StartupSplash
from event_checklist.ui.title_bar import app_icon

from .api import ApiError, Organization, TeamsV2Api
from .config import TeamsV2Config
from .permissions import TeamsPermissionController
from .session import Session, SessionStore
from .workspace import WorkspaceDatabase, clear_user_workspaces, workspace_root
from .sync_store import WorkspaceSnapshotStore
from .sync_engine import WorkspaceSyncEngine
from .realtime import RealtimeSignalClient
from .outbox import WorkspaceOutbox


class Worker(QThread):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, task: Callable[[], object]) -> None:
        super().__init__(); self.task = task

    def run(self) -> None:
        try:
            self.finished.emit(self.task())
        except Exception as exc:
            self.failed.emit(str(exc))


def _launch_options(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--update-health-file", default="")
    parser.add_argument("--restarting-after-update", action="store_true")
    return parser.parse_known_args(argv)[0]


def _write_update_health_file(path: str) -> None:
    if path:
        Path(path).write_text("ok", encoding="ascii")


class ShellTitleBar(QFrame):
    """V2 chrome used before Local's own title bar is available."""

    def __init__(self, window: QMainWindow) -> None:
        super().__init__(window); self.window = window
        self.setObjectName("TeamsShellTitleBar"); self.setFixedHeight(44)
        layout = QHBoxLayout(self); layout.setContentsMargins(14, 0, 0, 0); layout.setSpacing(8)
        icon = QLabel(); icon.setPixmap(app_icon().pixmap(22, 22)); icon.setFixedSize(24, 24)
        title = QLabel("이벤트 플로우 Teams V2"); title.setObjectName("TeamsShellTitle")
        layout.addWidget(icon); layout.addWidget(title); layout.addStretch()
        for text, tip, callback, name in (("—", "창 최소화", window.showMinimized, "TitleControlButton"), ("□", "창 최대화", self.toggle_maximized, "TitleControlButton"), ("×", "프로그램 종료", window.close, "TitleCloseButton")):
            button = QPushButton(text); button.setObjectName(name); button.setToolTip(tip); button.setFixedSize(46, 44); button.clicked.connect(callback); layout.addWidget(button)

    def toggle_maximized(self) -> None:
        self.window.showNormal() if self.window.isMaximized() else self.window.showMaximized()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximized(); event.accept()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and not self.window.isMaximized():
            handle = self.window.windowHandle()
            if handle: handle.startSystemMove()
            event.accept()


class LoginPage(QWidget):
    signed_in = Signal(object)

    def __init__(self, api: TeamsV2Api) -> None:
        super().__init__(); self.api = api
        self.email = QLineEdit(); self.email.setPlaceholderText("이메일")
        self.password = QLineEdit(); self.password.setPlaceholderText("비밀번호"); self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.message = QLabel("회사 계정으로 로그인하세요.")
        self.button = QPushButton("로그인"); self.button.setProperty("primary", True)
        self.signup_button = QPushButton("직원 회원가입"); self.signup_button.setProperty("quiet", True)
        form = QFormLayout(); form.addRow("이메일", self.email); form.addRow("비밀번호", self.password)
        card = QFrame(); card.setObjectName("Card"); card.setMaximumWidth(460)
        layout = QVBoxLayout(card); layout.setContentsMargins(36, 34, 36, 34); layout.addWidget(QLabel("EVENTFLOW TEAMS V2", objectName="PageTitle")); layout.addWidget(QLabel("Local 업무 화면과 회사 동기화를 함께 사용합니다.", objectName="PageDescription")); layout.addWidget(self.message); layout.addLayout(form); layout.addWidget(self.button); layout.addWidget(self.signup_button)
        root = QVBoxLayout(self); root.setContentsMargins(24, 24, 24, 24); root.addStretch(); root.addWidget(card, 0, Qt.AlignmentFlag.AlignHCenter); root.addStretch()
        self.button.clicked.connect(self.login); self.password.returnPressed.connect(self.button.click); self.signup_button.clicked.connect(self.sign_up)

    def sign_up(self) -> None:
        dialog = QDialog(self); dialog.setWindowTitle("직원 회원가입"); dialog.setMinimumWidth(420)
        form = QFormLayout(dialog)
        name, phone, email = QLineEdit(), QLineEdit(), QLineEdit()
        password, confirm, code = QLineEdit(), QLineEdit(), QLineEdit()
        password.setEchoMode(QLineEdit.EchoMode.Password); confirm.setEchoMode(QLineEdit.EchoMode.Password)
        code.setMaxLength(5); code.setPlaceholderText("회사 관리자에게 받은 5자리 코드")
        form.addRow("이름", name); form.addRow("연락처", phone); form.addRow("이메일", email); form.addRow("비밀번호", password); form.addRow("비밀번호 확인", confirm); form.addRow("회사 코드", code)
        submit = QPushButton("가입하고 시작하기"); submit.setProperty("primary", True); form.addRow(submit)
        def submit_signup() -> None:
            if not name.text().strip() or not email.text().strip() or not password.text() or not code.text().strip():
                QMessageBox.warning(dialog, "입력 확인", "이름, 이메일, 비밀번호, 회사 코드를 입력하세요."); return
            if len(password.text()) < 8 or password.text() != confirm.text():
                QMessageBox.warning(dialog, "비밀번호 확인", "8자 이상의 동일한 비밀번호를 입력하세요."); return
            submit.setEnabled(False)
            worker = Worker(lambda: self.api.sign_up_employee(email.text().strip(), password.text(), name.text().strip(), phone.text().strip(), code.text().strip()))
            dialog.worker = worker
            worker.finished.connect(lambda session: (dialog.accept(), self.signed_in.emit(session)))
            worker.failed.connect(lambda message: (submit.setEnabled(True), QMessageBox.warning(dialog, "회원가입 실패", message)))
            worker.start()
        submit.clicked.connect(submit_signup)
        dialog.exec()

    def login(self) -> None:
        if not self.email.text().strip() or not self.password.text():
            self.message.setText("이메일과 비밀번호를 입력하세요."); return
        self.button.setEnabled(False); self.message.setText("로그인하는 중…")
        self.worker = Worker(lambda: self.api.sign_in(self.email.text().strip(), self.password.text()))
        self.worker.finished.connect(self._done); self.worker.failed.connect(self._failed); self.worker.start()

    def _done(self, session: object) -> None:
        self.password.clear(); self.button.setEnabled(True); self.signed_in.emit(session)

    def _failed(self, message: str) -> None:
        self.button.setEnabled(True); self.message.setText(message or "로그인에 실패했습니다.")


class OrganizationPage(QWidget):
    selected = Signal(object)
    logout_requested = Signal()
    organizations_loaded = Signal()

    def __init__(self, api: TeamsV2Api) -> None:
        super().__init__(); self.api = api; self.organizations: list[Organization] = []
        self.selected_organization: Organization | None = None; self.company_buttons: list[QPushButton] = []
        self.message = QLabel("회사를 확인하는 중…")
        self.company_list = QWidget(); self.company_list.setObjectName("TeamsCompanyList"); self.company_layout = QVBoxLayout(self.company_list); self.company_layout.setContentsMargins(0, 0, 0, 0); self.company_layout.setSpacing(7)
        self.more_button = QPushButton(); self.more_button.setProperty("quiet", True); self.more_button.hide(); self.more_button.clicked.connect(self._show_more)
        self.button = QPushButton("선택한 회사로 시작"); self.button.setProperty("primary", True); self.button.setEnabled(False)
        self.refresh_button = QPushButton("회사 목록 다시 확인"); self.refresh_button.setProperty("quiet", True); self.refresh_button.clicked.connect(self.load)
        self.retry_button = QPushButton("회사 목록 다시 시도"); self.retry_button.setProperty("quiet", True); self.retry_button.hide(); self.retry_button.clicked.connect(self._retry)
        card = QFrame(); card.setObjectName("Card"); card.setMaximumWidth(520); layout = QVBoxLayout(card); layout.setContentsMargins(36, 34, 36, 34); layout.addWidget(QLabel("회사 선택", objectName="PageTitle")); layout.addWidget(QLabel("작업할 회사를 선택하면 저장된 작업본을 먼저 열고, 변경분은 뒤에서 조용히 동기화합니다.", objectName="PageDescription")); layout.addWidget(self.message); layout.addWidget(self.company_list); layout.addWidget(self.more_button); layout.addWidget(self.button); layout.addWidget(self.refresh_button)
        layout.addWidget(self.retry_button)
        self.logout_button = QPushButton("로그아웃"); self.logout_button.setProperty("quiet", True); layout.addWidget(self.logout_button)
        root = QVBoxLayout(self); root.setContentsMargins(24, 24, 24, 24); root.addStretch(); root.addWidget(card, 0, Qt.AlignmentFlag.AlignHCenter); root.addStretch(); self.button.clicked.connect(self.choose)
        self.logout_button.clicked.connect(self.logout_requested)

    def load(self) -> None:
        if getattr(self, "worker", None) and self.worker.isRunning():
            return
        self.button.setEnabled(False); self.refresh_button.setEnabled(False); self.selected_organization = None; self.message.setText("접근 가능한 회사를 확인하는 중…")
        self.retry_button.hide()
        self.worker = Worker(self.api.organizations); self.worker.finished.connect(self._loaded); self.worker.failed.connect(self._failed); self.worker.start()

    def _loaded(self, value: object) -> None:
        self._automatic_retries = 0
        self.refresh_button.setEnabled(True)
        self.organizations = value if isinstance(value, list) else []
        while self.company_layout.count():
            item = self.company_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self.company_buttons.clear()
        for index, organization in enumerate(self.organizations):
            status = "권한 승인 대기" if organization.status == "PENDING" else organization.display_role
            item = QPushButton(f"{organization.name}\n{status}"); item.setObjectName("TeamsCompanyChoice"); item.setProperty("quiet", True); item.setCheckable(True); item.setVisible(index < 5)
            item.clicked.connect(lambda _checked=False, value=organization: self._select(value))
            self.company_buttons.append(item); self.company_layout.addWidget(item)
        hidden_count = max(0, len(self.organizations) - 5)
        self.more_button.setText(f"회사 {hidden_count}개 더 보기" if hidden_count else "")
        self.more_button.setVisible(bool(hidden_count))
        if self.organizations: self._select(self.organizations[0])
        self.button.setEnabled(bool(self.organizations)); self.message.setText("작업할 회사를 선택하세요." if self.organizations else "현재 접근 가능한 회사가 없습니다.")
        self.organizations_loaded.emit()

    def _failed(self, message: str) -> None:
        self.refresh_button.setEnabled(True)
        message = message or "회사 목록을 불러오지 못했습니다."
        self.message.setText(message)
        self.retry_button.show()
        # A transient network/API failure should not force a user through a
        # full sign-out/sign-in cycle.  Try twice in the background, then
        # leave an explicit retry action available.
        if "세션이 만료" not in message and getattr(self, "_automatic_retries", 0) < 2:
            self._automatic_retries = getattr(self, "_automatic_retries", 0) + 1
            self.message.setText(f"{message}\n연결을 다시 확인합니다. ({self._automatic_retries}/2)")
            QTimer.singleShot(900 * self._automatic_retries, self.load)

    def _retry(self) -> None:
        self._automatic_retries = 0
        self.load()

    def choose(self) -> None:
        if self.selected_organization:
            self.selected.emit(self.selected_organization)

    def _select(self, organization: Organization) -> None:
        self.selected_organization = organization
        for button, value in zip(self.company_buttons, self.organizations): button.setChecked(value.id == organization.id)
        self.button.setText(f"{organization.name}로 시작")

    def _show_more(self) -> None:
        for button in self.company_buttons: button.show()
        self.more_button.hide()


class PendingApprovalPage(QWidget):
    refresh_requested = Signal()

    def __init__(self) -> None:
        super().__init__(); self.setObjectName("TeamsPendingApprovalPage")
        root = QVBoxLayout(self); root.setContentsMargins(36, 36, 36, 36); root.addStretch()
        card = QFrame(); card.setObjectName("Card"); card.setMaximumWidth(520); box = QVBoxLayout(card); box.setContentsMargins(38, 36, 38, 36)
        box.addWidget(QLabel("권한 승인 대기", objectName="PageTitle")); self.company = QLabel(); self.company.setObjectName("SectionTitle"); box.addWidget(self.company)
        box.addWidget(QLabel("아직 권한이 없습니다. 회사 관리자의 승인을 기다리고 있습니다. 승인되면 아래 버튼으로 바로 확인할 수 있습니다.", objectName="PageDescription"))
        self.refresh = QPushButton("권한 승인 다시 확인"); self.refresh.setProperty("primary", True); self.refresh.clicked.connect(self.refresh_requested); box.addWidget(self.refresh)
        self.message = QLabel(""); box.addWidget(self.message); root.addWidget(card, 0, Qt.AlignmentFlag.AlignHCenter); root.addStretch()

    def show_company(self, organization: Organization) -> None:
        self.company.setText(organization.name)


class ConflictDialog(QDialog):
    """Explicitly choose the server value or retry the user's local value."""

    def __init__(self, server_value: str, local_value: str, parent: QWidget) -> None:
        super().__init__(parent); self.keep_local = False
        self.setWindowTitle("동시 수정 확인"); self.setMinimumWidth(620)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("같은 항목을 다른 사용자가 먼저 수정했습니다. 자동으로 덮어쓰지 않았습니다."))
        layout.addWidget(QLabel("서버 변경")); server = QTextEdit(); server.setReadOnly(True); server.setPlainText(server_value); server.setMaximumHeight(145); layout.addWidget(server)
        layout.addWidget(QLabel("내 변경")); local = QTextEdit(); local.setReadOnly(True); local.setPlainText(local_value); local.setMaximumHeight(145); layout.addWidget(local)
        buttons = QDialogButtonBox()
        use_server = buttons.addButton("서버 변경 사용", QDialogButtonBox.ButtonRole.RejectRole)
        keep = buttons.addButton("내 변경 다시 적용", QDialogButtonBox.ButtonRole.AcceptRole)
        use_server.clicked.connect(self.reject); keep.clicked.connect(self._keep)
        layout.addWidget(buttons)

    def _keep(self) -> None:
        self.keep_local = True; self.accept()


class CompanyManagementPage(QWidget):
    """A real in-workspace page; dialogs are only used for a chosen action."""

    guests_requested = Signal()
    members_requested = Signal()
    company_code_requested = Signal()
    approvals_requested = Signal()

    def __init__(self, organization: Organization) -> None:
        super().__init__(); self.setObjectName("TeamsCompanyManagementPage")
        root = QVBoxLayout(self); root.setContentsMargins(42, 38, 42, 38); root.setSpacing(16)
        root.addWidget(QLabel("회사 관리", objectName="PageTitle"))
        root.addWidget(QLabel(f"{organization.name}의 직원 권한과 프로젝트 게스트를 관리합니다. 플랫폼 관리 기능은 웹앱에서만 제공합니다.", objectName="PageDescription"))
        if organization.role in {"OWNER", "ADMIN"}:
            approvals = QFrame(); approvals.setObjectName("Card"); approvals_layout = QVBoxLayout(approvals)
            approvals_row = QHBoxLayout(); approvals_copy = QVBoxLayout(); approvals_copy.addWidget(QLabel("직원 가입 승인", objectName="SectionTitle")); approvals_copy.addWidget(QLabel("회사 코드로 가입한 직원을 승인하고 기본 역할을 부여합니다.")); approvals_row.addLayout(approvals_copy, 1)
            approvals_button = QPushButton("가입 요청 확인"); approvals_button.setProperty("primary", True); approvals_button.setFixedWidth(156); approvals_button.clicked.connect(self.approvals_requested); approvals_row.addWidget(approvals_button, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter); approvals_layout.addLayout(approvals_row); root.addWidget(approvals)
            code = QFrame(); code.setObjectName("Card"); code_layout = QVBoxLayout(code)
            code_row = QHBoxLayout(); code_copy = QVBoxLayout(); code_copy.addWidget(QLabel("직원 가입 코드", objectName="SectionTitle")); code_copy.addWidget(QLabel("일반 직원 가입에만 쓰는 고정 5자리 코드입니다. 게스트는 프로젝트 초대 링크를 사용합니다.")); code_row.addLayout(code_copy, 1)
            self.company_code_button = QPushButton("회사 코드 복사"); self.company_code_button.setProperty("primary", True); self.company_code_button.setFixedWidth(156); self.company_code_button.clicked.connect(self.company_code_requested); code_row.addWidget(self.company_code_button, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter); code_layout.addLayout(code_row)
            root.addWidget(code)
            members = QFrame(); members.setObjectName("Card"); member_layout = QVBoxLayout(members)
            member_row = QHBoxLayout(); member_copy = QVBoxLayout(); member_copy.addWidget(QLabel("직원 및 권한", objectName="SectionTitle")); member_copy.addWidget(QLabel("직원 역할, 활성 상태, 화면별 조회·편집 권한을 관리합니다.")); member_row.addLayout(member_copy, 1)
            member_button = QPushButton("직원·권한 관리"); member_button.setProperty("primary", True); member_button.setFixedWidth(156); member_button.clicked.connect(self.members_requested); member_row.addWidget(member_button, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter); member_layout.addLayout(member_row)
            root.addWidget(members)
        guests = QFrame(); guests.setObjectName("Card"); guest_layout = QVBoxLayout(guests)
        guest_row = QHBoxLayout(); guest_copy = QVBoxLayout(); guest_copy.addWidget(QLabel("프로젝트 게스트 초대", objectName="SectionTitle")); guest_copy.addWidget(QLabel("게스트는 초대된 프로젝트의 체크리스트·달력만 조회합니다. 초대 링크는 한 번만 사용되며 7일 후 만료됩니다.")); guest_row.addLayout(guest_copy, 1)
        guest_button = QPushButton("게스트 초대 관리"); guest_button.setProperty("primary", True); guest_button.setFixedWidth(156); guest_button.clicked.connect(self.guests_requested); guest_row.addWidget(guest_button, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter); guest_layout.addLayout(guest_row)
        root.addWidget(guests); root.addStretch()

    def set_company_code_loading(self, loading: bool) -> None:
        if hasattr(self, "company_code_button"):
            self.company_code_button.setEnabled(not loading)
            self.company_code_button.setText("회사 코드 확인 중…" if loading else "회사 코드 복사")


class CompanyMembersPage(QWidget):
    """Select a person first, then edit role, status, and visible menus."""

    back_requested = Signal()
    role_labels = {"OWNER": "회사 소유자", "ADMIN": "회사 관리자", "PM": "프로젝트 담당자", "MEMBER": "일반 직원", "VIEWER": "조회 전용", "GUEST": "프로젝트 손님"}
    role_sort_order = {"OWNER": 0, "ADMIN": 1, "PM": 2, "MEMBER": 3, "VIEWER": 4, "GUEST": 5}
    role_defaults = {
        "OWNER": {"dashboard.view","events.view","events.create","events.edit","events.archive","checklist.view","checklist.edit","checklist.assign","checklist.structure","calendar.view","calendar.edit","settlement.view","settlement.edit","contacts.view","contacts.edit","master_items.view","master_items.edit","participants.view","participants.edit","exports.use","backup.create","backup.restore","members.view","members.manage","permissions.manage"},
        "ADMIN": {"dashboard.view","events.view","events.create","events.edit","events.archive","checklist.view","checklist.edit","checklist.assign","checklist.structure","calendar.view","calendar.edit","settlement.view","settlement.edit","contacts.view","contacts.edit","master_items.view","master_items.edit","participants.view","participants.edit","exports.use","backup.create","backup.restore","members.view","members.manage","permissions.manage"},
        "PM": {"dashboard.view","events.view","events.create","events.edit","events.archive","checklist.view","checklist.edit","checklist.assign","checklist.structure","calendar.view","calendar.edit","settlement.view","settlement.edit","contacts.view","exports.use"},
        "MEMBER": {"dashboard.view","events.view","checklist.view","checklist.edit","checklist.assign","checklist.structure","calendar.view","calendar.edit","contacts.view","exports.use"},
        "VIEWER": {"dashboard.view","events.view","checklist.view","calendar.view","contacts.view","exports.use"},
    }
    permission_groups = {
        "업무 화면": [("대시보드", ("dashboard.view",), ()), ("체크리스트", ("checklist.view",), ("checklist.edit", "checklist.assign", "checklist.structure")), ("달력", ("calendar.view",), ("calendar.edit",)), ("정산내역", ("settlement.view",), ("settlement.edit",))],
        "회사 데이터": [("기본 항목", ("master_items.view",), ("master_items.edit",)), ("업체·담당자", ("contacts.view",), ("contacts.edit",))],
    }

    def __init__(self, api: TeamsV2Api, organization: Organization) -> None:
        super().__init__(); self.api = api; self.organization = organization; self.members: list[dict] = []; self.selected_member: dict | None = None; self.permission_boxes: dict[str, QCheckBox] = {}; self.permission_rows: list[tuple[QCheckBox, QCheckBox | None, tuple[str, ...], tuple[str, ...]]] = []; self._updating_permissions = False
        root = QVBoxLayout(self); root.setContentsMargins(32, 28, 32, 28); root.setSpacing(12)
        top = QHBoxLayout(); top.addWidget(QLabel("직원 및 권한", objectName="PageTitle")); top.addStretch(); self.back = QPushButton("← 회사 관리"); self.back.setProperty("quiet", True); self.refresh = QPushButton("새로고침"); self.refresh.setProperty("primary", True); top.addWidget(self.back); top.addWidget(self.refresh); root.addLayout(top)
        root.addWidget(QLabel("왼쪽에서 직원을 선택한 뒤 역할과 화면별 조회·편집 권한을 정하세요. 편집을 허용하면 조회도 함께 허용됩니다.", objectName="PageDescription"))
        self.message = QLabel(""); root.addWidget(self.message)
        content = QHBoxLayout(); content.setSpacing(16); root.addLayout(content, 1)
        self.table = QTableWidget(0, 3); self.table.setObjectName("TeamsMemberTable"); self.table.setHorizontalHeaderLabels(["직원", "역할", "접근 상태"]); self.table.horizontalHeader().setStretchLastSection(True); self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection); self.table.setStyleSheet("QTableWidget#TeamsMemberTable::item:selected { background:#FCE8DE; color:#172033; border-top:1px solid #F15A24; border-bottom:1px solid #F15A24; } QTableWidget#TeamsMemberTable::item:selected:!active { background:#FCE8DE; color:#172033; }"); self.table.setMaximumWidth(480); content.addWidget(self.table, 1)
        detail = QFrame(); detail.setObjectName("Card"); detail_layout = QVBoxLayout(detail); detail_layout.setSpacing(10)
        self.permission_scroll = QScrollArea(); self.permission_scroll.setObjectName("TeamsPermissionScroll"); self.permission_scroll.setWidgetResizable(True); self.permission_scroll.setFrameShape(QFrame.Shape.NoFrame); self.permission_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff); self.permission_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded); self.permission_scroll.setWidget(detail); content.addWidget(self.permission_scroll, 2)
        self.selected_caption = QLabel("선택한 직원", objectName="Muted"); detail_layout.addWidget(self.selected_caption)
        self.person = QLabel("왼쪽에서 직원을 선택하세요.", objectName="SectionTitle"); detail_layout.addWidget(self.person)
        self.email = QLabel(""); self.email.setObjectName("Muted"); detail_layout.addWidget(self.email)
        form = QFormLayout(); self.role = QComboBox(); self.status = QComboBox(); self.status.addItem("활성 · 바로 업무 가능", "ACTIVE"); self.status.addItem("업무 중지 · 회사 접근 차단", "SUSPENDED")
        for code in ("OWNER","ADMIN","PM","MEMBER","VIEWER"): self.role.addItem(self.role_labels[code], code)
        form.addRow("역할", self.role); form.addRow("상태", self.status); detail_layout.addLayout(form)
        self.notice = QLabel("역할을 고르면 권장 권한이 설정됩니다. 필요한 화면만 조회 또는 편집으로 조정하세요."); self.notice.setObjectName("InfoGuide"); detail_layout.addWidget(self.notice)
        for group, permissions in self.permission_groups.items():
            section = QFrame(); section.setObjectName("TeamsPermissionSection"); section.setStyleSheet("QFrame#TeamsPermissionSection { background:#FAFAFB; border:1px solid #E3E5E8; border-radius:10px; } QLabel#SectionTitle { border:none; }")
            section_layout = QVBoxLayout(section); section_layout.setContentsMargins(16, 13, 16, 13); section_layout.setSpacing(10)
            section_layout.addWidget(QLabel(group, objectName="SectionTitle"))
            grid = QGridLayout(); grid.setHorizontalSpacing(18); grid.setVerticalSpacing(8); grid.addWidget(QLabel("기능"), 0, 0); grid.addWidget(QLabel("조회만"), 0, 1); grid.addWidget(QLabel("편집가능"), 0, 2)
            for index, (label, view_codes, edit_codes) in enumerate(permissions, start=1):
                view_box = QCheckBox(); view_box.setToolTip(f"{label} 조회 허용"); grid.addWidget(QLabel(label), index, 0)
                grid.addWidget(view_box, index, 1, Qt.AlignmentFlag.AlignHCenter)
                edit_box = QCheckBox() if edit_codes else None
                if edit_box: edit_box.setToolTip(f"{label} 편집 허용"); grid.addWidget(edit_box, index, 2, Qt.AlignmentFlag.AlignHCenter)
                else: grid.addWidget(QLabel("—"), index, 2, Qt.AlignmentFlag.AlignHCenter)
                self.permission_rows.append((view_box, edit_box, view_codes, edit_codes))
                for code in (*view_codes, *edit_codes): self.permission_boxes[code] = edit_box if code in edit_codes and edit_box else view_box
                view_box.toggled.connect(lambda checked, edit=edit_box: self._view_toggled(checked, edit))
                if edit_box: edit_box.toggled.connect(lambda checked, view=view_box: self._edit_toggled(checked, view))
            grid.setColumnStretch(0, 1); grid.setColumnMinimumWidth(1, 76); grid.setColumnMinimumWidth(2, 92)
            section_layout.addLayout(grid); detail_layout.addWidget(section)
        export_section = QFrame(); export_section.setObjectName("TeamsPermissionSection"); export_section.setStyleSheet("QFrame#TeamsPermissionSection { background:#FAFAFB; border:1px solid #E3E5E8; border-radius:10px; } QLabel#SectionTitle { border:none; }")
        export_layout = QHBoxLayout(export_section); export_layout.setContentsMargins(16, 13, 16, 13); export_layout.addWidget(QLabel("출력", objectName="SectionTitle")); export_layout.addStretch(); self.export_box = QCheckBox("PDF·Excel 출력 허용"); self.permission_boxes["exports.use"] = self.export_box; export_layout.addWidget(self.export_box); detail_layout.addWidget(export_section)
        detail_layout.addStretch(); self.apply = QPushButton("변경사항 적용"); self.apply.setProperty("primary", True); self.apply.setEnabled(False); detail_layout.addWidget(self.apply)
        self.back.clicked.connect(self.back_requested); self.refresh.clicked.connect(self.load); self.table.cellClicked.connect(self._select_row); self.role.currentIndexChanged.connect(self._role_changed); self.apply.clicked.connect(self.apply_changes)

    def load(self) -> None:
        self.refresh.setEnabled(False); self.message.setText("직원 목록을 불러오는 중…")
        try: self.members = self.api.company_members(self.organization.id)
        except ApiError as exc: self.message.setText(str(exc)); return
        finally: self.refresh.setEnabled(True)
        self.members.sort(key=lambda member: (self.role_sort_order.get(str(member.get("role")), 99), str(member.get("display_name") or member.get("email") or "").casefold()))
        self.table.setRowCount(len(self.members))
        for row, member in enumerate(self.members):
            name = str(member.get("display_name") or member.get("email") or member.get("user_id", ""))
            values = (name, self.role_labels.get(str(member.get("role")), str(member.get("role"))), "● 사용 가능" if member.get("status") == "ACTIVE" else "● 접근 중지")
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 2: item.setForeground(QColor("#18A558" if member.get("status") == "ACTIVE" else "#7B818A"))
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents(); self.message.setText(f"직원 {len(self.members)}명을 표시합니다.")
        if self.members: self._select_row(0, 0)

    def _select_row(self, row: int, _column: int) -> None:
        if row < 0 or row >= len(self.members): return
        self.table.selectRow(row)
        self.selected_member = self.members[row]; member = self.selected_member
        selected_name = str(member.get("display_name") or member.get("email") or "직원")
        self.selected_caption.setText(f"선택한 직원 · {row + 1}번")
        self.person.setText(selected_name); self.email.setText(str(member.get("email") or ""))
        role = str(member.get("role") or "MEMBER"); self.role.setCurrentIndex(max(0, self.role.findData(role))); self.status.setCurrentIndex(max(0, self.status.findData(str(member.get("status") or "ACTIVE"))))
        overrides = {str(item.get("permission_code")): str(item.get("effect")) for item in member.get("overrides", []) if isinstance(item, dict)}
        defaults = self.role_defaults.get(role, set())
        self._updating_permissions = True
        for view_box, edit_box, view_codes, edit_codes in self.permission_rows:
            view_box.setChecked(all(overrides.get(code) == "ALLOW" or (code in defaults and overrides.get(code) != "DENY") for code in view_codes))
            if edit_box: edit_box.setChecked(all(overrides.get(code) == "ALLOW" or (code in defaults and overrides.get(code) != "DENY") for code in edit_codes))
        self.export_box.setChecked(overrides.get("exports.use") == "ALLOW" or ("exports.use" in defaults and overrides.get("exports.use") != "DENY"))
        self._updating_permissions = False
        locked = role == "OWNER" and self.organization.role != "OWNER"
        self.role.setEnabled(not locked); self.status.setEnabled(not locked); self.apply.setEnabled(not locked)
        for box in set(self.permission_boxes.values()): box.setEnabled(not locked)
        self.notice.setText("회사 소유자는 소유자만 변경할 수 있습니다." if locked else "프로젝트 참여자·백업·직원 관리는 역할에 따라 자동 적용됩니다.")

    def _role_changed(self) -> None:
        if not self.selected_member: return
        defaults = self.role_defaults.get(str(self.role.currentData()), set()); self._updating_permissions = True
        for view_box, edit_box, view_codes, edit_codes in self.permission_rows:
            view_box.setChecked(all(code in defaults for code in view_codes))
            if edit_box: edit_box.setChecked(all(code in defaults for code in edit_codes))
        self.export_box.setChecked("exports.use" in defaults); self._updating_permissions = False

    def apply_changes(self) -> None:
        if not self.selected_member: return
        user_id = str(self.selected_member.get("user_id")); role = str(self.role.currentData()); status = str(self.status.currentData()); defaults = self.role_defaults.get(role, set())
        requested: dict[str, bool] = {"exports.use": self.export_box.isChecked()}
        for view_box, edit_box, view_codes, edit_codes in self.permission_rows:
            requested.update({code: view_box.isChecked() for code in view_codes})
            if edit_box: requested.update({code: edit_box.isChecked() for code in edit_codes})
        overrides = [{"permission_code": code, "effect": "ALLOW" if allowed else "DENY"} for code, allowed in requested.items() if allowed != (code in defaults)]
        self.apply.setEnabled(False); self.message.setText("변경사항을 적용하는 중…")
        try:
            self.api.update_company_member(self.organization.id, user_id, role, status)
            self.api.save_member_permission_overrides(self.organization.id, user_id, overrides)
        except ApiError as exc:
            self.message.setText(str(exc)); self.apply.setEnabled(True); return
        self.message.setText(f"{self.person.text()}님의 역할과 메뉴 권한을 변경했습니다.")
        self.load()

    def _view_toggled(self, checked: bool, edit_box: QCheckBox | None) -> None:
        if self._updating_permissions or checked or not edit_box: return
        edit_box.setChecked(False)

    def _edit_toggled(self, checked: bool, view_box: QCheckBox) -> None:
        if self._updating_permissions or not checked: return
        view_box.setChecked(True)


class GuestManagementPage(QWidget):
    """Guest links are created in the workspace, without a native dialog."""

    back_requested = Signal()

    def __init__(self, api: TeamsV2Api, organization: Organization, workspace: WorkspaceDatabase) -> None:
        super().__init__(); self.api = api; self.organization = organization; self.workspace = workspace
        root = QVBoxLayout(self); root.setContentsMargins(42, 38, 42, 38); root.setSpacing(14)
        top = QHBoxLayout(); top.addWidget(QLabel("프로젝트 게스트 초대", objectName="PageTitle")); top.addStretch(); back = QPushButton("← 회사 관리"); back.setProperty("quiet", True); top.addWidget(back); root.addLayout(top)
        root.addWidget(QLabel("초대 링크는 한 번만 사용할 수 있고 7일 후 만료됩니다. 게스트는 체크리스트·달력만 조회합니다.", objectName="PageDescription"))
        form = QFormLayout(); self.event = QComboBox(); self.settlement = QCheckBox("정산내역 조회 허용")
        self.settlement.setVisible(organization.role in {"OWNER", "ADMIN"})
        for item in workspace.query("SELECT id, name FROM events ORDER BY start_date, id"):
            remote = workspace.one("SELECT remote_id FROM teams_v2_entity_map WHERE entity_type='EVENT' AND local_id=?", (item["id"],))
            if remote: self.event.addItem(str(item["name"]), str(remote["remote_id"]))
        form.addRow("프로젝트", self.event); form.addRow("추가 권한", self.settlement); root.addLayout(form)
        self.create = QPushButton("초대 링크 만들기"); self.create.setProperty("primary", True); root.addWidget(self.create)
        self.link = QLineEdit(); self.link.setReadOnly(True); self.link.setPlaceholderText("생성된 초대 링크가 여기에 표시됩니다."); root.addWidget(self.link)
        self.message = QLabel(""); root.addWidget(self.message); root.addStretch()
        back.clicked.connect(self.back_requested); self.create.clicked.connect(self.create_invite)

    def create_invite(self) -> None:
        event_id = self.event.currentData()
        if not event_id: self.message.setText("초대할 프로젝트를 선택하세요."); return
        try: invite = self.api.create_guest_invitation(str(event_id), self.settlement.isChecked())
        except ApiError as exc: self.message.setText(str(exc)); return
        url = f"https://eventflow-web.tank-park.workers.dev/guest-invite?token={invite['token']}"
        self.link.setText(url); self.link.selectAll(); QApplication.clipboard().setText(url); self.message.setText("초대 링크를 클립보드에 복사했습니다.")


class GuestInvitationDialog(QDialog):
    """Small V2-only guest invitation manager backed by server RPCs."""

    def __init__(self, api: TeamsV2Api, organization: Organization, workspace: WorkspaceDatabase, parent: QWidget) -> None:
        super().__init__(parent); self.api = api; self.organization = organization; self.workspace = workspace
        self.setWindowTitle("프로젝트 게스트 초대"); self.setMinimumWidth(680); self.setModal(True)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("게스트는 초대된 프로젝트의 체크리스트·달력만 조회할 수 있습니다. 초대 링크는 한 번만 사용할 수 있고 7일 후 만료됩니다.", objectName="PageDescription"))
        form = QFormLayout(); self.event = QComboBox(); self.settlement = QCheckBox("정산내역 조회 허용")
        self.settlement.setVisible(organization.role in {"OWNER", "ADMIN"})
        for item in workspace.query("SELECT id, name FROM events ORDER BY start_date, id"):
            remote = workspace.one("SELECT remote_id FROM teams_v2_entity_map WHERE entity_type='EVENT' AND local_id=?", (item["id"],))
            if remote: self.event.addItem(str(item["name"]), str(remote["remote_id"]))
        form.addRow("프로젝트", self.event); form.addRow("추가 권한", self.settlement); layout.addLayout(form)
        row = QHBoxLayout(); self.create = QPushButton("초대 링크 만들기", objectName="primaryButton"); self.refresh = QPushButton("목록 새로고침")
        row.addWidget(self.create); row.addWidget(self.refresh); row.addStretch(); layout.addLayout(row)
        self.table = QTableWidget(0, 5); self.table.setHorizontalHeaderLabels(["프로젝트", "만료", "정산", "상태", "취소"]); self.table.horizontalHeader().setStretchLastSection(True); layout.addWidget(self.table)
        self.members_table: QTableWidget | None = None
        if organization.role in {"OWNER", "ADMIN"}:
            layout.addWidget(QLabel("직원 및 역할", objectName="PageTitle"))
            self.members_table = QTableWidget(0, 4); self.members_table.setHorizontalHeaderLabels(["직원", "역할", "상태", "변경"]); self.members_table.horizontalHeader().setStretchLastSection(True); layout.addWidget(self.members_table)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close); close.rejected.connect(self.reject); layout.addWidget(close)
        self.create.clicked.connect(self.create_invite); self.refresh.clicked.connect(self.load); self.load()

    def create_invite(self) -> None:
        event_id = self.event.currentData()
        if not event_id: QMessageBox.information(self, "프로젝트 필요", "초대할 프로젝트를 선택하세요."); return
        self.create.setEnabled(False)
        try:
            invite = self.api.create_guest_invitation(str(event_id), self.settlement.isChecked())
        except ApiError as exc:
            QMessageBox.warning(self, "초대 생성 실패", str(exc)); return
        finally:
            self.create.setEnabled(True)
        url = f"https://eventflow-web.tank-park.workers.dev/guest-invite?token={invite['token']}"
        QApplication.clipboard().setText(url)
        QMessageBox.information(self, "초대 링크 생성", f"초대 링크를 클립보드에 복사했습니다.\n\n{url}\n\n링크는 7일 안에 한 번만 사용할 수 있습니다.")
        self.load()

    def load(self) -> None:
        try: invitations = self.api.guest_invitations(self.organization.id)
        except ApiError as exc: QMessageBox.warning(self, "목록 조회 실패", str(exc)); return
        self.table.setRowCount(len(invitations))
        for row, invite in enumerate(invitations):
            state = "취소됨" if invite.get("revoked_at") else "사용됨" if invite.get("redeemed_at") else "만료" if str(invite.get("expires_at", "")) < __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat() else "사용 가능"
            for column, value in enumerate((invite.get("event_name", "프로젝트"), str(invite.get("expires_at", ""))[:16].replace("T", " "), "허용" if invite.get("settlement_allowed") else "숨김", state)):
                self.table.setItem(row, column, QTableWidgetItem(str(value)))
            cancel = QPushButton("초대 취소"); cancel.setEnabled(not invite.get("revoked_at") and not invite.get("redeemed_at")); cancel.clicked.connect(lambda _=False, iid=str(invite["id"]): self.revoke(iid)); self.table.setCellWidget(row, 4, cancel)
        self.table.resizeColumnsToContents()
        if self.members_table is not None:
            try: members = self.api.company_members(self.organization.id)
            except ApiError as exc: QMessageBox.warning(self, "직원 목록 조회 실패", str(exc)); return
            self.members_table.setRowCount(len(members))
            for row, member in enumerate(members):
                title = member.get("display_name") or member.get("email") or str(member.get("user_id"))[:8]
                for column, value in enumerate((title, member.get("role", ""), member.get("status", ""))): self.members_table.setItem(row, column, QTableWidgetItem(str(value)))
                edit = QPushButton("역할·상태 변경"); edit.setEnabled(not (member.get("role") == "OWNER" and self.organization.role != "OWNER")); edit.clicked.connect(lambda _=False, item=member: self.edit_member(item)); self.members_table.setCellWidget(row, 3, edit)
            self.members_table.resizeColumnsToContents()

    def edit_member(self, member: dict) -> None:
        options = ["OWNER", "ADMIN", "PM", "MEMBER", "VIEWER", "GUEST", "SUSPENDED"]
        current = str(member.get("role", "MEMBER")) if member.get("status") == "ACTIVE" else "SUSPENDED"
        choice, ok = QInputDialog.getItem(self, "직원 역할·상태", "역할 또는 비활성 상태", options, max(0, options.index(current) if current in options else 0), False)
        if not ok: return
        try: self.api.update_company_member(self.organization.id, str(member["user_id"]), None if choice == "SUSPENDED" else choice, "SUSPENDED" if choice == "SUSPENDED" else "ACTIVE")
        except ApiError as exc: QMessageBox.warning(self, "직원 변경 실패", str(exc)); return
        self.load()

    def revoke(self, invitation_id: str) -> None:
        if QMessageBox.question(self, "초대 취소", "이 초대 링크를 취소할까요?") != QMessageBox.StandardButton.Yes: return
        try: self.api.revoke_guest_invitation(invitation_id)
        except ApiError as exc: QMessageBox.warning(self, "초대 취소 실패", str(exc)); return
        self.load()


class TeamsV2Window(QMainWindow):
    def __init__(self, config: TeamsV2Config) -> None:
        super().__init__(); self.config = config; self.store = SessionStore(); self.api = TeamsV2Api(config); self.workspace_db: WorkspaceDatabase | None = None
        self.local_window: MainWindow | None = None; self.current_organization: Organization | None = None; self.permission_worker: Worker | None = None; self.snapshot_worker: Worker | None = None; self.changes_worker: Worker | None = None; self.sync_engine: WorkspaceSyncEngine | None = None; self.realtime: RealtimeSignalClient | None = None; self.access_realtime: RealtimeSignalClient | None = None; self._sync_workers: list[Worker] = []; self._opened_cursor = ""; self._opened_with_pending = False; self._force_snapshot = False
        self.update_info: UpdateInfo | None = None; self.update_progress: StartupSplash | None = None; self.update_check_worker: Worker | None = None; self.update_download_worker: Worker | None = None; self.company_code_worker: Worker | None = None
        self.company_management_page: CompanyManagementPage | None = None; self.company_members_page: CompanyMembersPage | None = None; self.guest_management_page: GuestManagementPage | None = None
        self.setWindowTitle("이벤트 플로우 Teams V2"); self.setWindowIcon(app_icon()); self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint); self.resize(1440, 900); self.setMinimumSize(1120, 700)
        outer = QWidget(); outer.setObjectName("AppRoot"); outer_layout = QVBoxLayout(outer); outer_layout.setContentsMargins(1, 1, 1, 1); outer_layout.setSpacing(0)
        self.shell_title_bar = ShellTitleBar(self); outer_layout.addWidget(self.shell_title_bar)
        self.stack = QStackedWidget(); outer_layout.addWidget(self.stack, 1); self.setCentralWidget(outer)
        self.login = LoginPage(self.api); self.organizations = OrganizationPage(self.api); self.pending_approval = PendingApprovalPage()
        self.stack.addWidget(self.login); self.stack.addWidget(self.organizations); self.stack.addWidget(self.pending_approval)
        self.login.signed_in.connect(self._signed_in); self.organizations.selected.connect(self._open_workspace); self.organizations.logout_requested.connect(self.logout); self.organizations.organizations_loaded.connect(self._persist_recovered_session); self.pending_approval.refresh_requested.connect(self._force_refresh)
        if is_packaged_app(): QTimer.singleShot(900, self._check_updates_on_launch)
        session = self.store.load()
        if session:
            self.api.session = session; self._start_access_realtime(); self.stack.setCurrentWidget(self.organizations); self.organizations.load()

    def _signed_in(self, session: object) -> None:
        if not isinstance(session, Session):
            return
        self.store.save(session); self._start_access_realtime(); self.stack.setCurrentWidget(self.organizations); self.organizations.load()

    def _persist_recovered_session(self) -> None:
        """Keep a rotated refresh token instead of retrying the expired one next launch."""
        if self.api.session:
            self.store.save(self.api.session)

    def _open_workspace(self, organization: Organization) -> None:
        if not self.api.session:
            return
        if organization.status == "PENDING":
            self._close_workspace(); self.current_organization = organization; self.pending_approval.show_company(organization); self.stack.setCurrentWidget(self.pending_approval); return
        self._close_workspace()
        self.current_organization = organization
        # The Local shell always receives a V2-owned database.  Its content is
        # replaced by the permission-filtered snapshot only after permission
        # verification has succeeded.
        root = workspace_root(self.config.data_root, self.api.session.user_id, organization.id)
        os.environ["EVENT_CHECKLIST_DATA_DIR"] = str(root)
        self.workspace_db = WorkspaceDatabase(root / "data" / "event_checklist.db", user_id=self.api.session.user_id, organization_id=organization.id)
        opened = self.workspace_db.one("SELECT remote_cursor FROM teams_v2_workspace WHERE singleton=1")
        self._opened_cursor = str(opened["remote_cursor"] or "") if opened else ""
        self._opened_with_pending = bool(self.workspace_db.pending_outbox())
        self.local_window = MainWindow(self.workspace_db, enable_update_check=False)
        self.local_window.setParent(self.stack)
        self.local_window.setWindowFlags(Qt.WindowType.Widget)
        self._configure_local_shell(self.local_window, organization)
        self.local_window.setEnabled(False)
        self.stack.addWidget(self.local_window); self.stack.setCurrentWidget(self.local_window); self.shell_title_bar.hide()
        self._set_sync_state("CHECKING", "권한 확인 중…")
        self.permission_worker = Worker(lambda: self.api.permissions(organization.id))
        self.permission_worker.finished.connect(lambda value, oid=organization.id: self._permissions_loaded(oid, value))
        self.permission_worker.failed.connect(lambda message, oid=organization.id: self._permissions_failed(oid, message))
        self.permission_worker.start()

    def _configure_local_shell(self, local: MainWindow, organization: Organization) -> None:
        """Inject Teams controls into Local's title bar without editing Local files."""
        # Local is embedded as a widget in the V2 frame.  Its original title
        # bar must therefore operate on the real outer window; otherwise it
        # accepts the drag event but has no native window to move.
        local.title_bar.window = self
        local.title_bar.update_button.hide(); local.title_bar.update_meta.hide()
        title_layout = local.title_bar.layout()
        self.sync_dot = QLabel(); self.sync_dot.setObjectName("TeamsSyncDot"); self.sync_dot.setFixedSize(10, 10)
        self.sync_text = QLabel(); self.sync_text.setObjectName("TeamsSyncText")
        self.sync_refresh = QPushButton("↻"); self.sync_refresh.setObjectName("TeamsSyncRefresh"); self.sync_refresh.setFixedSize(24, 24); self.sync_refresh.setToolTip("서버 변경사항 및 권한 다시 확인"); self.sync_refresh.clicked.connect(self._force_refresh)
        insert_at = max(0, title_layout.count() - 3)
        for offset, widget in enumerate((self.sync_dot, self.sync_text, self.sync_refresh)):
            title_layout.insertWidget(insert_at + offset, widget)
        self._replace_title_control(local.title_bar.minimum, self.showMinimized)
        self._replace_title_control(local.title_bar.maximum, self._toggle_maximized)
        self._replace_title_control(local.title_bar.close_button, self.close)
        # The Local save action is a recovery backup.  V2 synchronizes changes
        # automatically, so this slot becomes an explicit company switcher.
        try:
            local.save_button.clicked.disconnect()
        except RuntimeError:
            pass
        local.save_button.setObjectName("TeamsCompanySwitchButton")
        local.save_button.setProperty("teamsCompanySwitch", True)
        local.save_button.setText("회사변경")
        local.save_button.setToolTip("다른 회사 작업본으로 전환합니다. 변경사항은 자동 동기화됩니다.")
        local.save_button.clicked.connect(self._show_company_picker)
        settings_button = local.nav_buttons[4]
        settings_button.setText("⚙  설정")
        settings_button.setToolTip("기본 항목, 업체·담당자, 데이터 관리")
        self._install_company_management_button(local, organization)

    def _install_company_management_button(self, local: MainWindow, organization: Organization) -> None:
        """Add the V2-only company menu without altering the Local baseline."""
        if organization.role not in {"OWNER", "ADMIN", "PM", "MEMBER"}:
            return
        button = QPushButton("♙  회사 관리" if organization.role in {"OWNER", "ADMIN"} else "♙  게스트 초대")
        button.setProperty("nav", True); button.setToolTip("직원·권한 관리와 프로젝트 게스트 초대" if organization.role in {"OWNER", "ADMIN"} else "내가 접근할 수 있는 프로젝트에 게스트를 초대")
        layout = local.sidebar.layout(); insert_at = max(0, layout.count() - 5)
        layout.insertWidget(insert_at, button)
        self.company_management_page = CompanyManagementPage(organization)
        self.company_management_page.guests_requested.connect(self._show_guest_management_page)
        self.company_management_page.members_requested.connect(self._show_company_members_page)
        self.company_management_page.company_code_requested.connect(self._copy_company_join_code)
        self.company_management_page.approvals_requested.connect(self._review_pending_employee_requests)
        local.stack.addWidget(self.company_management_page)
        self.company_members_page = CompanyMembersPage(self.api, organization)
        self.company_members_page.back_requested.connect(lambda: local.stack.setCurrentWidget(self.company_management_page))
        local.stack.addWidget(self.company_members_page)
        if self.workspace_db:
            self.guest_management_page = GuestManagementPage(self.api, organization, self.workspace_db)
            self.guest_management_page.back_requested.connect(lambda: local.stack.setCurrentWidget(self.company_management_page))
            local.stack.addWidget(self.guest_management_page)
        button.clicked.connect(lambda: self._show_company_management(button))

    def _show_company_management(self, button: QPushButton) -> None:
        if not self.local_window or not self.company_management_page:
            return
        for nav in self.local_window.nav_buttons:
            nav.setChecked(False)
        button.setChecked(True)
        self.local_window.stack.setCurrentWidget(self.company_management_page)

    def _copy_company_join_code(self) -> None:
        if not self.current_organization or not self.company_management_page:
            return
        if self.company_code_worker and self.company_code_worker.isRunning():
            return
        organization_id = self.current_organization.id
        self.company_management_page.set_company_code_loading(True)
        self.company_code_worker = Worker(lambda: self.api.company_join_code(organization_id))
        self.company_code_worker.finished.connect(self._company_join_code_loaded)
        self.company_code_worker.failed.connect(self._company_join_code_failed)
        self.company_code_worker.start()

    def _company_join_code_loaded(self, value: object) -> None:
        if self.company_management_page:
            self.company_management_page.set_company_code_loading(False)
        if not isinstance(value, str) or len(value) != 5:
            self._show_toast("회사 코드를 확인하지 못했습니다.")
            return
        QApplication.clipboard().setText(value)
        self._show_toast(f"회사 코드 {value}를 클립보드에 복사했습니다.")

    def _company_join_code_failed(self, _message: str) -> None:
        if self.company_management_page:
            self.company_management_page.set_company_code_loading(False)
        self._show_toast("회사 코드를 불러오지 못했습니다. 관리자 권한을 확인해 주세요.")

    def _show_guest_management_page(self) -> None:
        if not self.local_window or not self.guest_management_page:
            return
        self.local_window.stack.setCurrentWidget(self.guest_management_page)

    def _show_company_members_page(self) -> None:
        if not self.local_window or not self.company_members_page:
            return
        self.local_window.stack.setCurrentWidget(self.company_members_page)
        self.company_members_page.load()

    def _review_pending_employee_requests(self) -> None:
        if not self.current_organization:
            return
        try:
            requests = self.api.pending_employee_requests(self.current_organization.id)
        except ApiError as exc:
            self._show_toast(str(exc)); return
        if not requests:
            self._show_toast("승인 대기 중인 직원 가입 요청이 없습니다."); return
        labels = [f"{item.get('display_name') or item.get('email')} · {item.get('email')}" for item in requests]
        selected, ok = QInputDialog.getItem(self, "직원 가입 승인", "가입 요청", labels, 0, False)
        if not ok: return
        request = requests[labels.index(selected)]
        decision = QMessageBox.question(self, "직원 가입 요청", "예: 승인\n아니요: 반려", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Yes)
        if decision == QMessageBox.StandardButton.Cancel: return
        if decision == QMessageBox.StandardButton.No:
            try: self.api.review_employee_request(str(request["id"]), "REJECTED")
            except ApiError as exc: self._show_toast(str(exc)); return
            self._show_toast("직원 가입 요청을 반려했습니다."); return
        role_label, ok = QInputDialog.getItem(self, "역할 선택", "승인할 역할", ["일반 직원", "조회 전용", "프로젝트 매니저", "회사 관리자"], 0, False)
        if not ok: return
        role = {"일반 직원":"MEMBER", "조회 전용":"VIEWER", "프로젝트 매니저":"PM", "회사 관리자":"ADMIN"}[role_label]
        try:
            self.api.review_employee_request(str(request["id"]), "APPROVED", role)
        except ApiError as exc:
            self._show_toast(str(exc)); return
        self._show_toast("직원 가입을 승인했습니다.")

    @staticmethod
    def _replace_title_control(button: QPushButton, callback: Callable[[], None]) -> None:
        try:
            button.clicked.disconnect()
        except RuntimeError:
            pass
        button.clicked.connect(callback)

    def _toggle_maximized(self) -> None:
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def _permissions_loaded(self, organization_id: str, value: object) -> None:
        if not self.current_organization or self.current_organization.id != organization_id or not self.local_window or not self.workspace_db:
            return
        permissions = set(value) if isinstance(value, set) else set()
        self.workspace_db.set_access_context(role=self.current_organization.role, permissions=permissions)
        cursor = self._opened_cursor
        if cursor and not self._force_snapshot:
            # A synchronized Local workspace is immediately usable.  Never
            # overwrite its outbox with a complete snapshot on later starts.
            controller = TeamsPermissionController(self.local_window, permissions, self.current_organization.role)
            controller.apply(); self.local_window.setEnabled(True)
            # The cached workspace is already safe to edit.  Start observing
            # its local outbox before the quiet delta request completes so a
            # user edit made during that request is never left unsent.
            self._start_sync_engine()
            self._start_realtime()
            if self._opened_with_pending:
                return
            self._set_sync_state("CHECKING", "서버 변경분 확인 중…")
            self.changes_worker = Worker(lambda: self.api.workspace_changes(organization_id, int(cursor or 0)))
            self.changes_worker.finished.connect(lambda changes, oid=organization_id: self._changes_loaded(oid, changes))
            self.changes_worker.failed.connect(lambda message, oid=organization_id: self._changes_failed(oid, message))
            self.changes_worker.start()
            return
        self._set_sync_state("CHECKING", "회사 작업본 확인 중…")
        self.snapshot_worker = Worker(lambda: self.api.workspace_snapshot(organization_id))
        self.snapshot_worker.finished.connect(lambda snapshot, oid=organization_id, granted=permissions: self._snapshot_loaded(oid, granted, snapshot))
        self.snapshot_worker.failed.connect(lambda message, oid=organization_id: self._snapshot_failed(oid, message))
        self.snapshot_worker.start()

    def _snapshot_loaded(self, organization_id: str, permissions: set[str], snapshot: object) -> None:
        self._force_snapshot = False
        if not self.current_organization or self.current_organization.id != organization_id or not self.local_window or not self.workspace_db:
            return
        if not isinstance(snapshot, dict):
            self._snapshot_failed(organization_id, "회사 작업본 응답이 올바르지 않습니다.")
            return
        try:
            WorkspaceSnapshotStore(self.workspace_db).apply_snapshot(snapshot)
            self.local_window.refresh_all()
        except Exception as exc:
            self._snapshot_failed(organization_id, str(exc))
            return
        controller = TeamsPermissionController(self.local_window, permissions, self.current_organization.role)
        controller.apply()
        self.local_window.setEnabled(True)
        self._set_sync_state("LOCAL", "동기화 완료")
        self._start_sync_engine()
        self._start_realtime()

    def _changes_loaded(self, organization_id: str, changes: object) -> None:
        if not self.current_organization or self.current_organization.id != organization_id or not self.local_window or not self.workspace_db:
            return
        if not isinstance(changes, dict):
            self._changes_failed(organization_id, "서버 변경분 응답이 올바르지 않습니다.")
            return
        # If a local edit was made while the request was in flight, preserve it
        # for the later conflict-aware sync stage instead of replacing it now.
        if self.workspace_db.pending_outbox():
            self._set_sync_state("CHECKING", "로컬 변경 전송 대기")
            return
        try:
            WorkspaceSnapshotStore(self.workspace_db).apply_changes(changes)
            self.local_window.refresh_all()
        except Exception as exc:
            self._changes_failed(organization_id, str(exc))
            return
        self._set_sync_state("LOCAL", "동기화 완료")
        self._start_sync_engine()
        self._start_realtime()

    def _changes_failed(self, organization_id: str, message: str) -> None:
        if not self.current_organization or self.current_organization.id != organization_id:
            return
        # Cached data remains usable.  A warning state is enough until the
        # approved retry/realtime worker is added in stage 4.
        self._set_sync_state("CHECKING", "서버 변경분 확인 보류", message or "서버 변경분을 확인하지 못했습니다.")

    def _snapshot_failed(self, organization_id: str, message: str) -> None:
        if not self.current_organization or self.current_organization.id != organization_id or not self.local_window:
            return
        self._set_sync_state("ERROR", "회사 작업본을 받을 수 없음", message or "서버 작업본 수신에 실패했습니다.")

    def _permissions_failed(self, organization_id: str, message: str) -> None:
        if not self.current_organization or self.current_organization.id != organization_id:
            return
        self._set_sync_state("ERROR", "권한을 확인할 수 없음", message or "서버 권한 확인에 실패했습니다.")

    def _set_sync_state(self, state: str, text: str, detail: str = "") -> None:
        if not hasattr(self, "sync_dot"):
            return
        colors = {"LOCAL": "#18A558", "SYNCED": "#18A558", "CHECKING": "#D99500", "SYNCING": "#D99500", "WAITING": "#D99500", "ERROR": "#E02020"}
        color = colors.get(state, "#D99500")
        self.sync_dot.setStyleSheet(f"background:{color}; border-radius:5px;")
        self.sync_dot.setToolTip(detail or text); self.sync_text.setText(text); self.sync_text.setToolTip(detail or text)

    def _start_access_realtime(self) -> None:
        if self.access_realtime or not self.api.session:
            return
        self.access_realtime = RealtimeSignalClient(self.config.supabase_url, self.config.publishable_key, self.api.session.access_token, self.api.session.user_id, "teams_v2_access_signals", "user_id")
        self.access_realtime.changed.connect(self._force_refresh)
        self.access_realtime.start()

    def _force_refresh(self) -> None:
        if not self.api.session:
            return
        if self.local_window and self.workspace_db and self.workspace_db.pending_outbox():
            self._show_toast("로컬 변경을 동기화한 뒤 서버 내용을 다시 확인해 주세요."); return
        if getattr(self, "access_refresh_worker", None) and self.access_refresh_worker.isRunning():
            return
        if hasattr(self, "sync_refresh"): self.sync_refresh.setEnabled(False)
        self._set_sync_state("CHECKING", "서버 변경사항 확인 중…") if hasattr(self, "sync_dot") else None
        self.access_refresh_worker = Worker(self.api.organizations)
        self.access_refresh_worker.finished.connect(self._force_refresh_loaded)
        self.access_refresh_worker.failed.connect(self._force_refresh_failed)
        self.access_refresh_worker.start()

    def _force_refresh_loaded(self, value: object) -> None:
        if hasattr(self, "sync_refresh"): self.sync_refresh.setEnabled(True)
        organizations = value if isinstance(value, list) else []
        self.organizations.organizations = organizations
        target = next((item for item in organizations if self.current_organization and item.id == self.current_organization.id), None)
        if target is None:
            self._close_workspace(); self.current_organization = None; self.stack.setCurrentWidget(self.organizations); self.organizations._loaded(organizations); return
        if target.status == "PENDING":
            self._open_workspace(target); return
        self._force_snapshot = True
        self._open_workspace(target)

    def _force_refresh_failed(self, message: str) -> None:
        if hasattr(self, "sync_refresh"): self.sync_refresh.setEnabled(True)
        self._set_sync_state("ERROR", "서버 변경사항 확인 실패", message)

    def _show_company_picker(self) -> None:
        # Close the embedded Local shell first, then defer page activation
        # until Qt has completed the button click, so the company list never
        # remains behind a deleted child widget.
        self._close_workspace()
        QTimer.singleShot(0, self._finish_show_company_picker)

    def _finish_show_company_picker(self) -> None:
        self.shell_title_bar.show(); self.stack.setCurrentWidget(self.organizations); self.organizations.load()

    def _check_updates_on_launch(self) -> None:
        """Apply a newer public release before the user starts work."""
        if self.update_check_worker and self.update_check_worker.isRunning():
            return
        self.update_check_worker = Worker(fetch_latest_release)
        self.update_check_worker.finished.connect(self._update_check_finished)
        self.update_check_worker.failed.connect(lambda _message: None)
        self.update_check_worker.start()

    def _update_check_finished(self, value: object) -> None:
        info = value if isinstance(value, UpdateInfo) else None
        if not info or not info.asset_url or version_tuple(info.version) <= version_tuple(__version__):
            return
        self.update_info = info
        self._download_and_apply_update()

    def _download_and_apply_update(self) -> None:
        if not self.update_info or self.update_download_worker:
            return
        self.setEnabled(False)
        self.update_progress = StartupSplash()
        self.update_progress.setWindowTitle("EventFlow Teams 업데이트")
        self.update_progress.show()
        self.update_progress.set_status(f"새 버전 {self.update_info.version}을 내려받고 있습니다…")
        self.update_download_worker = Worker(lambda: download_update(self.update_info))
        self.update_download_worker.finished.connect(self._update_downloaded)
        self.update_download_worker.failed.connect(self._update_failed)
        self.update_download_worker.start()

    def _update_downloaded(self, archive: object) -> None:
        if not isinstance(archive, Path) or not self.update_info:
            self._update_failed("업데이트 파일을 확인하지 못했습니다."); return
        if self.update_progress:
            self.update_progress.set_status("설치를 준비하고 있습니다. 잠시 후 자동으로 다시 시작합니다…")
        try:
            launch_installer(archive, self.update_info, os.getpid())
        except Exception as exc:
            self._update_failed(str(exc)); return
        QTimer.singleShot(700, QApplication.quit)

    def _update_failed(self, _message: str) -> None:
        # A temporary GitHub or network failure must never block normal login.
        if self.update_progress:
            self.update_progress.close(); self.update_progress = None
        self.update_download_worker = None
        self.setEnabled(True)

    def _close_workspace(self) -> None:
        if self.realtime:
            self.realtime.stop()
            self.realtime.wait(500)
            self.realtime.deleteLater()
            self.realtime = None
        if self.sync_engine:
            self.sync_engine.stop()
            self.sync_engine.deleteLater()
            self.sync_engine = None
        for worker in self._sync_workers:
            if worker.isRunning():
                worker.wait(250)
            worker.deleteLater()
        self._sync_workers.clear()
        if self.local_window:
            self.stack.removeWidget(self.local_window)
            self.local_window.close()
            self.local_window.deleteLater()
            self.local_window = None
        self.company_management_page = None; self.company_members_page = None; self.guest_management_page = None
        if self.workspace_db:
            self.workspace_db.close(); self.workspace_db = None
        self.current_organization = None
        self._opened_cursor = ""; self._opened_with_pending = False

    def _start_sync_engine(self) -> None:
        """Start V2-only background transmission after Local is usable."""
        if not self.workspace_db or not self.current_organization or self.sync_engine:
            return
        self.sync_engine = WorkspaceSyncEngine(
            self.workspace_db,
            self.current_organization.id,
            lambda mutations: self.api.apply_mutations(self.current_organization.id, mutations),
            self._run_sync_network,
        )
        self.sync_engine.state_changed.connect(self._set_sync_state)
        self.sync_engine.mutation_finished.connect(self._sync_mutation_finished)
        self.sync_engine.start()

    def _run_sync_network(self, task: Callable[[], object], done: Callable[[object], None], failed: Callable[[str], None]) -> None:
        worker = Worker(task)
        self._sync_workers.append(worker)
        def cleanup() -> None:
            if worker in self._sync_workers:
                self._sync_workers.remove(worker)
            worker.deleteLater()
        worker.finished.connect(done); worker.failed.connect(failed)
        worker.finished.connect(lambda _: cleanup()); worker.failed.connect(lambda _: cleanup())
        worker.start()

    def _sync_mutation_finished(self, result: str, detail: str) -> None:
        if result == "APPLIED":
            self._request_realtime_changes()
            return
        messages = {
            "WAITING": "인터넷 연결을 확인하면 변경을 자동으로 전송합니다.",
            "CONFLICT": "다른 사용자의 변경과 겹칩니다. 곧 비교 선택을 표시합니다.",
            "REJECTED": "변경을 서버가 거부했습니다. 권한 또는 최신 내용을 확인하세요.",
        }
        self._show_toast(messages.get(result, detail or "동기화 상태를 확인하세요."))
        if result == "CONFLICT":
            self._show_conflict_choice()

    def _show_toast(self, message: str) -> None:
        """A short in-app notice, never a native popup or loading window."""
        if not self.local_window:
            return
        toast = QFrame(self.local_window)
        toast.setObjectName("TeamsToast")
        box = QHBoxLayout(toast); box.setContentsMargins(14, 9, 14, 9)
        box.addWidget(QLabel(message))
        toast.setStyleSheet("QFrame#TeamsToast { background:#26323A; color:white; border-radius:7px; } QLabel { color:white; }")
        toast.adjustSize()
        toast.move(max(18, self.local_window.width() - toast.width() - 24), 56)
        toast.show()
        QTimer.singleShot(4200, toast.deleteLater)

    def _show_conflict_choice(self) -> None:
        if not self.workspace_db or not self.local_window:
            return
        conflict = self.workspace_db.one("SELECT * FROM teams_v2_conflicts WHERE status='OPEN' ORDER BY id LIMIT 1")
        if not conflict:
            return
        table = {"EVENT_TASK": "event_tasks", "EVENT": "events", "VENDOR": "contacts", "PERSON": "contacts", "MASTER_ITEM": "master_items"}.get(str(conflict["entity_type"]))
        local_row = self.workspace_db.one(f"SELECT * FROM {table} WHERE id=?", (conflict["local_id"],)) if table and conflict["local_id"] is not None else None
        import json
        server = json.dumps(json.loads(str(conflict["server_payload_json"] or "{}")), ensure_ascii=False, indent=2)
        local = json.dumps(dict(local_row) if local_row else {"message": "로컬 행을 찾을 수 없습니다."}, ensure_ascii=False, indent=2)
        dialog = ConflictDialog(server, local, self.local_window)
        dialog.exec()
        WorkspaceOutbox(self.workspace_db).resolve_conflict(int(conflict["id"]), keep_local=dialog.keep_local)
        if dialog.keep_local:
            self._show_toast("내 변경을 최신 서버 버전에 다시 적용합니다.")
        else:
            self._show_toast("서버 변경을 사용합니다.")
            self._request_realtime_changes()

    def _start_realtime(self) -> None:
        if self.realtime or not self.api.session or not self.current_organization:
            return
        self.realtime = RealtimeSignalClient(
            self.config.supabase_url, self.config.publishable_key,
            self.api.session.access_token, self.current_organization.id,
        )
        self.realtime.changed.connect(self._request_realtime_changes)
        self.realtime.state_changed.connect(self._realtime_state_changed)
        self.realtime.start()

    def _realtime_state_changed(self, state: str, text: str) -> None:
        if state == "STOPPED":
            return
        if state == "WAITING":
            self._set_sync_state("WAITING", text)

    def _request_realtime_changes(self) -> None:
        """Fetch authorized deltas after a signal; never refresh a whole screen."""
        if (not self.current_organization or not self.workspace_db or not self.local_window
                or self.workspace_db.pending_outbox() or (self.changes_worker and self.changes_worker.isRunning())):
            return
        row = self.workspace_db.one("SELECT remote_cursor FROM teams_v2_workspace WHERE singleton=1")
        cursor = int(row["remote_cursor"] or 0) if row else 0
        self.changes_worker = Worker(lambda: self.api.workspace_changes(self.current_organization.id, cursor))
        self.changes_worker.finished.connect(lambda changes, oid=self.current_organization.id: self._realtime_changes_loaded(oid, changes))
        self.changes_worker.failed.connect(lambda message, oid=self.current_organization.id: self._changes_failed(oid, message))
        self.changes_worker.start()

    def _realtime_changes_loaded(self, organization_id: str, changes: object) -> None:
        if not self.current_organization or self.current_organization.id != organization_id or not self.workspace_db or not self.local_window:
            return
        if not isinstance(changes, dict) or self.workspace_db.pending_outbox():
            return
        affected = self._current_event_task_ids(changes)
        try:
            applied = WorkspaceSnapshotStore(self.workspace_db).apply_changes(changes)
            if applied:
                self.local_window.refresh_all(self.local_window.selected_event_id)
                if affected:
                    QTimer.singleShot(80, lambda ids=affected: self._flash_task_rows(ids))
                    self._show_toast(f"현재 프로젝트 변경 {len(affected)}건을 반영했습니다.")
        except Exception as exc:
            self._changes_failed(organization_id, str(exc))

    def _current_event_task_ids(self, changes: dict) -> set[int]:
        if not self.workspace_db or not self.local_window or not self.local_window.selected_event_id:
            return set()
        current = self.workspace_db.one("SELECT remote_id FROM teams_v2_entity_map WHERE entity_type='EVENT' AND local_id=?", (self.local_window.selected_event_id,))
        current_id = str(current["remote_id"]) if current else ""
        result: set[int] = set()
        for change in changes.get("changes", []):
            if not isinstance(change, dict) or change.get("entity_type") != "EVENT_TASK":
                continue
            payload = change.get("payload") if isinstance(change.get("payload"), dict) else {}
            if str(payload.get("event_id") or "") != current_id:
                continue
            remote = str(payload.get("id") or change.get("entity_key") or "")
            row = self.workspace_db.one("SELECT local_id FROM teams_v2_entity_map WHERE entity_type='EVENT_TASK' AND remote_id=?", (remote,))
            if row:
                result.add(int(row["local_id"]))
        return result

    def _flash_task_rows(self, task_ids: set[int]) -> None:
        if not self.local_window or not task_ids:
            return
        table = self.local_window.events.table
        for row in range(table.rowCount()):
            matched = any((table.item(row, column) and table.item(row, column).data(Qt.ItemDataRole.UserRole) in task_ids) for column in range(table.columnCount()))
            if matched:
                for column in range(table.columnCount()):
                    item = table.item(row, column)
                    if item: item.setBackground(QBrush(QColor("#FFF3B0")))
        QTimer.singleShot(3000, lambda: self.local_window and self.local_window.events.set_event(self.local_window.selected_event_id))

    def logout(self) -> None:
        session = self.api.session
        self._close_workspace()
        if self.access_realtime:
            self.access_realtime.stop(); self.access_realtime.wait(500); self.access_realtime.deleteLater(); self.access_realtime = None
        if session:
            try:
                clear_user_workspaces(self.config.data_root, session.user_id)
            except OSError as exc:
                QMessageBox.warning(self, "작업본 삭제 실패", f"로그아웃은 완료했지만 이 기기의 작업본을 지우지 못했습니다.\n\n{exc}")
        self.store.clear(); self.api.session = None
        self.organizations.selected_organization = None
        self.shell_title_bar.show(); self.stack.setCurrentWidget(self.login)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._close_workspace()
        super().closeEvent(event)

    def nativeEvent(self, event_type, message):  # noqa: N802 - Windows Qt hook
        if event_type == b"windows_generic_MSG" and not self.isMaximized():
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0084:  # WM_NCHITTEST
                # Qt's cursor position is already DPI-normalized.  LPARAM is
                # physical pixels on some scaled Windows displays and made the
                # resize zone extend far into the content area.
                p = self.mapFromGlobal(self.cursor().pos()); border = 4
                left, right, top, bottom = p.x() < border, p.x() >= self.width() - border, p.y() < border, p.y() >= self.height() - border
                if top and left: return True, 13
                if top and right: return True, 14
                if bottom and left: return True, 16
                if bottom and right: return True, 17
                if left: return True, 10
                if right: return True, 11
                if top: return True, 12
                if bottom: return True, 15
        return super().nativeEvent(event_type, message)


def main(argv: list[str] | None = None) -> None:
    options = _launch_options(argv if argv is not None else sys.argv[1:])
    app = QApplication(sys.argv[:1])
    app.setApplicationName("이벤트 플로우 Teams V2")
    app.setStyleSheet(application_stylesheet())
    try:
        window = TeamsV2Window(TeamsV2Config.from_environment())
    except RuntimeError as exc:
        window = QMainWindow(); window.setCentralWidget(QLabel(str(exc))); window.resize(520, 180)
    window.show()
    if options.update_health_file:
        QTimer.singleShot(500, lambda: _write_update_health_file(options.update_health_file))
    raise SystemExit(app.exec())
