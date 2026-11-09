# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Commissioner pages: counts, outcomes, plain-language output."""

import json
import tempfile
import unittest
from pathlib import Path

from opencivic import hillsclerk as hc
from opencivic import people as pp

from test_region import jl, make_data

FX = Path(__file__).parent / "fixtures" / "hillsclerk" / "bocc-vote-comparison-2025-p1-2-69.txt"


class People(unittest.TestCase):
    def test_vote_kinds(self):
        for v, k in (("Aye", "yes"), ("In Favor", "yes"), ("Yes", "yes"), ("Nay", "no"), ("Opposed", "no"),
                     ("No", "no"), ("Absent", "none"), ("Excused", "none"), ("X", "none"), ("Recused", "none"), ("", "none")):
            self.assertEqual(pp.kind(v), k, v)

    def test_split_motion_and_outcome(self):
        self.assertEqual(pp.split_motion("PRS 25-0077; River Springs LLC; 13420 Boyette Rd. Moved approval."),
                         ("PRS 25-0077; River Springs LLC; 13420 Boyette Rd.", "Moved approval."))
        self.assertEqual(pp.outcome({"yes": 5, "no": 2, "passed": True}), "Passed 5 to 2")
        self.assertEqual(pp.outcome({"yes": 2, "no": 5, "passed": False}), "Failed 5 to 2")
        self.assertEqual(pp.decision_facts({"result": ""}, [{"vote": "Y"}, {"vote": "N"}])["passed"], None)
        self.assertEqual(pp.decision_facts({"result": "Pass"}, [{"vote": "Aye"}])["passed"], True)

    def test_record_links(self):
        meeting = "https://hernandocountyfl.legistar.com/MeetingDetail.aspx?LEGID=1494&GID=881&G=X"
        html_ = pp.record_link({"matter_url": "", "portal_url": meeting, "file_number": "17960"})
        self.assertIn("Official meeting record", html_)
        self.assertIn("look for item 17960", html_)
        self.assertNotIn("LegislationDetail", html_)
        clerk = pp.record_link({"matter_url": "https://www.hillsclerk.com/r.pdf", "file_number": "RCS 4692"})
        self.assertIn("the Clerk's vote report, RCS 4692", clerk)

    def test_official_wording_is_verbatim(self):
        text = "Chair Hagan sought a motion for each person to be given two minutes. Moved to approve."
        self.assertIn(text, pp.plain({"title": text}, 2))

    def test_pages(self):
        rows, _ = hc.parse_report(FX.read_text(), "hillsclerk:bocc-votes:2025", "https://www.hillsclerk.com/r.pdf")
        rows[3]["votes"][0]["code"] = "N"   # Boles votes no on one item
        rows[3]["subject"] += " Brandon Blvd."
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            data = make_data(d)
            (data / "listings" / "hillsclerk-bocc-votes.jsonl").write_text(jl(rows))
            counts = pp.write(data, d / "site", "https://example.org/")
            self.assertEqual(counts["hillsborough"], 7)   # Legistar land-use votes aren't double counted
            idx = (d / "site" / "commissioners" / "hillsborough.html").read_text()
            self.assertIn("Brandon and Lutz don't have a city government", idx)
            self.assertIn("Voted no once", idx)
            self.assertNotIn("1 times", idx)
            page = (d / "site" / "commissioners" / "hillsborough" / "chris-boles.html").read_text()
            self.assertIn(f"voting on <mark>{len(rows)} decisions</mark>", page)
            self.assertIn("Boles voted no once", page)
            yes = sum(v["code"] == "Y" for v in rows[3]["votes"])
            self.assertIn(f"Passed {yes} to 1", page)
            self.assertIn("Decisions that mention Brandon or Lutz", page)
            self.assertIn("Brandon Blvd.", page)
            self.assertIn("The Hillsborough Clerk marks this", page)
            self.assertTrue((d / "site" / "fonts" / "atkinson-hyperlegible-latin-700-normal.woff2").exists())
            self.assertTrue((d / "site" / "fonts" / "OFL-Atkinson-Hyperlegible.txt").exists())


if __name__ == "__main__":
    unittest.main()
