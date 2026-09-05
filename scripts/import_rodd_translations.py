#!/usr/bin/env python3
"""Import Laurel Rasplica Rodd's open-access translations into waka.json.

The source edition is *Shinkokinshu: New Collection of Poems Ancient and
Modern* (Brill, 2015), DOI 10.1163/9789004288294, licensed CC BY-NC-ND 4.0.
This is an offline maintenance utility: pass it a directory containing the
six downloaded seasonal-book PDFs (BP000002 through BP000007).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path


PDF_NAMES = {
    2: "9789004288294-BP000002.pdf",
    3: "9789004288294-BP000003.pdf",
    4: "9789004288294-BP000004.pdf",
    5: "9789004288294-BP000005.pdf",
    6: "9789004288294-BP000006.pdf",
    7: "9789004288294-BP000007.pdf",
}
BOOK_RANGES = {
    2: range(1, 99),
    3: range(99, 175),
    4: range(175, 285),
    5: range(285, 437),
    6: range(437, 551),
    7: range(551, 707),
}

# The right-hand column in the source PDF is keyed to this romanization.  It
# only needs to be close enough to distinguish a verse row from prose; minor
# historical-spelling variations are covered by SPECIAL_TRANSLATIONS below.
KANA = {
    "あ": "a", "い": "i", "う": "u", "え": "e", "お": "o",
    "か": "ka", "き": "ki", "く": "ku", "け": "ke", "こ": "ko",
    "さ": "sa", "し": "shi", "す": "su", "せ": "se", "そ": "so",
    "た": "ta", "ち": "chi", "つ": "tsu", "て": "te", "と": "to",
    "な": "na", "に": "ni", "ぬ": "nu", "ね": "ne", "の": "no",
    "は": "ha", "ひ": "hi", "ふ": "fu", "へ": "he", "ほ": "ho",
    "ま": "ma", "み": "mi", "む": "mu", "め": "me", "も": "mo",
    "や": "ya", "ゆ": "yu", "よ": "yo", "ら": "ra", "り": "ri",
    "る": "ru", "れ": "re", "ろ": "ro", "わ": "wa", "ゐ": "wi",
    "ゑ": "we", "を": "wo", "ん": "n", "が": "ga", "ぎ": "gi",
    "ぐ": "gu", "げ": "ge", "ご": "go", "ざ": "za", "じ": "ji",
    "ず": "zu", "ぜ": "ze", "ぞ": "zo", "だ": "da", "ぢ": "ji",
    "づ": "zu", "で": "de", "ど": "do", "ば": "ba", "び": "bi",
    "ぶ": "bu", "べ": "be", "ぼ": "bo", "ぱ": "pa", "ぴ": "pi",
    "ぷ": "pu", "ぺ": "pe", "ぽ": "po", "ゔ": "vu", "ぁ": "a",
    "ぃ": "i", "ぅ": "u", "ぇ": "e", "ぉ": "o", "ゎ": "wa",
    "ー": "", "ゝ": "",
}
DIGRAPHS = {
    "きゃ": "kya", "きゅ": "kyu", "きょ": "kyo", "ぎゃ": "gya",
    "ぎゅ": "gyu", "ぎょ": "gyo", "しゃ": "sha", "しゅ": "shu",
    "しょ": "sho", "じゃ": "ja", "じゅ": "ju", "じょ": "jo",
    "ちゃ": "cha", "ちゅ": "chu", "ちょ": "cho", "にゃ": "nya",
    "にゅ": "nyu", "にょ": "nyo", "ひゃ": "hya", "ひゅ": "hyu",
    "ひょ": "hyo", "びゃ": "bya", "びゅ": "byu", "びょ": "byo",
    "ぴゃ": "pya", "ぴゅ": "pyu", "ぴょ": "pyo", "みゃ": "mya",
    "みゅ": "myu", "みょ": "myo", "りゃ": "rya", "りゅ": "ryu",
    "りょ": "ryo", "てぃ": "ti", "でぃ": "di", "しぇ": "she",
    "じぇ": "je", "ちぇ": "che", "ふぁ": "fa", "ふぃ": "fi",
    "ふぇ": "fe", "ふぉ": "fo",
}
SPECIAL_TRANSLATIONS = {
    165: [
        "surely the season",
        "has passed I thought        the blooms must",
        "be gone           yet at this",
        "house where wisteria vines",
        "flower spring is eternal",
    ],
    210: [
        "what am I to do",
        "with my heart       this is his cry",
        "it seems              nightingale",
        "calling out in the moonlight",
        "gleaming from between the clouds",
    ],
    329: [
        "I will not rub my",
        "hunting clothing with dye but",
        "will leave that to these",
        "blossoms of the bush clover",
        "in the fields so thick with dew",
    ],
    373: [
        "near Takamado’s",
        "slopes the tips of small bamboo",
        "that line the field paths",
        "rustle    now I know that wintry",
        "winds began to blow today",
    ],
    458: [
        "this autumn arrived",
        "with the frost-covered wings of",
        "the geese beating through",
        "cold night after cold night and",
        "now the icy rains begin",
    ],
    559: [
        "in this house where all",
        "the leaves have fallen I spread",
        "but one side of my",
        "robe      though my sleeves are brightly",
        "dyed the storm passes unaware",
    ],
    660: [
        "the first snow fallen",
        "on the ancient Furu shrine",
        "buries the holy",
        "cedars     fields bound by sacred",
        "ropes hibernate for winter",
    ],
}
PAGE_HEADER = re.compile(
    r"^(?:Book\s+[IVX]+|Spring\s+i{1,2}|Summer|Autumn\s+i{1,2}|Winter)$",
    re.IGNORECASE,
)


def romanize(value: str) -> str:
    result: list[str] = []
    index = 0
    while index < len(value):
        current = value[index]
        if current == "っ":
            if index + 1 < len(value):
                following = DIGRAPHS.get(value[index + 1 : index + 3]) or KANA.get(
                    value[index + 1], ""
                )
                if following:
                    result.append(following[0] if following[0] not in "aeiou" else "t")
            index += 1
        elif value[index : index + 2] in DIGRAPHS:
            result.append(DIGRAPHS[value[index : index + 2]])
            index += 2
        else:
            result.append(KANA.get(current, ""))
            index += 1
    return "".join(result)


def normalize(value: str) -> str:
    value = value.lower().translate(str.maketrans("āēīōū", "aeiou"))
    value = re.sub(r"[^a-z]", "", value)
    return value.replace("ou", "o").replace("oo", "o").replace("ei", "e")


def levenshtein(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for index, character in enumerate(left, 1):
        current = [index]
        for right_index, right_character in enumerate(right, 1):
            current.append(
                min(
                    previous[right_index] + 1,
                    current[-1] + 1,
                    previous[right_index - 1] + (character != right_character),
                )
            )
        previous = current
    return previous[-1]


def find_verse_row(line: str, reading: str) -> tuple[float, str] | None:
    expanded = line.expandtabs(8)
    expected = normalize(romanize(reading))
    best: tuple[float, str] | None = None
    for cut in range(10, min(len(expanded), 110)):
        if not expanded[cut].isalpha() or (cut and expanded[cut - 1].isalpha()):
            continue
        score = levenshtein(normalize(expanded[:cut]), expected) / max(len(expected), 1)
        candidate = (score, expanded[cut:].strip())
        if best is None or candidate[0] < best[0]:
            best = candidate
    return best


def extract_book(lines: list[str], poems_by_number: dict[int, dict], numbers: range) -> dict[int, list[str]]:
    extracted: dict[int, list[str]] = {}
    position = 0
    for number in numbers:
        heading = re.compile(rf"^\s*{number}\s{{2,}}(.+?)\s*$")
        heading_index = next(
            (
                index
                for index in range(position, len(lines))
                if (match := heading.match(lines[index]))
                and not PAGE_HEADER.fullmatch(match.group(1).strip())
            ),
            None,
        )
        if heading_index is None:
            raise ValueError(f"Could not find heading for poem {number}")
        current = heading_index + 1
        translation: list[str] = []
        for reading in poems_by_number[number]["reading"]:
            found: tuple[int, tuple[float, str]] | None = None
            for index in range(current, min(current + 90, len(lines))):
                row = find_verse_row(lines[index], reading)
                if row and row[0] <= 0.35:
                    found = (index, row)
                    break
            if found is None:
                break
            current, row = found
            translation.append(row[1])
            current += 1
        if len(translation) == 5:
            extracted[number] = translation
            position = current
        elif number in SPECIAL_TRANSLATIONS:
            extracted[number] = SPECIAL_TRANSLATIONS[number]
            position = heading_index + 1
        else:
            raise ValueError(f"Could not parse all five verses for poem {number}")
    return extracted


def extract_pdf(pdf: Path) -> list[str]:
    with tempfile.TemporaryDirectory() as temporary_directory:
        output = Path(temporary_directory) / "text.txt"
        subprocess.run(["pdftotext", "-layout", str(pdf), str(output)], check=True)
        return output.read_text(encoding="utf-8").splitlines()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf_dir", type=Path)
    parser.add_argument("waka_json", type=Path)
    args = parser.parse_args()

    poems = json.loads(args.waka_json.read_text(encoding="utf-8"))
    poems_by_number = {poem["source"]["poem_number"]: poem for poem in poems}
    translations: dict[int, list[str]] = {}
    for book, numbers in BOOK_RANGES.items():
        lines = extract_pdf(args.pdf_dir / PDF_NAMES[book])
        translations.update(extract_book(lines, poems_by_number, numbers))

    if set(translations) != set(range(1, 707)):
        raise ValueError("Translation extraction did not cover poems 1 through 706")
    for poem in poems:
        poem["translation"] = translations[poem["source"]["poem_number"]]
    args.waka_json.write_text(
        json.dumps(poems, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
