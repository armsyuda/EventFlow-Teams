from __future__ import annotations


# 기준 Excel `설정` 시트 F열의 단위 드롭다운 원본 목록.
COMMON_UNITS = ["개", "동", "대", "식", "조", "명", "세트", "매", "장", "부", "회", "일", "박", "팀", "m", "㎡", "기타"]


def infer_default_unit(major: str, minor: str, name: str) -> str:
    """Return a practical event-industry unit without overwriting explicit data."""
    major, minor, name = (value or "" for value in (major, minor, name))

    exact = {
        "발전차": "대", "VJ": "명", "사회자": "명", "도우미": "명",
        "(출연진명)": "명", "내빈명단": "부", "인사말명단": "부", "퍼포먼스명단": "부",
        "초청장/봉투": "매", "포스터": "매", "리플렛": "부", "배치도": "장",
        "X배너": "개", "A보드": "개", "자이언트폴": "개", "윈드배너": "개",
        "버스": "대", "지하철": "식", "전광판": "식", "TV,라디오": "식",
        "행사보험": "식", "스탶복": "개", "무전기": "대", "인터컴": "대",
        "ID카드": "장", "차량비표": "장", "안전띠": "개", "경광봉": "개",
        "노트북,복합기": "대", "흰장갑,수반": "세트", "공구/사무비품": "식",
        "청소인력": "명", "쓰레기봉투": "장", "암롤박스": "대", "폐기물처리": "식",
        "숙박 시설": "박", "셔틀버스": "대", "식사": "식", "생수": "개", "운송": "회",
        "기록영상": "식", "기록사진": "식",
    }
    if name in exact:
        return exact[name]
    if minor == "인력":
        return "명"
    if minor == "행정":
        return "부"
    if minor == "렌탈":
        if "텐트" in name or name == "모바일화장실":
            return "동"
        if name == "펜스":
            return "m"
        return "개"
    if minor == "인쇄":
        return "부"
    if minor == "옥외":
        return "장" if "현수막" in name else "개"
    if name in {"(부스명)"}:
        return "개"
    if name in {"(전시명)"}:
        return "개"
    if name in {"(프로그램)", "개막퍼포먼스"}:
        return "식"
    return "식"
