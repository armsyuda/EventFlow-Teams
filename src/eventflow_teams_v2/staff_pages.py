from __future__ import annotations

from datetime import date
from typing import Callable

import json

from PySide6.QtCore import QDate, QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QTextEdit, QVBoxLayout, QWidget, QLineEdit
from event_checklist.ui.widgets import DirectDateEdit
from eventflow_teams_v2.work_card import TASK_MIME, WorkCard, WorkDetailDialog


ROLE_LABELS = {"OWNER": "대표", "ADMIN": "관리자", "PM": "PM", "MEMBER": "직원", "VIEWER": "조회자"}


class StaffWorkCard(QFrame):
    def __init__(self, member, parent=None):
        super().__init__(parent); self.member = member; self.setObjectName("StaffWorkCard")


class StaffTaskLane(QWidget):
    def __init__(self, member_id: str, can_move: bool, on_move, parent=None):
        super().__init__(parent); self.member_id=member_id; self.can_move=can_move; self.on_move=on_move; self.cards=[]
        self.setAcceptDrops(can_move); self.setObjectName("StaffTaskLane"); self.setStyleSheet("QWidget#StaffTaskLane{background:transparent;border:2px solid transparent;border-radius:10px;}")
        self.box=QVBoxLayout(self); self.box.setContentsMargins(2,2,2,2); self.box.setSpacing(10); self.box.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.indicator=QFrame(); self.indicator.setFixedHeight(4); self.indicator.setStyleSheet("background:#F4511E;border-radius:2px;"); self.indicator.hide(); self.indicator_position=1; self._indicator_animation=None

    def add_task(self, card: QWidget) -> None:
        self.cards.append(card); self.box.addWidget(card)

    def dragEnterEvent(self,event):  # noqa: N802
        if not self.can_move or not event.mimeData().hasFormat(TASK_MIME): return
        try: payload=json.loads(bytes(event.mimeData().data(TASK_MIME)).decode("utf-8"))
        except (ValueError,UnicodeDecodeError): event.ignore(); return
        if payload.get("work_kind")=="COMPANY_SELF" and str(payload.get("member_user_id"))!=self.member_id:
            self.setToolTip("사내 업무는 다른 직원에게 이관할 수 없습니다."); event.ignore(); return
        self.setStyleSheet("QWidget#StaffTaskLane{background:#FFF8F3;border:2px dashed #F4511E;border-radius:10px;}"); event.acceptProposedAction()

    def dragMoveEvent(self,event):  # noqa: N802
        if self.can_move and event.mimeData().hasFormat(TASK_MIME):
            try: payload=json.loads(bytes(event.mimeData().data(TASK_MIME)).decode("utf-8"))
            except (ValueError,UnicodeDecodeError): event.ignore(); return
            position=self._drop_position(event.position().y(),str(payload.get("task_id") or ""))
            if position!=self.indicator_position or not self.indicator.isVisible():
                self.box.removeWidget(self.indicator); self.box.insertWidget(position-1,self.indicator); self.indicator_position=position; self.indicator.show()
                self._indicator_animation=QPropertyAnimation(self.indicator,b"maximumHeight",self); self._indicator_animation.setDuration(150); self._indicator_animation.setStartValue(1); self._indicator_animation.setEndValue(10); self._indicator_animation.setEasingCurve(QEasingCurve.Type.OutCubic); self._indicator_animation.start()
            event.acceptProposedAction()

    def dragLeaveEvent(self,event):  # noqa: N802
        self.indicator.hide(); self.box.removeWidget(self.indicator); self.setStyleSheet("QWidget#StaffTaskLane{background:transparent;border:2px solid transparent;border-radius:10px;}"); super().dragLeaveEvent(event)

    def dropEvent(self,event):  # noqa: N802
        self.setStyleSheet("QWidget#StaffTaskLane{background:transparent;border:2px solid transparent;border-radius:10px;}")
        try: payload=json.loads(bytes(event.mimeData().data(TASK_MIME)).decode("utf-8"))
        except (ValueError,UnicodeDecodeError): event.ignore(); return
        if payload.get("source")!="staff": event.ignore(); return
        if payload.get("work_kind")=="COMPANY_SELF" and str(payload.get("member_user_id"))!=self.member_id: event.ignore(); return
        position=self._drop_position(event.position().y(),str(payload.get("task_id") or "")); self.indicator.hide(); self.box.removeWidget(self.indicator)
        if self.on_move(str(payload.get("task_id") or ""),self.member_id,position): event.acceptProposedAction()
        else: event.ignore()

    def _drop_position(self,y: float,dragged_task_id: str) -> int:
        candidates=[card for card in self.cards if str(getattr(card,"task",{}).get("id") or "")!=dragged_task_id]
        for index,card in enumerate(candidates):
            if y<card.geometry().center().y(): return index+1
        return len(candidates)+1


class StaffHorizontalScroll(QScrollArea):
    """Use the wheel to browse the staff-card strip without requiring Shift."""

    def wheelEvent(self, event):  # noqa: N802
        horizontal = self.horizontalScrollBar()
        if horizontal.maximum() > horizontal.minimum() and event.angleDelta().y():
            horizontal.setValue(horizontal.value() - event.angleDelta().y())
            event.accept(); return
        super().wheelEvent(event)


class EmployeeWorkPage(QWidget):
    """Company-visible checklist, project-additional, and company work board."""

    def __init__(self, db, open_task: Callable[[str], None], current_user_id: str = "", can_transfer: bool = False, on_transfer: Callable[[str, str, int], bool] | None = None, on_refresh_staff: Callable[[], None] | None = None, parent=None):
        super().__init__(parent); self.db = db; self.open_task = open_task; self.current_user_id = current_user_id; self.can_transfer = can_transfer; self.on_transfer = on_transfer; self.on_refresh_staff = on_refresh_staff; self.priorities: dict[str,dict[str,int]]={}
        root = QVBoxLayout(self); root.setContentsMargins(32, 28, 32, 32); root.setSpacing(12)
        root.addWidget(QLabel("직원업무", objectName="PageTitle"))
        root.addWidget(QLabel("직원별 체크리스트·프로젝트 추가 업무·사내 업무를 확인합니다. 휴가·출장 같은 개인 일정은 전체 달력에서 확인합니다.", objectName="PageDescription"))
        filters = QHBoxLayout(); filters.addWidget(QLabel("업무 범위")); self.project_filter = QComboBox(); self.project_filter.currentIndexChanged.connect(self.refresh); filters.addWidget(self.project_filter); filters.addStretch(); self.refresh_button = QPushButton("직원 목록 새로고침"); self.refresh_button.setProperty("quiet", True); self.refresh_button.clicked.connect(self._refresh_staff); filters.addWidget(self.refresh_button); root.addLayout(filters)
        self.scroll = StaffHorizontalScroll(); self.scroll.setObjectName("StaffWorkScroll"); self.scroll.setWidgetResizable(True); self.scroll.setFrameShape(QFrame.Shape.NoFrame); self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn); self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea#StaffWorkScroll{background:#F7F8FA;border:1px solid #E5E7EB;border-radius:12px;} QScrollArea#StaffWorkScroll > QWidget > QWidget{background:#F7F8FA;} QScrollBar:horizontal{height:18px;background:#E8EDF3;border-radius:9px;margin:5px 16px 7px 16px;} QScrollBar::handle:horizontal{min-width:110px;background:#98A2B3;border-radius:8px;} QScrollBar::handle:horizontal:hover{background:#667085;} QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal{width:0px;}")
        self.container = QWidget(); self.container.setObjectName("StaffWorkCanvas"); self.container.setStyleSheet("QWidget#StaffWorkCanvas{background:#F7F8FA;}")
        self.cards = QHBoxLayout(self.container); self.cards.setContentsMargins(16, 16, 16, 16); self.cards.setSpacing(16); self.cards.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.container); root.addWidget(self.scroll, 1)

    def refresh(self) -> None:
        previous_project = self.project_filter.currentData(); self.project_filter.blockSignals(True); self.project_filter.clear(); self.project_filter.addItem("전체 업무", ""); self.project_filter.addItem("사내 업무", "__COMPANY__")
        for event in self.db.query("SELECT remote_id,name FROM teams_v2_entity_map map JOIN events e ON e.id=map.local_id WHERE map.entity_type='EVENT' ORDER BY e.name"):
            self.project_filter.addItem(str(event["name"]), str(event["remote_id"]))
        self.project_filter.setCurrentIndex(max(0, self.project_filter.findData(previous_project))); self.project_filter.blockSignals(False)
        while self.cards.count():
            item = self.cards.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        staff = self.db.query("""SELECT * FROM teams_v2_staff_members WHERE status='ACTIVE'
            ORDER BY CASE role
                WHEN 'ADMIN' THEN 0
                WHEN 'PM' THEN 1
                WHEN 'MEMBER' THEN 2
                WHEN 'VIEWER' THEN 3
                WHEN 'OWNER' THEN 4
                ELSE 5
            END, display_name, user_id""")
        for member in staff:
            card = StaffWorkCard(member); card.setFixedWidth(300); card.setFixedHeight(690); card.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            card.setStyleSheet(f"QFrame#StaffWorkCard{{background:#fff;border:1px solid {member['color_hex']};border-top:6px solid {member['color_hex']};border-radius:12px;}}")
            layout = QVBoxLayout(card); layout.setContentsMargins(16, 13, 16, 16); layout.setSpacing(9)
            display_name = str(member["display_name"] or "").strip()
            if not display_name or display_name == "직원": display_name = f"직원 {str(member['user_id'])[:6]}"
            layout.addWidget(QLabel(display_name, objectName="SectionTitle"))
            title = str(member["job_title"] or ROLE_LABELS.get(str(member["role"]), "직원")); layout.addWidget(QLabel(title, objectName="Muted"))
            active = self._member_work(str(member["user_id"]), completed=False)
            completed = self._member_work(str(member["user_id"]), completed=True)
            layout.addWidget(QLabel(f"진행 업무 {len(active)}건", objectName="Muted"))
            task_scroll = QScrollArea(); task_scroll.setObjectName("StaffCardTaskScroll"); task_scroll.setWidgetResizable(True); task_scroll.setFrameShape(QFrame.Shape.NoFrame); task_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff); task_scroll.setStyleSheet("QScrollArea#StaffCardTaskScroll{background:transparent;border:none;} QScrollArea#StaffCardTaskScroll > QWidget > QWidget{background:transparent;} QScrollBar:vertical{width:10px;background:transparent;} QScrollBar::handle:vertical{min-height:36px;background:#CBD5E1;border-radius:5px;} QScrollBar::handle:vertical:hover{background:#94A3B8;}")
            task_canvas = StaffTaskLane(str(member["user_id"]),self.can_transfer,self.on_transfer); task_layout=task_canvas.box
            for task in active: task_canvas.add_task(self._task_card(task,str(member["user_id"])))
            if not active: task_layout.addWidget(QLabel("진행 중인 업무가 없습니다.", objectName="EmptyState"))
            if completed:
                toggle = QPushButton(f"완료 항목 보기 · {len(completed)}건"); toggle.setProperty("quiet", True); task_layout.addWidget(toggle)
                done_box = QWidget(); done_layout = QVBoxLayout(done_box); done_layout.setContentsMargins(0, 0, 0, 0); done_layout.setSpacing(5)
                for task in completed: done_layout.addWidget(self._task_card(task,str(member["user_id"]),draggable=False))
                done_box.hide(); toggle.clicked.connect(lambda checked=False, box=done_box, button=toggle, count=len(completed): (box.setVisible(not box.isVisible()), button.setText(("완료 항목 숨기기" if box.isVisible() else "완료 항목 보기") + f" · {count}건")))
                task_layout.addWidget(done_box)
            task_layout.addStretch(); task_scroll.setWidget(task_canvas); layout.addWidget(task_scroll, 1)
            self.cards.addWidget(card)
        if not staff:
            empty = QFrame(); empty.setObjectName("StaffWorkEmpty"); empty.setMinimumWidth(330)
            empty.setStyleSheet("QFrame#StaffWorkEmpty{background:#FFFFFF;border:1px dashed #CBD5E1;border-radius:12px;}")
            empty_layout = QVBoxLayout(empty); empty_layout.setContentsMargins(22, 22, 22, 22)
            empty_layout.addWidget(QLabel("직원 정보를 불러오는 중입니다.", objectName="SectionTitle"))
            empty_layout.addWidget(QLabel("서버 동기화가 끝나면 직원별 업무 카드가 표시됩니다.", objectName="Muted"))
            self.cards.addWidget(empty)
        # widgetResizable 상태에서도 카드 캔버스가 0px로 축소되지 않도록
        # 최소 폭/높이를 명시한다. 폭은 직원 카드 수만큼 넓어져 하단 막대로
        # 이동하고, 높이는 직원 카드의 업무 세로 스크롤 영역을 보장한다.
        self.cards.activate()
        card_count = max(1, len(staff))
        self.container.setMinimumWidth(card_count * 300 + (card_count + 1) * 16)
        self.container.setMinimumHeight(722)

    def _refresh_staff(self) -> None:
        if not self.on_refresh_staff:
            self.refresh()
            return
        self.refresh_button.setEnabled(False); self.refresh_button.setText("직원 확인 중…")
        self.on_refresh_staff()

    def staff_refresh_finished(self) -> None:
        self.refresh_button.setEnabled(True); self.refresh_button.setText("직원 목록 새로고침")
        self.refresh()

    def set_priorities(self, values: list[dict]) -> None:
        self.priorities={}
        for row in values:
            self.priorities.setdefault(str(row.get("member_user_id") or ""),{})[str(row.get("event_task_id") or "")]=int(row.get("sort_order") or 0)

    def _task_card(self, task, member_id: str, draggable: bool=True):
        # A company-work item is self-owned by policy.  Even managers must
        # not drag it onto another employee's card as a forced assignment.
        movable=self.can_transfer and draggable
        payload={"source":"staff","task_id":str(task["id"]),"member_user_id":member_id,"work_kind":str(task["work_kind"] or "CHECKLIST")} if movable else None
        return WorkCard(dict(task),open_detail=self._show_task_detail,drag_payload=payload,show_handle=movable)

    def _show_task_detail(self, task: dict) -> None:
        kind=str(task.get("work_kind") or "CHECKLIST")
        WorkDetailDialog(task,on_open=(lambda:self.open_task(str(task.get("id") or ""))) if kind=="CHECKLIST" else None,parent=self).exec()

    def _member_work(self, user_id: str, *, completed: bool):
        """Prefer the V3 mirror so a colleague's cross-project work is visible."""
        try:
            condition = "w.status='완료'" if completed else "w.status NOT IN ('완료','해당없음')"
            scope = self.project_filter.currentData() if hasattr(self, "project_filter") else ""
            if scope == "__COMPANY__": filter_sql, args = " AND w.work_scope='COMPANY'", (user_id,)
            elif scope: filter_sql, args = " AND w.event_id=?", (user_id, scope)
            else: filter_sql, args = "", (user_id,)
            rows=self.db.query(f"""SELECT w.remote_id id,w.name,w.major,w.detail,w.status,w.planned_start,w.due_date,w.work_scope,w.work_kind,w.row_version,w.assigned_member_user_id,
                COALESCE(e.name,CASE WHEN w.work_scope='COMPANY' THEN '사내 업무' ELSE '프로젝트' END) event_name,
                COALESCE(member.display_name,'담당자 미지정') assignee_name
                FROM teams_v3_work_items w LEFT JOIN teams_v2_entity_map map ON map.entity_type='EVENT' AND map.remote_id=w.event_id
                LEFT JOIN events e ON e.id=map.local_id LEFT JOIN teams_v2_staff_members member ON member.user_id=w.assigned_member_user_id WHERE w.assigned_member_user_id=? AND w.is_removed=0 AND {condition}{filter_sql}
                ORDER BY COALESCE(w.due_date,'9999-12-31'),w.sort_order""", args)
            priority=self.priorities.get(user_id,{})
            return sorted(rows,key=lambda row:(priority.get(str(row["id"]),10**9),str(row["due_date"] or "9999-12-31"),str(row["id"])))
        except Exception:
            condition = "t.status='완료'" if completed else "t.status NOT IN ('완료','해당없음')"
            return self.db.query(f"""SELECT t.id,t.name,t.major,t.detail,t.status,t.planned_start,t.due_date,'PROJECT' work_scope,'CHECKLIST' work_kind,e.name event_name,t.assigned_member_user_id,
                0 row_version,COALESCE(member.display_name,'담당자 미지정') assignee_name FROM event_tasks t
                JOIN events e ON e.id=t.event_id LEFT JOIN teams_v2_staff_members member ON member.user_id=t.assigned_member_user_id WHERE t.assigned_member_user_id=? AND t.is_removed=0 AND {condition}
                ORDER BY COALESCE(t.due_date,'9999-12-31'),t.sort_order""", (user_id,))


class PersonalScheduleDialog(QDialog):
    def __init__(self, schedule: dict | None, parent=None):
        super().__init__(parent); self.schedule = schedule or {}; self.setWindowTitle("개인 일정"); self.setMinimumWidth(440)
        root = QVBoxLayout(self); form = QFormLayout()
        self.start = DirectDateEdit(); self.end = DirectDateEdit()
        for widget, key in ((self.start, "start_date"), (self.end, "end_date")):
            widget.setDate(QDate.fromString(str(self.schedule.get(key) or date.today().isoformat()), "yyyy-MM-dd"))
        self.title = QLineEdit(str(self.schedule.get("title") or "")); self.title.setMaxLength(120)
        self.content = QTextEdit(str(self.schedule.get("private_content") or "")); self.content.setMaximumHeight(130)
        form.addRow("시작일", self.start); form.addRow("종료일", self.end); form.addRow("제목", self.title); form.addRow("내용 (선택)", self.content); root.addLayout(form)
        self.message = QLabel("제목은 회사 직원에게 보이며, 내용은 작성자와 관리자만 볼 수 있습니다.", objectName="InfoGuide"); root.addWidget(self.message)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel); buttons.accepted.connect(self._validate); buttons.rejected.connect(self.reject); root.addWidget(buttons)

    def _validate(self):
        if not self.title.text().strip(): self.message.setText("제목을 입력하세요."); return
        if self.end.date() < self.start.date(): self.message.setText("종료일은 시작일보다 빠를 수 없습니다."); return
        self.accept()

    def values(self) -> dict[str, str]:
        return {"start_date": self.start.date().toString("yyyy-MM-dd"), "end_date": self.end.date().toString("yyyy-MM-dd"), "title": self.title.text().strip(), "content": self.content.toPlainText().strip()}
