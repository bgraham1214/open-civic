# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Meeting pages and explainers."""

import tempfile
import unittest
from pathlib import Path

from opencivic import hillsclerk as hc
from opencivic import meetings

from test_region import jl, make_data

FX = Path(__file__).parent / "fixtures" / "hillsclerk" / "bocc-vote-comparison-2025-p1-2-69.txt"


class Meetings(unittest.TestCase):
    def test_pages(self):
        rows, _ = hc.parse_report(FX.read_text(), "hillsclerk:bocc-votes:2025", "https://www.hillsclerk.com/r.pdf")
        jan7 = [r for r in rows if r["date"] == "2025-01-07"]
        jan7[1]["votes"][0]["code"] = "N"
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            data = make_data(d)
            (data / "listings" / "hillsclerk-bocc-votes.jsonl").write_text(jl(rows))
            counts = meetings.write(data, d / "site")
            self.assertEqual(counts["hillsborough"], len({r["date"] for r in rows}))
            page = (d / "site" / "meetings" / "hillsborough" / "2025-01-07.html").read_text()
            self.assertIn(f"voted on <mark>{len(jan7)} decisions</mark>", page)
            self.assertIn("Small change to an approved development at 13420 Boyette Rd", page)
            self.assertIn("Voted no: Chris Boles", page)
            self.assertIn("1 decision had at least one no vote", page)
            self.assertIn("Official wording", page)
            self.assertIn("made by fixed rules, not AI", page)
            idx = (d / "site" / "meetings" / "hillsborough.html").read_text()
            self.assertIn("1 with a no vote", idx)
            self.assertTrue((d / "site" / "learn" / "land.html").exists())
            land = (d / "site" / "learn" / "land.html").read_text()
            self.assertIn("RES-4", land)
            self.assertIn("planhillsborough", land)

    def test_topic_phrase(self):
        self.assertEqual(meetings._topic_phrase({"land": 8, "other": 2}), "8 on building and land use and 2 others")
        self.assertEqual(meetings._topic_phrase({"money": 1}), "1 on money")


if __name__ == "__main__":
    unittest.main()
