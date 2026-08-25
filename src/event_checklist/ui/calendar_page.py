from __future__ import annotations

import calendar
from datetime import date

from PySide6.QtCore import QDate, QEvent, QPoint, QTimer, Qt, Signal
from PySide6.QtWidgets import QCalendarWidget, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSizePolicy, QSplitter, QVBoxLayout, QWidget

from ..pdf_export import export_calendar_pdf
from ..theme import status_color
from .month_timeline import MonthTimeline
from .pdf_export_dialog import configure_pdf_icon_button, export_calendar_pdf_from_page


CATEGORY_CARD_BORDERS = {
    "시스템": "#B8D4EA",
    "시설": "#BDDCC8",
    "행사": "#F2C8B8",
    "홍보": "#D4C8E6",
    "운영": "#E6D8AE",
}


class ElidedCardTitle(QLabel):
    """A one-line card title that never pushes the status badge outside its row."""
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self._full_text = text
        self.setText(text)
        self.setToolTip(text)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(0)

    def resizeEvent(self, event):
        self.setText(self.fontMetrics().elidedText(self._full_text, Qt.TextElideMode.ElideRight, self.width()))
        super().resizeEvent(event)


class CalendarTaskCard(QFrame):
    completion_requested = Signal(int, bool)
    postpone_requested = Signal(int, object)

    def __init__(self, task, parent=None):
        super().__init__(parent)
        self.task = dict(task)
        self.task_id = int(task["id"])
        self.setObjectName("CalendarTaskCard")
        due = date.fromisoformat(task["due_date"])
        overdue = task["status"] != "완료" and due < date.today()
        due_today = task["status"] != "완료" and due == date.today()
        urgency = "completed" if task["status"] == "완료" else ("critical" if overdue else ("dueToday" if due_today else "normal"))
        self.setProperty("urgency", urgency)
        border = CATEGORY_CARD_BORDERS.get(task["major"], "#D9DCE1")
        background = {
            "critical": "#FDECEC", "dueToday": "#FFF5CC", "completed": "#E8F7EF",
        }.get(urgency, "#FFFFFF")
        self.setStyleSheet(
            f"QFrame#CalendarTaskCard{{background:{background};border:{2 if due_today else 1}px solid {border};border-radius:10px;}}"
        )
        layout = QVBoxLayout(self); layout.setContentsMargins(9, 4, 9, 4); layout.setSpacing(2)
        top = QHBoxLayout(); top.setContentsMargins(0, 0, 0, 0); top.setSpacing(6)
        name = ElidedCardTitle(task["name"]); name.setObjectName("CalendarTaskName")
        badge_text = f"지연 · {task['status']}" if overdue else ("오늘 마감" if due_today else task["status"])
        fg, bg = (("#C9342C", "#FDECEC") if overdue else
                  (("#B54708", "#FFF2D6") if due_today else status_color(task["status"])))
        badge = QLabel(badge_text); badge.setObjectName("StatusBadge"); badge.setStyleSheet(f"color:{fg};background:{bg};")
        badge.setFixedHeight(20); badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top.addWidget(name, 1); top.addWidget(badge); layout.addLayout(top)
        actions = QHBoxLayout(); actions.setContentsMargins(0, 0, 0, 0); actions.setSpacing(6)
        complete = QPushButton("↩ 완료 취소" if task["status"] == "완료" else "완료 처리")
        complete.setProperty("compact", True)
        complete.setProperty("calendarCardAction", True)
        complete.setFixedHeight(22)
        complete.setProperty("success", task["status"] == "완료")
        complete.setProperty("primary", task["status"] != "완료")
        complete.clicked.connect(lambda: self.completion_requested.emit(self.task_id, task["status"] != "완료"))
        actions.addWidget(complete)
        if due_today:
            postpone = QPushButton("마감일 연기")
            postpone.setProperty("compact", True); postpone.setProperty("warning", True)
            postpone.setProperty("calendarCardAction", True); postpone.setFixedHeight(22)
            postpone.clicked.connect(lambda: self._open_calendar(postpone))
            actions.addWidget(postpone)
        actions.addStretch(); layout.addLayout(actions)

    def _open_calendar(self, anchor):
        calendar_popup = QCalendarWidget(self)
        calendar_popup.setWindowFlags(Qt.WindowType.Popup)
        calendar_popup.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        calendar_popup.setGridVisible(True)
        calendar_popup.setMinimumDate(QDate.currentDate())
        calendar_popup.setSelectedDate(QDate.fromString(self.task["due_date"], "yyyy-MM-dd"))
        calendar_popup.setFixedSize(340, 270)
        calendar_popup.clicked.connect(
            lambda selected: (self.postpone_requested.emit(self.task_id, selected.toPython()), calendar_popup.close())
        )
        calendar_popup.move(anchor.mapToGlobal(anchor.rect().bottomLeft()))
        calendar_popup.show(); calendar_popup.raise_(); calendar_popup.activateWindow()
        self._calendar_popup = calendar_popup


class CalendarPage(QWidget):
    changed = Signal(int)

    def __init__(self, service, db=None, parent=None):
        super().__init__(parent)
        self.service = service
        self.db = db or service.db
        self.event_id: int | None = None
        root = QVBoxLayout(self); root.setContentsMargins(32, 28, 32, 32); root.setSpacing(12)
        top = QHBoxLayout(); top.setSpacing(10)
        self.title = QLabel("달력"); self.title.setObjectName("PageTitle")
        top.addWidget(self.title, 0, Qt.AlignmentFlag.AlignBottom)
        top.addStretch()
        self.toggle = QPushButton("일정 목록 숨기기"); self.toggle.clicked.connect(self._toggle_side)
        top.addWidget(self.toggle)
        self.export_button = QPushButton()
        configure_pdf_icon_button(self.export_button)
        self.export_button.setToolTip("달력 PDF로 내보내기")
        self.export_button.setAccessibleName("달력 PDF로 내보내기")
        self.export_button.clicked.connect(self.export_pdf)
        top.addWidget(self.export_button)
        root.addLayout(top)

        self.navigation = QWidget(self)
        navigation = QHBoxLayout(self.navigation)
        navigation.setContentsMargins(0, 0, 0, 0); navigation.setSpacing(8)
        self.previous_button = QPushButton("‹"); self.previous_button.setFixedWidth(42); self.previous_button.clicked.connect(lambda: self._shift(-1))
        self.month_label = QLabel(""); self.month_label.setObjectName("SectionTitle"); self.month_label.setMinimumWidth(110); self.month_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.following_button = QPushButton("›"); self.following_button.setFixedWidth(42); self.following_button.clicked.connect(lambda: self._shift(1))
        self.today_button = QPushButton("오늘로 가기")
        today_width = max(120, self.today_button.fontMetrics().horizontalAdvance(self.today_button.text()) + 44)
        self.today_button.setFixedWidth(today_width); self.today_button.clicked.connect(self._go_today)
        navigation.addWidget(self.previous_button)
        navigation.addWidget(self.month_label)
        navigation.addWidget(self.following_button)
        navigation.addWidget(self.today_button)
        self.navigation.adjustSize()
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.calendar = MonthTimeline(); self.calendar.date_selected.connect(self.refresh_selected)
        self.calendar.installEventFilter(self)
        self.splitter.addWidget(self.calendar)
        self.side = QFrame(); self.side.setObjectName("CalendarSide")
        side_layout = QVBoxLayout(self.side); side_layout.setContentsMargins(16, 16, 16, 16)
        head = QHBoxLayout(); self.selected_title = QLabel(""); self.selected_title.setObjectName("SectionTitle")
        self.selected_count = QLabel(""); self.selected_count.setObjectName("Muted")
        head.addWidget(self.selected_title, 1); head.addWidget(self.selected_count); side_layout.addLayout(head)
        self.list = QListWidget(); self.list.setObjectName("CalendarTaskList"); self.list.setSpacing(7); side_layout.addWidget(self.list, 1)
        self.empty = QLabel("이 날짜에 진행 중인 업무가 없습니다.")
        self.empty.setObjectName("EmptyState"); self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        side_layout.addWidget(self.empty, 1); self.empty.hide()
        self.splitter.addWidget(self.side); self.splitter.setSizes([850, 390]); self.splitter.setHandleWidth(7)
        root.addWidget(self.splitter, 1)
        visible = self.db.get_setting("calendar_list_visible", "1") != "0"
        self.side.setVisible(visible); self.toggle.setText("일정 목록 숨기기" if visible else "일정 목록 보기")
        self._update_month_label()
        QTimer.singleShot(0, self._position_navigation)

    def set_event(self, event_id):
        self.event_id = event_id
        self.refresh()

    def refresh_events(self, selected_event_id=None):
        self.set_event(selected_event_id if selected_event_id is not None else self.event_id)

    def export_pdf(self):
        export_calendar_pdf_from_page(
            self, self.db, self.event_id, self.calendar.year, self.calendar.month, export_calendar_pdf,
        )

    def _shift(self, offset):
        self.calendar.shift_month(offset); self._update_month_label(); self.refresh_periods()

    def _go_today(self):
        today = date.today()
        self.calendar.set_month(today.year, today.month)
        self.calendar.selected = today
        self._update_month_label()
        self.refresh_periods()
        self.refresh_selected(today)
        self.calendar.update()

    def _update_month_label(self): self.month_label.setText(f"{self.calendar.year}년 {self.calendar.month}월")

    def _toggle_side(self):
        visible = not self.side.isVisible(); self.side.setVisible(visible)
        self.toggle.setText("일정 목록 숨기기" if visible else "일정 목록 보기")
        self.db.set_setting("calendar_list_visible", "1" if visible else "0")
        QTimer.singleShot(0, self._position_navigation)

    def eventFilter(self, watched, event):
        if watched is self.calendar and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._position_navigation)
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._position_navigation)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._position_navigation)

    def _position_navigation(self):
        if not self.calendar.isVisible():
            return
        self.navigation.adjustSize()
        calendar_left = self.calendar.mapTo(self, QPoint(0, 0)).x()
        calendar_center = calendar_left + self.calendar.width() // 2
        toggle_top = self.toggle.mapTo(self, QPoint(0, 0)).y()
        x = calendar_center - self.navigation.width() // 2
        y = toggle_top + (self.toggle.height() - self.navigation.height()) // 2
        self.navigation.move(x, y)
        self.navigation.raise_()

    def refresh(self): self.refresh_periods(); self.refresh_selected(self.calendar.selected)

    def refresh_periods(self):
        first = date(self.calendar.year, self.calendar.month, 1)
        last = date(self.calendar.year, self.calendar.month, calendar.monthrange(self.calendar.year, self.calendar.month)[1])
        self.calendar.set_tasks(self.service.calendar_range(first, last, self.event_id) if self.event_id else [])
        event = self.service.get_event(self.event_id) if self.event_id else None
        self.calendar.set_event_period(event if event and event["start_date"] and event["end_date"] else None)

    def refresh_selected(self, selected=None):
        selected = selected or self.calendar.selected
        self.selected_title.setText(f"{selected.year:04d}년 {selected.month:02d}월 {selected.day:02d}일"); self.list.clear()
        tasks = self.service.calendar_tasks(selected, self.event_id) if self.event_id else []
        self.selected_count.setText(f"{len(tasks)}개")
        if not tasks:
            self.list.hide(); self.empty.show(); return
        self.empty.hide(); self.list.show()
        for task in tasks:
            due_today = task["status"] != "완료" and task["due_date"] == date.today().isoformat()
            item = QListWidgetItem(); item.setSizeHint(item.sizeHint().__class__(0, 56)); self.list.addItem(item)
            card = CalendarTaskCard(task, self.list)
            card.completion_requested.connect(self._set_completed)
            card.postpone_requested.connect(self._postpone)
            self.list.setItemWidget(item, card)

    def _set_completed(self, task_id: int, completed: bool):
        self.service.set_completed(task_id, completed)
        self.refresh()
        self.changed.emit(self.event_id or 0)

    def _postpone(self, task_id: int, new_due: date):
        try:
            self.service.update_task(task_id, due_date=new_due.isoformat())
        except ValueError as exc:
            QMessageBox.warning(self, "일정 연기 확인", str(exc))
            return
        self.refresh()
        self.changed.emit(self.event_id or 0)
