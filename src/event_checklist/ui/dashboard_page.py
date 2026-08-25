from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QProgressBar, QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget

from ..theme import TOKENS
from .widgets import KpiCard


class EventCard(QFrame):
    selected = Signal(int)
    def __init__(self, event, progress, parent=None):
        super().__init__(parent); self.event_id = int(event["id"]); self.setObjectName("EventCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip("클릭하여 이 행사를 엽니다.")
        layout = QHBoxLayout(self); layout.setContentsMargins(18, 14, 14, 14)
        text = QVBoxLayout(); name = QLabel(event["name"]); name.setObjectName("EventCardTitle")
        dates = QLabel(f"행사 {event['start_date']}  →  {event['end_date'] or event['start_date']}"); dates.setObjectName("Muted")
        text.addWidget(name); text.addWidget(dates); layout.addLayout(text, 1)
        rate = QLabel(f"진행률 {progress}%"); rate.setObjectName("Muted")
        layout.addWidget(rate)
        for child in (name, dates, rate):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.selected.emit(self.event_id)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.selected.emit(self.event_id)
            event.accept()
            return
        super().keyPressEvent(event)


class DashboardPage(QWidget):
    create_requested = Signal(); event_selected = Signal(int); edit_requested = Signal(int); delete_requested = Signal(int); clear_requested = Signal()
    def __init__(self, service, parent=None):
        super().__init__(parent); self.service = service; self.event_id = None
        root = QVBoxLayout(self); root.setContentsMargins(32, 28, 32, 32)
        self.views = QStackedWidget(); self.views.addWidget(self._landing()); self.views.addWidget(self._overview()); root.addWidget(self.views)

    def _landing(self):
        page = QWidget(); layout = QVBoxLayout(page); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(18)
        top = QHBoxLayout(); box = QVBoxLayout(); title = QLabel("이벤트 플로우"); title.setObjectName("PageTitle")
        description = QLabel("새 행사를 만들거나 작업할 행사를 선택하세요."); description.setObjectName("PageDescription")
        box.addWidget(title); box.addWidget(description); top.addLayout(box); top.addStretch()
        create = QPushButton("+ 새 행사"); create.setProperty("primary", True); create.clicked.connect(self.create_requested); top.addWidget(create); layout.addLayout(top)
        label = QLabel("행사 목록"); label.setObjectName("SectionTitle"); layout.addWidget(label)
        self.event_list = QScrollArea(); self.event_list.setWidgetResizable(True); self.event_list.setObjectName("EventListArea")
        content = QWidget(); self.event_list_layout = QVBoxLayout(content); self.event_list_layout.setContentsMargins(0, 0, 4, 0); self.event_list_layout.setSpacing(10)
        self.event_list.setWidget(content); layout.addWidget(self.event_list, 1); return page

    def _overview(self):
        page = QWidget(); layout = QVBoxLayout(page); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(18)
        top = QHBoxLayout(); box = QVBoxLayout(); self.overview_title = QLabel(""); self.overview_title.setObjectName("PageTitle")
        self.overview_dates = QLabel(""); self.overview_dates.setObjectName("PageDescription"); box.addWidget(self.overview_title); box.addWidget(self.overview_dates)
        top.addLayout(box); top.addStretch(); edit = QPushButton("행사 정보 수정"); edit.clicked.connect(lambda: self.event_id and self.edit_requested.emit(self.event_id))
        delete = QPushButton("행사 삭제"); delete.setProperty("danger", True)
        delete.clicked.connect(lambda: self.event_id and self.delete_requested.emit(self.event_id))
        change = QPushButton("다른 행사 선택"); change.clicked.connect(self.clear_requested)
        top.addWidget(edit); top.addWidget(delete); top.addWidget(change); layout.addLayout(top)
        cards = QGridLayout(); self.kpis = {}
        for index, (key, label) in enumerate([("managed", "관리 대상"), ("completed", "완료"), ("in_progress", "진행중"), ("not_started", "미착수"), ("overdue", "지연")]):
            card = KpiCard(label); self.kpis[key] = card; cards.addWidget(card, 0, index)
        layout.addLayout(cards)
        progress_card = QFrame(); progress_card.setObjectName("Card"); pl = QVBoxLayout(progress_card); pl.setContentsMargins(20, 18, 20, 18)
        pt = QLabel("전체 진행률"); pt.setObjectName("SectionTitle"); self.progress_text = QLabel("0%"); self.progress_text.setObjectName("KpiValue")
        self.progress_bar = QProgressBar(); self.progress_bar.setRange(0, 100); self.progress_bar.setTextVisible(False)
        pl.addWidget(pt); pl.addWidget(self.progress_text); pl.addWidget(self.progress_bar); layout.addWidget(progress_card)
        urgent_title = QLabel("지연 · 7일 이내 마감"); urgent_title.setObjectName("SectionTitle"); layout.addWidget(urgent_title)
        self.urgent_list = QListWidget(); self.urgent_list.setObjectName("UrgentList"); self.urgent_list.setSpacing(4); layout.addWidget(self.urgent_list, 1); return page

    def refresh_events(self):
        while self.event_list_layout.count():
            item = self.event_list_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        events = self.service.list_events()
        if not events:
            empty = QLabel("아직 등록된 행사가 없습니다. 새 행사를 만들어 시작하세요."); empty.setObjectName("EmptyState"); empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.event_list_layout.addWidget(empty, 1); return
        for event in events:
            data = self.service.dashboard(int(event["id"])); card = EventCard(event, round((data.get("progress") or 0) * 100))
            card.selected.connect(self.event_selected); self.event_list_layout.addWidget(card)
        self.event_list_layout.addStretch()

    def set_event(self, event_id):
        self.event_id = event_id
        if not event_id: self.refresh_events(); self.views.setCurrentIndex(0); return
        event = self.service.get_event(event_id)
        if not event: self.set_event(None); return
        self.views.setCurrentIndex(1); self.overview_title.setText(event["name"])
        self.overview_dates.setText(f"행사 {event['start_date']}  →  {event['end_date'] or event['start_date']}")
        data = self.service.dashboard(event_id)
        for key, card in self.kpis.items(): card.set_value(data.get(key) or 0)
        progress = round((data.get("progress") or 0) * 100); self.progress_text.setText(f"{progress}% · {data.get('completed') or 0}/{data.get('managed') or 0}개 완료")
        self.progress_bar.setValue(progress); self.urgent_list.clear()
        for task in data["urgent"]:
            remaining = int(task["remaining_days"])
            date_label = f"{abs(remaining)}일 지연" if remaining < 0 else ("오늘 마감" if remaining == 0 else f"{remaining}일 후 마감")
            item = QListWidgetItem(f"{date_label}    {task['name']}    · {task['status']}")
            item.setSizeHint(item.sizeHint().expandedTo(item.sizeHint().__class__(0, 42))); overdue = remaining < 0
            item.setBackground(QColor(TOKENS["critical_weak"] if overdue else TOKENS["warning_weak"])); item.setForeground(QColor(TOKENS["critical"] if overdue else TOKENS["warning"]))
            self.urgent_list.addItem(item)
