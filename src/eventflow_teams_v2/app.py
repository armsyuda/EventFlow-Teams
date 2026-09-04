from __future__ import annotations

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
from .staff_pages import EmployeeWorkPage
from .my_space_page import MySpacePage
from .company_workspace import CompanyWorkspace
from .company_pages import CompanyCalendarPage, FinancePage
from .notification_page import NotificationPage
from .diagnostics import RuntimeWindowTrace


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
        card = QFrame(); card.setObjectName("Card"); card.setMaximumWidth(520); layout = QVBoxLayout(card); layout.setContentsMargins(36, 34, 36, 34); layout.setSpacing(12)
        layout.addWidget(QLabel("회사 선택", objectName="PageTitle")); layout.addWidget(QLabel("시작할 회사를 누르면 바로 업무 화면으로 들어갑니다.", objectName="PageDescription"))
        self.message = QLabel("회사를 확인하는 중…", card)
        self.company_list = QWidget(card); self.company_list.setObjectName("TeamsCompanyList"); self.company_layout = QVBoxLayout(self.company_list); self.company_layout.setContentsMargins(0, 0, 0, 0); self.company_layout.setSpacing(7)
        self.more_button = QPushButton(card); self.more_button.setProperty("quiet", True); self.more_button.hide(); self.more_button.clicked.connect(self._show_more)
        self.retry_button = QPushButton("회사 목록 다시 시도", card); self.retry_button.setProperty("quiet", True); self.retry_button.hide(); self.retry_button.clicked.connect(self._retry)
        layout.addWidget(self.message); layout.addWidget(self.company_list); layout.addWidget(self.more_button)
        layout.addWidget(self.retry_button)
        divider = QFrame(card); divider.setFrameShape(QFrame.Shape.HLine); divider.setStyleSheet("color:#E2E8F0;"); layout.addSpacing(12); layout.addWidget(divider); layout.addSpacing(8)
        self.logout_button = QPushButton("로그아웃", card); self.logout_button.setProperty("quiet", True); layout.addWidget(self.logout_button, 0, Qt.AlignmentFlag.AlignRight)
        root = QVBoxLayout(self); root.setContentsMargins(24, 24, 24, 24); root.addStretch(); root.addWidget(card, 0, Qt.AlignmentFlag.AlignHCenter); root.addStretch()
        self.logout_button.clicked.connect(self.logout_requested)

    def load(self) -> None:
        if getattr(self, "worker", None) and self.worker.isRunning():
            return
        self.selected_organization = None; self.message.setText("접근 가능한 회사를 확인하는 중…")
        self.retry_button.hide()
        self.worker = Worker(self.api.organizations); self.worker.finished.connect(self._loaded); self.worker.failed.connect(self._failed); self.worker.start()

    def _loaded(self, value: object) -> None:
        self._automatic_retries = 0
        self.organizations = value if isinstance(value, list) else []
        while self.company_layout.count():
            item = self.company_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self.company_buttons.clear()
        for index, organization in enumerate(self.organizations):
            # This page is already visible when the company list arrives.  A
            # parentless button followed by setVisible(True) becomes a tiny
            # top-level native window for one frame before the layout adopts
            # it.  Create it in the list from the beginning instead.
            item = QPushButton(organization.name, self.company_list); item.setObjectName("TeamsCompanyChoice"); item.setProperty("primary", True); item.setToolTip(organization.display_role)
            item.clicked.connect(lambda _checked=False, value=organization: self.choose(value))
            self.company_buttons.append(item); self.company_layout.addWidget(item); item.setVisible(index < 5)
        hidden_count = max(0, len(self.organizations) - 5)
        self.more_button.setText(f"회사 {hidden_count}개 더 보기" if hidden_count else "")
        self.more_button.setVisible(bool(hidden_count))
        self.message.setText("회사를 누르면 바로 시작합니다." if self.organizations else "현재 접근 가능한 회사가 없습니다.")
        self.organizations_loaded.emit()

    def _failed(self, message: str) -> None:
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

    def choose(self, organization: Organization) -> None:
        self.selected_organization = organization
        self.selected.emit(organization)

    def _select(self, organization: Organization) -> None:
        self.selected_organization = organization

    def _show_more(self) -> None:
        for button in self.company_buttons: button.show()
        self.more_button.hide()


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

    def __init__(self, organization: Organization, api: TeamsV2Api | None = None) -> None:
        super().__init__(); self.setObjectName("TeamsCompanyManagementPage"); self.organization = organization; self.api = api
        root = QVBoxLayout(self); root.setContentsMargins(42, 38, 42, 38); root.setSpacing(16)
        root.addWidget(QLabel("회사 관리", objectName="PageTitle"))
        root.addWidget(QLabel(f"{organization.name}의 직원 권한과 프로젝트 게스트를 관리합니다. 플랫폼 관리 기능은 웹앱에서만 제공합니다.", objectName="PageDescription"))
        if organization.role in {"OWNER", "ADMIN"}:
            code_card = QFrame(); code_card.setObjectName("Card"); code_layout = QVBoxLayout(code_card); code_layout.setSpacing(10)
            code_layout.addWidget(QLabel("직원 초대 회사 코드", objectName="SectionTitle"))
            code_layout.addWidget(QLabel("직원이 회원가입 화면에서 이 코드를 입력하면 회사 가입을 신청할 수 있습니다. 승인 후 업무를 시작할 수 있습니다."))
            code_row = QHBoxLayout(); self.join_code = QLineEdit(); self.join_code.setObjectName("CompanyJoinCode"); self.join_code.setReadOnly(True); self.join_code.setPlaceholderText("회사 코드 불러오는 중…"); self.join_code.setMinimumWidth(190); self.join_code.setMaximumWidth(250); self.join_code.setToolTip("코드를 드래그해 선택하거나 복사 버튼을 누르세요."); self.join_code.setStyleSheet("QLineEdit#CompanyJoinCode{background:#FFF7F2;border:1px solid #F5B59D;border-radius:10px;padding:8px 12px;color:#9E3A13;font-size:18px;font-weight:700;letter-spacing:4px;}")
            self.copy_join_code = QPushButton("코드 복사"); self.copy_join_code.setProperty("primary", True); self.copy_join_code.setEnabled(False); self.copy_join_code.clicked.connect(self._copy_join_code)
            code_row.addWidget(self.join_code); code_row.addWidget(self.copy_join_code); code_row.addStretch(); code_layout.addLayout(code_row); self.code_message = QLabel(""); self.code_message.setObjectName("Muted"); code_layout.addWidget(self.code_message)
            root.addWidget(code_card)
            members = QFrame(); members.setObjectName("Card"); member_layout = QVBoxLayout(members)
            member_row = QHBoxLayout(); member_copy = QVBoxLayout(); member_copy.addWidget(QLabel("직원 및 권한", objectName="SectionTitle")); member_copy.addWidget(QLabel("직원 역할, 활성 상태, 화면별 조회·편집 권한을 관리합니다.")); member_row.addLayout(member_copy, 1)
            member_button = QPushButton("직원·권한 관리"); member_button.setProperty("primary", True); member_button.setFixedWidth(156); member_button.clicked.connect(self.members_requested); member_row.addWidget(member_button, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter); member_layout.addLayout(member_row)
            root.addWidget(members)
        guests = QFrame(); guests.setObjectName("Card"); guest_layout = QVBoxLayout(guests)
        guest_row = QHBoxLayout(); guest_copy = QVBoxLayout(); guest_copy.addWidget(QLabel("프로젝트 게스트 초대", objectName="SectionTitle")); guest_copy.addWidget(QLabel("게스트는 초대된 프로젝트의 체크리스트·달력만 조회합니다. 초대 링크는 한 번만 사용되며 7일 후 만료됩니다.")); guest_row.addLayout(guest_copy, 1)
        guest_button = QPushButton("게스트 초대 관리"); guest_button.setProperty("primary", True); guest_button.setFixedWidth(156); guest_button.clicked.connect(self.guests_requested); guest_row.addWidget(guest_button, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter); guest_layout.addLayout(guest_row)
        root.addWidget(guests); root.addStretch()
        if self.api and organization.role in {"OWNER", "ADMIN"}:
            QTimer.singleShot(0, self.load_join_code)

    def load_join_code(self) -> None:
        if not self.api:
            return
        self.copy_join_code.setEnabled(False); self.join_code.setPlaceholderText("회사 코드 불러오는 중…"); self.code_message.setText("")
        try:
            code = self.api.company_join_code(self.organization.id)
        except ApiError as exc:
            self.join_code.clear(); self.join_code.setPlaceholderText("회사 코드를 불러오지 못했습니다."); self.code_message.setText(str(exc)); return
        self.join_code.setText(code); self.join_code.selectAll(); self.copy_join_code.setEnabled(True); self.code_message.setText("코드를 드래그해 선택하거나 ‘코드 복사’ 버튼을 누를 수 있습니다.")

    def _copy_join_code(self) -> None:
        code = self.join_code.text().strip()
        if not code:
            return
        QApplication.clipboard().setText(code); self.join_code.selectAll(); self.code_message.setText("회사 코드를 클립보드에 복사했습니다.")


class CompanyMembersPage(QWidget):
    """Select a person first, then edit role, status, and visible menus."""

    back_requested = Signal()
    role_labels = {"OWNER": "회사 소유자", "ADMIN": "회사 관리자", "PM": "프로젝트 담당자", "MEMBER": "일반 직원", "VIEWER": "조회 전용", "GUEST": "프로젝트 손님"}
    role_sort_order = {"OWNER": 0, "ADMIN": 1, "PM": 2, "MEMBER": 3, "VIEWER": 4, "GUEST": 5}
    role_defaults = {
        "OWNER": {"dashboard.view","events.view","events.create","events.edit","events.archive","checklist.view","checklist.edit","checklist.assign","checklist.structure","calendar.view","calendar.edit","settlement.view","settlement.edit","contacts.view","contacts.edit","master_items.view","master_items.edit","participants.view","participants.edit","exports.use","backup.create","backup.restore","members.view","members.manage","permissions.manage"},
        "ADMIN": {"dashboard.view","events.view","events.create","events.edit","events.archive","checklist.view","checklist.edit","checklist.assign","checklist.structure","calendar.view","calendar.edit","settlement.view","settlement.edit","contacts.view","contacts.edit","master_items.view","master_items.edit","participants.view","participants.edit","exports.use","backup.create","backup.restore","members.view","members.manage","permissions.manage"},
        "PM": {"dashboard.view","events.view","events.create","events.edit","events.archive","checklist.view","checklist.edit","checklist.assign","checklist.structure","calendar.view","calendar.edit","settlement.view","settlement.edit","contacts.view","exports.use"},
        "MEMBER": {"dashboard.view","events.view","events.create","checklist.view","checklist.edit","checklist.assign","checklist.structure","calendar.view","calendar.edit","contacts.view","exports.use"},
        "VIEWER": {"dashboard.view","events.view","checklist.view","calendar.view","contacts.view","exports.use"},
    }
    permission_groups = {
        "업무 화면": [("대시보드", ("dashboard.view",), ()), ("체크리스트", ("checklist.view",), ("checklist.edit", "checklist.assign", "checklist.structure")), ("전체 달력", ("calendar.view",), ("calendar.edit",)), ("정산내역", ("settlement.view",), ("settlement.edit",))],
        "회사 데이터": [("기본 항목", ("master_items.view",), ("master_items.edit",)), ("업체·담당자", ("contacts.view",), ("contacts.edit",))],
    }

    def __init__(self, api: TeamsV2Api, organization: Organization) -> None:
        super().__init__(); self.api = api; self.organization = organization; self.members: list[dict] = []; self.selected_member: dict | None = None; self.permission_boxes: dict[str, QCheckBox] = {}; self.permission_rows: list[tuple[QCheckBox, QCheckBox | None, tuple[str, ...], tuple[str, ...]]] = []; self._updating_permissions = False; self._dirty = False
        root = QVBoxLayout(self); root.setContentsMargins(32, 28, 32, 28); root.setSpacing(12)
        top = QHBoxLayout(); top.addWidget(QLabel("직원 및 권한", objectName="PageTitle")); top.addStretch(); self.back = QPushButton("← 회사 관리"); self.back.setProperty("quiet", True); self.refresh = QPushButton("새로고침"); self.refresh.setProperty("primary", True); top.addWidget(self.back); top.addWidget(self.refresh); root.addLayout(top)
        root.addWidget(QLabel("왼쪽에서 직원을 선택한 뒤 역할과 화면별 조회·편집 권한을 정하세요. 편집을 허용하면 조회도 함께 허용됩니다. ‘회사에서 삭제’는 계정과 업무 이력은 남기고 이 회사 접근만 즉시 중지합니다.", objectName="PageDescription"))
        self.message = QLabel(""); root.addWidget(self.message)
        content = QHBoxLayout(); content.setSpacing(16); root.addLayout(content, 1)
        self.table = QTableWidget(0, 3); self.table.setObjectName("TeamsMemberTable"); self.table.setHorizontalHeaderLabels(["직원", "역할", "접근 상태"]); self.table.horizontalHeader().setStretchLastSection(True); self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection); self.table.setStyleSheet("QTableWidget#TeamsMemberTable::item:selected { background:#FCE8DE; color:#172033; border-top:1px solid #F15A24; border-bottom:1px solid #F15A24; } QTableWidget#TeamsMemberTable::item:selected:!active { background:#FCE8DE; color:#172033; }"); self.table.setMaximumWidth(480); content.addWidget(self.table, 1)
        detail = QFrame(); detail.setObjectName("Card"); detail_layout = QVBoxLayout(detail); detail_layout.setSpacing(10)
        self.permission_scroll = QScrollArea(); self.permission_scroll.setObjectName("TeamsPermissionScroll"); self.permission_scroll.setWidgetResizable(True); self.permission_scroll.setFrameShape(QFrame.Shape.NoFrame); self.permission_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff); self.permission_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded); self.permission_scroll.setStyleSheet("QScrollArea#TeamsPermissionScroll{background:#FFFFFF;border:none;} QScrollArea#TeamsPermissionScroll QWidget#qt_scrollarea_viewport{background:#FFFFFF;} QScrollArea#TeamsPermissionScroll > QWidget > QWidget{background:#FFFFFF;}"); self.permission_scroll.viewport().setStyleSheet("background:#FFFFFF;"); self.permission_scroll.setWidget(detail); content.addWidget(self.permission_scroll, 2)
        self.selected_caption = QLabel("선택한 직원", objectName="Muted"); detail_layout.addWidget(self.selected_caption)
        self.person = QLabel("왼쪽에서 직원을 선택하세요.", objectName="SectionTitle"); detail_layout.addWidget(self.person)
        self.email = QLabel(""); self.email.setObjectName("Muted"); detail_layout.addWidget(self.email)
        form = QFormLayout(); self.role = QComboBox(); self.status = QComboBox(); self.status.addItem("활성 · 바로 업무 가능", "ACTIVE"); self.status.addItem("업무 중지 · 회사 접근 차단", "SUSPENDED")
        for code in ("OWNER","ADMIN","PM","MEMBER","VIEWER"): self.role.addItem(self.role_labels[code], code)
        form.addRow("역할", self.role); form.addRow("상태", self.status); detail_layout.addLayout(form)
        self.notice = QLabel("역할을 고르면 권장 권한이 설정됩니다. 필요한 화면만 조회 또는 편집으로 조정하세요."); self.notice.setObjectName("InfoGuide"); detail_layout.addWidget(self.notice)
        self.save_state = QLabel("저장된 변경사항이 없습니다.", objectName="Muted"); detail_layout.addWidget(self.save_state)
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
                view_box.toggled.connect(self._mark_dirty)
                if edit_box:
                    edit_box.toggled.connect(lambda checked, view=view_box: self._edit_toggled(checked, view))
                    edit_box.toggled.connect(self._mark_dirty)
            grid.setColumnStretch(0, 1); grid.setColumnMinimumWidth(1, 76); grid.setColumnMinimumWidth(2, 92)
            section_layout.addLayout(grid); detail_layout.addWidget(section)
        export_section = QFrame(); export_section.setObjectName("TeamsPermissionSection"); export_section.setStyleSheet("QFrame#TeamsPermissionSection { background:#FAFAFB; border:1px solid #E3E5E8; border-radius:10px; } QLabel#SectionTitle { border:none; }")
        export_layout = QHBoxLayout(export_section); export_layout.setContentsMargins(16, 13, 16, 13); export_layout.addWidget(QLabel("출력", objectName="SectionTitle")); export_layout.addStretch(); self.export_box = QCheckBox("PDF·Excel 출력 허용"); self.permission_boxes["exports.use"] = self.export_box; export_layout.addWidget(self.export_box); detail_layout.addWidget(export_section)
        detail_layout.addStretch(); actions = QHBoxLayout(); self.remove = QPushButton("회사에서 삭제"); self.remove.setProperty("danger", True); self.remove.setEnabled(False); self.apply = QPushButton("변경사항 저장"); self.apply.setProperty("primary", True); self.apply.setEnabled(False); actions.addWidget(self.remove); actions.addStretch(); actions.addWidget(self.apply); detail_layout.addLayout(actions)
        self.back.clicked.connect(self.back_requested); self.refresh.clicked.connect(self.load); self.table.cellClicked.connect(self._select_row); self.role.currentIndexChanged.connect(self._role_changed); self.status.currentIndexChanged.connect(self._mark_dirty); self.export_box.toggled.connect(self._mark_dirty); self.apply.clicked.connect(self.apply_changes); self.remove.clicked.connect(self.remove_member)

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
        self._updating_permissions = False; self._dirty = False
        locked = role == "OWNER" and self.organization.role != "OWNER"
        current_user_id = getattr(getattr(self.api, "session", None), "user_id", None)
        can_remove = role != "OWNER" and member.get("status") == "ACTIVE" and str(member.get("user_id")) != str(current_user_id)
        self.role.setEnabled(not locked); self.status.setEnabled(not locked); self.apply.setEnabled(False)
        self.remove.setEnabled(can_remove); self.remove.setToolTip("회사 소유자와 본인 계정은 회사에서 삭제할 수 없습니다." if not can_remove else "계정과 업무 이력은 보존하고 이 회사 접근만 중지합니다.")
        for box in set(self.permission_boxes.values()): box.setEnabled(not locked)
        self.notice.setText("회사 소유자는 소유자만 변경할 수 있습니다." if locked else "프로젝트 참여자·백업·직원 관리는 역할에 따라 자동 적용됩니다.")
        self.save_state.setText("저장된 변경사항이 없습니다." if not locked else "회사 소유자 권한은 소유자만 바꿀 수 있습니다.")

    def _role_changed(self) -> None:
        if not self.selected_member: return
        defaults = self.role_defaults.get(str(self.role.currentData()), set()); self._updating_permissions = True
        for view_box, edit_box, view_codes, edit_codes in self.permission_rows:
            view_box.setChecked(all(code in defaults for code in view_codes))
            if edit_box: edit_box.setChecked(all(code in defaults for code in edit_codes))
        self.export_box.setChecked("exports.use" in defaults); self._updating_permissions = False; self._mark_dirty()

    def apply_changes(self) -> None:
        if not self.selected_member: return
        user_id = str(self.selected_member.get("user_id")); role = str(self.role.currentData()); status = str(self.status.currentData()); defaults = self.role_defaults.get(role, set())
        requested: dict[str, bool] = {"exports.use": self.export_box.isChecked()}
        for view_box, edit_box, view_codes, edit_codes in self.permission_rows:
            requested.update({code: view_box.isChecked() for code in view_codes})
            if edit_box: requested.update({code: edit_box.isChecked() for code in edit_codes})
        overrides = [{"permission_code": code, "effect": "ALLOW" if allowed else "DENY"} for code, allowed in requested.items() if allowed != (code in defaults)]
        self.apply.setEnabled(False); self.apply.setText("서버에 저장 중…"); self.message.setText("변경사항을 서버에 저장하는 중…")
        try:
            self.api.save_company_member_access(self.organization.id, user_id, role, status, overrides)
        except ApiError as exc:
            self.message.setText(str(exc)); self.apply.setText("변경사항 저장"); self.apply.setEnabled(True); return
        saved_name = self.person.text()
        self._dirty = False; self.apply.setText("변경사항 저장")
        self.load()
        self.save_state.setText("서버 저장 완료 · 대상 직원에게 권한 변경 알림을 보냈습니다.")
        self.message.setText(f"{saved_name}님의 역할과 메뉴 권한을 서버에 저장했습니다.")

    def remove_member(self) -> None:
        if not self.selected_member:
            return
        member = self.selected_member
        if str(member.get("role")) == "OWNER":
            QMessageBox.warning(self, "회사에서 삭제", "회사 소유자는 다른 직원에게 소유자 권한을 넘긴 뒤에만 삭제할 수 있습니다.")
            return
        name = str(member.get("display_name") or member.get("email") or "이 직원")
        confirmation = QMessageBox.question(
            self,
            "회사에서 삭제",
            f"{name}님을 이 회사에서 삭제할까요?\n\n계정과 기존 업무 이력은 남지만, 이 회사의 Teams와 데이터 접근은 즉시 중지됩니다.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            return
        self.remove.setEnabled(False); self.message.setText("회사 접근을 중지하는 중…")
        try:
            self.api.remove_company_member(self.organization.id, str(member["user_id"]))
        except ApiError as exc:
            self.message.setText(str(exc)); self.remove.setEnabled(True); return
        self.selected_member = None
        self.load()
        self.message.setText(f"{name}님을 회사에서 삭제했습니다. 계정과 기존 업무 이력은 보존됩니다.")

    def _mark_dirty(self, *_args) -> None:
        if self._updating_permissions or not self.selected_member:
            return
        role = str(self.selected_member.get("role") or "MEMBER")
        locked = role == "OWNER" and self.organization.role != "OWNER"
        if locked:
            return
        self._dirty = True; self.apply.setEnabled(True); self.save_state.setText("저장 전 변경사항이 있습니다. ‘변경사항 저장’을 누르세요.")

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
        form = QFormLayout(); self.event = QComboBox(self); self.settlement = QCheckBox("정산내역 조회 허용", self)
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
        form = QFormLayout(); self.event = QComboBox(self); self.settlement = QCheckBox("정산내역 조회 허용", self)
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
    def __init__(self, config: TeamsV2Config, trace: RuntimeWindowTrace | None = None) -> None:
        super().__init__(); self.config = config; self.trace = trace; self.store = SessionStore(); self.api = TeamsV2Api(config); self.workspace_db: WorkspaceDatabase | None = None
        self.local_window: MainWindow | None = None; self.current_organization: Organization | None = None; self.permission_worker: Worker | None = None; self.snapshot_worker: Worker | None = None; self.changes_worker: Worker | None = None; self.access_refresh_worker: Worker | None = None; self.sync_engine: WorkspaceSyncEngine | None = None; self.realtime: RealtimeSignalClient | None = None; self._sync_workers: list[Worker] = []; self._opened_cursor = ""; self._opened_with_pending = False
        self.update_info: UpdateInfo | None = None; self.update_progress: StartupSplash | None = None; self.update_check_worker: Worker | None = None; self.update_download_worker: Worker | None = None
        self.company_management_page: CompanyManagementPage | None = None; self.company_members_page: CompanyMembersPage | None = None; self.guest_management_page: GuestManagementPage | None = None
        self.company_workspace: CompanyWorkspace | None = None; self.company_calendar_page: CompanyCalendarPage | None = None; self.company_finance_page: FinancePage | None = None; self.notification_page: NotificationPage | None = None; self.notification_button: QPushButton | None = None; self.company_v3_buttons: list[QPushButton] = []; self.v3_worker: Worker | None = None; self.notification_worker: Worker | None = None; self.v3_mutation_inflight = False; self._v3_initial_open = False; self._realtime_refresh_pending = False; self._v3_refresh_pending = False; self._notification_refresh_pending = False; self._known_notification_ids: set[str] = set(); self._notification_baseline_loaded = False
        self.v3_outbox_timer = QTimer(self); self.v3_outbox_timer.setInterval(1200); self.v3_outbox_timer.timeout.connect(self._flush_v3_outbox); self.v3_outbox_timer.start()
        self.setWindowTitle("이벤트 플로우 Teams V2"); self.setWindowIcon(app_icon()); self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint); self.resize(1440, 900); self.setMinimumSize(1120, 700)
        outer = QWidget(); outer.setObjectName("AppRoot"); outer_layout = QVBoxLayout(outer); outer_layout.setContentsMargins(1, 1, 1, 1); outer_layout.setSpacing(0)
        self.shell_title_bar = ShellTitleBar(self); outer_layout.addWidget(self.shell_title_bar)
        self.stack = QStackedWidget(); outer_layout.addWidget(self.stack, 1); self.setCentralWidget(outer)
        self.login = LoginPage(self.api); self.organizations = OrganizationPage(self.api)
        self.stack.addWidget(self.login); self.stack.addWidget(self.organizations)
        self.login.signed_in.connect(self._signed_in); self.organizations.selected.connect(self._open_workspace); self.organizations.logout_requested.connect(self.logout); self.organizations.organizations_loaded.connect(self._persist_recovered_session)
        if is_packaged_app():
            QTimer.singleShot(900, self._check_updates_on_launch)
        session = self.store.load()
        if session:
            self.api.session = session; self.stack.setCurrentWidget(self.organizations); self.organizations.load()

    def _signed_in(self, session: object) -> None:
        if not isinstance(session, Session):
            return
        self.store.save(session); self.stack.setCurrentWidget(self.organizations); self.organizations.load()

    def _persist_recovered_session(self) -> None:
        """Keep a rotated refresh token instead of retrying the expired one next launch."""
        if self.api.session:
            self.store.save(self.api.session)

    def _open_workspace(self, organization: Organization) -> None:
        if not self.api.session:
            return
        self._trace("company_selection_started")
        self._close_workspace()
        self.current_organization = organization
        self._v3_initial_open = True
        # The Local shell always receives a V2-owned database.  Its content is
        # replaced by the permission-filtered snapshot only after permission
        # verification has succeeded.
        root = workspace_root(self.config.data_root, self.api.session.user_id, organization.id)
        os.environ["EVENT_CHECKLIST_DATA_DIR"] = str(root)
        self.workspace_db = WorkspaceDatabase(root / "data" / "event_checklist.db", user_id=self.api.session.user_id, organization_id=organization.id)
        opened = self.workspace_db.one("SELECT remote_cursor FROM teams_v2_workspace WHERE singleton=1")
        self._opened_cursor = str(opened["remote_cursor"] or "") if opened else ""
        self._opened_with_pending = bool(self.workspace_db.pending_outbox())
        # Construct Local directly as an embedded child.  Constructing it as a
        # top-level window and reparenting it afterwards briefly flashes a
        # separate window on Windows when a company is selected.
        self.local_window = MainWindow(
            self.workspace_db,
            parent=self.stack,
            enable_update_check=False,
            embedded=True,
        )
        self._trace("local_shell_constructed")
        self._configure_local_shell(self.local_window, organization)
        self._install_company_workspace_features(self.local_window, organization)
        self._install_staff_features(self.local_window, organization)
        self._install_notification_features(self.local_window, organization)
        self.local_window.setEnabled(False)
        self.stack.addWidget(self.local_window); self.stack.setCurrentWidget(self.local_window); self.shell_title_bar.hide()
        self._trace("workspace_page_shown")
        self._set_sync_state("CHECKING", "권한 확인 중…")
        self.permission_worker = Worker(lambda: self.api.permissions(organization.id))
        self.permission_worker.finished.connect(lambda value, oid=organization.id: self._permissions_loaded(oid, value))
        self.permission_worker.failed.connect(lambda message, oid=organization.id: self._permissions_failed(oid, message))
        self.permission_worker.start()

    def _install_staff_features(self, local: MainWindow, organization: Organization) -> None:
        if not self.api.session:
            return
        # Guest invitations remain project-scoped read access.  They must not
        # discover the company-wide staff board or personal absence schedules.
        if organization.role == "GUEST":
            return
        if self.workspace_db and not self.workspace_db.one("SELECT 1 FROM teams_v2_staff_members WHERE user_id=?", (self.api.session.user_id,)):
            self.workspace_db.conn.execute(
                "INSERT INTO teams_v2_staff_members(user_id,display_name,role,job_title,color_hex,status) VALUES (?,?,?,?,?, 'ACTIVE')",
                (self.api.session.user_id, self.api.session.email.split("@", 1)[0], organization.role, "", "#A7D4F0"),
            )
            self.workspace_db.conn.commit()
        staff_page = EmployeeWorkPage(self.workspace_db, self._open_v3_task, self.api.session.user_id, organization.role in {"OWNER", "ADMIN"}, self._transfer_task_member, self._refresh_staff_directory, local)
        local.install_teams_staff_page(staff_page)
        QTimer.singleShot(0,self._refresh_staff_priorities)
        self.my_space_page = MySpacePage(self.workspace_db, self.api.session.user_id, self._save_personal_schedule_values, self._delete_personal_schedule, self._reorder_my_schedules, self._reorder_my_tasks, self._save_my_task_details, self._save_my_company_work, self._delete_my_company_work, self._save_my_project_work, self._delete_my_project_work, self._claim_my_checklist_work, organization.role != "GUEST", local, open_task=self._open_v3_task)
        local.stack.addWidget(self.my_space_page)
        my_button = QPushButton("나의 공간"); local.add_company_global_nav_button(my_button)
        my_button.clicked.connect(lambda: self._show_v3_page(self.my_space_page, my_button))
        local.events.set_staff_assignment_handler(self._assign_task_member)
        local.events.finance_button.hide()

    def _install_company_workspace_features(self, local: MainWindow, organization: Organization) -> None:
        """Mount V3 beside Local V2; no existing Local page or outbox is repurposed."""
        if not self.workspace_db:
            return
        self.company_workspace = CompanyWorkspace(self.workspace_db)
        local.hide_project_calendar_for_teams()
        self.company_calendar_page = CompanyCalendarPage(self.workspace_db, local)
        local.stack.addWidget(self.company_calendar_page)
        calendar_button = QPushButton("전체 달력"); calendar_button.setToolTip("모든 프로젝트 업무와 개인 일정을 표시합니다.")
        local.add_company_global_nav_button(calendar_button)
        calendar_button.clicked.connect(lambda: self._show_v3_page(self.company_calendar_page, calendar_button))
        self.company_v3_buttons = [calendar_button]
        if organization.role == "GUEST":
            for button in self.company_v3_buttons: button.hide()

    def _install_notification_features(self, local: MainWindow, organization: Organization) -> None:
        if organization.role == "GUEST": return
        self.notification_page = NotificationPage(self._load_notifications, self._mark_notification_read, self._delete_notification, self._open_notification, local)
        local.stack.addWidget(self.notification_page)
        self.notification_button = local.title_bar.notification_button
        self.notification_button.show(); self.notification_button.clicked.connect(self._show_notifications)

    def _show_notifications(self) -> None:
        if not self.local_window or not self.notification_page: return
        for nav in self.local_window.nav_buttons: nav.setChecked(False)
        self.local_window.stack.setCurrentWidget(self.notification_page); self.notification_page.refresh()

    def _load_notifications(self, unread_only: bool=False) -> list[dict]:
        if not self.current_organization: return []
        return self.api.notifications(self.current_organization.id, unread_only)

    def _mark_notification_read(self, notification_id: str | None) -> bool:
        if not self.current_organization: return False
        try: self.api.mark_notification_read(self.current_organization.id, notification_id); self._refresh_notifications_async(show_new=False); return True
        except ApiError as exc: self._show_toast(str(exc)); return False

    def _delete_notification(self, notification_id: str | None) -> bool:
        if not self.current_organization: return False
        try: self.api.delete_notification(self.current_organization.id, notification_id); self._refresh_notifications_async(show_new=False); return True
        except ApiError as exc: self._show_toast(str(exc)); return False

    def _open_notification(self, notice: dict) -> None:
        if not self.local_window: return
        task_id=str(notice.get("task_id") or "")
        mapping=self.workspace_db.one("SELECT local_id FROM teams_v2_entity_map WHERE entity_type='EVENT_TASK' AND remote_id=?",(task_id,)) if self.workspace_db and task_id else None
        if mapping: self.local_window.open_teams_task(int(mapping["local_id"])); return
        if hasattr(self,"my_space_page"):
            button=next((b for b in self.local_window.findChildren(QPushButton) if b.text()=="나의 공간"),None)
            if button: self._show_v3_page(self.my_space_page,button)

    def _refresh_notifications_async(self, show_new: bool=True) -> None:
        if self.notification_worker and self.notification_worker.isRunning(): self._notification_refresh_pending=True; return
        if not self.current_organization or not self.notification_button: return
        self._notification_refresh_pending=False
        oid=self.current_organization.id
        self.notification_worker=Worker(lambda:(self.api.notifications(oid,False),self.api.unread_notification_count(oid)))
        self.notification_worker.finished.connect(lambda value,organization_id=oid,notify=show_new:self._notifications_loaded(organization_id,value,notify))
        self.notification_worker.failed.connect(lambda _message:self._notification_refresh_finished())
        self.notification_worker.start()

    def _notification_refresh_finished(self) -> None:
        if self._notification_refresh_pending:
            self._notification_refresh_pending=False; QTimer.singleShot(0,self._refresh_notifications_async)

    def _notifications_loaded(self, organization_id: str, value: object, show_new: bool) -> None:
        if not self.current_organization or self.current_organization.id!=organization_id or not isinstance(value,tuple): return
        notices,count=value; notices=notices if isinstance(notices,list) else []
        ids={str(n.get("id")) for n in notices if isinstance(n,dict) and n.get("id")}
        if show_new and self._notification_baseline_loaded:
            for notice in reversed([n for n in notices if isinstance(n,dict) and str(n.get("id") or "") not in self._known_notification_ids]):
                self._show_toast(str(notice.get("message") or notice.get("title") or "새 알림"))
        self._known_notification_ids=ids; self._notification_baseline_loaded=True
        if self.notification_button: self.local_window.title_bar.set_notification_count(int(count or 0))
        if self.notification_page and self.local_window and self.local_window.stack.currentWidget() is self.notification_page: self.notification_page.set_notices(notices)
        self._notification_refresh_finished()

    def _show_v3_page(self, page: QWidget | None, button: QPushButton) -> None:
        if not self.local_window or not page:
            return
        for nav in self.local_window.nav_buttons:
            nav.setChecked(False)
        button.setChecked(True)
        if hasattr(page, "refresh"):
            page.refresh()
        if hasattr(self, "my_space_page") and page is self.my_space_page:
            self._refresh_my_task_priorities()
        self.local_window.stack.setCurrentWidget(page)

    def _refresh_my_task_priorities(self) -> None:
        if not self.current_organization or not self.workspace_db or not hasattr(self, "my_space_page"):
            return
        worker = Worker(lambda: self.api.my_task_priorities(self.current_organization.id))
        def loaded(value):
            if not self.workspace_db or not isinstance(value, list): return
            self.workspace_db.conn.execute("DELETE FROM teams_v2_my_task_priorities")
            self.workspace_db.conn.executemany("INSERT INTO teams_v2_my_task_priorities(event_task_id,sort_order) VALUES (?,?)", [(str(item["event_task_id"]), int(item.get("sort_order") or 0)) for item in value if isinstance(item, dict) and item.get("event_task_id")])
            self.workspace_db.conn.commit(); self.my_space_page.refresh()
        worker.finished.connect(loaded); worker.start(); self._sync_workers.append(worker)

    def _show_project_finance(self, button: QPushButton) -> None:
        if not self.local_window or not self.workspace_db or not self.company_finance_page or not self.local_window.selected_event_id:
            self._show_toast("프로젝트를 먼저 선택하세요.")
            return
        row = self.workspace_db.one("SELECT remote_id FROM teams_v2_entity_map WHERE entity_type='EVENT' AND local_id=?", (self.local_window.selected_event_id,))
        if not row:
            self._show_toast("선택한 프로젝트의 서버 연결을 찾을 수 없습니다.")
            return
        self.company_finance_page.select_project(str(row["remote_id"]))
        self._show_v3_page(self.company_finance_page, button)

    def _open_v3_project(self, remote_event_id: str) -> None:
        if not self.local_window or not self.workspace_db:
            return
        row = self.workspace_db.one("SELECT local_id FROM teams_v2_entity_map WHERE entity_type='EVENT' AND remote_id=?", (remote_event_id,))
        if not row:
            self._show_toast("프로젝트 작업본을 아직 받지 못했습니다.")
            return
        self.local_window.select_event(int(row["local_id"]))
        self.local_window.nav_buttons[1].click()

    def _create_finance_from_task(self, task: dict) -> None:
        """Bridge a selected V2 checklist row into a separately stored V3 actual expense."""
        if not self.workspace_db or not self.company_finance_page or not self.local_window:
            self._show_toast("실제 정산 화면을 준비하지 못했습니다.")
            return
        event = self.workspace_db.one("SELECT remote_id FROM teams_v2_entity_map WHERE entity_type='EVENT' AND local_id=?", (task.get("event_id"),))
        item = self.workspace_db.one("SELECT remote_id FROM teams_v2_entity_map WHERE entity_type='EVENT_TASK' AND local_id=?", (task.get("id"),))
        if not event or not item:
            self._show_toast("이 업무의 서버 연결을 동기화한 뒤 다시 시도하세요.")
            return
        self.company_finance_page.begin_from_task(str(event["remote_id"]), str(item["remote_id"]), str(task.get("name") or "업무 실제 정산"))
        button = next((candidate for candidate in self.company_v3_buttons if candidate.text() == "정산내역"), None)
        if button:
            self._show_v3_page(self.company_finance_page, button)

    def _load_v3_workspace(self) -> None:
        if self.v3_worker and self.v3_worker.isRunning(): self._v3_refresh_pending=True; return
        if not self.current_organization or not self.company_workspace:
            return
        organization_id = self.current_organization.id
        cursor = self.company_workspace.cursor()
        self.v3_worker = Worker(lambda: self.api.workspace_v3_changes(organization_id, cursor) if cursor else self.api.workspace_v3_snapshot(organization_id))
        self.v3_worker.finished.connect(lambda value, oid=organization_id, was_snapshot=not bool(cursor): self._v3_loaded(oid, value, was_snapshot))
        self.v3_worker.failed.connect(lambda message: self._show_toast(f"회사 전체 업무 동기화 보류: {message}"))
        self.v3_worker.start()

    def _v3_loaded(self, organization_id: str, value: object, was_snapshot: bool) -> None:
        if not self.current_organization or self.current_organization.id != organization_id or not self.company_workspace or not isinstance(value, dict):
            return
        try:
            (self.company_workspace.apply_snapshot(value) if was_snapshot else self.company_workspace.apply_changes(value))
            if self.company_calendar_page: self.company_calendar_page.refresh()
            if self.local_window and hasattr(self.local_window, "staff_work_page"):
                self.local_window.staff_work_page.refresh()
                self._refresh_staff_priorities()
            if hasattr(self, "my_space_page"): self.my_space_page.refresh()
            if self._v3_initial_open and self.company_calendar_page and self.local_window:
                self._v3_initial_open = False
                button = next((item for item in self.local_window.findChildren(QPushButton) if item.text() == "전체 달력"), None)
                if button:
                    self._show_v3_page(self.company_calendar_page, button)
        except Exception as exc:
            self._show_toast(f"회사 전체 업무 반영 실패: {exc}")
        finally:
            if self._v3_refresh_pending:
                self._v3_refresh_pending=False; QTimer.singleShot(0,self._load_v3_workspace)

    def _queue_v3(self, operation: str, payload: dict) -> None:
        if not self.company_workspace or not self.current_organization:
            return
        self.company_workspace.queue(operation, payload)
        self._flush_v3_outbox()

    def _flush_v3_outbox(self) -> None:
        if not self.company_workspace or not self.current_organization or self.v3_mutation_inflight:
            return
        prepared = self.company_workspace.next_mutation()
        if not prepared:
            return
        entry, mutation = prepared
        self.v3_mutation_inflight = True
        self._run_sync_network(
            lambda: self.api.apply_v3_mutations(self.current_organization.id, [mutation]),
            lambda value: self._v3_mutation_saved(entry, value),
            lambda message: self._v3_mutation_transport_failed(entry, message),
        )

    def _v3_mutation_saved(self, entry: dict, value: object) -> None:
        self.v3_mutation_inflight = False
        if not self.company_workspace or not isinstance(value, dict):
            return
        outcome = self.company_workspace.apply_mutation_response(entry, value)
        if outcome == "APPLIED":
            if self.company_calendar_page: self.company_calendar_page.refresh()
            if self.company_finance_page: self.company_finance_page.refresh()
            if hasattr(self, "my_space_page"): self.my_space_page.refresh()
            self._show_toast("회사 전체 업무 변경을 저장했습니다.")
        else:
            self._show_toast("회사 전체 업무 변경을 확인해야 합니다.")
        QTimer.singleShot(0, self._flush_v3_outbox)

    def _v3_mutation_transport_failed(self, entry: dict, message: str) -> None:
        self.v3_mutation_inflight = False
        if self.company_workspace:
            self.company_workspace.record_transport_failure(entry, message or "서버 연결을 확인할 수 없습니다.")
        self._show_toast("회사 전체 업무 변경을 오프라인 대기열에 보관했습니다.")

    def _save_personal_schedule_values(self, values: dict, schedule_id: str | None = None) -> bool:
        if not self.current_organization or not self.workspace_db or not self.local_window:
            return False
        try:
            saved = self.api.save_personal_schedule(self.current_organization.id, schedule_id, values["start_date"], values["end_date"], values["title"], values.get("content", ""))
            WorkspaceSnapshotStore(self.workspace_db)._upsert_personal_schedule(saved)
            self.workspace_db.conn.commit()
            if hasattr(self, "company_calendar_page"): self.company_calendar_page.refresh()
            if hasattr(self, "my_space_page"): self.my_space_page.refresh()
            return True
        except ApiError as exc:
            QMessageBox.warning(self.local_window, "개인 일정 저장 실패", str(exc)); return False

    def _delete_personal_schedule(self, schedule: dict) -> bool:
        if not self.current_organization or not self.workspace_db or not self.local_window:
            return False
        try:
            self.api.delete_personal_schedule(self.current_organization.id, str(schedule["id"]))
            self.workspace_db.conn.execute("DELETE FROM teams_v2_personal_schedules WHERE id=?", (str(schedule["id"]),)); self.workspace_db.conn.commit()
            if hasattr(self, "my_space_page"): self.my_space_page.refresh()
            self._show_toast("개인 일정을 삭제했습니다.")
            return True
        except ApiError as exc:
            QMessageBox.warning(self.local_window, "개인 일정 삭제 실패", str(exc)); return False

    def _reorder_my_schedules(self, schedule_ids: list[str]) -> None:
        if not self.current_organization or not self.workspace_db:
            return
        try:
            self.api.reorder_my_personal_schedules(self.current_organization.id, schedule_ids)
            for position, schedule_id in enumerate(schedule_ids, 1): self.workspace_db.conn.execute("UPDATE teams_v2_personal_schedules SET sort_order=? WHERE id=?", (position, schedule_id))
            self.workspace_db.conn.commit()
        except ApiError as exc:
            self._show_toast(f"개인 일정 순서 저장 실패: {exc}")

    def _reorder_my_tasks(self, task_ids: list[str]) -> bool:
        if not self.current_organization or not self.workspace_db:
            return False
        try:
            self.api.reorder_my_tasks(self.current_organization.id, task_ids)
            self.workspace_db.conn.execute("DELETE FROM teams_v2_my_task_priorities")
            self.workspace_db.conn.executemany("INSERT INTO teams_v2_my_task_priorities(event_task_id,sort_order) VALUES (?,?)", [(task_id, index) for index, task_id in enumerate(task_ids, 1)])
            self.workspace_db.conn.commit()
            return True
        except ApiError as exc:
            self._show_toast(f"내 업무 순서 저장 실패: {exc}")
            if hasattr(self,"my_space_page"): self.my_space_page.refresh()
            return False

    def _save_my_task_details(self, task_id: str, values: dict) -> bool:
        if not self.workspace_db or not self.company_workspace:
            return False
        task = self.workspace_db.one("SELECT row_version FROM teams_v3_work_items WHERE remote_id=?", (task_id,))
        if not task:
            return False
        self._queue_v3("WORK_PATCH", {"id": task_id, "expected_row_version": int(task["row_version"] or 0), **values})
        return True

    def _save_my_company_work(self, values: dict, work: dict | None) -> bool:
        """Persist one employee's company work without opening assignment controls."""
        if not self.current_organization or not self.workspace_db or not self.company_workspace:
            return False
        try:
            response = self.api.save_my_company_work(
                self.current_organization.id,
                str(work["remote_id"]) if work else None,
                int(work["row_version"] or 0) if work else None,
                values,
            )
            if str(response.get("status") or "") == "CONFLICT":
                self._show_toast("다른 변경이 먼저 저장되었습니다. 목록을 새로고침했습니다.")
                self._load_v3_workspace(); return False
            saved = response.get("entity")
            if not isinstance(saved, dict) or str(response.get("status") or "") != "APPLIED":
                raise ApiError(str(response.get("reason") or "사내 업무를 저장하지 못했습니다."))
            self.company_workspace.apply_changes({"cursor": self.company_workspace.cursor(), "changes": [{"entity_type": "WORK_ITEM", "entity_key": str(saved.get("id") or ""), "operation": "UPSERT", "payload": saved}]})
            if self.company_calendar_page: self.company_calendar_page.refresh()
            if self.local_window and hasattr(self.local_window, "staff_work_page"): self.local_window.staff_work_page.refresh()
            if hasattr(self, "my_space_page"): self.my_space_page.refresh()
            self._show_toast("사내 업무를 저장했습니다.")
            return True
        except ApiError as exc:
            QMessageBox.warning(self.local_window, "사내 업무 저장", str(exc)); return False

    def _delete_my_company_work(self, work: dict) -> bool:
        if not self.current_organization or not self.workspace_db or not self.company_workspace:
            return False
        try:
            response = self.api.delete_my_company_work(self.current_organization.id, str(work["remote_id"]), int(work["row_version"] or 0))
            if str(response.get("status") or "") == "CONFLICT":
                self._show_toast("다른 변경이 먼저 저장되었습니다. 목록을 새로고침했습니다.")
                self._load_v3_workspace(); return False
            saved = response.get("entity")
            if not isinstance(saved, dict) or str(response.get("status") or "") != "APPLIED":
                raise ApiError(str(response.get("reason") or "사내 업무를 삭제하지 못했습니다."))
            self.company_workspace.apply_changes({"cursor": self.company_workspace.cursor(), "changes": [{"entity_type": "WORK_ITEM", "entity_key": str(saved.get("id") or ""), "operation": "UPSERT", "payload": saved}]})
            if self.company_calendar_page: self.company_calendar_page.refresh()
            if self.local_window and hasattr(self.local_window, "staff_work_page"): self.local_window.staff_work_page.refresh()
            if hasattr(self, "my_space_page"): self.my_space_page.refresh()
            self._show_toast("사내 업무를 삭제했습니다.")
            return True
        except ApiError as exc:
            QMessageBox.warning(self.local_window, "사내 업무 삭제", str(exc)); return False

    def _save_my_project_work(self, values: dict, work: dict | None) -> bool:
        """Persist a member's self-owned project addition, never a checklist copy."""
        if not self.current_organization or not self.workspace_db or not self.company_workspace:
            return False
        event_id = str((work or {}).get("event_id") or "")
        if not event_id:
            event_id = str(values.pop("event_id", "") or "")
        if not event_id:
            return False
        try:
            response = self.api.save_my_project_work(self.current_organization.id, str(work["remote_id"]) if work else None, int(work["row_version"] or 0) if work else None, event_id, values)
            return self._apply_my_space_work_response(response, "프로젝트 추가 업무", "저장")
        except ApiError as exc:
            QMessageBox.warning(self.local_window, "프로젝트 추가 업무 저장", str(exc)); return False

    def _delete_my_project_work(self, work: dict) -> bool:
        if not self.current_organization or not self.workspace_db or not self.company_workspace:
            return False
        try:
            response = self.api.delete_my_project_work(self.current_organization.id, str(work["remote_id"]), int(work["row_version"] or 0))
            return self._apply_my_space_work_response(response, "프로젝트 추가 업무", "삭제")
        except ApiError as exc:
            QMessageBox.warning(self.local_window, "프로젝트 추가 업무 삭제", str(exc)); return False

    def _claim_my_checklist_work(self, checklist: dict) -> bool:
        if not self.current_organization or not self.workspace_db or not self.company_workspace:
            return False
        try:
            response = self.api.claim_my_checklist_work(self.current_organization.id, str(checklist["id"]), int(checklist["row_version"] or 0))
            return self._apply_my_space_work_response(response, "체크리스트 업무", "연결")
        except ApiError as exc:
            QMessageBox.warning(self.local_window, "체크리스트 업무 연결", str(exc)); return False

    def _apply_my_space_work_response(self, response: dict, label: str, action: str) -> bool:
        if not self.company_workspace:
            return False
        if str(response.get("status") or "") == "CONFLICT":
            self._show_toast("다른 변경이 먼저 저장되었습니다. 목록을 새로고침했습니다.")
            self._load_v3_workspace(); return False
        saved = response.get("entity")
        if not isinstance(saved, dict) or str(response.get("status") or "") != "APPLIED":
            raise ApiError(str(response.get("reason") or f"{label}을 {action}하지 못했습니다."))
        self.company_workspace.apply_changes({"cursor": self.company_workspace.cursor(), "changes": [{"entity_type": "WORK_ITEM", "entity_key": str(saved.get("id") or ""), "operation": "UPSERT", "payload": saved}]})
        if self.company_calendar_page: self.company_calendar_page.refresh()
        if self.local_window and hasattr(self.local_window, "staff_work_page"): self.local_window.staff_work_page.refresh()
        if hasattr(self, "my_space_page"): self.my_space_page.refresh()
        self._show_toast(f"{label}을 {action}했습니다.")
        return True

    def _open_v3_task(self, remote_task_id: str) -> None:
        if not self.workspace_db or not self.local_window:
            return
        row = self.workspace_db.one("SELECT local_id FROM teams_v2_entity_map WHERE entity_type='EVENT_TASK' AND remote_id=?", (remote_task_id,))
        if row: self.local_window.open_teams_task(int(row["local_id"]))

    def _assign_task_member(self, task, member_user_id) -> bool:
        return self._save_task_member(task, member_user_id, transfer=False)

    def _transfer_task_member(self, task_id: str, member_user_id: str, position: int=1) -> bool:
        if not self.workspace_db:
            return False
        # V3 company-wide cards keep their server UUID.  Queue that explicit
        # assignment through the manager-only transfer RPC so both the new
        # assignee and the prior assignee receive the existing app notice.
        if not str(task_id).isdigit():
            task = self.workspace_db.one("SELECT * FROM teams_v3_work_items WHERE remote_id=?", (str(task_id),))
            if not task or not self.company_workspace or not self.current_organization:
                return False
            try:
                response=self.api.move_member_task(self.current_organization.id,str(task_id),str(member_user_id),int(position),int(task["row_version"] or 0))
                saved=response.get("task") if isinstance(response,dict) else None
                if not isinstance(saved,dict): raise ApiError("업무 이동 결과를 확인할 수 없습니다.")
                self.company_workspace.apply_changes({"cursor": self.company_workspace.cursor(), "changes": [{"entity_type": "WORK_ITEM", "entity_key": str(task_id), "operation": "UPSERT", "payload": saved}]})
                self._refresh_staff_priorities()
                if self.local_window and hasattr(self.local_window, "staff_work_page"): self.local_window.staff_work_page.refresh()
                if self.company_calendar_page: self.company_calendar_page.refresh()
                if hasattr(self,"my_space_page"): self.my_space_page.refresh()
                if str(response.get("previous_member_user_id") or "")!=str(member_user_id): self._show_toast("업무를 이관하고 담당자들에게 알림을 보냈습니다.")
                return True
            except ApiError as exc:
                QMessageBox.warning(self.local_window, "업무 이동 실패", str(exc));
                if self.local_window and hasattr(self.local_window,"staff_work_page"): self.local_window.staff_work_page.refresh()
                return False
        task = self.workspace_db.one("SELECT * FROM event_tasks WHERE id=?", (int(task_id),))
        if not task:
            return False
        return self._save_task_member(task, member_user_id, transfer=True)

    def _refresh_staff_priorities(self) -> None:
        if not self.current_organization or not self.local_window or not hasattr(self.local_window,"staff_work_page") or not self.local_window.staff_work_page.can_transfer: return
        if getattr(self,"staff_priority_worker",None) and self.staff_priority_worker.isRunning(): return
        oid=self.current_organization.id; self.staff_priority_worker=Worker(lambda:self.api.staff_task_priorities(oid))
        self.staff_priority_worker.finished.connect(lambda values,organization_id=oid:self._staff_priorities_loaded(organization_id,values))
        self.staff_priority_worker.start()

    def _staff_priorities_loaded(self, organization_id: str, values: object) -> None:
        if not self.current_organization or self.current_organization.id!=organization_id or not self.local_window or not hasattr(self.local_window,"staff_work_page") or not isinstance(values,list): return
        self.local_window.staff_work_page.set_priorities([row for row in values if isinstance(row,dict)]); self.local_window.staff_work_page.refresh()

    def _save_task_member(self, task, member_user_id, transfer: bool) -> bool:
        if not self.current_organization or not self.workspace_db:
            return False
        mapping = self.workspace_db.one("SELECT remote_id,remote_version FROM teams_v2_entity_map WHERE entity_type='EVENT_TASK' AND local_id=?", (int(task["id"]),))
        if not mapping:
            QMessageBox.warning(self.local_window, "담당자 지정", "서버 업무 연결을 찾을 수 없습니다.")
            return False
        try:
            saved = (self.api.transfer_task_member(self.current_organization.id, str(mapping["remote_id"]), str(member_user_id), int(mapping["remote_version"] or 0)) if transfer
                     else self.api.assign_task_member(self.current_organization.id, str(mapping["remote_id"]), str(member_user_id) if member_user_id else None, int(mapping["remote_version"] or 0)))
            with self.workspace_db.applying_remote_changes():
                self.workspace_db.conn.execute("UPDATE event_tasks SET assigned_member_user_id=? WHERE id=?", (saved.get("assigned_member_user_id"), int(task["id"])))
                self.workspace_db.conn.execute("UPDATE teams_v2_entity_map SET remote_version=?,remote_updated_at=? WHERE entity_type='EVENT_TASK' AND local_id=?", (int(saved.get("row_version") or mapping["remote_version"]), str(saved.get("updated_at") or ""), int(task["id"])))
            self.workspace_db.conn.commit()
            if self.company_workspace:
                self.company_workspace.apply_changes({"cursor": self.company_workspace.cursor(), "changes": [{"entity_type": "WORK_ITEM", "entity_key": str(saved.get("id") or mapping["remote_id"]), "operation": "UPSERT", "payload": saved}]})
            if self.company_calendar_page:
                self.company_calendar_page.refresh()
            if self.local_window and hasattr(self.local_window, "staff_work_page"):
                self.local_window.staff_work_page.refresh()
            if hasattr(self, "my_space_page"):
                self.my_space_page.refresh()
            if transfer:
                self._show_toast("업무를 이관했습니다. 담당자에게 알림을 보냈습니다.")
            return True
        except ApiError as exc:
            QMessageBox.warning(self.local_window, "업무 이관 실패" if transfer else "담당자 지정 실패", str(exc))
            return False

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
        insert_at = max(0, title_layout.count() - 3)
        for offset, widget in enumerate((self.sync_dot, self.sync_text)):
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
        button.setToolTip("직원·권한 관리와 프로젝트 게스트 초대" if organization.role in {"OWNER", "ADMIN"} else "내가 접근할 수 있는 프로젝트에 게스트를 초대")
        local.add_company_management_nav_button(button)
        self.company_management_page = CompanyManagementPage(organization, self.api)
        self.company_management_page.guests_requested.connect(self._show_guest_management_page)
        self.company_management_page.members_requested.connect(self._show_company_members_page)
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
        button.setChecked(True)
        self.local_window.stack.setCurrentWidget(self.company_management_page)

    def _show_guest_management_page(self) -> None:
        if not self.local_window or not self.guest_management_page:
            return
        self.local_window.stack.setCurrentWidget(self.guest_management_page)

    def _show_company_members_page(self) -> None:
        if not self.local_window or not self.company_members_page:
            return
        self.local_window.stack.setCurrentWidget(self.company_members_page)
        self.company_members_page.load()

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
        self._trace("permissions_loaded")
        self.workspace_db.set_access_context(role=self.current_organization.role, permissions=permissions)
        self._apply_v3_menu_permissions(permissions)
        cursor = self._opened_cursor
        if cursor:
            # A synchronized Local workspace is immediately usable.  Never
            # overwrite its outbox with a complete snapshot on later starts.
            controller = TeamsPermissionController(self.local_window, permissions, self.current_organization.role)
            controller.apply(); self.local_window.setEnabled(True)
            # The cached workspace is already safe to edit.  Start observing
            # its local outbox before the quiet delta request completes so a
            # user edit made during that request is never left unsent.
            self._start_sync_engine()
            self._start_realtime()
            self._load_v3_workspace()
            self._refresh_notifications_async(show_new=False)
            self.staff_directory_worker = Worker(lambda: self.api.staff_directory(organization_id))
            self.staff_directory_worker.finished.connect(lambda members, oid=organization_id: self._staff_directory_loaded(oid, members))
            self.staff_directory_worker.start()
            if self._opened_with_pending:
                return
            self._set_sync_state("CHECKING", "서버 변경분 확인 중…")
            self.changes_worker = Worker(lambda: self.api.workspace_changes(organization_id, int(cursor or 0)))
            self.changes_worker.finished.connect(lambda changes, oid=organization_id: self._changes_loaded(oid, changes))
            self.changes_worker.failed.connect(lambda message, oid=organization_id: self._changes_failed(oid, message))
            self.changes_worker.start()
            return
        self._set_sync_state("CHECKING", "회사 작업본 확인 중…")
        self.snapshot_worker = Worker(lambda: self._workspace_snapshot_with_staff(organization_id))
        self.snapshot_worker.finished.connect(lambda snapshot, oid=organization_id, granted=permissions: self._snapshot_loaded(oid, granted, snapshot))
        self.snapshot_worker.failed.connect(lambda message, oid=organization_id: self._snapshot_failed(oid, message))
        self.snapshot_worker.start()

    def _apply_v3_menu_permissions(self, permissions: set[str]) -> None:
        """Mirror server visibility rules in the V3 shell; RPC remains final authority."""
        if not self.current_organization:
            return
        global_visible = self.current_organization.role != "GUEST"
        for index, button in enumerate(self.company_v3_buttons):
            if index < 2:
                button.setVisible(global_visible)
            else:
                button.setVisible(global_visible and "settlement.view" in permissions)
        if self.local_window:
            self.local_window.events.finance_button.hide()
        if self.company_finance_page:
            self.company_finance_page.configure_access(
                can_edit="settlement.edit" in permissions,
                allow_company=self.current_organization.role in {"OWNER", "ADMIN"},
            )

    def _staff_directory_loaded(self, organization_id: str, members: object) -> None:
        if not self.current_organization or self.current_organization.id != organization_id or not self.workspace_db or not self.local_window:
            return
        if not isinstance(members, list):
            return
        try:
            WorkspaceSnapshotStore(self.workspace_db).replace_staff_members([item for item in members if isinstance(item, dict)])
            self.workspace_db.conn.commit(); self.local_window.refresh_all(self.local_window.selected_event_id)
            if hasattr(self.local_window, "staff_work_page"):
                self.local_window.staff_work_page.staff_refresh_finished()
        except Exception:
            if hasattr(self.local_window, "staff_work_page"):
                self.local_window.staff_work_page.staff_refresh_finished()

    def _refresh_staff_directory(self) -> None:
        if not self.current_organization or not self.workspace_db or not self.local_window:
            return
        organization_id = self.current_organization.id
        if getattr(self, "staff_directory_worker", None) and self.staff_directory_worker.isRunning():
            return
        self.staff_directory_worker = Worker(lambda: self.api.staff_directory(organization_id))
        self.staff_directory_worker.finished.connect(lambda members, oid=organization_id: self._staff_directory_loaded(oid, members))
        self.staff_directory_worker.failed.connect(lambda _message: hasattr(self.local_window, "staff_work_page") and self.local_window.staff_work_page.staff_refresh_finished())
        self.staff_directory_worker.start()

    def _workspace_snapshot_with_staff(self, organization_id: str) -> dict:
        snapshot = self.api.workspace_snapshot(organization_id)
        # New desktop clients stay usable against a server that has not yet
        # received this optional feature migration; the owner still sees a
        # clearly labelled local card instead of a broken blank canvas.
        try:
            snapshot["staff_members"] = self.api.staff_directory(organization_id)
            snapshot["personal_schedules"] = self.api.personal_schedules(organization_id)
        except ApiError:
            snapshot["staff_members"] = []
            snapshot["personal_schedules"] = []
        snapshot["my_task_priorities"] = []
        return snapshot

    def _snapshot_loaded(self, organization_id: str, permissions: set[str], snapshot: object) -> None:
        if not self.current_organization or self.current_organization.id != organization_id or not self.local_window or not self.workspace_db:
            return
        if not isinstance(snapshot, dict):
            self._snapshot_failed(organization_id, "회사 작업본 응답이 올바르지 않습니다.")
            return
        try:
            WorkspaceSnapshotStore(self.workspace_db).apply_snapshot(snapshot)
            if self.api.session and not self.workspace_db.one("SELECT 1 FROM teams_v2_staff_members WHERE user_id=?", (self.api.session.user_id,)):
                self.workspace_db.conn.execute(
                    "INSERT INTO teams_v2_staff_members(user_id,display_name,role,job_title,color_hex,status) VALUES (?,?,?,?,?, 'ACTIVE')",
                    (self.api.session.user_id, self.api.session.email.split("@", 1)[0], self.current_organization.role, "", "#A7D4F0"),
                )
                self.workspace_db.conn.commit()
            self.local_window.refresh_all()
            self._trace("workspace_snapshot_rendered")
        except Exception as exc:
            self._snapshot_failed(organization_id, str(exc))
            return
        controller = TeamsPermissionController(self.local_window, permissions, self.current_organization.role)
        controller.apply()
        self.local_window.setEnabled(True)
        self._set_sync_state("LOCAL", "동기화 완료")
        self._start_sync_engine()
        self._start_realtime()
        self._load_v3_workspace()
        self._refresh_notifications_async(show_new=False)

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

    def _show_company_picker(self) -> None:
        # Close the embedded Local shell first, then defer page activation
        # until Qt has completed the button click, so the company list never
        # remains behind a deleted child widget.
        self._close_workspace()
        QTimer.singleShot(0, self._finish_show_company_picker)

    def _finish_show_company_picker(self) -> None:
        self.shell_title_bar.show(); self.stack.setCurrentWidget(self.organizations); self.organizations.load()

    def _check_updates_on_launch(self) -> None:
        """Apply a newer public release before login or company selection."""
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
            self._update_failed("업데이트 파일을 확인하지 못했습니다.")
            return
        if self.update_progress:
            self.update_progress.set_status("설치를 준비하고 있습니다. 잠시 후 자동으로 다시 시작합니다…")
        try:
            launch_installer(archive, self.update_info, os.getpid())
        except Exception as exc:
            self._update_failed(str(exc))
            return
        QTimer.singleShot(700, QApplication.quit)

    def _update_failed(self, _message: str) -> None:
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
        if self.notification_worker and self.notification_worker.isRunning(): self.notification_worker.wait(250)
        self.company_workspace = None; self.company_calendar_page = None; self.company_finance_page = None; self.notification_page = None; self.notification_button = None; self.v3_worker = None; self.notification_worker = None; self.v3_mutation_inflight = False; self._v3_initial_open = False; self._known_notification_ids.clear(); self._notification_baseline_loaded = False; self._realtime_refresh_pending = False; self._v3_refresh_pending = False; self._notification_refresh_pending = False
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

    def _trace(self, action: str) -> None:
        if self.trace:
            self.trace.record(action)

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
            self.api.session.access_token, self.current_organization.id, self.api.session.user_id,
        )
        self.realtime.changed.connect(self._request_realtime_changes)
        self.realtime.access_changed.connect(self._refresh_after_access_change)
        self.realtime.state_changed.connect(self._realtime_state_changed)
        self.realtime.start()

    def _realtime_state_changed(self, state: str, text: str) -> None:
        if state == "STOPPED":
            return
        if state == "WAITING":
            self._set_sync_state("WAITING", text)

    def _refresh_after_access_change(self) -> None:
        """Reload the app boundary immediately after a manager changes this user's access."""
        if not self.current_organization or not self.api.session or (self.access_refresh_worker and self.access_refresh_worker.isRunning()):
            return
        previous_id = self.current_organization.id

        def load_access() -> tuple[list[Organization], list[dict]]:
            return self.api.organizations(), []

        self.access_refresh_worker = Worker(load_access)
        self.access_refresh_worker.finished.connect(lambda value, oid=previous_id: self._access_refresh_loaded(oid, value))
        self.access_refresh_worker.failed.connect(lambda message: self._show_toast(f"권한 변경 확인 실패: {message}"))
        self.access_refresh_worker.start()

    def _access_refresh_loaded(self, previous_id: str, value: object) -> None:
        if not isinstance(value, tuple) or len(value) != 2:
            return
        organizations, notices = value
        messages = [str(item.get("message")) for item in notices if isinstance(item, dict) and item.get("message")]
        message = "\n".join(messages) if messages else "회사 권한이 변경되었습니다."
        target = next((item for item in organizations if item.id == previous_id), None) if isinstance(organizations, list) else None
        if target:
            self._show_toast(f"{message}\n새 권한을 적용하기 위해 화면을 새로고침합니다.")
            QTimer.singleShot(350, lambda organization=target: self._open_workspace(organization))
            return
        QMessageBox.information(self, "권한 변경", f"{message}\n현재 회사 접근이 변경되어 회사 선택 화면으로 이동합니다.")
        self._close_workspace(); self.organizations.load(); self.stack.setCurrentWidget(self.organizations)

    def _request_realtime_changes(self) -> None:
        """Fetch authorized deltas after a signal; never refresh a whole screen."""
        if not self.current_organization or not self.workspace_db or not self.local_window: return
        if self.workspace_db.pending_outbox() or (self.changes_worker and self.changes_worker.isRunning()):
            self._realtime_refresh_pending=True
            return
        self._realtime_refresh_pending=False
        self._load_v3_workspace()
        self._refresh_notifications_async(show_new=True)
        row = self.workspace_db.one("SELECT remote_cursor FROM teams_v2_workspace WHERE singleton=1")
        cursor = int(row["remote_cursor"] or 0) if row else 0
        def load_changes():
            changes = self.api.workspace_changes(self.current_organization.id, cursor)
            try:
                changes["my_task_priorities"] = self.api.my_task_priorities(self.current_organization.id)
            except Exception:
                changes["my_task_priorities"] = []
            return changes
        self.changes_worker = Worker(load_changes)
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
            if "my_task_priorities" in changes:
                self.workspace_db.conn.execute("DELETE FROM teams_v2_my_task_priorities")
                self.workspace_db.conn.executemany("INSERT INTO teams_v2_my_task_priorities(event_task_id,sort_order) VALUES (?,?)", [(str(item["event_task_id"]), int(item.get("sort_order") or 0)) for item in changes["my_task_priorities"] if isinstance(item, dict) and item.get("event_task_id")])
                self.workspace_db.conn.commit()
            if applied:
                self.local_window.refresh_all(self.local_window.selected_event_id)
                if hasattr(self, "my_space_page"): self.my_space_page.refresh()
                if affected:
                    QTimer.singleShot(80, lambda ids=affected: self._flash_task_rows(ids))
                    self._show_toast(f"현재 프로젝트 변경 {len(affected)}건을 반영했습니다.")
        except Exception as exc:
            self._changes_failed(organization_id, str(exc))
        finally:
            if self._realtime_refresh_pending:
                self._realtime_refresh_pending=False; QTimer.singleShot(0,self._request_realtime_changes)

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


def _update_health_file(argv: list[str]) -> Path | None:
    try:
        position = argv.index("--update-health-file")
        value = argv[position + 1].strip()
    except (ValueError, IndexError):
        return None
    return Path(value) if value else None


def main(argv: list[str] | None = None) -> None:
    health_file = _update_health_file(list(sys.argv[1:] if argv is None else argv))
    app = QApplication(sys.argv)
    app.setApplicationName("이벤트 플로우 Teams V2")
    app.setStyleSheet(application_stylesheet())
    ready_for_update = False
    try:
        config = TeamsV2Config.from_environment()
        trace = RuntimeWindowTrace(config.data_root)
        app.installEventFilter(trace)
        app.runtime_window_trace = trace  # Keep the trace alive for the whole app session.
        window = TeamsV2Window(config, trace)
        ready_for_update = True
    except RuntimeError as exc:
        window = QMainWindow(); window.setCentralWidget(QLabel(str(exc))); window.resize(520, 180)
    window.show()
    if ready_for_update and health_file is not None:
        QTimer.singleShot(500, lambda: health_file.write_text("ok", encoding="ascii"))
    raise SystemExit(app.exec())
