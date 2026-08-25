from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QDialogButtonBox, QFileDialog, QFrame, QHBoxLayout,
    QComboBox, QLabel, QMessageBox, QPushButton, QRadioButton, QVBoxLayout,
)

from ..pdf_export import PdfOptions, default_pdf_filename, next_available_pdf_path


def print_icon() -> QIcon:
    path = files("event_checklist").joinpath("resources/assets/print.svg")
    return QIcon(str(path)) if path.is_file() else QIcon()


def configure_pdf_icon_button(button: QPushButton, *, size: int = 42) -> None:
    button.setIcon(print_icon())
    button.setIconSize(QSize(22, 22))
    button.setObjectName("PdfExportButton")
    button.setFixedSize(size, size)
    button.setToolTip("PDF로 내보내기")
    button.setAccessibleName("PDF로 내보내기")


class PdfExportDialog(QDialog):
    def __init__(self, parent=None, *, default_orientation="PORTRAIT",
                 title_text="PDF로 내보내기", description_text="용지 크기와 방향을 선택하세요.",
                 guide_text="한 페이지에 들어가는 행 수와 줄바꿈 높이를 계산해 8pt 또는 10pt를 자동으로 적용합니다."):
        super().__init__(parent)
        self.setWindowTitle(title_text)
        self.setMinimumWidth(420)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(14)
        title = QLabel(title_text)
        title.setObjectName("SectionTitle")
        description = QLabel(description_text)
        description.setObjectName("Muted")
        root.addWidget(title); root.addWidget(description)
        root.addWidget(QLabel("용지 크기"))
        paper_row = QHBoxLayout()
        self.a4 = self._option("A4", "기본 선택", True)
        self.a3 = self._option("A3", "더 넓은 표")
        self.paper_group = QButtonGroup(self)
        for button in (self.a4, self.a3):
            self.paper_group.addButton(button); paper_row.addWidget(button)
        root.addLayout(paper_row)
        root.addWidget(QLabel("용지 방향"))
        orientation_row = QHBoxLayout()
        self.landscape = self._option("가로", "넓은 열 구성", default_orientation == "LANDSCAPE")
        self.portrait = self._option("세로", "더 많은 행", default_orientation == "PORTRAIT")
        self.orientation_group = QButtonGroup(self)
        for button in (self.landscape, self.portrait):
            self.orientation_group.addButton(button); orientation_row.addWidget(button)
        root.addLayout(orientation_row)
        guide = QLabel(guide_text)
        guide.setObjectName("InfoGuide"); guide.setWordWrap(True)
        root.addWidget(guide)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("내보내기")
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @staticmethod
    def _option(title: str, note: str, checked=False) -> QRadioButton:
        button = QRadioButton(f"{title}  ·  {note}")
        button.setProperty("pdfOption", True)
        button.setMinimumHeight(48)
        button.setChecked(checked)
        return button

    def options(self) -> PdfOptions:
        return PdfOptions(
            paper="A4" if self.a4.isChecked() else "A3",
            orientation="PORTRAIT" if self.portrait.isChecked() else "LANDSCAPE",
        )


class ChecklistPdfExportDialog(PdfExportDialog):
    def __init__(self, majors, vendors=(), pm_assignees=(), parent=None):
        super().__init__(
            parent,
            title_text="체크리스트 PDF로 내보내기",
            description_text="용지와 체크리스트 출력 범위를 선택하세요.",
        )
        panel = QFrame()
        panel.setObjectName("ChecklistPdfScope")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        layout.addWidget(QLabel("체크리스트 출력 범위"))
        self.scope_combo = QComboBox()
        self.scope_combo.addItem("전체 인쇄", "ALL")
        self.scope_combo.addItem("대분류 선택", "MAJOR")
        self.scope_combo.addItem("업체별 인쇄", "VENDOR")
        self.scope_combo.addItem("담당자(PM)별 인쇄", "PM")
        layout.addWidget(self.scope_combo)
        self.major_combo = QComboBox()
        for major in majors:
            self.major_combo.addItem(major, major)
        layout.addWidget(self.major_combo)
        self.vendor_combo = QComboBox()
        for vendor in vendors:
            self.vendor_combo.addItem(vendor["name"], int(vendor["id"]))
        layout.addWidget(self.vendor_combo)
        self.pm_combo = QComboBox()
        for person in pm_assignees:
            self.pm_combo.addItem(person["name"], int(person["id"]))
        layout.addWidget(self.pm_combo)
        self.layout().insertWidget(self.layout().count() - 1, panel)
        self.scope_combo.currentIndexChanged.connect(self._sync_scope)
        self._sync_scope()

    def _sync_scope(self):
        scope = self.scope_combo.currentData()
        self.major_combo.setEnabled(scope == "MAJOR")
        self.vendor_combo.setEnabled(scope == "VENDOR")
        self.pm_combo.setEnabled(scope == "PM")

    def major_filter(self):
        if self.scope_combo.currentData() == "MAJOR":
            return self.major_combo.currentData() or ""
        return ""

    def assignment_filter(self):
        scope = self.scope_combo.currentData()
        if scope == "VENDOR":
            return self.vendor_combo.currentData(), None, self.vendor_combo.currentText()
        if scope == "PM":
            return None, self.pm_combo.currentData(), self.pm_combo.currentText()
        return None, None, ""


class CalendarPdfExportDialog(PdfExportDialog):
    def __init__(self, categories, vendors=(), pm_assignees=(), parent=None):
        super().__init__(
            parent,
            default_orientation="LANDSCAPE",
            title_text="달력 PDF로 내보내기",
            description_text="용지와 일정 분류를 선택하세요.",
            guide_text="겹치는 일정이 달력 칸을 넘으면 같은 달력을 다음 페이지에 이어서 모든 항목을 표시합니다.",
        )
        self._categories = {major: list(minors) for major, minors in categories}
        panel = QFrame()
        panel.setObjectName("CalendarPdfScope")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        layout.addWidget(QLabel("달력 출력 범위"))
        self.scope_combo = QComboBox()
        self.scope_combo.addItem("전체 일정", "ALL")
        self.scope_combo.addItem("대분류 선택", "MAJOR")
        self.scope_combo.addItem("중분류 선택", "MINOR")
        self.scope_combo.addItem("업체별 인쇄", "VENDOR")
        self.scope_combo.addItem("담당자(PM)별 인쇄", "PM")
        layout.addWidget(self.scope_combo)
        self.major_combo = QComboBox()
        self.minor_combo = QComboBox()
        for major in self._categories:
            self.major_combo.addItem(major, major)
        layout.addWidget(self.major_combo)
        layout.addWidget(self.minor_combo)
        self.vendor_combo = QComboBox()
        for vendor in vendors:
            self.vendor_combo.addItem(vendor["name"], int(vendor["id"]))
        layout.addWidget(self.vendor_combo)
        self.pm_combo = QComboBox()
        for person in pm_assignees:
            self.pm_combo.addItem(person["name"], int(person["id"]))
        layout.addWidget(self.pm_combo)
        self.layout().insertWidget(self.layout().count() - 1, panel)
        self.scope_combo.currentIndexChanged.connect(self._sync_scope)
        self.major_combo.currentIndexChanged.connect(self._sync_minors)
        self._sync_minors()
        self._sync_scope()

    def _sync_minors(self):
        current = self.minor_combo.currentData()
        self.minor_combo.clear()
        for minor in self._categories.get(self.major_combo.currentData(), []):
            self.minor_combo.addItem(minor, minor)
        if current:
            self.minor_combo.setCurrentIndex(max(0, self.minor_combo.findData(current)))

    def _sync_scope(self):
        scope = self.scope_combo.currentData()
        self.major_combo.setEnabled(scope in {"MAJOR", "MINOR"})
        self.minor_combo.setEnabled(scope == "MINOR")
        self.vendor_combo.setEnabled(scope == "VENDOR")
        self.pm_combo.setEnabled(scope == "PM")

    def filters(self):
        scope = self.scope_combo.currentData()
        if scope == "MAJOR":
            return self.major_combo.currentData() or "", ""
        if scope == "MINOR":
            return self.major_combo.currentData() or "", self.minor_combo.currentData() or ""
        return "", ""

    def assignment_filter(self):
        scope = self.scope_combo.currentData()
        if scope == "VENDOR":
            return self.vendor_combo.currentData(), None, self.vendor_combo.currentText()
        if scope == "PM":
            return None, self.pm_combo.currentData(), self.pm_combo.currentText()
        return None, None, ""


def _assignment_choices(db, event_id):
    vendors = db.query(
        """SELECT DISTINCT c.id,c.name FROM event_tasks t
           JOIN contacts c ON c.id=t.vendor_id
           WHERE t.event_id=? AND t.is_removed=0 ORDER BY c.name,c.id""",
        (event_id,),
    )
    pm_assignees = db.query(
        """SELECT DISTINCT c.id,c.name FROM event_tasks t
           JOIN contacts c ON c.id=t.pm_assignee_id
           WHERE t.event_id=? AND t.is_removed=0 ORDER BY c.name,c.id""",
        (event_id,),
    )
    return vendors, pm_assignees


def export_pdf_from_page(parent, db, event_id, kind, exporter) -> Path | None:
    if not event_id:
        QMessageBox.information(parent, "행사 선택", "PDF로 내보낼 행사를 선택하세요.")
        return None
    major = ""
    if kind == "checklist":
        rows = db.query(
            """SELECT major,MIN(sort_order) first_order FROM event_tasks
               WHERE event_id=? AND is_removed=0 GROUP BY major ORDER BY first_order,major""",
            (event_id,),
        )
        vendors, pm_assignees = _assignment_choices(db, event_id)
        dialog = ChecklistPdfExportDialog([row["major"] for row in rows], vendors, pm_assignees, parent)
    else:
        dialog = PdfExportDialog(parent)
    if not dialog.exec():
        return None
    event = db.one("SELECT * FROM events WHERE id=?", (event_id,))
    options = dialog.options()
    if kind == "checklist":
        major = dialog.major_filter()
        vendor_id, pm_assignee_id, assignment_label = dialog.assignment_filter()
    else:
        vendor_id, pm_assignee_id, assignment_label = None, None, ""
    filename = default_pdf_filename(event, kind, options, major=major, scope_label=assignment_label)
    path, _ = QFileDialog.getSaveFileName(
        parent, "PDF로 내보내기", filename, "PDF (*.pdf)",
        options=QFileDialog.Option.DontConfirmOverwrite,
    )
    if not path:
        return None
    destination = Path(path)
    if destination.suffix.lower() != ".pdf":
        destination = destination.with_suffix(".pdf")
    destination = next_available_pdf_path(destination)
    try:
        if kind == "checklist":
            result = exporter(
                db, int(event_id), destination, options, major,
                vendor_id, pm_assignee_id, assignment_label,
            )
        else:
            result = exporter(db, int(event_id), destination, options)
    except Exception as exc:
        QMessageBox.critical(parent, "PDF 내보내기 실패", f"PDF 파일을 만들지 못했습니다.\n\n{exc}")
        return None
    QMessageBox.information(parent, "내보내기 완료", f"PDF 파일을 저장했습니다.\n{result}")
    return result


def export_calendar_pdf_from_page(parent, db, event_id, year, month, exporter) -> Path | None:
    if not event_id:
        QMessageBox.information(parent, "행사 선택", "PDF로 내보낼 행사를 선택하세요.")
        return None
    rows = db.query(
        """SELECT DISTINCT major,minor FROM event_tasks
           WHERE event_id=? AND is_removed=0 ORDER BY sort_order,major,minor""",
        (event_id,),
    )
    categories = []
    for row in rows:
        major = row["major"]
        pair = next((item for item in categories if item[0] == major), None)
        if pair is None:
            pair = (major, [])
            categories.append(pair)
        if row["minor"] not in pair[1]:
            pair[1].append(row["minor"])
    vendors, pm_assignees = _assignment_choices(db, event_id)
    dialog = CalendarPdfExportDialog(categories, vendors, pm_assignees, parent)
    if not dialog.exec():
        return None
    event = db.one("SELECT * FROM events WHERE id=?", (event_id,))
    options = dialog.options()
    major, minor = dialog.filters()
    vendor_id, pm_assignee_id, assignment_label = dialog.assignment_filter()
    filename = default_pdf_filename(
        event, "calendar", options, major=major, minor=minor, scope_label=assignment_label,
    )
    path, _ = QFileDialog.getSaveFileName(
        parent, "달력 PDF로 내보내기", filename, "PDF (*.pdf)",
        options=QFileDialog.Option.DontConfirmOverwrite,
    )
    if not path:
        return None
    destination = Path(path)
    if destination.suffix.lower() != ".pdf":
        destination = destination.with_suffix(".pdf")
    destination = next_available_pdf_path(destination)
    try:
        result = exporter(
            db, int(event_id), destination, int(year), int(month), options, major, minor,
            vendor_id, pm_assignee_id, assignment_label,
        )
    except Exception as exc:
        QMessageBox.critical(parent, "PDF 내보내기 실패", f"PDF 파일을 만들지 못했습니다.\n\n{exc}")
        return None
    QMessageBox.information(parent, "내보내기 완료", f"PDF 파일을 저장했습니다.\n{result}")
    return result
