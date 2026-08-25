from __future__ import annotations

from importlib.resources import files

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QAbstractButton, QComboBox, QListView, QTabBar, QTreeView


TOKENS = {
    "bg_basement": "#F7F8FA",
    "bg_layer": "#FFFFFF",
    "bg_weak": "#F2F3F5",
    "fg_neutral": "#212124",
    "fg_muted": "#686B70",
    "fg_subtle": "#868B94",
    "stroke": "#E5E7EB",
    "brand": "#F25B24",
    "brand_pressed": "#D84B18",
    "brand_weak": "#FFF0E8",
    "positive": "#18864B",
    "positive_weak": "#E8F7EF",
    "warning": "#9A6700",
    "warning_weak": "#FFF5CC",
    "critical": "#C9342C",
    "critical_weak": "#FDECEC",
    "informative": "#1769AA",
    "informative_weak": "#EAF3FB",
}


class ComboPopupPolisher(QObject):
    """Remove the native square background around rounded combo popups."""

    def eventFilter(self, watched, event):
        if (
            event.type() == QEvent.Type.Polish
            and watched.metaObject().className() == "QComboBoxPrivateContainer"
        ):
            watched.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            watched.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
            watched.setAutoFillBackground(False)
        return False


class InteractionCursorPolisher(QObject):
    """Use a hand cursor for controls and selectable lists that react to clicks."""

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Polish and isinstance(
            watched, (QAbstractButton, QComboBox, QTabBar, QListView, QTreeView)
        ):
            watched.setCursor(Qt.CursorShape.PointingHandCursor)
            if isinstance(watched, (QListView, QTreeView)):
                watched.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        return False


def application_stylesheet() -> str:
    c = TOKENS
    checkmark = str(files("event_checklist").joinpath("resources/assets/checkmark.svg")).replace("\\", "/")
    minus = str(files("event_checklist").joinpath("resources/assets/minus.svg")).replace("\\", "/")
    return f"""
    * {{
        font-family: "Segoe UI", "Malgun Gothic", sans-serif;
        font-size: 14px;
        color: {c['fg_neutral']};
    }}
    QMainWindow, QWidget#AppRoot {{ background: {c['stroke']}; }}
    QFrame#TitleBar {{ background: {c['bg_layer']}; border-bottom: 1px solid {c['stroke']}; }}
    QPushButton#MenuToggleButton {{ border: none; border-radius: 0; background: transparent; font-size: 22px; padding: 0; }}
    QPushButton#MenuToggleButton:hover {{ background: {c['bg_weak']}; color: {c['brand']}; }}
    QPushButton#MenuToggleButton:pressed {{ background: {c['brand_weak']}; }}
    QLabel#TitleBarName {{ font-weight: 700; font-size: 14px; }}
    QLabel#TitleBarEvent {{ color: {c['fg_muted']}; border-left: 1px solid {c['stroke']}; padding-left: 10px; }}
    QLabel#UpdateMeta {{ color: {c['fg_muted']}; font-size: 12px; padding: 0 4px 0 10px; }}
    QPushButton#TitleControlButton, QPushButton#TitleCloseButton {{
        min-height: 44px; padding: 0; border: none; border-radius: 0; background: transparent; font-size: 16px;
    }}
    QPushButton#TitleControlButton:hover {{ background: {c['bg_weak']}; }}
    QPushButton#TitleCloseButton:hover {{ background: #D9363E; color: white; }}
    QPushButton#UpdateButton {{ min-height: 30px; padding: 0 12px; color: {c['fg_muted']}; background: {c['bg_weak']}; border: none; }}
    QPushButton#UpdateButton:enabled {{ color: white; background: {c['brand']}; }}
    QPushButton#UpdateButton:enabled:hover {{ background: {c['brand_pressed']}; }}
    QFrame#Sidebar {{ background: {c['bg_layer']}; border-right: 1px solid {c['stroke']}; }}
    QFrame#SidebarSeparator {{ background: {c['stroke']}; border: none; max-height: 1px; }}
    QPushButton#HistoryButton {{ min-width: 0; min-height: 38px; padding: 0; font-size: 24px; font-weight: 700; }}
    QPushButton#HistoryButton:disabled {{ color: #C7CAD0; background: {c['bg_weak']}; }}
    QPushButton#SidebarSaveButton {{ min-height: 40px; font-weight: 700; color: {c['brand']}; background: {c['brand_weak']}; border-color: #FFD0BC; }}
    QPushButton#SidebarSaveButton:hover {{ background: #FFE2D6; }}
    QLabel#AppTitle {{ font-size: 18px; font-weight: 700; color: {c['brand']}; padding: 8px; }}
    QLabel#PageTitle {{ font-size: 26px; font-weight: 700; }}
    QLabel#PageDescription, QLabel#Muted {{ color: {c['fg_muted']}; }}
    QLabel#ChecklistCount {{ color: #A06F59; padding-left: 4px; }}
    QLabel#SectionTitle {{ font-size: 18px; font-weight: 700; }}
    QLabel#InfoGuide {{
        color: {c['informative']}; background: {c['informative_weak']};
        border: 1px solid #C9DFF2; border-radius: 8px; padding: 10px 12px;
    }}
    QPushButton {{
        min-height: 40px; padding: 0 16px; border: 1px solid {c['stroke']};
        border-radius: 8px; background: {c['bg_layer']}; font-weight: 600;
    }}
    QPushButton:hover {{ background: {c['bg_weak']}; }}
    QPushButton:pressed {{ background: #E9EAEC; }}
    QPushButton:focus, QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QDoubleSpinBox:focus {{
        border: 2px solid {c['brand']};
    }}
    QPushButton[primary="true"] {{ background: {c['brand']}; color: white; border: none; }}
    QPushButton[primary="true"]:hover {{ background: {c['brand_pressed']}; }}
    QPushButton[attention="true"] {{ color: {c['brand']}; border: 2px solid {c['brand']}; font-weight: 700; background: {c['bg_layer']}; }}
    QPushButton[attention="true"]:hover {{ color: white; background: {c['brand']}; }}
    QPushButton[quiet="true"] {{ color: {c['fg_muted']}; background: {c['bg_weak']}; border-color: {c['stroke']}; }}
    QPushButton[quiet="true"]:checked {{ color: {c['brand']}; background: {c['brand_weak']}; border-color: #F7C5AE; }}
    QPushButton[checklistAction="true"] {{ min-height: 42px; max-height: 42px; font-size: 13px; }}
    QPushButton[checklistAction="true"][primary="true"] {{ min-height: 44px; max-height: 44px; }}
    QPushButton[checklistAction="true"][attention="true"] {{ min-height: 40px; max-height: 40px; }}
    QWidget[checklistCompact="true"] {{ font-size: 13px; }}
    QPushButton#PdfExportButton {{ min-width: 0px; min-height: 0px; padding: 8px; background: {c['bg_layer']}; }}
    QPushButton#PdfExportButton:hover {{ background: {c['brand_weak']}; border-color: #F7C5AE; }}
    QRadioButton[pdfOption="true"] {{ background: {c['bg_layer']}; border: 1px solid {c['stroke']}; border-radius: 8px; padding: 0 14px; font-weight: 700; }}
    QRadioButton[pdfOption="true"]:checked {{ color: {c['brand']}; background: {c['brand_weak']}; border: 2px solid {c['brand']}; }}
    QRadioButton[pdfOption="true"]::indicator {{ width: 0px; height: 0px; }}
    QPushButton[danger="true"] {{ color: {c['critical']}; border-color: #F2BBB7; }}
    QPushButton[nav="true"] {{
        min-height: 44px; text-align: left; border: none; border-radius: 8px;
        padding-left: 16px; color: {c['fg_muted']};
    }}
    QPushButton[nav="true"]:checked {{ background: {c['brand_weak']}; color: {c['brand']}; font-weight: 700; }}
    QPushButton[nav="true"]:disabled {{ color: #B1B5BC; background: transparent; }}
    QFrame#Card {{ background: {c['bg_layer']}; border: 1px solid {c['stroke']}; border-radius: 12px; }}
    QFrame#EventCard {{ background: {c['bg_layer']}; border: 1px solid {c['stroke']}; border-radius: 12px; }}
    QFrame#EventCard:hover {{ background: {c['brand_weak']}; border-color: #F7C5AE; }}
    QFrame#EventCard:focus {{ border: 2px solid {c['brand']}; }}
    QLabel#EventCardTitle {{ font-size: 16px; font-weight: 700; }}
    QScrollArea#EventListArea {{ border: none; background: transparent; }}
    QScrollArea#EventListArea > QWidget > QWidget {{ background: transparent; }}
    QLabel#EmptyState {{ color: {c['fg_muted']}; background: {c['bg_layer']}; border: 1px dashed {c['stroke']}; border-radius: 12px; }}
    QLabel#KpiValue {{ font-size: 24px; font-weight: 700; }}
    QLineEdit, QComboBox, QDateEdit, QDoubleSpinBox, QSpinBox, QTextEdit {{
        min-height: 40px; background: {c['bg_layer']}; border: 1px solid {c['stroke']};
        border-radius: 8px; padding: 0 10px; selection-background-color: {c['brand']};
    }}
    QTextEdit {{ padding: 8px; }}
    QComboBox::drop-down {{ border: none; width: 28px; }}
    QDateEdit[directCalendar="true"] {{ padding-right: 10px; }}
    QDateEdit[directCalendar="true"] QLineEdit {{ background: transparent; border: none; padding: 0; }}
    QDateEdit[directCalendar="true"]::drop-down {{ width: 0px; border: none; background: transparent; }}
    QDateEdit[directCalendar="true"]::down-arrow {{ image: none; width: 0px; height: 0px; }}
    QComboBox QAbstractItemView {{
        background: {c['bg_layer']}; color: {c['fg_neutral']}; border: 1px solid {c['stroke']};
        border-radius: 9px; padding: 5px; outline: none;
        selection-background-color: {c['brand_weak']}; selection-color: {c['brand_pressed']};
    }}
    QComboBoxPrivateContainer {{ background: transparent; border: none; padding: 0; }}
    QComboBox QAbstractItemView::item {{ min-height: 34px; padding: 0 9px; border-radius: 6px; }}
    QComboBox QAbstractItemView::item:selected {{ background: {c['brand_weak']}; color: {c['brand_pressed']}; }}
    QCheckBox {{ spacing: 8px; }}
    QCheckBox::indicator, QTreeView::indicator, QListView::indicator {{
        width: 19px; height: 19px; border: 1px solid #C9CDD3; border-radius: 5px; background: {c['bg_layer']};
    }}
    QCheckBox::indicator:hover, QTreeView::indicator:hover, QListView::indicator:hover {{ border-color: {c['brand']}; }}
    QCheckBox::indicator:checked, QTreeView::indicator:checked, QListView::indicator:checked {{
        background: {c['brand']}; border-color: {c['brand']}; image: url("{checkmark}");
    }}
    QCheckBox::indicator:indeterminate, QTreeView::indicator:indeterminate, QListView::indicator:indeterminate {{
        background: {c['brand']}; border-color: {c['brand']}; image: url("{minus}");
    }}
    QCheckBox::indicator:disabled, QTreeView::indicator:disabled, QListView::indicator:disabled {{
        background: {c['bg_weak']}; border-color: {c['stroke']};
    }}
    QTableWidget, QTreeWidget, QListWidget, QCalendarWidget {{
        background: {c['bg_layer']}; border: 1px solid {c['stroke']}; border-radius: 10px;
        gridline-color: {c['stroke']}; selection-background-color: {c['brand_weak']};
        selection-color: {c['fg_neutral']}; outline: none;
    }}
    QTableWidget {{ alternate-background-color: #FAFAFB; }}
    QListWidget {{ alternate-background-color: #FAFAFB; }}
    QListWidget#UrgentList {{ background: transparent; border: none; }}
    QListWidget#UrgentList::item {{ border: 1px solid {c['stroke']}; border-radius: 8px; padding: 0 14px; }}
    QListWidget#UrgentList::item:selected {{ border: 1px solid {c['brand']}; color: {c['fg_neutral']}; }}
    QCalendarWidget QWidget#qt_calendar_navigationbar {{ background: {c['bg_weak']}; }}
    QCalendarWidget QToolButton {{
        background: transparent; color: {c['fg_neutral']}; border: none; font-weight: 700;
    }}
    QCalendarWidget QAbstractItemView:enabled {{
        background: {c['bg_layer']}; color: {c['fg_neutral']};
        selection-background-color: {c['brand_weak']}; selection-color: {c['fg_neutral']};
        alternate-background-color: {c['bg_layer']};
    }}
    QHeaderView {{ background: {c['bg_weak']}; }}
    QHeaderView::section {{
        background: {c['bg_weak']}; color: {c['fg_muted']}; border: none;
        border-bottom: 1px solid {c['stroke']}; padding: 10px; font-weight: 700;
    }}
    QHeaderView[columnResizeGuides="true"]::section:horizontal {{
        border-right: 1px solid #C9CDD3;
    }}
    QHeaderView[columnResizeGuides="true"]::section:horizontal:hover {{
        border-right: 2px solid {c['brand']};
    }}
    QTableCornerButton::section {{ background: {c['bg_weak']}; border: none; border-bottom: 1px solid {c['stroke']}; }}
    QTableWidget::item {{ padding: 7px; }}
    QTableWidget[embeddedEditors="true"]::item {{ padding: 3px 7px; }}
    QProgressBar {{ min-height: 14px; border: none; border-radius: 7px; background: {c['bg_weak']}; text-align: center; }}
    QProgressBar::chunk {{ background: {c['brand']}; border-radius: 7px; }}
    QScrollBar:vertical {{
        background: {c['bg_weak']}; width: 12px; margin: 2px; border: none; border-radius: 6px;
    }}
    QScrollBar::handle:vertical {{
        background: #C9CDD3; min-height: 32px; border-radius: 4px; margin: 1px;
    }}
    QScrollBar::handle:vertical:hover {{ background: #AEB4BC; }}
    QScrollBar:horizontal {{
        background: {c['bg_weak']}; height: 12px; margin: 2px; border: none; border-radius: 6px;
    }}
    QScrollBar::handle:horizontal {{
        background: #C9CDD3; min-width: 32px; border-radius: 4px; margin: 1px;
    }}
    QScrollBar::handle:horizontal:hover {{ background: #AEB4BC; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none; background: transparent; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QTabWidget::pane {{
        background: {c['bg_layer']}; border: 1px solid {c['stroke']}; border-radius: 10px;
        top: -1px;
    }}
    QTabBar {{ background: transparent; }}
    QTabBar::tab {{
        background: {c['bg_weak']}; color: {c['fg_muted']}; border: 1px solid {c['stroke']};
        padding: 11px 24px; min-width: 88px; margin-right: 4px;
        border-top-left-radius: 8px; border-top-right-radius: 8px;
    }}
    QTabBar::tab:selected {{ background: {c['bg_layer']}; color: {c['brand']}; border-bottom-color: {c['bg_layer']}; font-weight: 700; }}
    QTabBar::tab:hover:!selected {{ background: {c['brand_weak']}; color: {c['brand']}; }}
    QSplitter::handle {{ background: {c['bg_weak']}; border-radius: 3px; }}
    QSplitter::handle:hover {{ background: #DDE0E4; }}
    QFrame#CalendarSide {{ background: {c['bg_weak']}; border: 1px solid {c['stroke']}; border-radius: 12px; }}
    QFrame#EventItemsPanel {{ background: {c['bg_layer']}; border: 1px solid {c['stroke']}; border-radius: 12px; }}
    QListWidget#CalendarTaskList {{ background: transparent; border: none; }}
    QListWidget#CalendarTaskList::item {{ background: transparent; border: none; }}
    QListWidget#CalendarTaskList::item:selected {{ background: transparent; color: {c['fg_neutral']}; }}
    QFrame#CalendarTaskCard {{ background: {c['bg_layer']}; border: 1px solid {c['stroke']}; border-radius: 10px; }}
    QFrame#CalendarTaskCard[urgency="critical"] {{ background: {c['critical_weak']}; border-color: #F1BBB7; }}
    QFrame#CalendarTaskCard[urgency="dueToday"] {{ background: {c['warning_weak']}; border: 2px solid {c['warning']}; }}
    QFrame#CalendarTaskCard[urgency="warning"] {{ background: {c['warning_weak']}; border-color: #E9D77E; }}
    QFrame#CalendarTaskCard[urgency="completed"] {{ background: {c['positive_weak']}; border-color: #B9DEC9; }}
    QLabel#DueTodayGuide {{ color: #8A4B08; font-size: 12px; font-weight: 700; }}
    QLabel#CalendarEventName {{ color: {c['fg_muted']}; font-size: 12px; }}
    QLabel#CalendarTaskName {{ color: {c['fg_neutral']}; font-size: 15px; font-weight: 700; }}
    QLabel#StatusBadge {{ border-radius: 9px; padding: 3px 8px; font-size: 12px; font-weight: 700; }}
    QPushButton[compact="true"] {{ min-height: 30px; padding: 0 10px; border-radius: 7px; font-size: 12px; }}
    QPushButton[compact="true"][calendarCardAction="true"] {{ min-height: 22px; max-height: 22px; padding: 0 7px; border-radius: 6px; font-size: 11px; }}
    QPushButton[success="true"] {{ color: {c['positive']}; background: {c['positive_weak']}; border-color: #B9DEC9; }}
    QPushButton[warning="true"] {{ color: {c['warning']}; background: {c['warning_weak']}; border-color: #E9D77E; }}
    QDialog {{ background: {c['bg_basement']}; }}
    QDialogButtonBox QPushButton {{ min-width: 96px; }}
    QToolTip {{ background: {c['fg_neutral']}; color: white; padding: 6px; border: none; }}
    """


def status_color(status: str) -> tuple[str, str]:
    return {
        "완료": (TOKENS["positive"], TOKENS["positive_weak"]),
        "진행중": (TOKENS["informative"], TOKENS["informative_weak"]),
        "확인요청": (TOKENS["warning"], TOKENS["warning_weak"]),
        "보류": (TOKENS["fg_muted"], TOKENS["bg_weak"]),
        "해당없음": (TOKENS["fg_subtle"], TOKENS["bg_weak"]),
        "미착수": (TOKENS["fg_muted"], TOKENS["bg_weak"]),
    }.get(status, (TOKENS["fg_neutral"], TOKENS["bg_layer"]))
