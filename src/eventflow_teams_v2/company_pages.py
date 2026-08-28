"""Company-wide V3 work and actual-finance pages, independent from Local V2 UI."""

from __future__ import annotations

import calendar
from datetime import date
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QSplitter, QVBoxLayout, QWidget
from event_checklist.ui.month_timeline import MonthTimeline
from event_checklist.theme import status_color
from event_checklist.ui.calendar_page import CATEGORY_CARD_BORDERS

FINANCE_KIND_LABELS = {"EXPENSE": "지출", "INCOME": "수입", "REFUND": "환불", "ADJUSTMENT": "조정"}
FINANCE_STATUS_LABELS = {"PLANNED": "예정", "COMPLETED": "완료", "CANCELED": "취소"}


def _project_name(db, event_id: str | None) -> str:
    if not event_id:
        return "프로젝트 외"
    row = db.one("SELECT e.name FROM events e JOIN teams_v2_entity_map m ON m.entity_type='EVENT' AND m.local_id=e.id WHERE m.remote_id=?", (event_id,))
    return str(row["name"]) if row else "프로젝트"


class CompanyWorkPage(QWidget):
    def __init__(self, db, create_work: Callable[[dict], None], open_project: Callable[[str], None] | None = None, parent=None):
        super().__init__(parent); self.db = db; self.create_work = create_work; self.open_project = open_project; self.can_edit = False
        root = QVBoxLayout(self); root.setContentsMargins(32, 28, 32, 32); root.setSpacing(12)
        top = QHBoxLayout(); copy = QVBoxLayout(); copy.addWidget(QLabel("전체 업무", objectName="PageTitle")); copy.addWidget(QLabel("모든 프로젝트 업무와 프로젝트 외 업무를 한 곳에서 확인합니다.", objectName="PageDescription")); top.addLayout(copy, 1)
        self.add_button = QPushButton("업무 추가"); self.add_button.clicked.connect(self._add); top.addWidget(self.add_button); root.addLayout(top)
        filters = QHBoxLayout(); self.project = QComboBox(); self.member = QComboBox(); self.project.currentIndexChanged.connect(self.refresh); self.member.currentIndexChanged.connect(self.refresh); self.status = QComboBox(); self.status.addItems(["전체 상태", "미착수", "진행중", "확인요청", "완료", "보류", "해당없음"]); self.status.currentIndexChanged.connect(self.refresh); filters.addWidget(QLabel("프로젝트")); filters.addWidget(self.project); filters.addSpacing(12); filters.addWidget(QLabel("담당자")); filters.addWidget(self.member); filters.addSpacing(12); filters.addWidget(QLabel("상태")); filters.addWidget(self.status); filters.addStretch(); root.addLayout(filters)
        self.scroll = QScrollArea(); self.scroll.setObjectName("CompanyWorkScroll"); self.scroll.setWidgetResizable(True); self.scroll.setFrameShape(QFrame.Shape.NoFrame); self.scroll.setStyleSheet("QScrollArea#CompanyWorkScroll{background:#F7F8FA;border:none;} QScrollArea#CompanyWorkScroll > QWidget > QWidget{background:#F7F8FA;}"); self.canvas = QWidget(); self.canvas.setObjectName("CompanyWorkCanvas"); self.canvas.setStyleSheet("QWidget#CompanyWorkCanvas{background:#F7F8FA;}"); self.rows = QVBoxLayout(self.canvas); self.rows.setContentsMargins(0, 0, 0, 0); self.rows.setSpacing(7); self.rows.setAlignment(Qt.AlignmentFlag.AlignTop); self.scroll.setWidget(self.canvas); root.addWidget(self.scroll, 1)

    def refresh(self) -> None:
        current, current_member = self.project.currentData(), self.member.currentData()
        self.project.blockSignals(True); self.member.blockSignals(True); self.project.clear(); self.member.clear(); self.project.addItem("전체 프로젝트", "") ; self.project.addItem("프로젝트 외", "__COMPANY__")
        for row in self.db.query("SELECT remote_id,name FROM teams_v2_entity_map m JOIN events e ON e.id=m.local_id WHERE m.entity_type='EVENT' ORDER BY e.name"):
            self.project.addItem(str(row["name"]), str(row["remote_id"]))
        found = self.project.findData(current)
        self.project.setCurrentIndex(found if found >= 0 else 0); self.project.blockSignals(False)
        self.member.addItem("전체 직원", "")
        try:
            for member in self.db.query("SELECT user_id,display_name,job_title FROM teams_v2_staff_members WHERE status='ACTIVE' ORDER BY display_name,user_id"):
                label = str(member["display_name"] or member["user_id"])
                if member["job_title"]: label += f" · {member['job_title']}"
                self.member.addItem(label, str(member["user_id"]))
        except Exception: pass
        self.member.setCurrentIndex(max(0, self.member.findData(current_member))); self.member.blockSignals(False)
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        clauses = ["is_removed=0"]; args: list[object] = []
        selected = self.project.currentData()
        if selected == "__COMPANY__": clauses.append("work_scope='COMPANY'")
        elif selected: clauses.append("event_id=?"); args.append(selected)
        if self.member.currentData(): clauses.append("assigned_member_user_id=?"); args.append(self.member.currentData())
        if self.status.currentIndex() > 0: clauses.append("status=?"); args.append(self.status.currentText())
        work = self.db.query("SELECT * FROM teams_v3_work_items WHERE " + " AND ".join(clauses) + " ORDER BY CASE work_scope WHEN 'COMPANY' THEN 0 ELSE 1 END, COALESCE(due_date,'9999-12-31'),sort_order,name", tuple(args))
        for item in work:
            row = QFrame(); row.setObjectName("CompanyWorkRow"); row.setStyleSheet("QFrame#CompanyWorkRow{background:white;border:1px solid #E2E8F0;border-radius:9px;}")
            layout = QHBoxLayout(row); layout.setContentsMargins(16, 10, 16, 10); layout.setSpacing(14)
            layout.addWidget(QLabel(_project_name(self.db, item["event_id"]), objectName="Muted"), 1)
            layout.addWidget(QLabel(f"{item['major']} · {item['minor']}"), 1)
            layout.addWidget(QLabel(str(item["name"])), 3)
            layout.addWidget(QLabel(str(item["status"])), 1)
            layout.addWidget(QLabel(str(item["due_date"] or "마감일 미입력"), objectName="Muted"), 1)
            if item["event_id"] and self.open_project:
                open_button = QPushButton("프로젝트 열기"); open_button.setProperty("compact", True); open_button.clicked.connect(lambda _checked=False, event_id=str(item["event_id"]): self.open_project(event_id)); layout.addWidget(open_button)
            self.rows.addWidget(row)
        if not work: self.rows.addWidget(QLabel("표시할 업무가 없습니다.", objectName="EmptyState"))

    def configure_access(self, can_edit: bool) -> None:
        self.can_edit = can_edit; self.add_button.setVisible(can_edit)

    def _add(self) -> None:
        if not self.can_edit:
            return
        dialog = QDialog(self); dialog.setWindowTitle("회사 전체 업무 추가"); form = QFormLayout(dialog); scope = QComboBox(); scope.addItem("프로젝트 외", "COMPANY")
        for row in self.db.query("SELECT remote_id,name FROM teams_v2_entity_map m JOIN events e ON e.id=m.local_id WHERE m.entity_type='EVENT' ORDER BY e.name"): scope.addItem(str(row["name"]), str(row["remote_id"]))
        name = QLineEdit(); major = QLineEdit("회사 운영"); minor = QLineEdit("기타"); form.addRow("프로젝트", scope); form.addRow("업무명", name); form.addRow("대분류", major); form.addRow("중분류", minor); buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel); form.addRow(buttons); buttons.rejected.connect(dialog.reject)
        def accept() -> None:
            if not name.text().strip(): return
            event = scope.currentData(); self.create_work({"work_scope": "COMPANY" if event == "COMPANY" else "PROJECT", "event_id": "" if event == "COMPANY" else event, "name": name.text().strip(), "major": major.text().strip() or "회사 운영", "minor": minor.text().strip() or "기타"}); dialog.accept()
        buttons.accepted.connect(accept); dialog.exec()


class FinancePage(QWidget):
    def __init__(self, db, create_finance: Callable[[dict], None], mutate_finance: Callable[[str, dict], None] | None = None, parent=None):
        super().__init__(parent); self.db = db; self.create_finance = create_finance; self.mutate_finance = mutate_finance; self._task_prefill: dict | None = None
        root = QVBoxLayout(self); root.setContentsMargins(32, 28, 32, 32); root.setSpacing(12)
        self.can_edit = False; self.allow_company = False
        top = QHBoxLayout(); copy = QVBoxLayout(); copy.addWidget(QLabel("정산내역", objectName="PageTitle")); copy.addWidget(QLabel("실제 수입·지출 장부입니다. 기존 체크리스트 단가와 자동 연동되지 않습니다.", objectName="PageDescription")); top.addLayout(copy, 1); self.add_button = QPushButton("실제 정산 추가"); self.add_button.clicked.connect(self._add); top.addWidget(self.add_button); root.addLayout(top)
        filters = QHBoxLayout(); self.project = QComboBox(); self.kind = QComboBox(); self.status = QComboBox()
        self.kind.addItem("전체 유형", ""); self.kind.addItems(["EXPENSE", "INCOME", "REFUND", "ADJUSTMENT"]); self.status.addItem("전체 상태", ""); self.status.addItems(["PLANNED", "COMPLETED", "CANCELED"])
        filters.addWidget(QLabel("프로젝트")); filters.addWidget(self.project); filters.addSpacing(12); filters.addWidget(QLabel("유형")); filters.addWidget(self.kind); filters.addSpacing(12); filters.addWidget(QLabel("상태")); filters.addWidget(self.status); filters.addStretch(); root.addLayout(filters)
        self.total = QLabel(); root.addWidget(self.total, 0)
        self.scroll = QScrollArea(); self.scroll.setObjectName("FinanceScroll"); self.scroll.setWidgetResizable(True); self.scroll.setFrameShape(QFrame.Shape.NoFrame); self.scroll.setStyleSheet("QScrollArea#FinanceScroll{background:#F7F8FA;border:none;} QScrollArea#FinanceScroll > QWidget > QWidget{background:#F7F8FA;}"); self.canvas = QWidget(); self.canvas.setObjectName("FinanceCanvas"); self.canvas.setStyleSheet("QWidget#FinanceCanvas{background:#F7F8FA;}"); self.rows = QVBoxLayout(self.canvas); self.rows.setContentsMargins(0, 0, 0, 0); self.rows.setSpacing(7); self.rows.setAlignment(Qt.AlignmentFlag.AlignTop); self.scroll.setWidget(self.canvas); root.addWidget(self.scroll, 1)
        self.project.currentIndexChanged.connect(self.refresh); self.kind.currentIndexChanged.connect(self.refresh); self.status.currentIndexChanged.connect(self.refresh)

    def refresh(self) -> None:
        selected_project = self.project.currentData(); self.project.blockSignals(True); self.project.clear(); self.project.addItem("회사 전체", ""); self.project.addItem("프로젝트 외 정산", "__COMPANY__")
        for row in self.db.query("SELECT remote_id,name FROM teams_v2_entity_map m JOIN events e ON e.id=m.local_id WHERE m.entity_type='EVENT' ORDER BY e.name"): self.project.addItem(str(row["name"]), str(row["remote_id"]))
        self.project.setCurrentIndex(max(0, self.project.findData(selected_project))); self.project.blockSignals(False)
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        clauses: list[str] = []; args: list[object] = []; project = self.project.currentData()
        if project == "__COMPANY__": clauses.append("event_id IS NULL")
        elif project: clauses.append("event_id=?"); args.append(project)
        if self.kind.currentData(): clauses.append("entry_kind=?"); args.append(self.kind.currentData())
        if self.status.currentData(): clauses.append("settlement_status=?"); args.append(self.status.currentData())
        entries = self.db.query("SELECT * FROM teams_v3_financial_entries" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY COALESCE(planned_date,'9999-12-31'),title", tuple(args))
        total = sum(int(row["total_amount"] or 0) for row in entries if row["settlement_status"] != "CANCELED")
        self.total.setText(f"등록 {len(entries)}건 · 합계 {total:,}원")
        for item in entries:
            row = QFrame(); row.setStyleSheet("QFrame{background:white;border:1px solid #E2E8F0;border-radius:9px;}"); layout = QHBoxLayout(row); layout.setContentsMargins(16, 10, 16, 10)
            layout.addWidget(QLabel(_project_name(self.db, item["event_id"]), objectName="Muted"), 1); layout.addWidget(QLabel(FINANCE_KIND_LABELS.get(str(item["entry_kind"]), str(item["entry_kind"]))), 1); layout.addWidget(QLabel(str(item["title"])), 3); layout.addWidget(QLabel(f"{int(item['total_amount']):,}원"), 1); layout.addWidget(QLabel(FINANCE_STATUS_LABELS.get(str(item["settlement_status"]), str(item["settlement_status"]))), 1); layout.addWidget(QLabel(str(item["planned_date"] or "일자 미입력"), objectName="Muted"), 1)
            if self.can_edit and self.mutate_finance:
                edit = QPushButton("수정"); edit.setProperty("compact", True); edit.clicked.connect(lambda _checked=False, entry=dict(item): self._edit(entry)); layout.addWidget(edit)
                delete = QPushButton("삭제"); delete.setProperty("compact", True); delete.clicked.connect(lambda _checked=False, entry=dict(item): self._delete(entry)); layout.addWidget(delete)
            self.rows.addWidget(row)
        if not entries: self.rows.addWidget(QLabel("실제 정산 항목이 없습니다. 기존 업무 견적은 기존 정산 화면에서 그대로 확인할 수 있습니다.", objectName="EmptyState"))

    def select_project(self, remote_event_id: str | None) -> None:
        """Open the same actual-finance ledger narrowed to one selected project."""
        self.refresh()
        index = self.project.findData(str(remote_event_id or ""))
        self.project.setCurrentIndex(index if index >= 0 else 0)

    def configure_access(self, *, can_edit: bool, allow_company: bool) -> None:
        self.can_edit, self.allow_company = can_edit, allow_company
        self.add_button.setVisible(can_edit)

    def begin_from_task(self, event_id: str, task_id: str, task_name: str) -> None:
        """Open a new, independent actual-ledger entry linked to one task."""
        self._task_prefill = {"event_id": event_id, "event_task_id": task_id, "title": task_name}
        self.select_project(event_id)
        self._add()

    def _add(self) -> None:
        if not self.can_edit:
            return
        prefill = self._task_prefill or {}
        dialog = QDialog(self); dialog.setWindowTitle("실제 정산 추가"); form = QFormLayout(dialog); title = QLineEdit(prefill.get("title", "")); amount = QLineEdit(); kind = QComboBox(); kind.addItems(["EXPENSE", "INCOME", "REFUND", "ADJUSTMENT"]); status = QComboBox(); status.addItems(["PLANNED", "COMPLETED"]); project = QComboBox()
        if self.allow_company: project.addItem("프로젝트 외", "")
        for row in self.db.query("SELECT remote_id,name FROM teams_v2_entity_map m JOIN events e ON e.id=m.local_id WHERE m.entity_type='EVENT' ORDER BY e.name"): project.addItem(str(row["name"]), str(row["remote_id"]))
        selected_project = self.project.currentData()
        if selected_project == "__COMPANY__": project.setCurrentIndex(0)
        elif selected_project:
            index = project.findData(selected_project)
            if index >= 0: project.setCurrentIndex(index)
        if prefill.get("event_id"):
            index = project.findData(prefill["event_id"])
            if index >= 0: project.setCurrentIndex(index)
        form.addRow("제목", title); form.addRow("유형", kind); form.addRow("프로젝트", project); form.addRow("공급가", amount); form.addRow("상태", status); buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel); form.addRow(buttons); buttons.rejected.connect(dialog.reject)
        def accept() -> None:
            try: supply = int(amount.text().replace(",", ""))
            except ValueError: return
            if not title.text().strip() or supply < 0: return
            payload = {"title": title.text().strip(), "entry_kind": kind.currentText(), "event_id": project.currentData(), "supply_amount": supply, "vat_type": "TAXABLE", "settlement_status": status.currentText(), "planned_date": date.today().isoformat()}
            if prefill.get("event_task_id") and project.currentData() == prefill.get("event_id"):
                payload["event_task_id"] = prefill["event_task_id"]
            self.create_finance(payload); dialog.accept()
        buttons.accepted.connect(accept); dialog.exec()
        self._task_prefill = None

    def _edit(self, entry: dict) -> None:
        if not self.can_edit or not self.mutate_finance:
            return
        dialog = QDialog(self); dialog.setWindowTitle("실제 정산 수정"); form = QFormLayout(dialog)
        title = QLineEdit(str(entry["title"])); amount = QLineEdit(str(entry["supply_amount"])); kind = QComboBox(); kind.addItems(["EXPENSE", "INCOME", "REFUND", "ADJUSTMENT"]); kind.setCurrentText(str(entry["entry_kind"])); status = QComboBox(); status.addItems(["PLANNED", "COMPLETED", "CANCELED"]); status.setCurrentText(str(entry["settlement_status"]))
        form.addRow("제목", title); form.addRow("유형", kind); form.addRow("공급가", amount); form.addRow("상태", status); buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel); form.addRow(buttons); buttons.rejected.connect(dialog.reject)
        def accept() -> None:
            try: supply = int(amount.text().replace(",", ""))
            except ValueError: return
            if not title.text().strip() or supply < 0: return
            self.mutate_finance("FINANCE_PATCH", {"id": entry["remote_id"], "row_version": entry["row_version"], "title": title.text().strip(), "entry_kind": kind.currentText(), "supply_amount": supply, "settlement_status": status.currentText()}); dialog.accept()
        buttons.accepted.connect(accept); dialog.exec()

    def _delete(self, entry: dict) -> None:
        if not self.can_edit or not self.mutate_finance:
            return
        if QMessageBox.question(self, "실제 정산 삭제", f"‘{entry['title']}’ 실제 정산을 삭제할까요?") != QMessageBox.StandardButton.Yes:
            return
        self.mutate_finance("FINANCE_DELETE", {"id": entry["remote_id"], "row_version": entry["row_version"]})


class CompanyCalendarPage(QWidget):
    """Whole-company calendar backed only by the V3 mirror.

    The Local `CalendarPage` remains the selected-project calendar.  Keeping
    this separate avoids making an old project-only service silently return
    company work.
    """
    def __init__(self, db, parent=None):
        super().__init__(parent); self.db = db
        root = QVBoxLayout(self); root.setContentsMargins(32, 28, 32, 32); root.setSpacing(12)
        title_row = QHBoxLayout(); title_row.setSpacing(14); title_row.addWidget(QLabel("전체 달력", objectName="PageTitle")); description = QLabel("모든 프로젝트 업무와 프로젝트 외 업무를 표시합니다.", objectName="PageDescription"); title_row.addWidget(description, 0, Qt.AlignmentFlag.AlignBottom); title_row.addStretch(); root.addLayout(title_row)
        filters = QHBoxLayout(); filters.setSpacing(10); self.project = QComboBox(); self.member = QComboBox(); self.personal = QCheckBox("개인 일정 표시"); self.personal.setChecked(True)
        for item in (self.project, self.member): item.currentIndexChanged.connect(self.refresh)
        self.previous = QPushButton("‹"); self.next = QPushButton("›"); self.month = QLabel(objectName="SectionTitle"); self.month.setMinimumWidth(124); self.month.setAlignment(Qt.AlignmentFlag.AlignCenter); self.previous.setToolTip("이전 달"); self.next.setToolTip("다음 달")
        self.personal.toggled.connect(self.refresh); self.previous.clicked.connect(lambda: self._shift(-1)); self.next.clicked.connect(lambda: self._shift(1))
        filters.addWidget(self.previous); filters.addWidget(self.month); filters.addWidget(self.next); filters.addSpacing(18); filters.addWidget(QLabel("프로젝트")); filters.addWidget(self.project); filters.addSpacing(12); filters.addWidget(QLabel("직원")); filters.addWidget(self.member); filters.addSpacing(10); filters.addWidget(self.personal); filters.addStretch()
        self.list_toggle = QPushButton("일정 목록 숨기기"); self.list_toggle.setProperty("compact", True); self.list_toggle.clicked.connect(self._toggle_list); filters.addWidget(self.list_toggle); root.addLayout(filters)
        split = QSplitter(Qt.Orientation.Horizontal); self.timeline = MonthTimeline(); self.timeline.date_selected.connect(self._selected); split.addWidget(self.timeline)
        self.split = split; self.side = QFrame(); self.side.setObjectName("CalendarSide"); side_layout = QVBoxLayout(self.side); side_layout.setContentsMargins(14, 14, 14, 14); side_layout.setSpacing(10); self.selected_title = QLabel(objectName="SectionTitle"); self.list = QListWidget(); self.list.setObjectName("CalendarTaskList"); self.list.setSpacing(8); self.list.setViewportMargins(0, 2, 0, 2); self.list.setStyleSheet("QListWidget#CalendarTaskList{background:transparent;border:none;outline:0;} QListWidget#CalendarTaskList::item{background:transparent;border:none;}"); side_layout.addWidget(self.selected_title); side_layout.addWidget(self.list, 1); split.addWidget(self.side); split.setSizes([860, 350]); root.addWidget(split, 1)
        self.refresh()

    def _shift(self, offset: int) -> None:
        self.timeline.shift_month(offset); self.refresh()

    def _toggle_list(self) -> None:
        visible = self.side.isVisible()
        self.side.setVisible(not visible)
        self.list_toggle.setText("일정 목록 보기" if visible else "일정 목록 숨기기")
        if not visible:
            self.split.setSizes([860, 350])

    def _load_filters(self) -> None:
        selected_project, selected_member = self.project.currentData(), self.member.currentData()
        self.project.blockSignals(True); self.member.blockSignals(True); self.project.clear(); self.member.clear(); self.project.addItem("전체 프로젝트", ""); self.project.addItem("프로젝트 외", "__COMPANY__")
        for row in self.db.query("SELECT remote_id,name FROM teams_v2_entity_map m JOIN events e ON e.id=m.local_id WHERE m.entity_type='EVENT' ORDER BY e.name"): self.project.addItem(str(row["name"]), str(row["remote_id"]))
        self.member.addItem("전체 직원", "")
        try:
            for row in self.db.query("SELECT user_id,display_name FROM teams_v2_staff_members WHERE status='ACTIVE' ORDER BY display_name,user_id"): self.member.addItem(str(row["display_name"] or row["user_id"]), str(row["user_id"]))
        except Exception: pass
        self.project.setCurrentIndex(max(0, self.project.findData(selected_project))); self.member.setCurrentIndex(max(0, self.member.findData(selected_member))); self.project.blockSignals(False); self.member.blockSignals(False)

    def refresh(self) -> None:
        self._load_filters(); self.month.setText(f"{self.timeline.year}년 {self.timeline.month}월")
        clauses = ["is_removed=0", "planned_start IS NOT NULL", "due_date IS NOT NULL"]; args: list[object] = []; project = self.project.currentData(); member = self.member.currentData()
        if project == "__COMPANY__": clauses.append("work_scope='COMPANY'")
        elif project: clauses.append("event_id=?"); args.append(project)
        if member: clauses.append("assigned_member_user_id=?"); args.append(member)
        tasks = [dict(row) for row in self.db.query("SELECT * FROM teams_v3_work_items WHERE " + " AND ".join(clauses), tuple(args))]
        try:
            colors = {str(row["user_id"]): row["color_hex"] for row in self.db.query("SELECT user_id,color_hex FROM teams_v2_staff_members")}
            for task in tasks: task["member_color_hex"] = colors.get(str(task.get("assigned_member_user_id") or ""))
        except Exception: pass
        self.timeline.set_tasks(tasks)
        schedules: list[dict] = []
        if self.personal.isChecked():
            try:
                rows = self.db.query("SELECT s.*,m.display_name member_name,m.color_hex FROM teams_v2_personal_schedules s LEFT JOIN teams_v2_staff_members m ON m.user_id=s.member_user_id")
                schedules = [dict(row) for row in rows if not member or str(row["member_user_id"]) == str(member)]
            except Exception: pass
        current_member_id = ""
        try:
            workspace = self.db.one("SELECT user_id FROM teams_v2_workspace WHERE singleton=1")
            current_member_id = str(workspace["user_id"] or "") if workspace else ""
        except Exception:
            pass
        self.timeline.set_personal_schedules(schedules, priority_member_user_id=current_member_id); self.timeline.set_event_period(None); self._selected(self.timeline.selected)

    def _selected(self, selected: date) -> None:
        self.selected_title.setText(f"{selected.year}년 {selected.month:02d}월 {selected.day:02d}일"); self.list.clear(); selected_iso = selected.isoformat(); count = 0
        for task in self.timeline.tasks:
            if str(task["planned_start"]) <= selected_iso <= str(task["due_date"]):
                item = QListWidgetItem(); item.setSizeHint(item.sizeHint().__class__(0, 72)); self.list.addItem(item); self.list.setItemWidget(item, self._task_card(dict(task))); count += 1
        for schedule in self.timeline.personal_schedules:
            if str(schedule["start_date"]) <= selected_iso <= str(schedule["end_date"]):
                item = QListWidgetItem(); item.setSizeHint(item.sizeHint().__class__(0, 72)); self.list.addItem(item); self.list.setItemWidget(item, self._schedule_card(dict(schedule))); count += 1
        if not count:
            item = QListWidgetItem(); item.setSizeHint(item.sizeHint().__class__(0, 54)); self.list.addItem(item); empty = QFrame(); empty.setStyleSheet("QFrame{background:#FFFFFF;border:1px dashed #CBD5E1;border-radius:10px;}"); line = QHBoxLayout(empty); line.addWidget(QLabel("이 날짜에 일정이 없습니다.", objectName="Muted")); self.list.setItemWidget(item, empty)

    def _task_card(self, task: dict) -> QFrame:
        card = QFrame(); card.setObjectName("CalendarTaskCard"); border = str(task.get("member_color_hex") or CATEGORY_CARD_BORDERS.get(str(task.get("major") or ""), "#D9DCE1")); card.setStyleSheet(f"QFrame#CalendarTaskCard{{background:#FFFFFF;border:1px solid {border};border-radius:10px;}}")
        layout = QVBoxLayout(card); layout.setContentsMargins(10, 7, 10, 7); layout.setSpacing(3); top = QHBoxLayout(); top.addWidget(QLabel(f"{_project_name(self.db, task.get('event_id'))} · {task.get('major') or '미분류'}", objectName="Muted"), 1); status = QLabel(str(task.get("status") or "미착수")); foreground, background = status_color(str(task.get("status") or "미착수")); status.setStyleSheet(f"color:{foreground};background:{background};border-radius:8px;padding:1px 7px;"); top.addWidget(status); layout.addLayout(top); layout.addWidget(QLabel(str(task.get("name") or "업무"), objectName="CalendarTaskName")); return card

    def _schedule_card(self, schedule: dict) -> QFrame:
        card = QFrame(); card.setObjectName("CalendarTaskCard"); color = str(schedule.get("color_hex") or "#A7D4F0"); card.setStyleSheet(f"QFrame#CalendarTaskCard{{background:#FFFFFF;border:1px solid {color};border-radius:10px;}}")
        layout = QVBoxLayout(card); layout.setContentsMargins(10, 7, 10, 7); layout.setSpacing(3); top = QHBoxLayout(); top.addWidget(QLabel("개인 일정", objectName="Muted"), 1); member = QLabel(str(schedule.get("member_name") or "직원")); member.setStyleSheet(f"color:#344054;background:{color};border-radius:8px;padding:1px 7px;"); top.addWidget(member); layout.addLayout(top); layout.addWidget(QLabel(str(schedule.get("title") or "개인 일정"), objectName="CalendarTaskName")); return card
