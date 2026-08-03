"""Normalization helpers for schedule months, dates and semester labels."""
from __future__ import annotations

from datetime import date, datetime
import re
from typing import Any, Dict, Iterable, Optional, Tuple


DAY_NAMES: Tuple[str, ...] = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб")
DAY_INDEX = {name: index for index, name in enumerate(DAY_NAMES)}
MONTH_NAMES = {
    1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель", 5: "Май", 6: "Июнь",
    7: "Июль", 8: "Август", 9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь",
}
MONTH_GENITIVE = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня",
    7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}
MONTH_PREFIXES = {
    "янв": 1, "фев": 2, "мар": 3, "апр": 4, "май": 5, "мая": 5,
    "июн": 6, "июл": 7, "авг": 8, "сен": 9, "сент": 9,
    "окт": 10, "ноя": 11, "дек": 12,
}
MONTH_NUMBERS = {name.casefold(): number for number, name in MONTH_NAMES.items()}
SEMESTER_LABELS = {"spring": "весенний", "autumn": "осенний", "unknown": "не определён"}
ACADEMIC_YEAR_RE = re.compile(r"\b(20\d{2})\s*[-–—/]\s*(20\d{2}|\d{2})\b")


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def month_number(value: Any) -> Optional[int]:
    if isinstance(value, (date, datetime)):
        return value.month
    text = _text(value).casefold().replace("ё", "е")
    if not text:
        return None
    direct = MONTH_NUMBERS.get(text)
    if direct:
        return direct
    for prefix, number in MONTH_PREFIXES.items():
        if re.search(rf"(?<![а-яa-z]){re.escape(prefix)}[а-я]*", text, re.I):
            return number
    iso = re.search(r"(?<!\d)(?:19|20)\d{2}[-/.](\d{1,2})[-/.]\d{1,2}(?!\d)", text)
    if iso and 1 <= int(iso.group(1)) <= 12:
        return int(iso.group(1))
    ordinary = re.search(r"(?<!\d)\d{1,2}[-/.](\d{1,2})(?:[-/.]\d{2,4})?(?!\d)", text)
    if ordinary and 1 <= int(ordinary.group(1)) <= 12:
        return int(ordinary.group(1))
    return None


def canonical_month(value: Any) -> Optional[str]:
    number = month_number(value)
    return MONTH_NAMES.get(number) if number else None


def next_month(value: Any) -> Optional[str]:
    number = month_number(value)
    if number is None:
        return None
    return MONTH_NAMES[1 if number == 12 else number + 1]


def extract_date_parts(value: Any, fallback_month: Any = None) -> Dict[str, Any]:
    """Extract day, month and optional year from an Excel date-like value."""

    if isinstance(value, (date, datetime)):
        return {"day": value.day, "month": MONTH_NAMES[value.month], "year": value.year}
    text = _text(value).casefold().replace("ё", "е")
    fallback = canonical_month(fallback_month)
    if not text:
        return {"day": 0, "month": fallback, "year": 0}

    match = re.search(r"(?<!\d)((?:19|20)\d{2})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)", text)
    if match:
        year, month, day = map(int, match.groups())
        try:
            date(year, month, day)
            return {"day": day, "month": MONTH_NAMES[month], "year": year}
        except ValueError:
            pass

    match = re.search(r"(?<!\d)(\d{1,2})[-/.](\d{1,2})(?:[-/.](\d{2,4}))?(?!\d)", text)
    if match:
        day, month = int(match.group(1)), int(match.group(2))
        raw_year = match.group(3)
        year = int(raw_year) if raw_year else 0
        if raw_year and year < 100:
            year += 2000
        try:
            date(year or 2000, month, day)
            return {"day": day, "month": MONTH_NAMES[month], "year": year}
        except ValueError:
            pass

    named_month = month_number(text)
    day_match = re.search(r"(?<!\d)([1-9]|[12]\d|3[01])(?!\d)", text)
    if named_month and day_match:
        return {"day": int(day_match.group(1)), "month": MONTH_NAMES[named_month], "year": 0}

    if re.fullmatch(r"\d{1,2}(?:\.0+)?", text):
        day = int(float(text))
        if 1 <= day <= 31:
            return {"day": day, "month": fallback, "year": 0}
    return {"day": 0, "month": canonical_month(text) or fallback, "year": 0}


def semester_kind_from_text(value: Any) -> str:
    text = _text(value).casefold().replace("ё", "е")
    if "весен" in text:
        return "spring"
    if "осен" in text:
        return "autumn"
    match = re.search(r"(?:семестр\s*№?\s*(\d{1,2})|(\d{1,2})\s*[-–]?(?:й|ый|ой)?\s*семестр)", text)
    if match:
        number = int(match.group(1) or match.group(2))
        if number > 0:
            return "autumn" if number % 2 else "spring"
    return "unknown"


def semester_kind_from_months(values: Iterable[Any]) -> str:
    numbers = {number for value in values if (number := month_number(value)) is not None}
    spring = bool(numbers & {2, 3, 4, 5, 6})
    autumn = bool(numbers & {1, 8, 9, 10, 11, 12})
    if spring and autumn:
        return "mixed"
    if spring:
        return "spring"
    if autumn:
        return "autumn"
    return "unknown"


def academic_year_from_text(value: Any) -> Tuple[str, Optional[Tuple[int, int]]]:
    match = ACADEMIC_YEAR_RE.search(_text(value))
    if not match:
        return "", None
    first = int(match.group(1))
    second = int(match.group(2))
    if second < 100:
        second = first // 100 * 100 + second
    if second != first + 1:
        return "", None
    return f"{first}/{second}", (first, second)


def _slot_key(week: int, day_name: str) -> str:
    return f"{int(week)}:{day_name}"


def _parse_slot_key(value: str) -> Optional[Tuple[int, str]]:
    try:
        week_text, day_name = str(value).split(":", 1)
        week = int(week_text)
    except (TypeError, ValueError):
        return None
    return (week, day_name) if day_name in DAY_INDEX else None
