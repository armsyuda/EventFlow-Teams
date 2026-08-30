from __future__ import annotations

import argparse
import os
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from .config import ensure_directories
from .ui.startup_splash import StartupSplash


def _arguments(argv=None):
    parser = argparse.ArgumentParser(description="이벤트 플로우")
    parser.add_argument("--smoke-test", action="store_true", help="창을 초기화한 뒤 자동 종료")
    parser.add_argument("--data-dir", help="개발·검증용 사용자 데이터 폴더")
    parser.add_argument("--screenshot", help="검수용으로 창 이미지를 저장한 뒤 종료")
    parser.add_argument("--page", type=int, choices=range(0, 5), default=0, help="검수용 시작 화면 번호")
    parser.add_argument("--update-health-file", help=argparse.SUPPRESS)
    parser.add_argument("--restarting-after-update", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _arguments(argv)
    if args.data_dir:
        os.environ["EVENT_CHECKLIST_DATA_DIR"] = args.data_dir
    ensure_directories()

    qt_app = QApplication(sys.argv[:1])
    qt_app.setApplicationName("이벤트 플로우")
    qt_app.setOrganizationName("EventFlow")
    qt_app.setStyle("Fusion")

    # A package started outside the stable install folder is only a bootstrap
    # process: it copies the app and immediately starts the real process. Do
    # not show a splash here, otherwise users see one splash per process.
    from .install_service import is_fixed_installation, is_packaged_app, is_review_build, launch_fixed_installation, repair_shortcuts

    normal_start = not args.smoke_test and not args.screenshot
    if is_packaged_app() and normal_start and not is_fixed_installation() and not is_review_build():
        launch_fixed_installation(os.getpid())
        return 0
    if is_packaged_app() and normal_start:
        repair_shortcuts()

    show_splash = normal_start
    splash = StartupSplash() if show_splash else None
    if splash is not None:
        splash.show()
        splash.set_status(
            "새 버전으로 다시 시작하고 있습니다…"
            if args.restarting_after_update else "실행 환경을 확인하고 있습니다…"
        )

    # Keep the first paint lightweight. These modules pull in every page and
    # spreadsheet/export dependency, so load them only after the splash exists.
    from .backup import create_rotating_auto_backup
    from .config import backup_dir, database_path, history_dir
    from .database import Database
    from .theme import ComboPopupPolisher, InteractionCursorPolisher, application_stylesheet
    from .ui.main_window import MainWindow
    from .ui.title_bar import app_icon

    if splash is not None:
        splash.set_status("화면 디자인을 준비하고 있습니다…")
    qt_app.setWindowIcon(app_icon())
    qt_app.setStyleSheet(application_stylesheet())
    popup_polisher = ComboPopupPolisher(qt_app)
    qt_app.installEventFilter(popup_polisher)
    cursor_polisher = InteractionCursorPolisher(qt_app)
    qt_app.installEventFilter(cursor_polisher)
    db = None
    try:
        if splash is not None:
            splash.set_status("프로젝트 데이터를 확인하고 있습니다…")
        db = Database(database_path())
        if not any(backup_dir().glob("auto_event_flow_*.db")):
            create_rotating_auto_backup(db, backup_dir(), keep=10)
        db.enable_history(history_dir(), limit=50)
        if splash is not None:
            splash.set_status("대시보드를 구성하고 있습니다…")
        window = MainWindow(db, enable_update_check=not args.smoke_test and not args.screenshot)
        if args.page:
            window.nav_buttons[args.page].click()
        window.show()
        if splash is not None:
            splash.finish(window)
        if args.update_health_file:
            health_file = Path(args.update_health_file)
            QTimer.singleShot(500, lambda: health_file.write_text("ok", encoding="ascii"))
        if args.screenshot:
            def capture_and_quit():
                window.grab().save(args.screenshot)
                qt_app.quit()
            QTimer.singleShot(900, capture_and_quit)
        elif args.smoke_test:
            QTimer.singleShot(700, qt_app.quit)
        return qt_app.exec()
    except Exception as exc:
        traceback.print_exc()
        if splash is not None:
            splash.close()
        QMessageBox.critical(None, "시작 실패", f"프로그램을 시작하지 못했습니다.\n\n{exc}")
        return 1
    finally:
        if db is not None:
            db.cleanup_history()
            db.close()


if __name__ == "__main__":
    raise SystemExit(main())
