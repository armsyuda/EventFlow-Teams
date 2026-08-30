from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget,
)


class StartupSplash(QWidget):
    """Small first-paint window shown before the heavier application modules load."""

    def __init__(self):
        super().__init__(None)
        self.setObjectName("StartupSplash")
        self.setWindowTitle("이벤트 플로우 시작 중")
        self.setWindowFlags(
            Qt.WindowType.SplashScreen
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(420, 214)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        card = QFrame(); card.setObjectName("SplashCard")
        layout = QVBoxLayout(card); layout.setContentsMargins(28, 26, 28, 24); layout.setSpacing(14)

        brand = QHBoxLayout(); brand.setSpacing(12)
        mark = QLabel("이플"); mark.setObjectName("SplashMark"); mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(46, 46)
        names = QVBoxLayout(); names.setSpacing(2)
        title = QLabel("이벤트 플로우"); title.setObjectName("SplashTitle")
        subtitle = QLabel("프로젝트 준비를 더 명확하게"); subtitle.setObjectName("SplashSubtitle")
        names.addWidget(title); names.addWidget(subtitle)
        brand.addWidget(mark); brand.addLayout(names); brand.addStretch()
        layout.addLayout(brand)

        self.status = QLabel("프로그램을 준비하고 있습니다…")
        self.status.setObjectName("SplashStatus")
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setObjectName("SplashProgress")
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(7)
        layout.addWidget(self.progress)
        outer.addWidget(card)

        self.setStyleSheet("""
            QWidget#StartupSplash { background: transparent; }
            QFrame#SplashCard {
                background: #FFFFFF;
                border: 1px solid #E5E7EB;
                border-radius: 18px;
            }
            QLabel { font-family: "Segoe UI", "Malgun Gothic", sans-serif; color: #212124; }
            QLabel#SplashMark {
                color: #FFFFFF;
                background: #F25B24;
                border-radius: 12px;
                font-size: 15px;
                font-weight: 700;
            }
            QLabel#SplashTitle { font-size: 21px; font-weight: 700; }
            QLabel#SplashSubtitle { color: #868B94; font-size: 12px; }
            QLabel#SplashStatus { color: #686B70; font-size: 13px; padding-top: 6px; }
            QProgressBar#SplashProgress {
                background: #FFF0E8;
                border: none;
                border-radius: 3px;
            }
            QProgressBar#SplashProgress::chunk {
                background: #F25B24;
                border-radius: 3px;
                width: 54px;
            }
        """)
        self._center_on_screen()

    def _center_on_screen(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(area.center() - self.rect().center())

    def set_status(self, text: str) -> None:
        self.status.setText(text)
        QApplication.processEvents()

    def finish(self, window) -> None:
        QApplication.processEvents()
        self.close()
        window.raise_()
        window.activateWindow()
