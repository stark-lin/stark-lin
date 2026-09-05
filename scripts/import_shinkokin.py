#!/usr/bin/env python3
"""Build the static waka dataset from local source HTML files.

This is an offline maintenance tool. The daily profile job never calls it and
never accesses the network.
"""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path


BOOKS = {
    1: ("春歌上", "spring"),
    2: ("春歌下", "spring"),
    3: ("夏歌", "summer"),
    4: ("秋歌上", "autumn"),
    5: ("秋歌下", "autumn"),
    6: ("冬歌", "winter"),
}
VOLUME_KANJI = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六"}

CURATED_TRANSLATIONS = {
    706: [
        "On this day each year,",
        "I grieve, wondering whether",
        "this will be my last;",
        "yet once again I have lived",
        "to greet another year’s end.",
    ],
}

SEASON_KO = {
    "spring": [
        "東風解凍", "黄鶯睍睆", "魚上氷", "土脉潤起", "霞始靆", "草木萌動",
        "蟄虫啓戸", "桃始笑", "菜虫化蝶", "雀始巣", "桜始開", "雷乃発声",
        "玄鳥至", "鴻雁北", "虹始見", "葭始生", "霜止出苗", "牡丹華",
    ],
    "summer": [
        "蛙始鳴", "蚯蚓出", "竹笋生", "蚕起食桑", "紅花栄", "麦秋至",
        "螳螂生", "腐草為蛍", "梅子黄", "乃東枯", "菖蒲華", "半夏生",
        "温風至", "蓮始開", "鷹乃学習", "桐始結花", "土潤溽暑", "大雨時行",
    ],
    "autumn": [
        "涼風至", "寒蝉鳴", "蒙霧升降", "綿柎開", "天地始粛", "禾乃登",
        "草露白", "鶺鴒鳴", "玄鳥去", "雷乃収声", "蟄虫坏戸", "水始涸",
        "鴻雁来", "菊花開", "蟋蟀在戸", "霜始降", "霎時施", "楓蔦黄",
    ],
    "winter": [
        "山茶始開", "地始凍", "金盞香", "虹蔵不見", "朔風払葉", "橘始黄",
        "閉塞成冬", "熊蟄穴", "鱖魚群", "乃東生", "麋角解", "雪下出麦",
        "芹乃栄", "水泉動", "雉始雊", "款冬華", "水沢腹堅", "鶏始乳",
    ],
}

BOOK_RANGES = {
    "spring": (1, 174),
    "summer": (175, 284),
    "autumn": (285, 550),
    "winter": (551, 706),
}

BLOCK_RE = re.compile(
    r"<b><a name=(?P<number>\d{4})>(?P<block>.*?)(?=<b><a name=\d{4}>|\Z)",
    re.IGNORECASE | re.DOTALL,
)
POEM_RE = re.compile(r"<font color=ddddff>(.*?)</font>", re.IGNORECASE | re.DOTALL)
AUTHOR_RE = re.compile(r"<p align=right>(.*?)</ul>", re.IGNORECASE | re.DOTALL)
RUBY_RE = re.compile(r"<ruby>(.*?)</ruby>", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>", re.DOTALL)


def clean_markup(value: str, *, reading: bool = False) -> str:
    # Repair two recurring transcription typos in the source's otherwise
    # regular ruby markup before selecting the base text or its reading.
    value = value.replace("<rt>>", "<rt>")
    value = re.sub(r"</ruby(?=[^>])", "</ruby>", value, flags=re.IGNORECASE)

    def replace_ruby(match: re.Match[str]) -> str:
        ruby = match.group(1)
        tag = "rt" if reading else "rb"
        selected = re.search(rf"<{tag}>(.*?)</{tag}>", ruby, re.IGNORECASE | re.DOTALL)
        return selected.group(1) if selected else ruby

    value = RUBY_RE.sub(replace_ruby, value)
    value = re.sub(r"<font size=1>.*?</font>", "", value, flags=re.IGNORECASE | re.DOTALL)
    value = TAG_RE.sub("", value)
    value = html.unescape(value).replace("\ufeff", "")
    return re.sub(r"[ \t\r\n]+", " ", value).strip(" 　")


def split_verses(markup: str, *, reading: bool = False) -> list[str]:
    value = clean_markup(markup, reading=reading)
    return [part.strip() for part in re.split(r"　+", value) if part.strip()]


def allowed_ko(number: int, season: str, text: list[str]) -> list[str]:
    """Assign a small order-based window within the source book's season.

    The anthology's original sequence is the primary fine-grained seasonal
    evidence available consistently for all 706 poems. Generic season poems
    receive a wider window; poems with concrete natural imagery stay narrower.
    """
    first, last = BOOK_RANGES[season]
    kos = SEASON_KO[season]
    position = (number - first) / max(1, last - first)
    center = min(len(kos) - 1, int(position * len(kos)))

    joined = "".join(text)
    season_word = {"spring": "春", "summer": "夏", "autumn": "秋", "winter": "冬"}[season]
    radius = 2 if season_word in joined else 1
    start = max(0, center - radius)
    end = min(len(kos), center + radius + 1)
    return kos[start:end]


def load_wikisource_readings(path: Path) -> dict[int, list[str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    wikitext = payload["parse"]["wikitext"]
    starts = list(re.finditer(r'<span id="(\d{5})">', wikitext))
    readings: dict[int, list[str]] = {}
    for index, start in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(wikitext)
        block = wikitext[start.end():end]
        lines = [line.strip() for line in block.splitlines() if line.count("－") == 4]
        if len(lines) == 1:
            readings[int(start.group(1))] = lines[0].split("－")
    return readings


def parse_volume(path: Path, volume: int, fallback_readings: dict[int, list[str]]) -> list[dict]:
    book, season = BOOKS[volume]
    contents = path.read_text(encoding="utf-8-sig")
    poems: list[dict] = []

    for match in BLOCK_RE.finditer(contents):
        number = int(match.group("number"))
        block = match.group("block")
        heading_end = block.find("</b>")
        poem_match = POEM_RE.search(block)
        if heading_end < 0 or not poem_match:
            raise ValueError(f"Cannot parse poem {number}")

        heading = re.sub(r"^\d{4}　?", "", block[:heading_end])
        kotobagaki = clean_markup(heading) or None
        text = split_verses(poem_match.group(1))
        reading = split_verses(poem_match.group(1), reading=True)
        used_fallback_text = False
        if len(reading) != 5 or any(re.search(r"[<>()]", verse) for verse in reading):
            reading = fallback_readings.get(number, [])
        if len(text) != 5 and len(reading) == 5:
            text = reading.copy()
            used_fallback_text = True
        if len(text) != 5 or len(reading) != 5:
            raise ValueError(
                f"Poem {number} does not have five parsed verses: "
                f"text={len(text)}, reading={len(reading)}"
            )

        author_match = AUTHOR_RE.search(block, poem_match.end())
        if not author_match:
            raise ValueError(f"Cannot parse author for poem {number}")
        author = clean_markup(author_match.group(1))

        poems.append(
            {
                "id": f"shinkokin-{number:04d}",
                "source": {
                    "anthology": "新古今和歌集",
                    "book": book,
                    "poem_number": number,
                    "text_source": (
                        f"https://ja.wikisource.org/wiki/新古今和歌集/巻第{VOLUME_KANJI[volume]}"
                        if used_fallback_text
                        else f"https://miko.org/~uraki/kuon/furu/text/waka/shikokin/shikokin0{volume}.htm"
                    ),
                    "reading_source": f"https://ja.wikisource.org/wiki/新古今和歌集/巻第{VOLUME_KANJI[volume]}",
                },
                "author": author,
                "kotobagaki": kotobagaki,
                "text": text,
                "reading": reading,
                "translation": CURATED_TRANSLATIONS.get(number),
                "allowed_ko": allowed_ko(number, season, text),
            }
        )

    return poems


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "source_dir",
        type=Path,
        help="Directory containing shikokin01.html through shikokin06.html",
    )
    parser.add_argument("output", type=Path, help="Output waka.json path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    poems: list[dict] = []
    for volume in BOOKS:
        readings = load_wikisource_readings(args.source_dir / f"shinkokin-vol{volume}.json")
        poems.extend(
            parse_volume(
                args.source_dir / f"shikokin0{volume}.html",
                volume,
                readings,
            )
        )

    numbers = [poem["source"]["poem_number"] for poem in poems]
    if numbers != list(range(1, 707)):
        raise ValueError("Expected the complete contiguous poem range 1..706")

    args.output.write_text(
        json.dumps(poems, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
