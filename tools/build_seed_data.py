from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "01_Contents" / "체크리스트_항목목록(백업).csv"
OUTPUT = ROOT / "03_Program" / "src" / "event_checklist" / "resources" / "master_items.json"


def schedule_for(major: str, minor: str, name: str) -> tuple[str, int, int]:
    text = f"{major} {minor} {name}"
    if name == "결과보고서":
        return "END", 1, 30
    if minor == "기록":
        return "START", -1, 7
    if minor == "환경정리":
        return "END", -1, 1
    if minor == "행정":
        if any(word in text for word in ("안전", "허가", "신고", "검사", "보험")):
            return "START", -90, -14
        return "START", -120, -30
    if major == "시스템":
        return "START", -60, -3
    if major == "시설":
        return "START", -45, -2
    if major == "행사":
        if minor == "연출":
            return "START", -90, -7
        return "START", -75, -5
    if major == "홍보":
        if minor == "공통":
            return "START", -75, -45
        if minor == "온라인":
            return "START", -60, -3
        if minor == "인쇄":
            return "START", -60, -7
        return "START", -45, -3
    if minor == "인력":
        return "START", -30, -3
    if minor == "비품/물품":
        return "START", -30, -1
    return "START", -30, -1


def cleaned(value: str | None) -> str:
    value = (value or "").strip()
    return "" if value in {"81", "#NAME?"} else value


def build() -> list[dict]:
    with SOURCE.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    additions = [
        {"대분류": "시스템", "중분류": "무대", "항목": "카메라다이", "세부내용 · 확인 포인트": "", "수량": "1", "단위": "식"},
        {"대분류": "시스템", "중분류": "무대", "항목": "콘솔다이", "세부내용 · 확인 포인트": "", "수량": "1", "단위": "식"},
    ]
    rows[1:1] = additions

    result: list[dict] = []
    for index, row in enumerate(rows, 1):
        major = cleaned(row.get("대분류"))
        minor = cleaned(row.get("중분류"))
        name = cleaned(row.get("항목"))
        anchor, start_offset, due_offset = schedule_for(major, minor, name)
        quantity_text = cleaned(row.get("수량"))
        result.append(
            {
                "id": index,
                "major": major,
                "minor": minor,
                "name": name,
                "detail": cleaned(row.get("세부내용 · 확인 포인트")),
                "anchor": anchor,
                "start_offset": start_offset,
                "due_offset": due_offset,
                "quantity": float(quantity_text) if quantity_text else None,
                "unit": cleaned(row.get("단위")),
                "sort_order": index,
                "active": True,
            }
        )
    return result


def main() -> int:
    items = build()
    if len(items) != 120:
        raise SystemExit(f"기본 항목 수 오류: {len(items)}")
    serialized = json.dumps(items, ensure_ascii=False, indent=2)
    if "\"81\"" in serialized or "#NAME?" in serialized:
        raise SystemExit("오염값이 남아 있습니다.")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(serialized + "\n", encoding="utf-8")
    print(f"WROTE {OUTPUT} ({len(items)} items)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
