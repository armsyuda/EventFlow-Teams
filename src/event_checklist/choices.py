from __future__ import annotations

from dataclasses import dataclass

from .units import COMMON_UNITS


@dataclass(frozen=True)
class MasterChoiceCatalog:
    """Shared category and unit choices derived from the user's current data."""

    majors: tuple[str, ...]
    minors_by_major: dict[str, tuple[str, ...]]
    units: tuple[str, ...]


def _append_unique(target: list[str], value) -> None:
    text = str(value or "").strip()
    if text and text not in target:
        target.append(text)


def load_master_choice_catalog(db) -> MasterChoiceCatalog:
    majors: list[str] = []
    minors: dict[str, list[str]] = {}
    units: list[str] = list(COMMON_UNITS)
    for row in db.query("SELECT major,minor,unit FROM master_items ORDER BY sort_order,id"):
        major = str(row["major"] or "").strip()
        minor = str(row["minor"] or "").strip()
        _append_unique(majors, major)
        if major:
            minors.setdefault(major, [])
            _append_unique(minors[major], minor)
        _append_unique(units, row["unit"])
    for row in db.query("SELECT major,minor,unit FROM event_tasks ORDER BY event_id,sort_order,id"):
        major = str(row["major"] or "").strip()
        minor = str(row["minor"] or "").strip()
        _append_unique(majors, major)
        if major:
            minors.setdefault(major, [])
            _append_unique(minors[major], minor)
        _append_unique(units, row["unit"])
    return MasterChoiceCatalog(
        tuple(majors),
        {major: tuple(values) for major, values in minors.items()},
        tuple(units),
    )
