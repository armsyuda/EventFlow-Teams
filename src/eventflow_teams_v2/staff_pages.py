from __future__ import annotations

from datetime import date
from typing import Callable

from PySide6.QtCore import QDate, QMimeData, QPoint, Qt
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QTextEdit, QVBoxLayout, QWidget, QLineEdit
from event_checklist.ui.widgets import DirectDateEdit


ROLE_LABELS = {"OWNER": "대표", "ADMIN": "관리자", "PM": "PM", "MEMBER": "직원", "VIEWER": "조회자"}
PASTEL_SPECTRUM = (
    ("#F3B6B6", "빨강"), ("#F6C0A8", "주황빨강"), ("#F7CBA4", "주황"), ("#F8D8A6", "연주황"), ("#F7E4A8", "황금"),
    ("#F5EEAA", "노랑"), ("#E1EAA9", "노랑연두"), ("#CBE6A8", "연두"), ("#B5E1AF", "초록"), ("#A8DEC0", "민트초록"),
    ("#A7DDCE", "청록"), ("#A8E0DD", "물빛"), ("#A8DFE8", "하늘청록"), ("#A7D4F0", "하늘"), ("#AAC6ED", "파랑"),
    ("#B0BAEA", "남색"), ("#C0B5E8", "남보라"), ("#D0B4E8", "보라"), ("#DFB5E8", "연보라"), ("#E9B7E1", "자주보라"),
)


class WorkTaskCard(QFrame):
    def __init__(self, task, open_task: Callable[[int], None], draggable: bool, parent=None):
        super().__init__(parent); self.task = task; self.open_task = open_task; self.draggable = draggable; self._drag_origin: QPoint | None = None
        self.setObjectName("StaffTaskCard"); self.setMinimumHeight(72)
        self.setStyleSheet("QFrame#StaffTaskCard{background:#F8FAFC;border:1px solid #E2E8F0;border-radius:9px;} QFrame#StaffTaskCard:hover{border-color:#94A3B8;background:#FFFFFF;}")
        row = QHBoxLayout(self); row.setContentsMargins(11, 8, 11, 8); row.setSpacing(10)
        text = QVBoxLayout(); text.setSpacing(2)
        text.addWidget(QLabel(str(task["event_name"]), objectName="Muted"))
        text.addWidget(QLabel(f"[{task['major']}] {task['name']}"))
        due = str(task["due_date"] or "마감일 미입력")
        text.addWidget(QLabel(f"{task['status']} · {due}", objectName="Muted")); row.addLayout(text, 1)
        if draggable:
            handle = QLabel("⋮⋮"); handle.setObjectName("Muted"); handle.setToolTip("다른 직원 카드로 끌어 업무 이관"); row.addWidget(handle)

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton: self._drag_origin = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        if not self.draggable or not self._drag_origin or not (event.buttons() & Qt.MouseButton.LeftButton):
            return super().mouseMoveEvent(event)
        if (event.pos() - self._drag_origin).manhattanLength() < 8: return
        data = QMimeData(); data.setText(str(self.task["id"])); drag = QDrag(self); drag.setMimeData(data); drag.exec(Qt.DropAction.MoveAction)

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._drag_origin and (event.pos() - self._drag_origin).manhattanLength() < 8:
            try: self.open_task(int(self.task["id"]))
            except (TypeError, ValueError): pass  # company V3 rows have a remote UUID, not a Local row id
        self._drag_origin = None; super().mouseReleaseEvent(event)


class StaffWorkCard(QFrame):
    def __init__(self, member, can_transfer: bool, on_transfer: Callable[[str, str], bool] | None, parent=None):
        super().__init__(parent); self.member = member; self.can_transfer = can_transfer; self.on_transfer = on_transfer
        self.setObjectName("StaffWorkCard"); self.setAcceptDrops(can_transfer)

    def dragEnterEvent(self, event):  # noqa: N802
        if self.can_transfer and event.mimeData().hasText(): event.acceptProposedAction()

    def dropEvent(self, event):  # noqa: N802
        if not self.can_transfer or not self.on_transfer: return
        task_id = event.mimeData().text().strip()
        if not task_id: return
        if self.on_transfer(task_id, str(self.member["user_id"])): event.acceptProposedAction()


class StaffHorizontalScroll(QScrollArea):
    """Use the wheel to browse the staff-card strip without requiring Shift."""

    def wheelEvent(self, event):  # noqa: N802
        horizontal = self.horizontalScrollBar()
        if horizontal.maximum() > horizontal.minimum() and event.angleDelta().y():
            horizontal.setValue(horizontal.value() - event.angleDelta().y())
            event.accept(); return
        super().wheelEvent(event)


class EmployeeWorkPage(QWidget):
    """Company-visible active work board; personal absences remain calendar-only."""

    def __init__(self, db, open_task: Callable[[int], None], current_user_id: str = "", on_color_change: Callable[[str], None] | None = None, can_transfer: bool = False, on_transfer: Callable[[str, str], bool] | None = None, on_refresh_staff: Callable[[], None] | None = None, parent=None):
        super().__init__(parent); self.db = db; self.open_task = open_task; self.current_user_id = current_user_id; self.on_color_change = on_color_change; self.can_transfer = can_transfer; self.on_transfer = on_transfer; self.on_refresh_staff = on_refresh_staff
        root = QVBoxLayout(self); root.setContentsMargins(32, 28, 32, 32); root.setSpacing(12)
        root.addWidget(QLabel("직원업무", objectName="PageTitle"))
        root.addWidget(QLabel("동료가 맡은 진행 업무를 확인합니다. 개인 일정은 이 화면에 표시되지 않습니다.", objectName="PageDescription"))
        filters = QHBoxLayout(); filters.addWidget(QLabel("업무 범위")); self.project_filter = QComboBox(); self.project_filter.currentIndexChanged.connect(self.refresh); filters.addWidget(self.project_filter); filters.addStretch(); self.refresh_button = QPushButton("직원 목록 새로고침"); self.refresh_button.setProperty("quiet", True); self.refresh_button.clicked.connect(self._refresh_staff); filters.addWidget(self.refresh_button); root.addLayout(filters)
        self.scroll = StaffHorizontalScroll(); self.scroll.setObjectName("StaffWorkScroll"); self.scroll.setWidgetResizable(True); self.scroll.setFrameShape(QFrame.Shape.NoFrame); self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn); self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea#StaffWorkScroll{background:#F7F8FA;border:1px solid #E5E7EB;border-radius:12px;} QScrollArea#StaffWorkScroll > QWidget > QWidget{background:#F7F8FA;} QScrollBar:horizontal{height:18px;background:#E8EDF3;border-radius:9px;margin:5px 16px 7px 16px;} QScrollBar::handle:horizontal{min-width:110px;background:#98A2B3;border-radius:8px;} QScrollBar::handle:horizontal:hover{background:#667085;} QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal{width:0px;}")
        self.container = QWidget(); self.container.setObjectName("StaffWorkCanvas"); self.container.setStyleSheet("QWidget#StaffWorkCanvas{background:#F7F8FA;}")
        self.cards = QHBoxLayout(self.container); self.cards.setContentsMargins(16, 16, 16, 16); self.cards.setSpacing(16); self.cards.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.container); root.addWidget(self.scroll, 1)

    def refresh(self) -> None:
        previous_project = self.project_filter.currentData(); self.project_filter.blockSignals(True); self.project_filter.clear(); self.project_filter.addItem("전체 업무", "")
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
            card = StaffWorkCard(member, self.can_transfer, self.on_transfer); card.setFixedWidth(300); card.setFixedHeight(690); card.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
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
            task_canvas = QWidget(); task_canvas.setStyleSheet("background:transparent;"); task_layout = QVBoxLayout(task_canvas); task_layout.setContentsMargins(0, 0, 2, 0); task_layout.setSpacing(8); task_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
            for task in active: task_layout.addWidget(self._task_card(task))
            if not active: task_layout.addWidget(QLabel("진행 중인 업무가 없습니다.", objectName="EmptyState"))
            if completed:
                toggle = QPushButton(f"완료 항목 보기 · {len(completed)}건"); toggle.setProperty("quiet", True); task_layout.addWidget(toggle)
                done_box = QWidget(); done_layout = QVBoxLayout(done_box); done_layout.setContentsMargins(0, 0, 0, 0); done_layout.setSpacing(5)
                for task in completed: done_layout.addWidget(self._task_card(task))
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

    def _task_card(self, task):
        return WorkTaskCard(task, self.open_task, self.can_transfer)

    def _member_work(self, user_id: str, *, completed: bool):
        """Prefer the V3 mirror so a colleague's cross-project work is visible."""
        try:
            condition = "w.status='완료'" if completed else "w.status NOT IN ('완료','해당없음')"
            scope = self.project_filter.currentData() if hasattr(self, "project_filter") else ""; filter_sql = " AND w.event_id=?" if scope else ""; args = (user_id, scope) if scope else (user_id,)
            return self.db.query(f"""SELECT w.remote_id id,w.name,w.major,w.status,w.due_date,
                COALESCE(e.name,CASE WHEN w.work_scope='COMPANY' THEN '프로젝트 외' ELSE '프로젝트' END) event_name
                FROM teams_v3_work_items w LEFT JOIN teams_v2_entity_map map ON map.entity_type='EVENT' AND map.remote_id=w.event_id
                LEFT JOIN events e ON e.id=map.local_id WHERE w.assigned_member_user_id=? AND w.is_removed=0 AND {condition}{filter_sql}
                ORDER BY COALESCE(w.due_date,'9999-12-31'),w.sort_order""", args)
        except Exception:
            condition = "t.status='완료'" if completed else "t.status NOT IN ('완료','해당없음')"
            return self.db.query(f"""SELECT t.id,t.name,t.major,t.status,t.due_date,e.name event_name FROM event_tasks t
                JOIN events e ON e.id=t.event_id WHERE t.assigned_member_user_id=? AND t.is_removed=0 AND {condition}
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
