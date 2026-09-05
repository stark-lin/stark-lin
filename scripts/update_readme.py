#!/usr/bin/env python3
"""Update the generated poem and date regions of the profile README."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
KO_DATA = ROOT / "data" / "72ko.json"
WAKA_DATA = ROOT / "data" / "waka.json"
TOKYO = ZoneInfo("Asia/Tokyo")


def month_day(value: str) -> tuple[int, int]:
    month, day = value.split("-", 1)
    return int(month), int(day)


def in_period(day: date, start: str, end: str) -> bool:
    current = (day.month, day.day)
    start_key, end_key = month_day(start), month_day(end)
    if start_key < end_key:
        return start_key <= current < end_key
    return current >= start_key or current < end_key


def current_period(day: date, periods: list[dict]) -> dict:
    matches = [period for period in periods if in_period(day, period["start"], period["end"])]
    if len(matches) != 1:
        raise ValueError(f"Expected one seasonal period for {day.isoformat()}, found {len(matches)}")
    return matches[0]


def select_waka(day: date, period: dict, poems: list[dict]) -> dict:
    seasonal = [poem for poem in poems if poem["season"] == period["season"]]
    if not seasonal:
        raise ValueError(f"No poems available for {period['season']}")

    # Keep the small pool near the current point in the season, then vary it by day.
    nearby = sorted(
        seasonal,
        key=lambda poem: (abs(poem["season_progress"] - period["season_progress"]), poem["id"]),
    )[: min(3, len(seasonal))]
    key = f"{day.isoformat()}:{period['name']}".encode("utf-8")
    index = int.from_bytes(hashlib.sha256(key).digest()[:8], "big") % len(nearby)
    return nearby[index]


def waka_markdown(period: dict, poem: dict) -> str:
    japanese = "<br>\n".join(poem["text"])
    translation = "<br>\n".join(poem["translation"])
    return (
        '<div align="center">\n\n'
        f"{period['name']}\n\n"
        f"{japanese}\n\n"
        f"{poem['author']}\n\n"
        f"{translation}\n\n"
        "</div>"
    )


def replace_region(contents: str, name: str, replacement: str) -> str:
    pattern = rf"(<!-- {name}:START -->)\n.*?\n(<!-- {name}:END -->)"
    updated, count = re.subn(pattern, rf"\1\n{replacement}\n\2", contents, flags=re.DOTALL)
    if count != 1:
        raise ValueError(f"Expected exactly one {name} generated region, found {count}")
    return updated


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read {path.relative_to(ROOT)}: {exc}") from exc


def validate(periods: list[dict], poems: list[dict]) -> None:
    if len(periods) != 72:
        raise ValueError(f"Expected 72 seasonal periods, found {len(periods)}")
    names = [period["name"] for period in periods]
    if len(set(names)) != len(names):
        raise ValueError("Seasonal period names must be unique")
    validation_start = date(2024, 1, 1)  # Leap year exercises every month-day boundary.
    for offset in range(366):
        current_period(date.fromordinal(validation_start.toordinal() + offset), periods)
    for poem in poems:
        required = {"id", "season", "season_progress", "text", "author", "translation", "source_book"}
        missing = required - poem.keys()
        if (
            missing
            or poem["season"] not in {"spring", "summer", "autumn", "winter"}
            or len(poem["text"]) != 5
            or not poem["author"]
            or not poem["translation"]
        ):
            raise ValueError(f"Invalid poem {poem.get('id', '<unknown>')}: missing {sorted(missing)} or incomplete text")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=date.fromisoformat, help="JST date for a reproducible update (YYYY-MM-DD)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        ko_data = load_json(KO_DATA)
        periods = ko_data["periods"]
        poems = load_json(WAKA_DATA)
        validate(periods, poems)
        day = args.date if args.date else datetime.now(TOKYO).date()
        period = current_period(day, periods)
        poem = select_waka(day, period, poems)
        contents = README.read_text(encoding="utf-8")
        contents = replace_region(contents, "WAKA", waka_markdown(period, poem))
        contents = replace_region(contents, "DATE", f"`{day.isoformat()}`")
        README.write_text(contents, encoding="utf-8")
    except (KeyError, OSError, ValueError) as exc:
        print(f"README not updated: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
