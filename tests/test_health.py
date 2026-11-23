# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""The health check flags the silent failures we have actually seen (opencivic/health.py)."""

import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from opencivic import health

TODAY = date(2026, 11, 22)
RX = r"^.*\((?:City\ Council)\s*\)$"


def every(days: int, start: date, end: date) -> list[str]:
    out, d = [], start
    while d <= end:
        out.append(d.isoformat())
        d += timedelta(days=days)
    return out


def cc_meetings(dates, category="City Council", name="City Council Meeting", files=1, first_id=1):
    return [{"event_id": first_id + n, "date": d, "name": name, "category": category, "agenda_id": first_id + n,
             "files": [{"file_id": n}] * files} for n, d in enumerate(dates)]


def cc_items(meetings, sections_only=False):
    rows = []
    for m in meetings:
        rows.append({"event_id": m["event_id"], "date": m["date"], "is_section": True, "title": "CALL TO ORDER"})
        if not sections_only:
            rows.append({"event_id": m["event_id"], "date": m["date"], "is_section": False, "title": "An item"})
    return rows


def kinds(result):
    return [p["kind"] for p in result["problems"]]


class Government(unittest.TestCase):
    def check(self, meetings, items, body="City Council", platform="civicclerk", rx=RX):
        return health.government("x", "City of X", platform, meetings, items, rx, TODAY, body)

    def test_healthy_government_is_not_flagged(self):
        ms = cc_meetings(every(14, date(2025, 1, 6), date(2026, 12, 14)))
        r = self.check(ms, cc_items([m for m in ms if m["date"] <= TODAY.isoformat()]))
        self.assertEqual(r["problems"], [])
        self.assertEqual(r["gap_days"], 14)
        self.assertEqual(r["quiet_after_days"], health.QUIET_FLOOR)

    def test_a_holiday_break_is_not_flagged(self):
        # weekly meetings, then three weeks off: under the floor, so not an alarm
        ms = cc_meetings(every(7, date(2025, 11, 3), date(2026, 11, 1)))
        r = self.check(ms, cc_items(ms))
        self.assertEqual(r["problems"], [])

    def test_frozen_listing_top_200(self):
        # Nov 18, 2026: `$top=200` capped the answer, so the listing silently stopped months ago
        ms = cc_meetings(every(14, date(2025, 1, 6), date(2026, 4, 20)))
        r = self.check(ms, cc_items(ms))
        self.assertEqual(kinds(r), ["listing"])
        self.assertIn(f"ends on {ms[-1]['date']}", r["problems"][0]["text"])

    def test_bartow_listing_ends_in_june(self):
        ms = cc_meetings(every(14, date(2025, 8, 18), date(2026, 6, 15)), category="City Commission",
                         name="City Commission Meeting")
        r = self.check(ms, cc_items(ms), body="City Commission", rx=r"^.*\((?:City\ Commission)\s*\)$")
        self.assertEqual(kinds(r), ["listing"])
        self.assertIn(f"ends on {ms[-1]['date']}", r["problems"][0]["text"])

    def test_indian_harbour_beach_meetings_without_files(self):
        dates = every(14, date(2025, 1, 6), date(2026, 11, 16))
        ms = cc_meetings(dates[:30], files=1) + cc_meetings(dates[30:], files=0, first_id=100)
        r = self.check(ms, [])
        self.assertEqual(kinds(r), ["items"])
        self.assertIn("no published file", r["problems"][0]["text"])

    def test_items_stop_while_meetings_continue(self):
        ms = cc_meetings(every(14, date(2025, 1, 6), date(2026, 11, 16)))
        r = self.check(ms, cc_items([m for m in ms if m["date"] < "2026-09-01"]))
        self.assertEqual(kinds(r), ["items"])
        self.assertIn("files listed but no agenda items", r["problems"][0]["text"])

    def test_only_section_headings(self):
        ms = cc_meetings(every(14, date(2025, 1, 6), date(2026, 11, 16)))
        old = [m for m in ms if m["date"] < "2026-09-01"]
        new = [m for m in ms if m["date"] >= "2026-09-01"]
        r = self.check(ms, cc_items(old) + cc_items(new, sections_only=True))
        self.assertIn("section headings", r["problems"][0]["text"])

    def test_board_renamed_in_listing(self):
        # Santa Rosa and Palatka moved to "General"; the council's meetings stop matching
        old = cc_meetings(every(14, date(2025, 1, 6), date(2026, 8, 31)))
        new = cc_meetings(every(14, date(2026, 9, 14), date(2026, 11, 16)), category="General", first_id=500)
        r = self.check(old + new, cc_items(old))
        self.assertIn("board", kinds(r))
        self.assertIn("City Council Meeting (General)", r["problems"][0]["text"])
        self.assertIn("renamed", kinds(r))

    def test_old_rename_with_a_few_matched_meetings(self):
        # St. Cloud: council under "General" most of 2026, one meeting a quarter still matched,
        # so the gap is long and the "board" rule stays quiet; the "renamed" rule doesn't
        matched = cc_meetings(["2025-12-11", "2026-03-05", "2026-07-16", "2026-09-17"])
        general = cc_meetings(every(14, date(2026, 7, 2), date(2026, 11, 12)), category="General", first_id=500)
        r = self.check(matched + general, cc_items(matched))
        self.assertEqual(kinds(r), ["renamed"])
        self.assertIn("'General'", r["problems"][0]["text"])

    def test_similar_names_of_other_boards_are_not_a_rename(self):
        ms = cc_meetings(every(14, date(2025, 1, 6), date(2026, 11, 16)))
        others = cc_meetings(every(14, date(2026, 8, 3), date(2026, 11, 16)), category="General",
                             name="Planning Commission Meeting", first_id=500)
        r = self.check(ms + others, cc_items(ms))
        self.assertEqual(r["problems"], [])

    def test_legistar_events(self):
        ev = [{"event_id": n, "date": d, "body": "City Commission"}
              for n, d in enumerate(every(14, date(2025, 1, 6), date(2026, 11, 16)))]
        items = [{"event_id": e["event_id"], "date": e["date"], "title": "An item"} for e in ev]
        r = self.check(ev, items, body="City Commission", platform="legistar", rx=r"^City Commission$")
        self.assertEqual(r["problems"], [])
        r = self.check(ev, items[:20], body="City Commission", platform="legistar", rx=r"^City Commission$")
        self.assertEqual(kinds(r), ["items"])

    def test_no_meetings_at_all(self):
        self.assertEqual(kinds(self.check([], [])), ["listing"])


class Payments(unittest.TestCase):
    def lists(self, read_until: str):
        return [{"name": f"t:{n}", "meeting_date": d, "lines": 900 if d <= read_until else 0}
                for n, d in enumerate(every(14, date(2025, 1, 9), date(2026, 11, 12)))]

    def test_santa_rosa_new_layout_reads_zero_lines(self):
        rows = self.lists("2026-05-07")
        first_unread = next(r["meeting_date"] for r in rows if not r["lines"])
        r = health.payment_list("santarosacounty", "Santa Rosa County", rows, TODAY)
        self.assertEqual(kinds(r), ["unread"])
        self.assertIn(f"since {first_unread}", r["problems"][0]["text"])

    def test_payment_lists_read_and_current(self):
        r = health.payment_list("colliercounty", "Collier County", self.lists("2026-12-31"), TODAY)
        self.assertEqual(r["problems"], [])

    def test_payment_lists_stop_arriving(self):
        rows = [r for r in self.lists("2026-12-31") if r["meeting_date"] < "2026-09-01"]
        r = health.payment_list("colliercounty", "Collier County", rows, TODAY)
        self.assertEqual(kinds(r), ["listing"])

    def test_duplicates_are_skipped(self):
        rows = self.lists("2026-12-31") + [{"name": "t:dup", "meeting_date": "2026-11-20", "lines": 0,
                                             "duplicate_of": "t:1"}]
        self.assertEqual(health.payment_list("c", "C", rows, TODAY)["problems"], [])

    def test_pasco_registers(self):
        weeks = [{"week": d} for d in every(7, date(2026, 9, 27), date(2026, 11, 15))]
        self.assertEqual(health.pasco_registers(weeks, TODAY)["problems"], [])
        self.assertEqual(kinds(health.pasco_registers(weeks[:2], TODAY)), ["listing"])


class Tracebacks(unittest.TestCase):
    def test_counts_tracebacks_per_log(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "entities-log.txt").write_text('{"ok": 1}\nTraceback (most recent call last):\n  File "x"\n')
            (p / "florida-log.txt").write_text("fine\n")
            (p / "data.jsonl").write_text("Traceback (most recent call last):\n")  # not a log
            self.assertEqual(health.tracebacks(p), {"entities-log.txt": 1})


class Check(unittest.TestCase):
    def test_check_reads_the_registry_files(self):
        with tempfile.TemporaryDirectory() as d:
            data = Path(d)
            (data / "listings").mkdir()
            r = health.check(data, TODAY)
            self.assertGreater(r["governments"], 100)
            # nothing stored: every government's listing is empty, and says so
            self.assertTrue(all(g["problems"] for g in r["records"]))
            json.dumps(r)


if __name__ == "__main__":
    unittest.main()
