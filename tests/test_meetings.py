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
            clerk_dates = {r["date"] for r in rows}
            pages = {p.stem for p in (d / "site" / "meetings" / "hillsborough").glob("*.html")}
            extra = pages - clerk_dates            # the Legistar land-use meeting, with no Clerk votes yet
            self.assertEqual(counts["hillsborough"], len(clerk_dates) + len(extra))
            self.assertEqual(len(extra), 1)
            agenda_only = (d / "site" / "meetings" / "hillsborough" / f"{extra.pop()}.html").read_text()
            self.assertIn("this page shows what was on the agenda, not what was decided", agenda_only)
            self.assertIn("When and where:", agenda_only)
            page = (d / "site" / "meetings" / "hillsborough" / "2025-01-07.html").read_text()
            self.assertIn(f"voted on <mark>{len(jan7)} decisions</mark>", page)
            self.assertIn("Small change to an approved development at 13420 Boyette Rd", page)
            self.assertIn("Voted no: Chris Boles", page)
            self.assertIn("1 decision had at least one no vote", page)
            self.assertIn("Official wording", page)
            self.assertIn("made by fixed rules, not AI", page)
            self.assertIn('"@type":"Event","name":"Hillsborough County Commission meeting","startDate":"2025-01-07"', page)
            self.assertIn('<div class="tally" aria-hidden="true">', page)   # the outcome is read out from the text
            self.assertIn('<span aria-current="page">January 7, 2025</span>', page)
            idx = (d / "site" / "meetings" / "hillsborough.html").read_text()
            self.assertIn("1 with a no vote", idx)
            self.assertTrue((d / "site" / "learn" / "land.html").exists())
            land = (d / "site" / "learn" / "land.html").read_text()
            self.assertIn("RES-4", land)
            self.assertIn("planhillsborough", land)

    def test_upcoming_and_cancelled_meetings(self):
        from opencivic.explain import explain
        row = {"item": {"key": "k", "date": "2026-11-17", "title": "Award of contract to Acme Inc. for $2,000,000",
                        "matter_type": ""}, "votes": [], "facts": None,
               "x": explain("Award of contract to Acme Inc. for $2,000,000")}
        info = {"time": "9:00 AM", "location": "John Law Ayers Commission Chambers, Room 160",
                "portal_url": "https://hernandocountyfl.legistar.com/MeetingDetail.aspx?LEGID=1497", "agenda_status": "Final"}
        page = meetings.meeting_page("hernando", "2026-11-17", [row], True, ("", ""), info, "2026-11-09")
        self.assertIn("This meeting is coming up. <mark>1 item</mark> is on the agenda", page)
        self.assertIn("Tuesday, November 17, 2026, 9:00 AM, John Law Ayers Commission Chambers, Room 160.", page)
        self.assertIn('"startDate":"2026-11-17T09:00"', page)
        self.assertIn("what&#x27;s on the agenda</title>", page)
        gone = meetings.meeting_page("hernando", "2026-11-17", [row], True, ("", ""),
                                     {**info, "agenda_status": "Cancelled"}, "2026-11-09")
        self.assertIn("The county lists this meeting as cancelled", gone)
        self.assertIn("EventCancelled", gone)

    def test_pasco_meetings_named_by_place_are_commission_meetings(self):
        self.assertTrue(meetings._commission("Board of County Commissioners, Dade City"))
        self.assertTrue(meetings._commission("Board of County Commissioners Workshop, New Port Richey"))
        self.assertFalse(meetings._commission("Joint Board of County Commissioners Regional Roundtable"))
        self.assertFalse(meetings._commission("Board of County Commissioners and Brooksville City Council Interlocal"))

    def test_topic_phrase(self):
        self.assertEqual(meetings._topic_phrase({"land": 8, "other": 2}), "8 on building and land use and 2 others")
        self.assertEqual(meetings._topic_phrase({"money": 1}), "1 on money")


if __name__ == "__main__":
    unittest.main()
