from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QDate, QSize, Qt
from PySide6.QtWidgets import QAbstractItemView, QButtonGroup, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSizePolicy, QStackedWidget, QTextEdit, QVBoxLayout, QWidget

from event_checklist.ui.widgets import DirectDateEdit


class MySpacePage(QWidget):
    """One place for a member's checklist, project-additional, and company work."""

    def __init__(self, db, user_id: str, save_schedule: Callable[[dict, str | None], bool], delete_schedule: Callable[[dict], bool], reorder_schedules: Callable[[list[str]], None], reorder_tasks: Callable[[list[str]], None], save_task: Callable[[str, dict], bool], save_company_work: Callable[[dict, dict | None], bool], delete_company_work: Callable[[dict], bool], save_project_work: Callable[[dict, dict | None], bool], delete_project_work: Callable[[dict], bool], claim_checklist_work: Callable[[dict], bool], can_manage_company_work: bool = True, parent=None):
        super().__init__(parent)
        self.db, self.user_id = db, user_id
        self.save_schedule, self.delete_schedule, self.reorder_schedules, self.reorder_tasks = save_schedule, delete_schedule, reorder_schedules, reorder_tasks
        self.save_task, self.save_company_work, self.delete_company_work = save_task, save_company_work, delete_company_work
        self.save_project_work, self.delete_project_work, self.claim_checklist_work = save_project_work, delete_project_work, claim_checklist_work
        self.can_manage_company_work = can_manage_company_work
        self._suppress = False
        self._editing_work: dict | None = None
        self._editing_schedule: dict | None = None
        self._work_scope: str | None = None

        root = QVBoxLayout(self); root.setContentsMargins(32, 28, 32, 32); root.setSpacing(16)
        root.addWidget(QLabel("나의 공간", objectName="PageTitle"))
        columns = QHBoxLayout(); columns.setSpacing(16); root.addLayout(columns, 1)
        left, right = self._column(), self._column(); self.management_column = right; columns.addWidget(left, 11); columns.addWidget(right, 9)
        left_layout = left.layout(); left_layout.addWidget(QLabel("내 업무 우선순위", objectName="SectionTitle")); left_layout.addWidget(QLabel("⋮⋮ 손잡이를 잡아 끌면 급한 순서로 바꿀 수 있습니다. 이 순서는 나에게만 적용됩니다.", objectName="Muted"))
        self.tasks = self._sortable_list(self._save_task_order, "MySpaceTaskList"); self.tasks.itemDoubleClicked.connect(self._open_work_from_priority); left_layout.addWidget(self.tasks, 1)

        right_layout = right.layout(); right_layout.addWidget(QLabel("개인 관리", objectName="SectionTitle"))
        tabs = QHBoxLayout(); tabs.setSpacing(8); self.work_tab = self._tab_button("업무", "work"); self.schedule_tab = self._tab_button("개인 일정", "schedule"); tabs.addWidget(self.work_tab); tabs.addWidget(self.schedule_tab); tabs.addStretch(); right_layout.addLayout(tabs)
        self.management_stack = QStackedWidget()
        self.work_panel, work_form = self._form_panel("업무 등록", "체크리스트 업무, 프로젝트 추가 업무, 사내 업무를 한 곳에서 관리합니다.", compact=True)
        self.schedule_panel, schedule_form = self._form_panel("내 개인 일정", "휴가, 출장, 경조사 등 자리를 비우는 기간을 등록하세요.")
        self._build_work_form(work_form); self._build_schedule_form(schedule_form)
        self.management_stack.addWidget(self.work_panel); self.management_stack.addWidget(self.schedule_panel); right_layout.addWidget(self.management_stack, 1)
        self._select_management("work")

    def _column(self) -> QFrame:
        column = QFrame(); column.setObjectName("MySpaceColumn"); column.setStyleSheet("QFrame#MySpaceColumn{background:#FFFFFF;border:1px solid #E2E8F0;border-radius:16px;}")
        layout = QVBoxLayout(column); layout.setContentsMargins(18, 18, 18, 18); layout.setSpacing(10); return column

    def _form_panel(self, title: str, description: str, compact: bool = False) -> tuple[QWidget, QVBoxLayout]:
        panel = QWidget(); root = QVBoxLayout(panel); root.setContentsMargins(0, 2, 0, 0); root.setSpacing(10)
        root.addWidget(QLabel(title, objectName="SectionTitle")); root.addWidget(QLabel(description, objectName="Muted"))
        form = QFrame(); form.setObjectName("MySpaceManagementForm"); form.setStyleSheet("QFrame#MySpaceManagementForm{background:#F8FAFC;border:1px solid #DCE5EF;border-radius:12px;}")
        layout = QVBoxLayout(form); layout.setContentsMargins(14, 13, 14, 14); layout.setSpacing(8); root.addWidget(form)
        if compact:
            form.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
            root.addStretch(1)
        return panel, layout

    def _tab_button(self, text: str, key: str) -> QPushButton:
        button = QPushButton(text); button.setCheckable(True); button.setProperty("compact", True); button.setMinimumWidth(104); button.clicked.connect(lambda: self._select_management(key)); return button

    def _select_management(self, key: str) -> None:
        is_work = key == "work"; self.work_tab.setChecked(is_work); self.schedule_tab.setChecked(not is_work)
        self.work_tab.setStyleSheet("QPushButton{background:#EAF1F6;color:#40576B;border:1px solid #AABCCC;font-weight:700;}" if is_work else "")
        self.schedule_tab.setStyleSheet("QPushButton{background:#EAF1F6;color:#40576B;border:1px solid #AABCCC;font-weight:700;}" if not is_work else "")
        self.management_stack.setCurrentWidget(self.work_panel if is_work else self.schedule_panel)

    def _field(self, label: str, widget: QWidget) -> QWidget:
        box = QWidget(); layout = QVBoxLayout(box); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(4); layout.addWidget(QLabel(label, objectName="Muted")); layout.addWidget(widget); return box

    def _build_work_form(self, layout: QVBoxLayout) -> None:
        layout.addWidget(QLabel("1. 등록할 업무 종류를 먼저 선택하세요", objectName="SectionTitle"))
        self.scope_tabs = QFrame(); self.scope_tabs.setObjectName("WorkScopeTabs")
        self.scope_tabs.setStyleSheet("""
            QFrame#WorkScopeTabs { background:transparent; border:none; }
            QFrame#WorkScopeTabs QPushButton {
                min-height:44px; padding:0 12px; background:#FFFFFF; color:#344054;
                border:1px solid #AAB8C8; border-radius:9px; font-weight:700;
            }
            QFrame#WorkScopeTabs QPushButton:hover { background:#FFF4ED; color:#D83A0E; border:1px solid #F4511E; }
            QFrame#WorkScopeTabs QPushButton:pressed { background:#FFE7D6; }
            QFrame#WorkScopeTabs QPushButton:checked { background:#F4511E; color:#FFFFFF; border:2px solid #D83A0E; }
        """)
        scope_row = QHBoxLayout(self.scope_tabs); scope_row.setContentsMargins(0, 0, 0, 0); scope_row.setSpacing(10)
        self.scope_group = QButtonGroup(self); self.scope_group.setExclusive(True)
        self.checklist_scope = self._scope_button("체크리스트 업무", "CHECKLIST"); self.project_scope = self._scope_button("프로젝트 추가 업무", "PROJECT"); self.company_scope = self._scope_button("사내 업무", "COMPANY")
        for button in (self.checklist_scope, self.project_scope, self.company_scope):
            self.scope_group.addButton(button); scope_row.addWidget(button, 1)
        layout.addWidget(self.scope_tabs)
        self.project_picker = QComboBox(); self.project_picker.currentIndexChanged.connect(self._refresh_checklist_picker); self.project_field = self._field("프로젝트", self.project_picker); layout.addWidget(self.project_field)
        self.checklist_picker = QComboBox(); self.checklist_field = self._field("체크리스트 항목", self.checklist_picker); layout.addWidget(self.checklist_field)
        self.work_details = QWidget(); detail_layout = QVBoxLayout(self.work_details); detail_layout.setContentsMargins(0, 0, 0, 0); detail_layout.setSpacing(8)
        dates = QHBoxLayout(); self.work_start, self.work_end = DirectDateEdit(), DirectDateEdit(); self.work_start.setDate(QDate.currentDate()); self.work_end.setDate(QDate.currentDate()); dates.addWidget(self._field("시작일", self.work_start)); dates.addWidget(self._field("마감일", self.work_end)); detail_layout.addLayout(dates)
        self.work_title = QLineEdit(); self.work_title.setPlaceholderText("업무명"); detail_layout.addWidget(self._field("업무명", self.work_title))
        self.work_status = QComboBox(); self.work_status.addItems(["미착수", "진행중", "확인요청", "보류", "완료"]); detail_layout.addWidget(self._field("상태", self.work_status))
        self.work_content = QTextEdit(); self.work_content.setPlaceholderText("메모는 선택 사항입니다."); self.work_content.setFixedHeight(58); detail_layout.addWidget(self._field("메모", self.work_content)); layout.addWidget(self.work_details)
        self.work_message = QLabel("업무 종류를 선택해야 입력과 등록을 시작할 수 있습니다.", objectName="InfoGuide"); layout.addWidget(self.work_message)
        actions = QHBoxLayout(); actions.addStretch(); self.work_cancel = QPushButton("입력 비우기"); self.work_cancel.setProperty("quiet", True); self.work_cancel.clicked.connect(self._clear_work_form); self.work_submit = QPushButton("사내 업무 등록"); self.work_submit.setProperty("primary", True); self.work_submit.clicked.connect(self._save_work_form); actions.addWidget(self.work_cancel); actions.addWidget(self.work_submit); layout.addLayout(actions)
        self._set_work_scope(None)

    def _scope_button(self, text: str, scope: str) -> QPushButton:
        button = QPushButton(text); button.setCheckable(True); button.clicked.connect(lambda: self._set_work_scope(scope)); return button

    def _set_work_scope(self, scope: str | None) -> None:
        self._work_scope = scope
        if scope is None:
            self.scope_group.setExclusive(False)
        for button, key in ((self.checklist_scope, "CHECKLIST"), (self.project_scope, "PROJECT"), (self.company_scope, "COMPANY")):
            button.setChecked(key == scope)
        self.scope_group.setExclusive(True)
        needs_project = scope in {"CHECKLIST", "PROJECT"}; self.project_field.setVisible(needs_project); self.checklist_field.setVisible(scope == "CHECKLIST"); self.work_details.setVisible(scope != "CHECKLIST")
        self.work_submit.setEnabled(scope is not None)
        if scope is None: self.work_details.hide(); self.work_message.setText("업무 종류를 선택해야 입력과 등록을 시작할 수 있습니다."); self.work_submit.setText("업무 종류를 선택하세요")
        elif scope == "CHECKLIST": self.work_message.setText("프로젝트의 공식 체크리스트 항목을 선택해 내 담당 업무로 연결합니다. 새 업무는 만들어지지 않습니다."); self.work_submit.setText("체크리스트 업무 연결")
        elif scope == "PROJECT": self.work_message.setText("체크리스트에 없는 개인 추가 업무입니다. 선택한 프로젝트에만 연결되며 본인만 수정·삭제할 수 있습니다."); self.work_submit.setText("프로젝트 추가 업무 등록")
        else: self.work_message.setText("프로젝트와 무관한 업무입니다. 등록한 본인에게만 연결되며 전체 달력에 표시됩니다."); self.work_submit.setText("사내 업무 등록")

    def _build_schedule_form(self, layout: QVBoxLayout) -> None:
        dates = QHBoxLayout(); self.schedule_start, self.schedule_end = DirectDateEdit(), DirectDateEdit(); self.schedule_start.setDate(QDate.currentDate()); self.schedule_end.setDate(QDate.currentDate()); dates.addWidget(self._field("시작일", self.schedule_start)); dates.addWidget(self._field("종료일", self.schedule_end)); layout.addLayout(dates)
        self.schedule_title = QLineEdit(); self.schedule_title.setPlaceholderText("일정 제목 (예: 여름휴가)"); layout.addWidget(self._field("제목", self.schedule_title)); self.schedule_content = QTextEdit(); self.schedule_content.setPlaceholderText("설명은 선택 사항입니다."); self.schedule_content.setFixedHeight(58); layout.addWidget(self._field("설명", self.schedule_content))
        self.schedule_message = QLabel("제목은 회사 직원에게 보이며, 내용은 작성자와 관리자만 볼 수 있습니다.", objectName="InfoGuide"); layout.addWidget(self.schedule_message)
        actions = QHBoxLayout(); actions.addStretch(); self.schedule_cancel = QPushButton("입력 비우기"); self.schedule_cancel.setProperty("quiet", True); self.schedule_cancel.clicked.connect(self._clear_schedule_form); self.schedule_submit = QPushButton("일정 등록"); self.schedule_submit.setProperty("primary", True); self.schedule_submit.clicked.connect(self._save_schedule_form); actions.addWidget(self.schedule_cancel); actions.addWidget(self.schedule_submit); layout.addLayout(actions)
        layout.addWidget(QLabel("등록된 개인 일정", objectName="SectionTitle")); self.schedules = self._sortable_list(self._save_schedule_order, "MySpaceScheduleList"); layout.addWidget(self.schedules, 1)

    def _sortable_list(self, callback, object_name: str) -> QListWidget:
        view = QListWidget(); view.setObjectName(object_name); view.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove); view.setDefaultDropAction(Qt.DropAction.MoveAction); view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection); view.setSpacing(8); view.setUniformItemSizes(False); view.setStyleSheet(f"QListWidget#{object_name}{{background:transparent;border:none;outline:0;}} QListWidget#{object_name}::item{{background:transparent;border:none;}}")
        view.model().rowsMoved.connect(lambda *_args: None if self._suppress else callback()); return view

    def refresh(self) -> None:
        self._suppress = True
        color = self.db.one("SELECT color_hex FROM teams_v2_staff_members WHERE user_id=?", (self.user_id,)); selected_color = str(color["color_hex"]) if color else "#A7D4F0"; self.management_column.setStyleSheet(f"QFrame#MySpaceColumn{{background:#FFFFFF;border:2px solid {selected_color};border-radius:16px;}}")
        self._refresh_project_picker(); self.schedules.clear(); self.tasks.clear()
        for schedule in self.db.query("SELECT * FROM teams_v2_personal_schedules WHERE member_user_id=? ORDER BY sort_order,start_date,id", (self.user_id,)):
            item = QListWidgetItem(); item.setData(Qt.ItemDataRole.UserRole, str(schedule["id"])); item.setSizeHint(QSize(0, 104)); self.schedules.addItem(item); self.schedules.setItemWidget(item, self._schedule_card(dict(schedule)))
        if not self.schedules.count(): self._empty(self.schedules, "등록한 개인 일정이 없습니다.")
        priority = {str(row["event_task_id"]): int(row["sort_order"]) for row in self.db.query("SELECT * FROM teams_v2_my_task_priorities")}
        tasks = self.db.query("""SELECT w.remote_id,w.event_id,w.work_scope,w.work_kind,w.major,w.name,w.status,w.due_date,w.sort_order,w.created_by,w.assigned_member_user_id,COALESCE(e.name,'프로젝트') event_name
          FROM teams_v3_work_items w LEFT JOIN teams_v2_entity_map map ON map.entity_type='EVENT' AND map.remote_id=w.event_id LEFT JOIN events e ON e.id=map.local_id
          WHERE w.assigned_member_user_id=? AND w.is_removed=0 AND w.status NOT IN ('완료','해당없음') ORDER BY COALESCE(w.due_date,'9999-12-31'),w.sort_order""", (self.user_id,))
        tasks = sorted(tasks, key=lambda row: (priority.get(str(row["remote_id"]), 10**9), str(row["due_date"] or "9999-12-31"), int(row["sort_order"])))
        for task in tasks:
            item = QListWidgetItem(); item.setData(Qt.ItemDataRole.UserRole, str(task["remote_id"])); item.setSizeHint(QSize(0, 108)); self.tasks.addItem(item); self.tasks.setItemWidget(item, self._task_card(dict(task)))
        if not self.tasks.count(): self._empty(self.tasks, "현재 등록·배정된 업무가 없습니다.")
        self._suppress = False

    def _refresh_project_picker(self) -> None:
        current = self.project_picker.currentData(); self.project_picker.blockSignals(True); self.project_picker.clear(); self.project_picker.addItem("프로젝트를 선택하세요", "")
        events = self.db.query("SELECT e.id,e.name FROM events e JOIN teams_v2_entity_map map ON map.entity_type='EVENT' AND map.local_id=e.id ORDER BY e.start_date DESC,e.name")
        for event in events:
            remote = self.db.one("SELECT remote_id FROM teams_v2_entity_map WHERE entity_type='EVENT' AND local_id=?", (event["id"],)); self.project_picker.addItem(str(event["name"] or "프로젝트"), str(remote["remote_id"]) if remote else "")
        index = self.project_picker.findData(current); self.project_picker.setCurrentIndex(index if index >= 0 else 0); self.project_picker.blockSignals(False); self._refresh_checklist_picker()

    def _refresh_checklist_picker(self) -> None:
        event_id = str(self.project_picker.currentData() or ""); self.checklist_picker.clear(); self.checklist_picker.addItem("체크리스트 항목을 선택하세요", "")
        if not event_id: return
        rows = self.db.query("SELECT remote_id,name,major,status,assigned_member_user_id,row_version FROM teams_v3_work_items WHERE event_id=? AND work_scope='PROJECT' AND work_kind='CHECKLIST' AND is_removed=0 AND status NOT IN ('완료','해당없음') ORDER BY sort_order,name", (event_id,))
        for row in rows:
            assigned = str(row["assigned_member_user_id"] or ""); suffix = " · 내 업무" if assigned == self.user_id else " · 다른 직원 담당" if assigned else ""
            self.checklist_picker.addItem(f"{row['major']} · {row['name']}{suffix}", {"id": str(row["remote_id"]), "row_version": int(row["row_version"] or 0), "assigned": assigned})

    def _empty(self, target: QListWidget, text: str) -> None:
        item = QListWidgetItem(); item.setFlags(Qt.ItemFlag.NoItemFlags); item.setSizeHint(QSize(0, 68)); target.addItem(item); card = QFrame(); card.setStyleSheet("QFrame{background:#F8FAFC;border:1px dashed #CBD5E1;border-radius:12px;}"); row = QHBoxLayout(card); row.addWidget(QLabel(text, objectName="Muted")); target.setItemWidget(item, card)

    def _handle(self) -> QLabel:
        handle = QLabel("⋮⋮\n⋮⋮"); handle.setAlignment(Qt.AlignmentFlag.AlignCenter); handle.setToolTip("끌어 순서 변경"); handle.setFixedWidth(24); handle.setStyleSheet("color:#98A2B3;font-weight:700;"); return handle

    def _schedule_card(self, schedule: dict) -> QWidget:
        card = QFrame(); card.setStyleSheet("QFrame{background:#FFFFFF;border:1px solid #DCE5EF;border-radius:12px;}"); row = QHBoxLayout(card); row.setContentsMargins(10, 10, 10, 10); row.setSpacing(8); row.addWidget(self._handle()); text = QVBoxLayout(); text.addWidget(QLabel(str(schedule["title"]), objectName="CalendarTaskName")); text.addWidget(QLabel(f"{schedule['start_date']}  ~  {schedule['end_date']}", objectName="Muted")); row.addLayout(text, 1)
        edit = QPushButton("수정"); edit.setProperty("compact", True); edit.clicked.connect(lambda: self._load_schedule_form(schedule)); remove = QPushButton("삭제"); remove.setProperty("compact", True); remove.clicked.connect(lambda: self._confirm_delete(remove, schedule, self.delete_schedule)); row.addWidget(edit); row.addWidget(remove); return card

    def _task_card(self, task: dict) -> QWidget:
        card = QFrame(); card.setStyleSheet("QFrame{background:#FFFFFF;border:1px solid #DCE5EF;border-radius:12px;} QFrame:hover{border-color:#98A2B3;background:#FCFDFE;}"); row = QHBoxLayout(card); row.setContentsMargins(10, 10, 12, 10); row.setSpacing(8); row.addWidget(self._handle()); text = QVBoxLayout(); text.setSpacing(3)
        kind = str(task.get("work_kind") or ("COMPANY_SELF" if task.get("work_scope")=="COMPANY" else "CHECKLIST")); label = "사내 업무" if kind == "COMPANY_SELF" else f"{task['event_name']} · 프로젝트 추가 업무" if kind == "PROJECT_ADDITIONAL" else f"{task['event_name']} · 체크리스트"
        text.addWidget(QLabel(label, objectName="Muted")); name = QLabel(str(task["name"]), objectName="CalendarTaskName"); name.setWordWrap(True); text.addWidget(name); text.addWidget(QLabel(f"{task['status']}  ·  {task['due_date'] or '마감일 미입력'}", objectName="Muted")); row.addLayout(text, 1)
        own = kind in {"COMPANY_SELF", "PROJECT_ADDITIONAL"} and str(task.get("created_by") or self.user_id) == self.user_id
        if own:
            edit = QPushButton("수정"); edit.setProperty("compact", True); edit.clicked.connect(lambda: self._load_own_work_form(task)); remove = QPushButton("삭제"); remove.setProperty("compact", True); remove.clicked.connect(lambda: self._confirm_delete(remove, task, self._delete_own_work)); row.addWidget(edit); row.addWidget(remove)
        else: row.addWidget(QLabel("더블클릭하여 상세 보기", objectName="Muted"))
        return card

    def _load_own_work_form(self, task: dict) -> None:
        kind = str(task.get("work_kind") or ""); self._editing_work = task; self._select_management("work"); self._set_work_scope("COMPANY" if kind == "COMPANY_SELF" else "PROJECT")
        if kind == "PROJECT_ADDITIONAL": self.project_picker.setCurrentIndex(max(0, self.project_picker.findData(str(task.get("event_id") or ""))))
        self.work_title.setText(str(task.get("name") or "")); self.work_status.setCurrentText(str(task.get("status") or "미착수")); self.work_start.setDate(QDate.fromString(str(task.get("planned_start") or QDate.currentDate().toString("yyyy-MM-dd")), "yyyy-MM-dd")); self.work_end.setDate(QDate.fromString(str(task.get("due_date") or QDate.currentDate().toString("yyyy-MM-dd")), "yyyy-MM-dd")); self.work_content.setPlainText(str(task.get("detail") or "")); self.work_cancel.setText("수정 취소"); self.work_submit.setText("수정 저장")

    def _clear_work_form(self) -> None:
        self._editing_work = None; self.work_title.clear(); self.work_status.setCurrentText("미착수"); self.work_start.setDate(QDate.currentDate()); self.work_end.setDate(QDate.currentDate()); self.work_content.clear(); self.work_cancel.setText("입력 비우기"); self._set_work_scope(None)

    def _save_work_form(self) -> None:
        if self._work_scope is None:
            self.work_message.setText("먼저 등록할 업무 종류를 선택하세요.")
            return
        if self._work_scope == "CHECKLIST":
            selected = self.checklist_picker.currentData()
            if not isinstance(selected, dict) or not selected.get("id"): self.work_message.setText("연결할 체크리스트 항목을 선택하세요."); return
            if selected.get("assigned") and selected["assigned"] != self.user_id: self.work_message.setText("이 항목은 이미 다른 직원에게 배정되어 있습니다."); return
            if self.claim_checklist_work(selected): self.work_message.setText("체크리스트 업무를 내 업무에 연결했습니다.")
            return
        if not self.work_title.text().strip(): self.work_message.setText("업무명을 입력하세요."); self.work_title.setFocus(); return
        if self.work_end.date() < self.work_start.date(): self.work_message.setText("마감일은 시작일보다 빠를 수 없습니다."); self.work_end.setFocus(); return
        values = {"name": self.work_title.text().strip(), "status": self.work_status.currentText(), "planned_start": self.work_start.date().toString("yyyy-MM-dd"), "due_date": self.work_end.date().toString("yyyy-MM-dd"), "detail": self.work_content.toPlainText().strip()}
        if self._work_scope == "PROJECT":
            event_id = str(self.project_picker.currentData() or "")
            if not event_id: self.work_message.setText("프로젝트를 선택하세요."); return
            values["event_id"] = event_id
            saved = self.save_project_work(values, self._editing_work)
        else: saved = self.save_company_work(values, self._editing_work)
        if saved: self._clear_work_form()

    def _delete_own_work(self, task: dict) -> bool:
        return self.delete_project_work(task) if str(task.get("work_kind") or "") == "PROJECT_ADDITIONAL" else self.delete_company_work(task)

    def _open_work_from_priority(self, item: QListWidgetItem) -> None:
        task_id = str(item.data(Qt.ItemDataRole.UserRole) or ""); task = self.db.one("SELECT * FROM teams_v3_work_items WHERE remote_id=?", (task_id,))
        if task and str(task["work_kind"] or "") in {"COMPANY_SELF", "PROJECT_ADDITIONAL"}: self._load_own_work_form(dict(task))

    def _load_schedule_form(self, schedule: dict) -> None:
        self._editing_schedule = schedule; self._select_management("schedule"); self.schedule_title.setText(str(schedule.get("title") or "")); self.schedule_start.setDate(QDate.fromString(str(schedule.get("start_date") or QDate.currentDate().toString("yyyy-MM-dd")), "yyyy-MM-dd")); self.schedule_end.setDate(QDate.fromString(str(schedule.get("end_date") or QDate.currentDate().toString("yyyy-MM-dd")), "yyyy-MM-dd")); self.schedule_content.setPlainText(str(schedule.get("private_content") or "")); self.schedule_submit.setText("일정 수정 저장"); self.schedule_cancel.setText("수정 취소")

    def _clear_schedule_form(self) -> None:
        self._editing_schedule = None; self.schedule_title.clear(); self.schedule_start.setDate(QDate.currentDate()); self.schedule_end.setDate(QDate.currentDate()); self.schedule_content.clear(); self.schedule_submit.setText("일정 등록"); self.schedule_cancel.setText("입력 비우기"); self.schedule_message.setText("제목은 회사 직원에게 보이며, 내용은 작성자와 관리자만 볼 수 있습니다.")

    def _save_schedule_form(self) -> None:
        title = self.schedule_title.text().strip()
        if not title: self.schedule_message.setText("일정 제목을 입력하세요."); self.schedule_title.setFocus(); return
        if self.schedule_end.date() < self.schedule_start.date(): self.schedule_message.setText("종료일은 시작일보다 빠를 수 없습니다."); self.schedule_end.setFocus(); return
        values = {"start_date": self.schedule_start.date().toString("yyyy-MM-dd"), "end_date": self.schedule_end.date().toString("yyyy-MM-dd"), "title": title, "content": self.schedule_content.toPlainText().strip()}; schedule_id = str(self._editing_schedule.get("id") or "") if self._editing_schedule else None
        if self.save_schedule(values, schedule_id): self._clear_schedule_form()

    @staticmethod
    def _confirm_delete(button: QPushButton, item: dict, callback: Callable[[dict], bool]) -> None:
        if button.text() != "정말 삭제": button.setText("정말 삭제"); button.setProperty("danger", True); return
        callback(item)

    def _save_schedule_order(self) -> None:
        values = [str(self.schedules.item(index).data(Qt.ItemDataRole.UserRole)) for index in range(self.schedules.count()) if self.schedules.item(index).data(Qt.ItemDataRole.UserRole)]
        if values: self.reorder_schedules(values)

    def _save_task_order(self) -> None:
        values = [str(self.tasks.item(index).data(Qt.ItemDataRole.UserRole)) for index in range(self.tasks.count()) if self.tasks.item(index).data(Qt.ItemDataRole.UserRole)]
        if values: self.reorder_tasks(values)
