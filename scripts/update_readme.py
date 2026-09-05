#!/usr/bin/env python3
"""Validate static waka data and update the generated README region."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import sys
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
KO_DATA = ROOT / "data" / "72ko.json"
WAKA_DATA = ROOT / "data" / "waka.json"
SEASONS = {"spring", "summer", "autumn", "winter"}
BOOK_SEASONS = {
    "春歌上": "spring",
    "春歌下": "spring",
    "夏歌": "summer",
    "秋歌上": "autumn",
    "秋歌下": "autumn",
    "冬歌": "winter",
}
BOOK_RANGES = {
    "春歌上": range(1, 99),
    "春歌下": range(99, 175),
    "夏歌": range(175, 285),
    "秋歌上": range(285, 437),
    "秋歌下": range(437, 551),
    "冬歌": range(551, 707),
}
START_MARKER = "<!-- WAKA:START -->"
END_MARKER = "<!-- WAKA:END -->"
JAPANESE_ERAS = (
    (date(2019, 5, 1), "令和"),
    (date(1989, 1, 8), "平成"),
    (date(1926, 12, 25), "昭和"),
    (date(1912, 7, 30), "大正"),
    (date(1868, 10, 23), "明治"),
)


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        try:
            label = path.relative_to(ROOT)
        except ValueError:
            label = path
        raise ValueError(f"cannot read {label}: {exc}") from exc


def month_day(value: Any, field: str) -> tuple[int, int]:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be MM-DD")
    try:
        parsed = datetime.strptime(f"2024-{value}", "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"{field} must be a valid MM-DD") from exc
    return parsed.month, parsed.day


def in_period(day: date, start: str, end: str) -> bool:
    current = (day.month, day.day)
    start_key = month_day(start, "period start")
    end_key = month_day(end, "period end")
    if start_key < end_key:
        return start_key <= current < end_key
    return current >= start_key or current < end_key


def current_ko(day: date, periods: list[dict[str, Any]]) -> dict[str, Any]:
    matches = [period for period in periods if in_period(day, period["start"], period["end"])]
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one ko for {day.isoformat()}, found {len(matches)}"
        )
    return matches[0]


def require_nonempty_string(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")


def validate_periods(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or payload.get("timezone") != "Asia/Tokyo":
        raise ValueError("data/72ko.json must declare timezone Asia/Tokyo")
    periods = payload.get("periods")
    if not isinstance(periods, list) or len(periods) != 72:
        count = len(periods) if isinstance(periods, list) else 0
        raise ValueError(f"expected 72 ko, found {count}")

    names: list[str] = []
    for index, period in enumerate(periods):
        if not isinstance(period, dict):
            raise ValueError(f"ko at index {index} must be an object")
        for field in ("name", "start", "end", "season"):
            require_nonempty_string(period.get(field), f"ko[{index}].{field}")
        if period["season"] not in SEASONS:
            raise ValueError(f"invalid season for ko {period['name']}")
        month_day(period["start"], f"ko {period['name']} start")
        month_day(period["end"], f"ko {period['name']} end")
        if period["start"] == period["end"]:
            raise ValueError(f"ko {period['name']} has an empty date range")
        names.append(period["name"])

    if len(set(names)) != len(names):
        raise ValueError("ko names must be unique")

    validation_day = date(2024, 1, 1)
    for offset in range(366):
        current_ko(validation_day + timedelta(days=offset), periods)
    return periods


def validate_poems(
    payload: Any, periods: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise ValueError("data/waka.json must contain a list")

    ko_seasons = {period["name"]: period["season"] for period in periods}
    ids: set[str] = set()
    poem_numbers_by_book = {book: set() for book in BOOK_RANGES}
    coverage = {name: 0 for name in ko_seasons}

    for index, poem in enumerate(payload):
        label = poem.get("id", f"index {index}") if isinstance(poem, dict) else f"index {index}"
        if not isinstance(poem, dict):
            raise ValueError(f"poem {label} must be an object")

        require_nonempty_string(poem.get("id"), f"poem {label} id")
        if poem["id"] in ids:
            raise ValueError(f"duplicate poem id: {poem['id']}")
        ids.add(poem["id"])

        source = poem.get("source")
        if not isinstance(source, dict):
            raise ValueError(f"poem {label} source must be an object")
        if source.get("anthology") != "新古今和歌集":
            raise ValueError(f"poem {label} must be sourced from 新古今和歌集")
        book = source.get("book")
        if book not in BOOK_RANGES:
            raise ValueError(f"poem {label} has an invalid source book")
        number = source.get("poem_number")
        if not isinstance(number, int) or isinstance(number, bool):
            raise ValueError(f"poem {label} source poem_number must be an integer")
        if number not in BOOK_RANGES[book]:
            raise ValueError(f"poem {label} number {number} does not belong to {book}")
        if number in poem_numbers_by_book[book]:
            raise ValueError(f"duplicate poem number {number} in {book}")
        poem_numbers_by_book[book].add(number)
        expected_id = f"shinkokin-{number:04d}"
        if poem["id"] != expected_id:
            raise ValueError(f"poem {label} id must be {expected_id}")

        require_nonempty_string(poem.get("author"), f"poem {label} author")
        if "kotobagaki" not in poem or (
            poem["kotobagaki"] is not None and not isinstance(poem["kotobagaki"], str)
        ):
            raise ValueError(f"poem {label} kotobagaki must be a string or null")
        text = poem.get("text")
        if not isinstance(text, list) or len(text) != 5:
            raise ValueError(f"poem {label} text must contain exactly five verses")
        for verse_index, verse in enumerate(text):
            require_nonempty_string(verse, f"poem {label} text[{verse_index}]")

        reading = poem.get("reading")
        if reading is not None:
            if not isinstance(reading, list) or len(reading) != 5:
                raise ValueError(f"poem {label} reading must contain exactly five verses")
            for verse_index, verse in enumerate(reading):
                require_nonempty_string(verse, f"poem {label} reading[{verse_index}]")

        translation = poem.get("translation")
        if translation is not None:
            if not isinstance(translation, list) or not translation:
                raise ValueError(f"poem {label} translation must be a non-empty list")
            for line_index, line in enumerate(translation):
                require_nonempty_string(line, f"poem {label} translation[{line_index}]")

        allowed = poem.get("allowed_ko")
        if not isinstance(allowed, list) or not allowed:
            raise ValueError(f"poem {label} allowed_ko must not be empty")
        if len(set(allowed)) != len(allowed):
            raise ValueError(f"poem {label} allowed_ko contains duplicates")
        unknown = [name for name in allowed if name not in ko_seasons]
        if unknown:
            raise ValueError(f"poem {label} references unknown ko: {unknown}")
        wrong_season = [
            name for name in allowed if ko_seasons[name] != BOOK_SEASONS[book]
        ]
        if wrong_season:
            raise ValueError(
                f"poem {label} crosses its source season without review: {wrong_season}"
            )
        for name in allowed:
            coverage[name] += 1

    for book, expected in BOOK_RANGES.items():
        if poem_numbers_by_book[book] != set(expected):
            missing = sorted(set(expected) - poem_numbers_by_book[book])
            raise ValueError(f"{book} is incomplete; missing poem numbers: {missing[:10]}")

    uncovered = [name for name, count in coverage.items() if count == 0]
    if uncovered:
        raise ValueError(f"ko without eligible waka: {uncovered}")
    return payload


def select_waka(day: date, ko: dict[str, Any], poems: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = [poem for poem in poems if ko["name"] in poem["allowed_ko"]]
    candidates.sort(key=lambda poem: poem["id"])
    if not candidates:
        raise ValueError(f"no eligible waka for {ko['name']}")

    key = f"{day.isoformat()}:{ko['name']}".encode("utf-8")
    digest = hashlib.sha256(key).digest()
    index = int.from_bytes(digest[:8], "big") % len(candidates)
    return candidates[index]


def japanese_calendar_date(day: date) -> str:
    for era_start, era_name in JAPANESE_ERAS:
        if day >= era_start:
            era_year = day.year - era_start.year + 1
            year = "元" if era_year == 1 else str(era_year)
            return f"{era_name}{year}年{day.month}月{day.day}日"
    raise ValueError(f"Japanese era is not supported for {day.isoformat()}")


def waka_markdown(day: date, ko: dict[str, Any], poem: dict[str, Any]) -> str:
    japanese = "<br>\n".join(html.escape(line, quote=False) for line in poem["text"])
    sections = [
        '<div align="center">',
        japanese,
        html.escape(poem["author"], quote=False),
    ]
    translation = poem.get("translation")
    if translation:
        sections.append(
            "<br>\n".join(f"*{html.escape(line, quote=False)}*" for line in translation)
        )
    sections.append(
        f"{day.isoformat()} UTC ｜ {japanese_calendar_date(day)} ｜ "
        f"{html.escape(ko['name'])}"
    )
    sections.append("</div>")
    return "\n\n".join(sections)


def replace_generated_region(contents: str, replacement: str) -> str:
    start_count = contents.count(START_MARKER)
    end_count = contents.count(END_MARKER)
    if start_count != 1 or end_count != 1:
        raise ValueError(
            f"expected one WAKA marker pair, found start={start_count}, end={end_count}"
        )
    start = contents.index(START_MARKER) + len(START_MARKER)
    end = contents.index(END_MARKER)
    if start >= end:
        raise ValueError("WAKA markers are out of order")
    return f"{contents[:start]}\n{replacement}\n{contents[end:]}"


def atomic_write(path: Path, contents: str) -> None:
    mode = path.stat().st_mode
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as temporary:
            temporary.write(contents)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.chmod(temporary_name, mode)
        os.replace(temporary_name, path)
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--date", type=date.fromisoformat, help="UTC date for a reproducible update (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--check", action="store_true", help="validate data and README markers without modifying README"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        periods = validate_periods(load_json(KO_DATA))
        poems = validate_poems(load_json(WAKA_DATA), periods)
        day = args.date if args.date else datetime.now(UTC).date()
        ko = current_ko(day, periods)
        poem = select_waka(day, ko, poems)
        contents = README.read_text(encoding="utf-8")
        updated = replace_generated_region(contents, waka_markdown(day, ko, poem))
        if not args.check and updated != contents:
            atomic_write(README, updated)
    except (KeyError, OSError, TypeError, ValueError) as exc:
        print(f"README not updated: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
