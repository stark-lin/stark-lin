from __future__ import annotations

import copy
import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from datetime import UTC, date, datetime
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import update_readme as profile  # noqa: E402


class ProfileDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.period_payload = json.loads(profile.KO_DATA.read_text(encoding="utf-8"))
        cls.poem_payload = json.loads(profile.WAKA_DATA.read_text(encoding="utf-8"))
        cls.periods = profile.validate_periods(cls.period_payload)
        cls.poems = profile.validate_poems(cls.poem_payload, cls.periods)

    def test_complete_six_book_corpus_is_valid(self) -> None:
        self.assertEqual(len(self.poems), 706)
        self.assertEqual(
            {poem["source"]["poem_number"] for poem in self.poems},
            set(range(1, 707)),
        )

    def test_every_day_in_a_leap_year_resolves_once(self) -> None:
        self.assertEqual(profile.current_ko(date(2024, 2, 29), self.periods)["name"], "霞始靆")

    def test_cross_year_period_is_resolved(self) -> None:
        self.assertEqual(profile.current_ko(date(2026, 12, 31), self.periods)["name"], "麋角解")
        self.assertEqual(profile.current_ko(date(2027, 1, 1), self.periods)["name"], "雪下出麦")

    def test_selection_is_stable_when_json_order_changes(self) -> None:
        day = date(2026, 9, 6)
        ko = profile.current_ko(day, self.periods)
        selected = profile.select_waka(day, ko, self.poems)
        reordered = profile.select_waka(day, ko, list(reversed(self.poems)))
        self.assertEqual(selected["id"], reordered["id"])

        candidates = sorted(
            (poem for poem in self.poems if ko["name"] in poem["allowed_ko"]),
            key=lambda poem: poem["id"],
        )
        key = f"{day.isoformat()}:{ko['name']}".encode("utf-8")
        expected_index = int.from_bytes(hashlib.sha256(key).digest()[:8], "big") % len(candidates)
        self.assertEqual(selected["id"], candidates[expected_index]["id"])

    def test_uncovered_ko_is_rejected(self) -> None:
        poems = copy.deepcopy(self.poems)
        for poem in poems:
            poem["allowed_ko"] = [name for name in poem["allowed_ko"] if name != "東風解凍"]
        with self.assertRaisesRegex(ValueError, "ko without eligible waka"):
            profile.validate_poems(poems, self.periods)

    def test_invalid_data_does_not_modify_readme(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            ko_path = temporary / "72ko.json"
            waka_path = temporary / "waka.json"
            readme_path = temporary / "README.md"
            ko_path.write_text(json.dumps(self.period_payload), encoding="utf-8")
            waka_path.write_text("[]", encoding="utf-8")
            original = "must stay unchanged\n"
            readme_path.write_text(original, encoding="utf-8")

            with (
                mock.patch.object(profile, "KO_DATA", ko_path),
                mock.patch.object(profile, "WAKA_DATA", waka_path),
                mock.patch.object(profile, "README", readme_path),
                mock.patch.object(sys, "argv", ["update_readme.py"]),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(profile.main(), 1)

            self.assertEqual(readme_path.read_text(encoding="utf-8"), original)


class ReadmeRegionTests(unittest.TestCase):
    def test_current_tokyo_date_converts_utc_at_midnight_boundary(self) -> None:
        self.assertEqual(
            profile.current_tokyo_date(datetime(2026, 9, 6, 14, 59, tzinfo=UTC)),
            date(2026, 9, 6),
        )
        self.assertEqual(
            profile.current_tokyo_date(datetime(2026, 9, 6, 15, 0, tzinfo=UTC)),
            date(2026, 9, 7),
        )

    def test_japanese_calendar_date_uses_era_year(self) -> None:
        self.assertEqual(profile.japanese_calendar_date(date(2019, 5, 1)), "令和元年5月1日")
        self.assertEqual(profile.japanese_calendar_date(date(2026, 9, 6)), "令和8年9月6日")
        self.assertEqual(profile.japanese_calendar_date(date(1989, 1, 8)), "平成元年1月8日")

    def test_waka_metadata_is_only_rendered_at_the_bottom(self) -> None:
        rendered = profile.waka_markdown(
            date(2026, 9, 6),
            {"name": "禾乃登", "sekki": "処暑"},
            {
                "text": ["一", "二", "三", "四", "五"],
                "author": "作者",
                "translation": ["Translation"],
            },
        )
        self.assertNotIn("禾乃登 · 2026-09-06", rendered)
        self.assertIn("<div align=\"center\">\n\n一<br>", rendered)
        self.assertIn("2026-09-06 ｜ 令和8年9月6日 ｜ [処暑] 禾乃登\n\n</div>", rendered)

    def test_only_generated_region_changes(self) -> None:
        contents = "before\n<!-- WAKA:START -->\nold\n<!-- WAKA:END -->\nafter\n"
        updated = profile.replace_generated_region(contents, "new")
        self.assertEqual(
            updated,
            "before\n<!-- WAKA:START -->\nnew\n<!-- WAKA:END -->\nafter\n",
        )

    def test_duplicate_marker_is_rejected(self) -> None:
        contents = (
            "<!-- WAKA:START -->\n<!-- WAKA:START -->\n"
            "<!-- WAKA:END -->"
        )
        with self.assertRaisesRegex(ValueError, "expected one WAKA marker pair"):
            profile.replace_generated_region(contents, "new")

    def test_reversed_markers_are_rejected(self) -> None:
        contents = "<!-- WAKA:END -->\n<!-- WAKA:START -->"
        with self.assertRaisesRegex(ValueError, "out of order"):
            profile.replace_generated_region(contents, "new")


if __name__ == "__main__":
    unittest.main()
