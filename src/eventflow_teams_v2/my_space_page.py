from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QDate, QSize, Qt
from PySide6.QtWidgets import QAbstractItemView, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QTextEdit, QVBoxLayout, QWidget
from event_checklist.ui.widgets import DirectDateEdit

from .staff_pages import PASTEL_SPECTRUM


class ColorCascade(QWidget):
    """Overlapping circular palette used in the My Space title row."""
    def __init__(self, changed: Callable[[str], None], parent=None):
        super().__init__(parent); self.changed = changed; self.buttons: list[tuple[str, QPushButton]] = []; self.setFixedSize(470, 38)
        for color, label in PASTEL_SPECTRUM:
            button = QPushButton(self); button.setToolTip(label); button.setFixedSize(30, 30)
            button.clicked.connect(lambda _checked=False, value=color: self.changed(value)); self.buttons.append((color, button))

    def set_selected(self, selected: str) -> None:
        selected_button = None
        for index, (color, button) in enumerate(self.buttons):
            button.move(index * 23, 4)
            if index:
                button.stackUnder(self.buttons[index - 1][1])
            border = "1px solid #344054" if color == selected else "1px solid #94A3B8"
            button.setStyleSheet(f"QPushButton{{background:{color};border:{border};border-radius:15px;min-width:30px;max-width:30px;min-height:30px;max-height:30px;padding:0;}} QPushButton:hover{{border:3px solid #475467;}}")
            if color == selected:
                selected_button = button
        if selected_button:
            selected_button.raise_()


class MySpacePage(QWidget):
    """Private colour, absence scheduling and personal task-priority workspace."""
    def __init__(self, db, user_id: str, change_color: Callable[[str], None], save_schedule: Callable[[dict], bool], edit_schedule: Callable[[dict | None], None], delete_schedule: Callable[[dict], None], reorder_schedules: Callable[[list[str]], None], reorder_tasks: Callable[[list[str]], None], save_task: Callable[[str, dict], bool], parent=None):
        super().__init__(parent); self.db, self.user_id = db, user_id; self.change_color, self.save_schedule = change_color, save_schedule; self.edit_schedule, self.delete_schedule = edit_schedule, delete_schedule; self.reorder_schedules, self.reorder_tasks, self.save_task = reorder_schedules, reorder_tasks, save_task; self._suppress = False
        root = QVBoxLayout(self); root.setContentsMargins(32, 28, 32, 32); root.setSpacing(16)
        title = QHBoxLayout(); title.addWidget(QLabel("나의 공간", objectName="PageTitle")); title.addStretch(); self.palette = ColorCascade(self.change_color); title.addWidget(self.palette, 0, Qt.AlignmentFlag.AlignTop); root.addLayout(title)
        columns = QHBoxLayout(); columns.setSpacing(16); root.addLayout(columns, 1); left = self._column(); right = self._column(); self.schedule_column = right; columns.addWidget(left, 11); columns.addWidget(right, 9)
        left_layout = left.layout(); left_layout.addWidget(QLabel("내 업무 우선순위", objectName="SectionTitle")); left_layout.addWidget(QLabel("⋮⋮ 손잡이를 잡아 끌면 급한 순서로 바꿀 수 있습니다. 이 순서는 나에게만 적용됩니다.", objectName="Muted"))
        self.tasks = self._sortable_list(self._save_task_order, "MySpaceTaskList"); self.tasks.itemDoubleClicked.connect(self._show_task_detail); left_layout.addWidget(self.tasks, 1)
        right_layout = right.layout(); right_layout.addWidget(QLabel("내 일정 등록", objectName="SectionTitle")); right_layout.addWidget(QLabel("휴가, 출장, 경조사 등 자리를 비우는 기간을 등록하세요.", objectName="Muted"))
        form = QFrame(); form.setObjectName("MySpaceScheduleForm"); self.schedule_form = form; form_layout = QVBoxLayout(form); form_layout.setContentsMargins(14, 13, 14, 14); form_layout.setSpacing(8)
        dates = QHBoxLayout(); self.start = DirectDateEdit(); self.end = DirectDateEdit()
        for control in (self.start, self.end): control.setDate(QDate.currentDate())
        dates.addWidget(self._field("시작일", self.start)); dates.addWidget(self._field("종료일", self.end)); form_layout.addLayout(dates)
        self.schedule_title = QLineEdit(); self.schedule_title.setPlaceholderText("일정 제목 (예: 여름휴가)"); form_layout.addWidget(self._field("제목", self.schedule_title))
        self.schedule_content = QTextEdit(); self.schedule_content.setPlaceholderText("설명은 선택 사항입니다."); self.schedule_content.setFixedHeight(62); form_layout.addWidget(self._field("설명", self.schedule_content)); register = QPushButton("일정 등록"); register.setProperty("primary", True); register.clicked.connect(self._register_schedule); form_layout.addWidget(register, 0, Qt.AlignmentFlag.AlignRight); right_layout.addWidget(form)
        divider = QFrame(); divider.setFrameShape(QFrame.Shape.HLine); divider.setStyleSheet("color:#E2E8F0;"); right_layout.addWidget(divider); right_layout.addWidget(QLabel("등록된 내 일정", objectName="SectionTitle")); self.schedules = self._sortable_list(self._save_schedule_order, "MySpaceScheduleList"); right_layout.addWidget(self.schedules, 1)

    def _column(self) -> QFrame:
        column = QFrame(); column.setObjectName("MySpaceColumn"); column.setStyleSheet("QFrame#MySpaceColumn{background:#FFFFFF;border:1px solid #E2E8F0;border-radius:16px;}"); layout = QVBoxLayout(column); layout.setContentsMargins(18, 18, 18, 18); layout.setSpacing(10); return column

    def _field(self, label: str, widget: QWidget) -> QWidget:
        box = QWidget(); layout = QVBoxLayout(box); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(4); layout.addWidget(QLabel(label, objectName="Muted")); layout.addWidget(widget); return box

    def _sortable_list(self, callback, object_name: str) -> QListWidget:
        view = QListWidget(); view.setObjectName(object_name); view.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove); view.setDefaultDropAction(Qt.DropAction.MoveAction); view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection); view.setSpacing(8); view.setUniformItemSizes(False); view.setStyleSheet(f"QListWidget#{object_name}{{background:transparent;border:none;outline:0;}} QListWidget#{object_name}::item{{background:transparent;border:none;}}")
        view.model().rowsMoved.connect(lambda *_args: None if self._suppress else callback()); return view

    def refresh(self) -> None:
        self._suppress = True; selected = self.db.one("SELECT color_hex FROM teams_v2_staff_members WHERE user_id=?", (self.user_id,)); selected_color = str(selected["color_hex"]) if selected else "#A7D4F0"; self.palette.set_selected(selected_color); self.schedule_column.setStyleSheet(f"QFrame#MySpaceColumn{{background:#FFFFFF;border:2px solid {selected_color};border-radius:16px;}}"); self.schedules.clear(); self.tasks.clear()
        for schedule in self.db.query("SELECT * FROM teams_v2_personal_schedules WHERE member_user_id=? ORDER BY sort_order,start_date,id", (self.user_id,)):
            item = QListWidgetItem(); item.setData(Qt.ItemDataRole.UserRole, str(schedule["id"])); item.setSizeHint(QSize(0, 104)); self.schedules.addItem(item); self.schedules.setItemWidget(item, self._schedule_card(dict(schedule)))
        if not self.schedules.count(): self._empty(self.schedules, "등록한 개인 일정이 없습니다.")
        priority = {str(row["event_task_id"]): int(row["sort_order"]) for row in self.db.query("SELECT * FROM teams_v2_my_task_priorities")}
        tasks = self.db.query("""SELECT w.remote_id,w.event_id,w.work_scope,w.major,w.name,w.status,w.due_date,w.sort_order,COALESCE(e.name,CASE WHEN w.work_scope='COMPANY' THEN '프로젝트 외' ELSE '프로젝트' END) event_name FROM teams_v3_work_items w LEFT JOIN teams_v2_entity_map map ON map.entity_type='EVENT' AND map.remote_id=w.event_id LEFT JOIN events e ON e.id=map.local_id WHERE w.assigned_member_user_id=? AND w.is_removed=0 AND w.status NOT IN ('완료','해당없음') ORDER BY COALESCE(w.due_date,'9999-12-31'),w.sort_order""", (self.user_id,))
        tasks = sorted(tasks, key=lambda row: (priority.get(str(row["remote_id"]), 10**9), str(row["due_date"] or "9999-12-31"), int(row["sort_order"])))
        for task in tasks:
            item = QListWidgetItem(); item.setData(Qt.ItemDataRole.UserRole, str(task["remote_id"])); item.setSizeHint(QSize(0, 108)); self.tasks.addItem(item); self.tasks.setItemWidget(item, self._task_card(dict(task)))
        if not self.tasks.count(): self._empty(self.tasks, "현재 배정된 진행 업무가 없습니다.")
        self._suppress = False

    def _empty(self, target: QListWidget, text: str) -> None:
        item = QListWidgetItem(); item.setFlags(Qt.ItemFlag.NoItemFlags); item.setSizeHint(QSize(0, 68)); target.addItem(item); card = QFrame(); card.setStyleSheet("QFrame{background:#F8FAFC;border:1px dashed #CBD5E1;border-radius:12px;}"); row = QHBoxLayout(card); row.addWidget(QLabel(text, objectName="Muted")); target.setItemWidget(item, card)

    def _handle(self) -> QLabel:
        handle = QLabel("⋮⋮\n⋮⋮"); handle.setAlignment(Qt.AlignmentFlag.AlignCenter); handle.setToolTip("끌어 순서 변경"); handle.setFixedWidth(24); handle.setStyleSheet("color:#98A2B3;font-weight:700;"); return handle

    def _schedule_card(self, schedule: dict) -> QWidget:
        card = QFrame(); card.setObjectName("MySpaceScheduleCard"); card.setStyleSheet("QFrame#MySpaceScheduleCard{background:#FFFFFF;border:1px solid #DCE5EF;border-radius:12px;}"); row = QHBoxLayout(card); row.setContentsMargins(10, 10, 10, 10); row.setSpacing(8); row.addWidget(self._handle()); text = QVBoxLayout(); text.setSpacing(2); text.addWidget(QLabel(str(schedule["title"]), objectName="CalendarTaskName")); text.addWidget(QLabel(f"{schedule['start_date']}  ~  {schedule['end_date']}", objectName="Muted")); content = str(schedule.get("private_content") or "").strip()
        if content: detail = QLabel(content, objectName="Muted"); detail.setWordWrap(True); text.addWidget(detail)
        row.addLayout(text, 1); edit = QPushButton("수정"); edit.setProperty("compact", True); edit.clicked.connect(lambda: self.edit_schedule(schedule)); row.addWidget(edit); remove = QPushButton("삭제"); remove.setProperty("compact", True); remove.clicked.connect(lambda: self.delete_schedule(schedule)); row.addWidget(remove); return card

    def _task_card(self, task: dict) -> QWidget:
        card = QFrame(); card.setObjectName("MySpaceTaskCard"); card.setStyleSheet("QFrame#MySpaceTaskCard{background:#FFFFFF;border:1px solid #DCE5EF;border-radius:12px;} QFrame#MySpaceTaskCard:hover{border-color:#98A2B3;background:#FCFDFE;}"); row = QHBoxLayout(card); row.setContentsMargins(10, 10, 12, 10); row.setSpacing(8); row.addWidget(self._handle()); text = QVBoxLayout(); text.setSpacing(3); text.addWidget(QLabel(f"{task['event_name']} · {task['major'] or '미분류'}", objectName="Muted")); name = QLabel(str(task["name"]), objectName="CalendarTaskName"); name.setWordWrap(True); text.addWidget(name); text.addWidget(QLabel(f"{task['status']}  ·  {task['due_date'] or '마감일 미입력'}", objectName="Muted")); row.addLayout(text, 1); hint = QLabel("더블클릭하여 상세 보기", objectName="Muted"); hint.setStyleSheet("color:#98A2B3;"); row.addWidget(hint); return card

    def _show_task_detail(self, item: QListWidgetItem) -> None:
        task_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if not task_id:
            return
        task = self.db.one("SELECT name,planned_start,due_date,status,detail FROM teams_v3_work_items WHERE remote_id=?", (task_id,))
        if not task:
            return
        dialog = QDialog(self); dialog.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint); dialog.setModal(True); dialog.setMinimumWidth(620); dialog.setStyleSheet("QDialog{background:transparent;}")
        outer = QVBoxLayout(dialog); outer.setContentsMargins(0, 0, 0, 0); card = QFrame(); card.setObjectName("MyTaskDetailDialog"); card.setStyleSheet("QFrame#MyTaskDetailDialog{background:#FFFFFF;border:1px solid #DCE5EF;border-radius:16px;} QLabel#TaskDialogEyebrow{color:#667085;font-size:12px;} QLabel#TaskDialogTitle{color:#172B4D;font-size:22px;font-weight:700;} QLineEdit,QTextEdit,QComboBox,QDateEdit{background:#F8FAFC;border:1px solid #DCE5EF;border-radius:8px;padding:7px;}"); outer.addWidget(card)
        root = QVBoxLayout(card); root.setContentsMargins(24, 20, 24, 20); root.setSpacing(16); header = QHBoxLayout(); heading = QVBoxLayout(); heading.addWidget(QLabel("내 업무", objectName="TaskDialogEyebrow")); heading.addWidget(QLabel("업무 상세", objectName="TaskDialogTitle")); header.addLayout(heading); header.addStretch(); close = QPushButton("×"); close.setFixedSize(32, 32); close.setStyleSheet("QPushButton{border:none;color:#667085;font-size:24px;padding:0;} QPushButton:hover{background:#F2F4F7;border-radius:16px;}"); close.clicked.connect(dialog.reject); header.addWidget(close); root.addLayout(header)
        title = QLineEdit(str(task["name"] or "")); title.setPlaceholderText("업무 제목"); root.addWidget(self._field("업무 제목", title))
        dates = QHBoxLayout(); start = DirectDateEdit(); end = DirectDateEdit(); start.setDate(QDate.fromString(str(task["planned_start"] or QDate.currentDate().toString("yyyy-MM-dd")), "yyyy-MM-dd")); end.setDate(QDate.fromString(str(task["due_date"] or QDate.currentDate().toString("yyyy-MM-dd")), "yyyy-MM-dd")); dates.addWidget(self._field("시작일", start)); dates.addWidget(self._field("마감일", end)); root.addLayout(dates)
        status = QComboBox(); status.addItems(["미착수", "진행중", "확인요청", "완료", "보류", "해당없음"]); status.setCurrentIndex(max(0, status.findText(str(task["status"] or "미착수")))); root.addWidget(self._field("진행 상태", status)); detail = QTextEdit(str(task["detail"] or "")); detail.setMinimumHeight(150); detail.setPlaceholderText("상세 업무내용을 입력하세요."); root.addWidget(self._field("상세 업무내용", detail))
        buttons = QHBoxLayout(); buttons.addStretch(); cancel = QPushButton("취소"); save = QPushButton("수정 완료"); save.setProperty("primary", True); buttons.addWidget(cancel); buttons.addWidget(save); root.addLayout(buttons); cancel.clicked.connect(dialog.reject)
        def apply():
            if not title.text().strip() or end.date() < start.date(): return
            values = {"name": title.text().strip(), "planned_start": start.date().toString("yyyy-MM-dd"), "due_date": end.date().toString("yyyy-MM-dd"), "status": status.currentText(), "detail": detail.toPlainText().strip()}
            if self.save_task(task_id, values): dialog.accept()
        save.clicked.connect(apply); dialog.exec()

    def _register_schedule(self) -> None:
        title = self.schedule_title.text().strip()
        if not title: self.schedule_title.setFocus(); self.schedule_title.setPlaceholderText("일정 제목을 입력하세요."); return
        if self.end.date() < self.start.date(): self.end.setFocus(); return
        values = {"start_date": self.start.date().toString("yyyy-MM-dd"), "end_date": self.end.date().toString("yyyy-MM-dd"), "title": title, "content": self.schedule_content.toPlainText().strip()}
        if self.save_schedule(values): self.schedule_title.clear(); self.schedule_content.clear(); self.start.setDate(QDate.currentDate()); self.end.setDate(QDate.currentDate())

    def _save_schedule_order(self) -> None:
        values = [str(self.schedules.item(index).data(Qt.ItemDataRole.UserRole)) for index in range(self.schedules.count()) if self.schedules.item(index).data(Qt.ItemDataRole.UserRole)]
        if values: self.reorder_schedules(values)

    def _save_task_order(self) -> None:
        values = [str(self.tasks.item(index).data(Qt.ItemDataRole.UserRole)) for index in range(self.tasks.count()) if self.tasks.item(index).data(Qt.ItemDataRole.UserRole)]
        if values: self.reorder_tasks(values)
