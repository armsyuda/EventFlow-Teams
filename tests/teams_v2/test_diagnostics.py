from PySide6.QtWidgets import QApplication, QLabel

from eventflow_teams_v2.diagnostics import RuntimeWindowTrace


def test_runtime_window_trace_records_only_technical_widget_metadata(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    trace = RuntimeWindowTrace(tmp_path)
    app.installEventFilter(trace)
    try:
        label = QLabel("sensitive display text")
        label.setObjectName("TraceLabel")
        label.show()
        app.processEvents()
        label.close()
        app.processEvents()

        contents = trace.path.read_text(encoding="utf-8")
        assert "trace_started" in contents
        assert "widget=QLabel" in contents
        assert "sensitive display text" not in contents
        assert "TraceLabel" in contents
    finally:
        app.removeEventFilter(trace)
