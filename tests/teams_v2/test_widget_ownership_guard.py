"""Static guard for Qt widgets that could briefly become native windows.

Qt adopts widgets when a layout receives them, but showing a widget before
that adoption turns it into a top-level native window for at least one event
loop cycle.  The guard intentionally covers both the Teams shell and the
embedded Local work UI because they share one frozen executable.
"""

from __future__ import annotations

import ast
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src"
UI_TREES = (SOURCE_ROOT / "eventflow_teams_v2", SOURCE_ROOT / "event_checklist")

# These two paths intentionally open independent windows: the update progress
# window and the last-resort startup error window.  Every other widget must be
# owned before it is made visible.
TOP_LEVEL_WINDOW_ALLOWLIST = {
    ("eventflow_teams_v2/app.py", 1164, "StartupSplash"),
    ("eventflow_teams_v2/app.py", 1482, "QMainWindow"),
    ("event_checklist/app.py", 89, "MainWindow"),
    ("event_checklist/ui/main_window.py", 380, "StartupSplash"),
}

QT_WIDGET_BASES = {
    "QWidget", "QFrame", "QDialog", "QMainWindow", "QLabel", "QPushButton",
    "QCheckBox", "QComboBox", "QLineEdit", "QPlainTextEdit", "QTextEdit",
    "QTableWidget", "QTreeWidget", "QListWidget", "QScrollArea", "QCalendarWidget",
    "QDateEdit", "QSpinBox", "QProgressBar", "QSplitter", "QTabWidget",
    "QStackedWidget", "QDockWidget", "QToolButton", "QGroupBox", "QMenu",
    "QMessageBox", "QFileDialog",
}
ATTACH_METHODS = {
    "addWidget", "insertWidget", "setWidget", "setCentralWidget", "setCellWidget",
    "setItemWidget", "addTab", "insertTab", "addPermanentWidget", "addRow",
}
DISPLAY_METHODS = {"show", "open", "exec", "exec_", "raise_", "activateWindow"}


def _reference(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _reference(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _is_explicitly_parented(call: ast.Call, known_widgets: set[str]) -> bool:
    if any(keyword.arg == "parent" and not isinstance(keyword.value, ast.Constant) for keyword in call.keywords):
        return True
    # A text variable (for example ``QPushButton(company.name)``) is not a
    # parent.  Treat only ``self``, a declared parent parameter, or a widget
    # already known in this scope as an explicit parent.
    for argument in call.args:
        reference = _reference(argument)
        if reference == "self" or reference == "parent" or (reference and reference.startswith("self.")):
            return True
        if reference in known_widgets:
            return True
    return False


def _iter_scope_nodes(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.AST]:
    nodes: list[ast.AST] = []

    def visit(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if child is not function and isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
                continue
            nodes.append(child)
            visit(child)

    visit(function)
    return sorted(nodes, key=lambda node: (getattr(node, "lineno", -1), getattr(node, "col_offset", -1)))


def _widget_class_names(trees: dict[Path, ast.Module]) -> set[str]:
    names = set(QT_WIDGET_BASES)
    changed = True
    while changed:
        changed = False
        for tree in trees.values():
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                bases = {_reference(base) or "" for base in node.bases}
                if node.name not in names and names.intersection(bases):
                    names.add(node.name)
                    changed = True
    return names


def _violations_for_function(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    widget_classes: set[str],
    relative_path: str,
) -> list[str]:
    ownership: dict[str, tuple[bool, str]] = {}
    violations: list[str] = []
    for node in _iter_scope_nodes(function):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if isinstance(value, ast.Call) and (_call_name(value) in widget_classes):
                for target_node in targets:
                    target = _reference(target_node)
                    if target:
                        ownership[target] = (
                            _is_explicitly_parented(value, set(ownership)),
                            _call_name(value) or target,
                        )
            continue
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        method = node.func.attr
        receiver = _reference(node.func.value)
        if method in ATTACH_METHODS:
            for argument in node.args:
                target = _reference(argument)
                if target in ownership:
                    ownership[target] = (True, ownership[target][1])
            continue
        if method == "setParent" and receiver in ownership:
            ownership[receiver] = (True, ownership[receiver][1])
            continue
        visible = method in DISPLAY_METHODS
        if method == "setVisible" and node.args:
            visible = not (isinstance(node.args[0], ast.Constant) and node.args[0].value is False)
        if visible and receiver in ownership and not ownership[receiver][0]:
            widget_class = ownership[receiver][1]
            if (relative_path, node.lineno, widget_class) not in TOP_LEVEL_WINDOW_ALLOWLIST:
                violations.append(f"{relative_path}:{node.lineno} {receiver}.{method}() before ownership")
    return violations


def test_no_embedded_widget_is_shown_before_it_has_an_owner() -> None:
    trees = {
        path: ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for root in UI_TREES
        for path in root.rglob("*.py")
    }
    widget_classes = _widget_class_names(trees)
    violations = [
        violation
        for path, tree in trees.items()
        for function in ast.walk(tree)
        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
        for violation in _violations_for_function(function, widget_classes, path.relative_to(SOURCE_ROOT).as_posix())
    ]
    assert not violations, "\n".join(violations)
