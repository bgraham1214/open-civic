# SPDX-License-Identifier: AGPL-3.0-or-later
"""The fleet collector (florida.py): newest meetings first, inside a budget, resumed the next night."""

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from opencivic import florida
from opencivic.fetch import FetchError
from opencivic.jurisdictions import FLORIDA, JURISDICTIONS


class FakeLegistar:
    """Three County Commission meetings with two voted items each, and a planning board meeting."""

    def __init__(self):
        self.requested: list[str] = []
        self.modified = "2026-01-01T00:00:00"

    def get_json(self, url):
        self.requested.append(url)
        if "/events?" in url:
            return [{"EventId": i, "EventBodyName": "Board of County Commissioners" if i < 4 else "Planning Board",
                     "EventDate": f"2026-0{i}-10T00:00:00", "EventTime": "9:00 AM", "EventLastModifiedUtc": "x",
                     "EventInSiteURL": f"https://testfl.legistar.com/MeetingDetail.aspx?ID={i}"} for i in (1, 2, 3, 4)]
        if "officerecords" in url:
            return []
        if "/eventitems?" in url:
            ev = int(url.split("/events/")[1].split("/")[0])
            return [{"EventItemId": ev * 10 + n, "EventItemTitle": f"Item {n}", "EventItemAgendaSequence": n,
                     "EventItemPassedFlag": 1, "EventItemPassedFlagName": "Pass",
                     "EventItemLastModifiedUtc": self.modified} for n in (1, 2)]
        if url.endswith("/votes"):
            return [{"VoteId": 1, "VotePersonName": "A. Member", "VoteValueName": "Yes", "VoteSort": 1}]
        raise FetchError(f"unexpected {url}")


class Collect(unittest.TestCase):
    def setUp(self):
        self.row = {"slug": "testcounty", "name": "Test County", "short": "Test", "place": "Test", "kind": "county",
                    "county": "Test", "platform": "legistar", "account": "testfl",
                    "body": "Board of County Commissioners", "boards": ["Board of County Commissioners"]}
        JURISDICTIONS["testcounty"] = {"board_rx": r"^Board of County Commissioners$"}
        self.addCleanup(JURISDICTIONS.pop, "testcounty")

    def run_once(self, data, fetcher, first, minutes=5, slice_=0):
        with mock.patch.object(florida, "FLORIDA", [self.row]):
            return florida.collect(Path(data), minutes, first, slice_, fetchers={"legistar": fetcher},
                                   today=date(2026, 6, 1))

    def test_newest_first_then_resumes(self):
        with tempfile.TemporaryDirectory() as d:
            f = FakeLegistar()
            # room for one meeting (1 request for its items + 2 roll calls); no backfill round
            with mock.patch.object(florida.Budget, "left", lambda self: self.requests < 3):
                s = self.run_once(d, f, first=3)
            lst = Path(d) / "listings"
            items = [json.loads(x) for x in (lst / "legistar-testfl-items.jsonl").read_text().splitlines()]
            self.assertEqual({i["date"] for i in items}, {"2026-03-10"})          # the newest Commission meeting
            self.assertEqual(s["unfinished"], {"testcounty": 2})
            events = (lst / "legistar-testfl-events.jsonl").read_text().splitlines()
            self.assertEqual(len(events), 4)                                       # every board's meetings are listed
            # the next night picks up the two older meetings and doesn't re-read the one it has
            f2 = FakeLegistar()
            s = self.run_once(d, f2, first=50)
            self.assertEqual(s["unfinished"], {})
            self.assertFalse(any("/events/3/" in u for u in f2.requested))
            self.assertFalse(any("/events/4/" in u for u in f2.requested))        # not the governing board
            votes = (lst / "legistar-testfl-votes.jsonl").read_text().splitlines()
            self.assertEqual(len(votes), 6)

    def test_recent_meeting_reread_but_roll_calls_kept(self):
        with tempfile.TemporaryDirectory() as d:
            self.run_once(d, FakeLegistar(), first=50)
            f = FakeLegistar()
            with mock.patch.object(florida, "FLORIDA", [self.row]):
                florida.collect(Path(d), 5, 50, 0, fetchers={"legistar": f}, today=date(2026, 3, 20))
            # Mar 10 is within the refresh window: its items are read again, its unchanged roll calls are not
            self.assertTrue(any("/events/3/eventitems" in u for u in f.requested))
            self.assertFalse(any(u.endswith("/votes") for u in f.requested))
            f.modified = "2026-03-19T00:00:00"                                   # the clerk edits the items
            with mock.patch.object(florida, "FLORIDA", [self.row]):
                florida.collect(Path(d), 5, 50, 0, fetchers={"legistar": f}, today=date(2026, 3, 20))
            self.assertEqual(sum(u.endswith("/votes") for u in f.requested), 2)


class Registry(unittest.TestCase):
    def test_rows_are_usable(self):
        slugs = [f["slug"] for f in FLORIDA]
        self.assertEqual(len(slugs), len(set(slugs)))
        for f in FLORIDA:
            self.assertIn(f["platform"], ("legistar", "civicclerk"))
            self.assertTrue(f["boards"], f["slug"])
            self.assertEqual(JURISDICTIONS[f["slug"]]["govt"], "county" if f["kind"] == "county" else "city")
            self.assertEqual(f["slug"].endswith("county"), f["kind"] == "county", f["slug"])


if __name__ == "__main__":
    unittest.main()


class BoardNames(unittest.TestCase):
    """Nov 18, 2026: Santa Rosa and Palatka moved their board meetings to the "General" category; names_rx
    keeps them without taking in other boards."""

    def test_names_rx(self):
        import re
        from opencivic.jurisdictions import JURISDICTIONS as J
        sr = re.compile(J["santarosacounty"]["board_rx"])
        self.assertTrue(sr.match("Regular Meeting (Regular Meeting )"))
        self.assertTrue(sr.match("Commission Regular Meeting (General)"))
        self.assertTrue(sr.match("Commission Regular  Meeting (General)"))
        self.assertFalse(sr.match("Commission Committee Meeting (General)"))
        self.assertFalse(sr.match("Zoning Board (General)"))
        pk = re.compile(J["palatka"]["board_rx"])
        self.assertTrue(pk.match("City Commission Meeting (General)"))
        self.assertTrue(pk.match("City Commission Budget Workshop #2 (General)"))
        self.assertFalse(pk.match("Community Redevelopment Agency Meeting (General)"))
        self.assertFalse(pk.match("Planning Board Meeting (Planning Board)"))
