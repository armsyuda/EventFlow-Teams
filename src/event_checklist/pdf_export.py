from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QMarginsF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPageLayout, QPageSize, QPainter, QPdfWriter, QPen

from .services import EventService


@dataclass(frozen=True)
class PdfOptions:
    paper: str = "A4"
    orientation: str = "PORTRAIT"

    def __post_init__(self):
        if self.paper not in {"A4", "A3"}:
            raise ValueError("PDF 용지는 A4 또는 A3만 사용할 수 있습니다.")
        if self.orientation not in {"PORTRAIT", "LANDSCAPE"}:
            raise ValueError("PDF 방향은 세로 또는 가로만 사용할 수 있습니다.")


INK = QColor("#212124")
MUTED = QColor("#686B70")
SUBTLE = QColor("#868B94")
LINE = QColor("#E5E7EB")
SOFT = QColor("#F7F8FA")
HEADER = QColor("#EEF0F3")
BRAND = QColor("#F25B24")
BRAND_DARK = QColor("#D84B18")
BRAND_SOFT = QColor("#FFF0E8")
MINOR_SOFT = QColor("#F2F3F5")
STATUS = {
    "완료": (QColor("#18864B"), QColor("#E8F7EF")),
    "진행중": (QColor("#1769AA"), QColor("#EAF3FB")),
    "확인요청": (QColor("#9A6700"), QColor("#FFF5CC")),
}
CALENDAR_CATEGORY_COLORS = {
    "시스템": QColor("#D8E8F6"),
    "시설": QColor("#DCEFE3"),
    "행사": QColor("#FCE1D6"),
    "홍보": QColor("#E7DFF3"),
    "운영": QColor("#F5EACB"),
}


def _money(value) -> str:
    return f"{int(value or 0):,}원"


def _short_date(value) -> str:
    value = str(value or "").strip()
    return value[5:].replace("-", ".") if len(value) >= 10 else (value or "미입력")


def _safe_filename(value: str) -> str:
    clean = "".join("_" if char in '<>:"/\\|?*' else char for char in str(value)).strip(" .")
    return (clean[:80].rstrip(" ._") or "프로젝트")


def default_pdf_filename(event, kind: str, options: PdfOptions = PdfOptions(), printed_on=None,
                         major: str = "", minor: str = "", scope_label: str = "") -> str:
    label = {"checklist": "체크리스트", "settlement": "정산내역", "calendar": "달력"}[kind]
    output_date = (printed_on or date.today()).strftime("%Y%m%d")
    orientation = "세로" if options.orientation == "PORTRAIT" else "가로"
    parts = [label, _safe_filename(event["name"])]
    if major:
        parts.append(_safe_filename(major))
    if minor:
        parts.append(_safe_filename(minor))
    if scope_label:
        parts.append(_safe_filename(scope_label))
    parts.extend([output_date, f"{options.paper}{orientation}"])
    return "_".join(parts) + ".pdf"


def next_available_pdf_path(path: Path) -> Path:
    """Keep every export by appending _2, _3, ... when a name already exists."""
    path = Path(path)
    if not path.exists():
        return path
    index = 2
    while True:
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


class _PdfCanvas:
    def __init__(self, destination: Path, options: PdfOptions):
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.writer = QPdfWriter(str(destination))
        self.writer.setResolution(144)
        page_size = QPageSize(QPageSize.PageSizeId.A4 if options.paper == "A4" else QPageSize.PageSizeId.A3)
        orientation = (
            QPageLayout.Orientation.Portrait
            if options.orientation == "PORTRAIT"
            else QPageLayout.Orientation.Landscape
        )
        self.writer.setPageLayout(QPageLayout(page_size, orientation, QMarginsF(0, 0, 0, 0)))
        self.writer.setTitle("Event Flow PDF")
        self.painter = QPainter(self.writer)
        if not self.painter.isActive():
            raise OSError("PDF 파일을 만들 수 없습니다.")
        self.page = 0
        self.width = float(self.writer.width())
        self.height = float(self.writer.height())
        if options.paper == "A4":
            base_w, base_h = ((595.28, 841.89) if options.orientation == "PORTRAIT" else (841.89, 595.28))
        else:
            base_w, base_h = ((841.89, 1190.55) if options.orientation == "PORTRAIT" else (1190.55, 841.89))
        self.sx = self.width / base_w
        self.sy = self.height / base_h
        self.scale = min(self.sx, self.sy)

    def close(self):
        self.painter.end()

    def new_page(self):
        if self.page:
            self.writer.newPage()
        self.page += 1
        self.painter.fillRect(QRectF(0, 0, self.width, self.height), QColor("white"))
        self.painter.fillRect(QRectF(0, 0, self.width, 5 * self.scale), BRAND)

    def rect(self, x, y, w, h, fill=None, stroke=None, radius=0):
        rect = QRectF(x, y, w, h)
        self.painter.setBrush(fill if fill is not None else Qt.BrushStyle.NoBrush)
        self.painter.setPen(QPen(stroke, max(0.7, self.scale * 0.55)) if stroke is not None else Qt.PenStyle.NoPen)
        if radius:
            self.painter.drawRoundedRect(rect, radius, radius)
        else:
            self.painter.drawRect(rect)

    def line(self, x1, y1, x2, y2, color=LINE, width=0.55):
        self.painter.setPen(QPen(color, max(0.6, width * self.scale)))
        self.painter.drawLine(x1, y1, x2, y2)

    def text(self, rect, value, size=8, color=INK, bold=False, align=Qt.AlignmentFlag.AlignLeft,
             wrap=False, elide=True):
        value = str(value or "")
        font = QFont("Malgun Gothic", size)
        font.setBold(bold)
        self.painter.setFont(font)
        self.painter.setPen(color)
        flags = align | Qt.AlignmentFlag.AlignVCenter
        if wrap:
            flags |= Qt.TextFlag.TextWordWrap
        elif elide:
            value = self.painter.fontMetrics().elidedText(value, Qt.TextElideMode.ElideRight, int(rect.width()))
        self.painter.drawText(rect, int(flags), value)

    def fitted_text(self, rect, value, size=11.5, min_size=6.5, color=INK, bold=True):
        """Draw a full title, shrinking first and wrapping only exceptionally long names."""
        value = str(value or "")
        chosen = float(size)
        while chosen > min_size:
            font = QFont("Malgun Gothic")
            font.setPointSizeF(chosen)
            font.setBold(bold)
            if QFontMetricsF(font, self.painter.device()).horizontalAdvance(value) <= rect.width():
                break
            chosen = max(min_size, chosen - 0.25)
        font = QFont("Malgun Gothic")
        font.setPointSizeF(chosen)
        font.setBold(bold)
        metrics = QFontMetricsF(font, self.painter.device())
        self.painter.setFont(font)
        self.painter.setPen(color)
        flags = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        if metrics.horizontalAdvance(value) > rect.width():
            flags |= Qt.TextFlag.TextWordWrap
        self.painter.drawText(rect, int(flags), value)
        return min(metrics.horizontalAdvance(value), rect.width())


def _scaled_rect(canvas, x, y, w, h):
    return QRectF(x * canvas.sx, y * canvas.sy, w * canvas.sx, h * canvas.sy)


def _page_metrics(options: PdfOptions):
    if options.paper == "A4":
        return (595.28, 841.89) if options.orientation == "PORTRAIT" else (841.89, 595.28)
    return (841.89, 1190.55) if options.orientation == "PORTRAIT" else (1190.55, 841.89)


class _Document:
    def __init__(self, destination, options, event, title, context_label):
        self.options = options
        self.event = event
        self.title = title
        self.context_label = context_label
        self.canvas = _PdfCanvas(destination, options)
        self.base_w, self.base_h = _page_metrics(options)
        self.margin = 26
        self.page_no = 0
        self.printed_at = datetime.now().strftime("%Y.%m.%d  %H:%M")

    def close(self):
        self.canvas.close()

    def start_page(self, summary_text):
        c = self.canvas
        c.new_page(); self.page_no += 1
        sx, sy = c.sx, c.sy
        def r(x, y, w, h): return _scaled_rect(c, x, y, w, h)
        c.text(r(self.margin, 15, 48, 12), "EVENT FLOW", 6.8, BRAND, True)
        c.text(r(self.margin + 48, 15, 145, 12), self.title, 6.8, MUTED, True)
        c.text(r(self.base_w - self.margin - 130, 15, 130, 12),
               f"출력  {self.printed_at}", 5.4, SUBTLE, False, Qt.AlignmentFlag.AlignRight)

        multiline_summary = "\n" in summary_text
        summary_w = (195 if self.base_w < 700 else 260) if multiline_summary else (130 if self.base_w < 700 else 205)
        period_w = 105 if self.base_w < 700 else 125
        gap = 7
        summary_x = self.base_w - self.margin - summary_w
        period_x = summary_x - gap - period_w
        title_w = max(100, period_x - gap - self.margin)
        title_rect = r(self.margin, 29, title_w, 24)
        c.fitted_text(title_rect, self.event["name"], 11.5, 6.0, INK, True)
        c.text(r(self.margin, 52, title_w, 10), self.context_label, 5.3, MUTED, True)
        c.line((period_x - 4) * sx, 37 * sy, (period_x - 4) * sx, 52 * sy)
        c.text(r(period_x, 36, period_w, 16), f"프로젝트 기간  {_event_period(self.event)}", 6.5, MUTED, True)
        c.text(
            r(summary_x, 34, summary_w, 22), summary_text, 5.2 if multiline_summary else 7,
            BRAND_DARK, True, Qt.AlignmentFlag.AlignRight,
            wrap=multiline_summary, elide=not multiline_summary,
        )
        c.line(self.margin * sx, 66 * sy, (self.base_w - self.margin) * sx, 66 * sy, LINE, 0.7)
        return 76

    def footer(self, note):
        c = self.canvas
        c.text(_scaled_rect(c, self.margin, self.base_h - 31, self.base_w * .68, 12), note, 6.5, MUTED)
        c.text(_scaled_rect(c, self.base_w - self.margin - 100, self.base_h - 31, 100, 12),
               f"Event Flow  ·  {self.page_no}", 6.5, MUTED, False, Qt.AlignmentFlag.AlignRight)


def _progress(tasks):
    counts = {key: 0 for key in ("완료", "진행중", "확인요청")}
    for task in tasks:
        if task["status"] in counts:
            counts[task["status"]] += 1
    return f"완료 {counts['완료']} · 진행 {counts['진행중']} · 확인 {counts['확인요청']}"


def _event_period(event):
    period = str(event["start_date"] or "")
    if event["end_date"]:
        period += f" - {str(event['end_date'])[5:]}"
    return period or "미입력"


def _group_ranges(rows, major_index=0, minor_index=1):
    major_ranges = []
    minor_ranges = []
    start = 0
    while start < len(rows):
        major = rows[start][major_index]
        end = start + 1
        while end < len(rows) and rows[end][major_index] == major:
            end += 1
        major_ranges.append((start, end, major))
        minor_start = start
        while minor_start < end:
            minor = rows[minor_start][minor_index]
            minor_end = minor_start + 1
            while minor_end < end and rows[minor_end][minor_index] == minor:
                minor_end += 1
            minor_ranges.append((minor_start, minor_end, minor))
            minor_start = minor_end
        start = end
    return major_ranges, minor_ranges


def _draw_groups(c, body_top, row_heights, rows, x, widths):
    prefix = [0]
    for height in row_heights:
        prefix.append(prefix[-1] + height)
    major_ranges, minor_ranges = _group_ranges(rows)
    for start, end, label in major_ranges:
        y = body_top + prefix[start]; h = prefix[end] - prefix[start]
        c.rect(x, y, widths[0], h, BRAND_SOFT, QColor("#F8D5C5"))
        c.text(QRectF(x, y, widths[0], h), label, 7, BRAND_DARK, True, Qt.AlignmentFlag.AlignCenter)
    mx = x + widths[0]
    for start, end, label in minor_ranges:
        y = body_top + prefix[start]; h = prefix[end] - prefix[start]
        c.rect(mx, y, widths[1], h, MINOR_SOFT, LINE)
        c.text(QRectF(mx, y, widths[1], h), label, 6.7, INK, True, Qt.AlignmentFlag.AlignCenter)


def _fit_rows(available, compact_height, roomy_height, count, compact_limit):
    if count <= compact_limit and count * compact_height <= available:
        return compact_height, 8
    return roomy_height, 10


def _checklist_standard_columns(total_width: float) -> tuple[list[str], list[float]]:
    """Return a complete, gap-free header and width model for wide checklist PDFs."""
    headers = [
        "순서", "대분류", "중분류", "항목", "세부내용", "수량", "단위", "상태", "작업 시작일", "마감일",
        "PM 담당자", "업체", "업체담당자", "전화번호",
    ]
    order_width = 24.0
    # 세부내용 비중을 일부 줄여 수량·단위 공간을 확보하고, 총 폭은 페이지 크기 안에 유지한다.
    ratios = [.050, .060, .120, .155, .045, .045, .052, .060, .060, .060, .065, .065, .068]
    data_width = max(0.0, total_width - order_width)
    ratio_total = sum(ratios)
    widths = [order_width] + [data_width * ratio / ratio_total for ratio in ratios]
    return headers, widths


def _checklist_standard(doc, tasks):
    c = doc.canvas; sx, sy = c.sx, c.sy
    landscape = doc.options.orientation == "LANDSCAPE"
    a3 = doc.options.paper == "A3"
    if a3 and not landscape:
        compact_h, roomy_h, compact_limit = 23, 28, 44
    elif a3:
        compact_h, roomy_h, compact_limit = 25, 31, 30
    else:
        compact_h, roomy_h, compact_limit = 22, 28, 18
    head_h = 29
    available = doc.base_h - 76 - 42 - head_h
    row_h, font_size = _fit_rows(available, compact_h, roomy_h, len(tasks), compact_limit)
    per_page = max(1, int(available // row_h))
    table_w = doc.base_w - 2 * doc.margin
    headers, all_widths_base = _checklist_standard_columns(table_w)
    order_w, widths_base = all_widths_base[0], all_widths_base[1:]
    for page_start in range(0, len(tasks) or 1, per_page):
        page_rows = tasks[page_start:page_start + per_page]
        y = doc.start_page(_progress(tasks))
        x = doc.margin + order_w
        c.rect(doc.margin * sx, y * sy, table_w * sx, head_h * sy, HEADER, None, 5 * c.scale)
        c.text(
            _scaled_rect(c, doc.margin, y, order_w, head_h), headers[0], 6.5, MUTED, True,
            Qt.AlignmentFlag.AlignCenter,
        )
        cx = x
        for label, width in zip(headers[1:], widths_base):
            c.text(_scaled_rect(c, cx, y, width, head_h), label, 6.5, MUTED, True, Qt.AlignmentFlag.AlignCenter)
            cx += width
        body_top = (y + head_h) * sy
        widths = [value * sx for value in widths_base]
        draw_rows = []
        for index, task in enumerate(page_rows):
            ry = body_top + index * row_h * sy
            rh = row_h * sy
            c.rect(doc.margin * sx, ry, order_w * sx, rh, QColor("white") if index % 2 == 0 else SOFT, LINE)
            c.text(QRectF(doc.margin * sx, ry, order_w * sx, rh), str(page_start + index + 1), font_size - 1.5, MUTED, False, Qt.AlignmentFlag.AlignCenter)
            values = [task["major"], task["minor"], task["name"], task["detail"],
                      str(int(task["quantity"] or 0)), task["unit"] or "식", task["status"],
                      _short_date(task["planned_start"]), _short_date(task["due_date"]),
                      task["pm_assignee_name"] or "미지정", task["vendor_name"] or "미지정",
                      task["assignee_name"] or "미지정", task["assignee_phone"] or ""]
            draw_rows.append(values)
            cx = x * sx
            for col, (value, width) in enumerate(zip(values, widths)):
                c.rect(cx, ry, width, rh, QColor("white") if index % 2 == 0 else SOFT, LINE)
                if col not in (0, 1):
                    if col == 7:
                        fg, bg = STATUS.get(str(value), (MUTED, MINOR_SOFT))
                        badge_w = min(width - 6 * sx, 38 * sx)
                        c.rect(cx + (width - badge_w) / 2, ry + (rh - 14 * sy) / 2, badge_w, 14 * sy, bg, None, 7 * c.scale)
                        c.text(QRectF(cx, ry, width, rh), value, font_size - 1.5, fg, True, Qt.AlignmentFlag.AlignCenter)
                    else:
                        # values 인덱스: 0 major, 1 minor, 2 name, 3 detail(세부내용), 4 quantity(수량), ...
                        align = Qt.AlignmentFlag.AlignLeft if col == 3 else Qt.AlignmentFlag.AlignCenter
                        pad = 4 * sx if align == Qt.AlignmentFlag.AlignLeft else 0
                        c.text(QRectF(cx + pad, ry, width - 2 * pad, rh), value, font_size - 1.2, INK, col == 2, align)
                cx += width
        _draw_groups(c, body_top, [row_h * sy] * len(draw_rows), draw_rows, x * sx, widths[:2])
        doc.footer(f"자동 출력 · {font_size}pt · 페이지당 최대 {per_page}행")


def _checklist_a4_portrait(doc, tasks):
    c = doc.canvas; sx, sy = c.sx, c.sy
    head_h, compact_h, roomy_h, compact_limit = 34, 21.5, 26, 28
    available = doc.base_h - 76 - 42 - head_h
    row_h, font_size = _fit_rows(available, compact_h, roomy_h, len(tasks), compact_limit)
    per_page = max(1, int(available // row_h))
    # 열 폭 합계를 A4 세로 가용 폭(595.28-2*26=543pt)과 정확히 일치시켜 우측 빈 공간을 없앤다.
    widths_base = [20, 34, 40, 60, 100, 34, 33, 33, 62, 63, 64]
    headers = ["순서", "대분류", "중분류", "항목", "세부내용", "수량", "단위", "진행", "시작일", "마감일", "PM 담당자"]
    subs = ["", "", "", "", "", "", "", "", "업체", "업체담당자", "전화번호"]
    for page_start in range(0, len(tasks) or 1, per_page):
        page_tasks = tasks[page_start:page_start + per_page]
        y = doc.start_page(_progress(tasks))
        x = doc.margin
        table_w = sum(widths_base)
        c.rect(x * sx, y * sy, table_w * sx, head_h * sy, HEADER, None, 5 * c.scale)
        cx = x
        for col, (label, width) in enumerate(zip(headers, widths_base)):
            if col < 8:
                c.text(_scaled_rect(c, cx, y, width, head_h), label, 6.2, MUTED, True, Qt.AlignmentFlag.AlignCenter)
            else:
                c.text(_scaled_rect(c, cx, y, width, head_h / 2), label, 5.3, MUTED, True, Qt.AlignmentFlag.AlignCenter)
                c.line(cx * sx, (y + head_h / 2) * sy, (cx + width) * sx, (y + head_h / 2) * sy)
                c.text(_scaled_rect(c, cx, y + head_h / 2, width, head_h / 2), subs[col], 5.3, MUTED, True, Qt.AlignmentFlag.AlignCenter)
            cx += width
        body_top = (y + head_h) * sy
        widths = [value * sx for value in widths_base]
        draw_rows = []
        for index, task in enumerate(page_tasks):
            ry = body_top + index * row_h * sy; rh = row_h * sy
            values = [task["major"], task["minor"], task["name"], task["detail"],
                      str(int(task["quantity"] or 0)), task["unit"] or "식", task["status"]]
            draw_rows.append(values)
            cx = x * sx
            for width in widths:
                c.rect(cx, ry, width, rh, QColor("white") if index % 2 == 0 else SOFT, LINE); cx += width
            c.text(QRectF(x * sx, ry, widths[0], rh), str(page_start + index + 1), 5.4, MUTED, False, Qt.AlignmentFlag.AlignCenter)
            c.text(QRectF((x + sum(widths_base[:3])) * sx, ry, widths[3], rh), task["name"], font_size - 2.1, INK, True, Qt.AlignmentFlag.AlignCenter)
            c.text(QRectF((x + sum(widths_base[:4])) * sx + 3 * sx, ry, widths[4] - 6 * sx, rh), task["detail"], font_size - 2.5)
            c.text(QRectF((x + sum(widths_base[:5])) * sx, ry, widths[5], rh), str(int(task["quantity"] or 0)), font_size - 2.6, INK, False, Qt.AlignmentFlag.AlignCenter)
            unit_x = (x + sum(widths_base[:6])) * sx
            c.text(QRectF(unit_x, ry, widths[6], rh), task["unit"] or "식", font_size - 2.6, INK, False, Qt.AlignmentFlag.AlignCenter)
            status_x = (x + sum(widths_base[:7])) * sx
            fg, bg = STATUS.get(task["status"], (MUTED, MINOR_SOFT))
            c.rect(status_x + 3 * sx, ry + 4 * sy, widths[7] - 6 * sx, rh - 8 * sy, bg, None, 7 * c.scale)
            c.text(QRectF(status_x, ry, widths[7], rh), task["status"], font_size - 2.8, fg, True, Qt.AlignmentFlag.AlignCenter)
            top = [_short_date(task["planned_start"]), _short_date(task["due_date"]), task["pm_assignee_name"] or "미지정"]
            bottom = [task["vendor_name"] or "미지정", task["assignee_name"] or "미지정", task["assignee_phone"] or ""]
            for offset, (top_value, bottom_value) in enumerate(zip(top, bottom), start=8):
                cell_x = (x + sum(widths_base[:offset])) * sx
                c.line(cell_x + 2 * sx, ry + rh / 2, cell_x + widths[offset] - 2 * sx, ry + rh / 2)
                c.text(QRectF(cell_x, ry, widths[offset], rh / 2), top_value, font_size - 3.3, INK, False, Qt.AlignmentFlag.AlignCenter)
                c.text(QRectF(cell_x, ry + rh / 2, widths[offset], rh / 2), bottom_value, font_size - 3.6, MUTED, False, Qt.AlignmentFlag.AlignCenter)
        groups = [[row[0], row[1]] for row in draw_rows]
        _draw_groups(c, body_top, [row_h * sy] * len(groups), groups, (x + widths_base[0]) * sx, widths[1:3])
        doc.footer(f"A4 세로 밀집형 · {font_size}pt · 페이지당 최대 {per_page}행")


def export_checklist_pdf(db, event_id: int, destination: Path, options: PdfOptions = PdfOptions(),
                         major: str = "", vendor_id: int | None = None,
                         pm_assignee_id: int | None = None, scope_label: str = ""):
    service = EventService(db)
    event = service.get_event(event_id)
    if not event:
        raise ValueError("내보낼 프로젝트를 찾을 수 없습니다.")
    tasks = [dict(row) for row in service.list_tasks(
        event_id, major=major, vendor_id=vendor_id, pm_assignee_id=pm_assignee_id,
    )]
    if vendor_id is not None:
        scope = f"업체 {scope_label}"
    elif pm_assignee_id is not None:
        scope = f"담당자(PM) {scope_label}"
    elif major:
        scope = f"대분류 {major}"
    else:
        scope = "전체"
    context = f"실행 업무 현황 · {scope}"
    doc = _Document(destination, options, event, "프로젝트 체크리스트", context)
    try:
        if options.paper == "A4" and options.orientation == "PORTRAIT":
            _checklist_a4_portrait(doc, tasks)
        else:
            _checklist_standard(doc, tasks)
    finally:
        doc.close()
    return Path(destination)


def _calendar_weeks(year: int, month: int):
    weeks = calendar.Calendar(firstweekday=6).monthdatescalendar(year, month)
    while len(weeks) < 6:
        start = weeks[-1][-1] + timedelta(days=1)
        weeks.append([start + timedelta(days=offset) for offset in range(7)])
    return weeks[:6]


def _calendar_week_lanes(tasks, week):
    start, end = week[0], week[-1]
    lanes = []
    segments = []
    ordered = sorted(tasks, key=lambda task: (task["due_date"], task["sort_order"], task["name"]))
    for task in ordered:
        task_start = date.fromisoformat(task["planned_start"])
        task_end = date.fromisoformat(task["due_date"])
        if task_end < start or task_start > end:
            continue
        first, last = max(task_start, start), min(task_end, end)
        first_index, last_index = (first - start).days, (last - start).days
        lane = next(
            (index for index, spans in enumerate(lanes)
             if all(last_index < used_first or first_index > used_last for used_first, used_last in spans)),
            len(lanes),
        )
        if lane == len(lanes):
            lanes.append([])
        lanes[lane].append((first_index, last_index))
        segments.append((lane, task, first_index, last_index, task_start == first, task_end == last))
    return segments, len(lanes)


def _calendar_filter_label(major: str, minor: str, count: int, scope_label: str = "",
                           *, is_pm: bool = False) -> str:
    if scope_label:
        kind = "담당자(PM)" if is_pm else "업체"
        return f"{kind} {scope_label} · {count}개"
    if minor:
        return f"{major} · {minor} · {count}개"
    if major:
        return f"대분류 {major} · {count}개"
    return f"전체 일정 · {count}개"


def _draw_calendar_page(doc, weeks, week_lanes, year, month, lane_start, lane_capacity,
                        page_index, page_count, summary):
    c = doc.canvas; sx, sy = c.sx, c.sy
    summary_text = summary if page_count == 1 else f"{summary} · {page_index + 1}/{page_count}"
    y = doc.start_page(summary_text)
    x = doc.margin
    table_w = doc.base_w - 2 * doc.margin
    month_h, week_head_h = 25, 24
    c.rect(x * sx, y * sy, table_w * sx, month_h * sy, HEADER, None, 5 * c.scale)
    c.text(_scaled_rect(c, x, y, table_w, month_h), f"{year}년 {month}월", 9.2, INK, True,
           Qt.AlignmentFlag.AlignCenter)
    weekdays = ["일", "월", "화", "수", "목", "금", "토"]
    col_w = table_w / 7
    head_y = y + month_h
    for column, label in enumerate(weekdays):
        color = QColor("#C9342C") if column in (0, 6) else MUTED
        c.rect((x + column * col_w) * sx, head_y * sy, col_w * sx, week_head_h * sy, SOFT, LINE)
        c.text(_scaled_rect(c, x + column * col_w, head_y, col_w, week_head_h), label, 7, color, True,
               Qt.AlignmentFlag.AlignCenter)
    body_y = head_y + week_head_h
    body_bottom = doc.base_h - 42
    row_h = (body_bottom - body_y) / 6
    lane_h = min(17, max(12, (row_h - 25) / max(1, lane_capacity) - 2))
    font_size = 7.2 if doc.options.paper == "A4" else 8

    for week_index, week in enumerate(weeks):
        row_y = body_y + week_index * row_h
        for column, value in enumerate(week):
            cell_x = x + column * col_w
            c.rect(cell_x * sx, row_y * sy, col_w * sx, row_h * sy, QColor("white"), LINE)
            date_color = SUBTLE if value.month != month else (QColor("#C9342C") if column in (0, 6) else INK)
            c.text(_scaled_rect(c, cell_x + 5, row_y + 3, col_w - 10, 16), str(value.day), 7.2,
                   date_color, value == date.today())
        segments, _ = week_lanes[week_index]
        for lane, task, first, last, is_start, is_end in segments:
            if not lane_start <= lane < lane_start + lane_capacity:
                continue
            visible_lane = lane - lane_start
            bar_x = x + first * col_w + (4 if is_start else 1)
            bar_w = (last - first + 1) * col_w - (8 if is_start and is_end else 3)
            bar_y = row_y + 23 + visible_lane * (lane_h + 2)
            background = CALENDAR_CATEGORY_COLORS.get(task["major"], QColor("#E5E7EB"))
            c.rect(bar_x * sx, bar_y * sy, bar_w * sx, lane_h * sy, background, None, 4 * c.scale)
            label = task["name"]
            c.text(_scaled_rect(c, bar_x + 3, bar_y, bar_w - 6, lane_h), label, font_size, INK, True,
                   Qt.AlignmentFlag.AlignCenter)
    doc.footer(f"달력만 출력 · 일정 겹침 자동 분할 · {page_index + 1}/{page_count}")


def export_calendar_pdf(db, event_id: int, destination: Path, year: int, month: int,
                        options: PdfOptions = PdfOptions("A4", "LANDSCAPE"),
                        major: str = "", minor: str = "", vendor_id: int | None = None,
                        pm_assignee_id: int | None = None, scope_label: str = ""):
    service = EventService(db)
    event = service.get_event(event_id)
    if not event:
        raise ValueError("내보낼 프로젝트를 찾을 수 없습니다.")
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    tasks = [dict(row) for row in service.calendar_range(
        first, last, event_id, major, minor, vendor_id, pm_assignee_id,
    )]
    weeks = _calendar_weeks(year, month)
    week_lanes = [_calendar_week_lanes(tasks, week) for week in weeks]
    # Landscape favors wider labels; portrait favors more vertical lanes.
    capacity = {
        ("A4", "LANDSCAPE"): 3,
        ("A4", "PORTRAIT"): 5,
        ("A3", "LANDSCAPE"): 5,
        ("A3", "PORTRAIT"): 8,
    }[(options.paper, options.orientation)]
    max_lanes = max((count for _, count in week_lanes), default=0)
    page_count = max(1, (max_lanes + capacity - 1) // capacity)
    summary = _calendar_filter_label(
        major, minor, len(tasks), scope_label, is_pm=pm_assignee_id is not None,
    )
    doc = _Document(destination, options, event, "프로젝트 달력", f"{year}년 {month}월 일정")
    try:
        for page_index in range(page_count):
            _draw_calendar_page(
                doc, weeks, week_lanes, year, month, page_index * capacity, capacity,
                page_index, page_count, summary,
            )
    finally:
        doc.close()
    return Path(destination)


def settlement_header_summary(summary):
    budget = summary["budget"]
    mode = summary["budget_tax_mode"]
    difference = summary["difference"]
    if not budget:
        return f"전체 프로젝트 금액  미입력\n정산 합계  {_money(summary['total'])} · 예산 비교 불가"
    mode_label = "VAT 포함" if mode == "INCLUDED" else ("VAT 별도" if mode == "EXCLUDED" else "VAT 기준 미선택")
    if mode == "EXCLUDED":
        comparison_label = "정산 공급가"
        comparison_value = summary["supply"]
    else:
        comparison_label = "정산 합계"
        comparison_value = summary["total"]
    if difference is None:
        difference_text = "VAT 기준 선택 필요"
    else:
        difference_text = "예산과 일치" if difference == 0 else f"{_money(abs(difference))} {'남음' if difference > 0 else '부족'}"
    return (
        f"전체 프로젝트 금액({mode_label})  {_money(budget)}\n"
        f"{comparison_label}  {_money(comparison_value)} · {difference_text}"
    )


def _settlement_rows(summary):
    rows = []
    current = None
    for item in summary["items"]:
        if current is not None and item["major"] != current:
            rows.append(("subtotal", current, summary["categories"][current]))
        rows.append(("item", item, None)); current = item["major"]
    if current is not None:
        rows.append(("subtotal", current, summary["categories"][current]))
    rows.append(("total", "전체 합계", summary))
    return rows


def _settlement_columns(options):
    if options.paper == "A4" and options.orientation == "PORTRAIT":
        return (
            ["대분류", "중분류", "항목", "세부내용", "수량", "단위", "단가", "공급가", "VAT", "VAT액", "합계", "업체"],
            [26, 30, 70, 133, 20, 18, 45, 45, 26, 38, 45, 47],
            True,
        )
    ratios = [.070, .075, .150, .045, .045, .090, .090, .055, .075, .090, .090, .125]
    width = _page_metrics(options)[0] - 52
    return (
        ["대분류", "중분류", "항목", "수량", "단위", "프로젝트 단가", "공급가", "VAT", "VAT 금액", "합계", "업체", "세부내용"],
        [width * ratio for ratio in ratios],
        False,
    )


def _item_values(item, portrait):
    vat_label = "과세" if item["vat_type"] == "TAXABLE" else "면세"
    if portrait:
        return [item["major"], item["minor"], item["name"], item["detail"] or item["note"] or "",
                str(item["quantity"] or 0), item["unit"] or "식", f"{int(item['unit_price'] or 0):,}",
                f"{item['supply']:,}", vat_label, f"{item['vat']:,}", f"{item['total']:,}", item["vendor_name"] or "미지정"]
    return [item["major"], item["minor"], item["name"], str(item["quantity"] or 0), item["unit"] or "식",
            f"{int(item['unit_price'] or 0):,}", f"{item['supply']:,}", vat_label, f"{item['vat']:,}",
            f"{item['total']:,}", item["vendor_name"] or "미지정", item["detail"] or item["note"] or ""]


def _settlement_pdf(doc, summary):
    c = doc.canvas; sx, sy = c.sx, c.sy
    headers, widths_base, portrait = _settlement_columns(doc.options)
    display = _settlement_rows(summary)
    head_h = 29
    compact = doc.options.paper == "A4" and doc.options.orientation == "PORTRAIT"
    font_size = 8 if len(summary["items"]) <= (28 if compact else 24) else 10
    standard_h = 21 if compact and font_size == 8 else (25 if font_size == 8 else 31)
    summary_h = 23 if compact else standard_h
    max_y = doc.base_h - 42
    index = 0
    while index < len(display):
        y = doc.start_page(settlement_header_summary(summary))
        x = doc.margin
        table_w = sum(widths_base)
        c.rect(x * sx, y * sy, table_w * sx, head_h * sy, HEADER, None, 5 * c.scale)
        cx = x
        for label, width in zip(headers, widths_base):
            c.text(_scaled_rect(c, cx, y, width, head_h), label, 6.3, MUTED, True, Qt.AlignmentFlag.AlignCenter)
            cx += width
        ry_base = y + head_h
        page_entries = []
        used = 0.0
        while index < len(display):
            kind, payload, totals = display[index]
            if kind == "item":
                detail = str(payload["detail"] or payload["note"] or "")
                rh = standard_h + (9 if compact and len(detail) > 30 else 0)
            else:
                rh = summary_h
            # Keep a category subtotal with its preceding item instead of leaving
            # a subtotal alone at the top of the next page.
            next_h = 0
            if kind == "item" and index + 1 < len(display) and display[index + 1][0] == "subtotal":
                next_h = summary_h
            if used and ry_base + used + rh + next_h > max_y:
                break
            if used and ry_base + used + rh > max_y:
                break
            page_entries.append((kind, payload, totals, rh)); used += rh; index += 1
        current_item_index = 0
        for local_index, (kind, payload, totals, rh) in enumerate(page_entries):
            ry = (ry_base + sum(entry[3] for entry in page_entries[:local_index])) * sy
            cell_h = rh * sy
            if kind == "item":
                item = payload; values = _item_values(item, portrait)
                cx = x * sx
                for col, (value, width_base) in enumerate(zip(values, widths_base)):
                    width = width_base * sx
                    c.rect(cx, ry, width, cell_h, QColor("white") if current_item_index % 2 == 0 else SOFT, LINE)
                    if compact or col not in (0, 1):
                        detail_col = 3 if portrait else 11
                        align = Qt.AlignmentFlag.AlignLeft if col == detail_col else Qt.AlignmentFlag.AlignCenter
                        pad = 3 * sx if align != Qt.AlignmentFlag.AlignCenter else 0
                        wrap = col == detail_col and rh > standard_h
                        c.text(QRectF(cx + pad, ry, width - 2 * pad, cell_h), value, font_size - 2.2, INK, col == 2, align, wrap=wrap)
                    cx += width
                current_item_index += 1
            else:
                c.rect(x * sx, ry, table_w * sx, cell_h, BRAND_SOFT, None)
                label = f"{payload} 소계" if kind == "subtotal" else "전체 합계"
                c.text(QRectF(x * sx, ry, 117 * sx, cell_h), label, 7.2, BRAND_DARK, True,
                       Qt.AlignmentFlag.AlignCenter)
                amount_cols = (7, 9, 10) if portrait else (6, 8, 9)
                amount_values = (totals["supply"], totals["vat"], totals["total"])
                for col, value in zip(amount_cols, amount_values):
                    left = (x + sum(widths_base[:col])) * sx
                    width = widths_base[col] * sx
                    c.text(QRectF(left, ry, width, cell_h), f"{value:,}", 6.7, BRAND_DARK, True,
                           Qt.AlignmentFlag.AlignCenter)
        # Standard pages preserve visible category grouping. Compact A4 keeps repeated labels
        # because the very small row height is more readable than vertically centered spans.
        if not compact:
            run_start = 0
            while run_start < len(page_entries):
                if page_entries[run_start][0] != "item":
                    run_start += 1
                    continue
                run_end = run_start + 1
                while run_end < len(page_entries) and page_entries[run_end][0] == "item":
                    run_end += 1
                run = page_entries[run_start:run_end]
                run_top = (ry_base + sum(entry[3] for entry in page_entries[:run_start])) * sy
                run_rows = [[entry[1]["major"], entry[1]["minor"]] for entry in run]
                run_heights = [entry[3] * sy for entry in run]
                _draw_groups(
                    c, run_top, run_heights, run_rows, x * sx,
                    [widths_base[0] * sx, widths_base[1] * sx],
                )
                run_start = run_end
        doc.footer(f"{font_size}pt · 긴 세부내용 행만 자동 확장 · 대분류 소계 유지")


def export_settlement_pdf(db, event_id: int, destination: Path, options: PdfOptions = PdfOptions()):
    service = EventService(db)
    summary = service.settlement_summary(event_id)
    event = summary["event"]
    if not event:
        raise ValueError("내보낼 프로젝트를 찾을 수 없습니다.")
    doc = _Document(destination, options, event, "프로젝트 정산내역", "공급가 및 VAT 정산")
    try:
        _settlement_pdf(doc, summary)
    finally:
        doc.close()
    return Path(destination)
