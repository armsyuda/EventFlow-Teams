from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout,
    QLabel, QRadioButton, QVBoxLayout,
)

from ..pdf_export import PdfOptions


class ExcelExportDialog(QDialog):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Excel로 내보내기")
        self.setMinimumWidth(480)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(12)
        title = QLabel("Excel로 내보내기")
        title.setObjectName("SectionTitle")
        description = QLabel("프로젝트, 문서 종류와 인쇄 형식을 선택하세요.")
        description.setObjectName("Muted")
        root.addWidget(title)
        root.addWidget(description)

        root.addWidget(QLabel("프로젝트 선택"))
        self.event_combo = QComboBox()
        for event in db.query("SELECT id,name FROM events ORDER BY start_date,id"):
            self.event_combo.addItem(event["name"], int(event["id"]))
        root.addWidget(self.event_combo)

        root.addWidget(QLabel("내보낼 문서"))
        kind_row = QHBoxLayout()
        self.checklist = self._option("체크리스트", "분류 선택 가능", True)
        self.settlement = self._option("정산내역", "전체 정산")
        self.kind_group = QButtonGroup(self)
        for button in (self.checklist, self.settlement):
            self.kind_group.addButton(button)
            kind_row.addWidget(button)
        root.addLayout(kind_row)

        paper_orientation = QHBoxLayout()
        paper_box = QFrame()
        paper_layout = QVBoxLayout(paper_box)
        paper_layout.setContentsMargins(0, 0, 6, 0)
        paper_layout.addWidget(QLabel("용지 크기"))
        self.a4 = self._option("A4", "기본", True)
        self.a3 = self._option("A3", "넓은 표")
        self.paper_group = QButtonGroup(self)
        for button in (self.a4, self.a3):
            self.paper_group.addButton(button)
            paper_layout.addWidget(button)
        orientation_box = QFrame()
        orientation_layout = QVBoxLayout(orientation_box)
        orientation_layout.setContentsMargins(6, 0, 0, 0)
        orientation_layout.addWidget(QLabel("용지 방향"))
        self.portrait = self._option("세로", "많은 행", True)
        self.landscape = self._option("가로", "넓은 열")
        self.orientation_group = QButtonGroup(self)
        for button in (self.portrait, self.landscape):
            self.orientation_group.addButton(button)
            orientation_layout.addWidget(button)
        paper_orientation.addWidget(paper_box)
        paper_orientation.addWidget(orientation_box)
        root.addLayout(paper_orientation)

        self.scope_panel = QFrame()
        self.scope_panel.setObjectName("ExcelChecklistScope")
        scope_layout = QVBoxLayout(self.scope_panel)
        scope_layout.setContentsMargins(14, 12, 14, 12)
        scope_layout.setSpacing(7)
        scope_layout.addWidget(QLabel("체크리스트 출력 범위"))
        self.scope_combo = QComboBox()
        self.scope_combo.addItem("전체", "ALL")
        self.scope_combo.addItem("대분류 선택", "MAJOR")
        self.scope_combo.addItem("중분류 선택", "MINOR")
        self.major_combo = QComboBox()
        self.minor_combo = QComboBox()
        scope_layout.addWidget(self.scope_combo)
        scope_layout.addWidget(self.major_combo)
        scope_layout.addWidget(self.minor_combo)
        root.addWidget(self.scope_panel)

        guide = QLabel("PDF와 동일한 색상·분류 병합·정렬을 적용하고 선택한 용지에 맞춰 인쇄 영역을 설정합니다.")
        guide.setObjectName("InfoGuide")
        guide.setWordWrap(True)
        root.addWidget(guide)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("내보내기")
        buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(self.event_combo.count() > 0)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.event_combo.currentIndexChanged.connect(self._load_categories)
        self.kind_group.buttonToggled.connect(self._sync_kind)
        self.scope_combo.currentIndexChanged.connect(self._sync_scope)
        self.major_combo.currentIndexChanged.connect(self._load_minors)
        self._load_categories()
        self._sync_kind()
        self._sync_scope()

    @staticmethod
    def _option(title: str, note: str, checked=False) -> QRadioButton:
        button = QRadioButton(f"{title}  ·  {note}")
        button.setProperty("pdfOption", True)
        button.setMinimumHeight(42)
        button.setChecked(checked)
        return button

    def _load_categories(self):
        event_id = self.event_combo.currentData()
        current = self.major_combo.currentData()
        self.major_combo.clear()
        if event_id:
            rows = self.db.query(
                """SELECT major,MIN(sort_order) first_order FROM event_tasks
                   WHERE event_id=? AND is_removed=0 GROUP BY major ORDER BY first_order,major""",
                (event_id,),
            )
            for row in rows:
                self.major_combo.addItem(row["major"], row["major"])
        if current:
            self.major_combo.setCurrentIndex(max(0, self.major_combo.findData(current)))
        self._load_minors()

    def _load_minors(self):
        event_id = self.event_combo.currentData()
        major = self.major_combo.currentData()
        current = self.minor_combo.currentData()
        self.minor_combo.clear()
        if event_id and major:
            rows = self.db.query(
                """SELECT minor,MIN(sort_order) first_order FROM event_tasks
                   WHERE event_id=? AND major=? AND is_removed=0
                   GROUP BY minor ORDER BY first_order,minor""",
                (event_id, major),
            )
            for row in rows:
                self.minor_combo.addItem(row["minor"], row["minor"])
        if current:
            self.minor_combo.setCurrentIndex(max(0, self.minor_combo.findData(current)))

    def _sync_kind(self):
        self.scope_panel.setEnabled(self.checklist.isChecked())
        self._sync_scope()

    def _sync_scope(self):
        scope = self.scope_combo.currentData()
        self.major_combo.setEnabled(scope in {"MAJOR", "MINOR"} and self.checklist.isChecked())
        self.minor_combo.setEnabled(scope == "MINOR" and self.checklist.isChecked())

    def values(self):
        kind = "checklist" if self.checklist.isChecked() else "settlement"
        scope = self.scope_combo.currentData() if kind == "checklist" else "ALL"
        major = (self.major_combo.currentData() or "") if scope in {"MAJOR", "MINOR"} else ""
        minor = (self.minor_combo.currentData() or "") if scope == "MINOR" else ""
        return {
            "event_id": self.event_combo.currentData(),
            "kind": kind,
            "options": PdfOptions(
                "A4" if self.a4.isChecked() else "A3",
                "PORTRAIT" if self.portrait.isChecked() else "LANDSCAPE",
            ),
            "major": major,
            "minor": minor,
        }
