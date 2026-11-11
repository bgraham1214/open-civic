# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Offline tests for the Legistar adapter, against saved Hillsborough and Hernando responses."""

import json
import unittest
from datetime import date
from pathlib import Path

from opencivic import legistar as lg
from opencivic.fetch import FetchError, FixtureFetcher

FIX = Path(__file__).parent / "fixtures" / "legistar"


def load(name):
    return json.loads((FIX / name).read_text("utf-8"))


class Events(unittest.TestCase):
    def test_parse_and_page(self):
        url = lg.events_url("hernandocountyfl", "2025-01-01")
        self.assertIn("$filter=EventDate%20ge%20datetime%272025-01-01%27", url)
        f = FixtureFetcher({url: FIX / "hernandocountyfl-events.json"})
        events = lg.crawl_events("hernandocountyfl", f, "2025-01-01")
        self.assertEqual([e["event_id"] for e in events], [1484, 1488])  # sorted by date
        e = events[1]
        self.assertEqual((e["date"], e["body"], e["minutes_status"]), ("2026-09-01", "Board of County Commissioners", "Final"))
        self.assertTrue(e["portal_url"].startswith("https://hernandocountyfl.legistar.com/MeetingDetail.aspx"))
        self.assertEqual(f.requested, [url])  # fewer than 1000 rows: no second page

    def test_private_bodies_skipped(self):
        raw = load("hernandocountyfl-events.json")
        raw[0] = {**raw[0], "EventBodyName": "Value Adjustment Board"}
        tmp = Path(self.id().replace(".", "_") + ".json")
        tmp.write_text(json.dumps(raw))
        self.addCleanup(tmp.unlink)
        f = FixtureFetcher({lg.events_url("x", "2025-01-01"): tmp})
        self.assertEqual(len(lg.crawl_events("x", f, "2025-01-01")), 1)
        f = FixtureFetcher({lg.events_url("x", "2025-01-01"): tmp})
        self.assertEqual(len(lg.crawl_events("x", f, "2025-01-01", include_private=True)), 2)

    def test_error_body_is_an_error(self):
        tmp = Path(self.id().replace(".", "_") + ".json")
        tmp.write_text(json.dumps({"Message": "Agency not found"}))
        self.addCleanup(tmp.unlink)
        with self.assertRaises(FetchError):
            lg.crawl_events("nope", FixtureFetcher({lg.events_url("nope", "2025-01-01"): tmp}), "2025-01-01")


class Items(unittest.TestCase):
    EV = lg.parse_event("hillsboroughcounty", load("hillsboroughcounty-event-1412.json"))

    def fetcher(self):
        return FixtureFetcher({
            lg.items_url("hillsboroughcounty", 1412): FIX / "hillsboroughcounty-event-1412-items.json",
            lg.votes_url("hillsboroughcounty", 131875): FIX / "hillsboroughcounty-item-131875-votes.json",
            lg.votes_url("hillsboroughcounty", 131876): FIX / "empty-votes.json",
            lg.votes_url("hillsboroughcounty", 131869): FIX / "empty-votes.json",
        })

    def test_items_and_votes(self):
        f = self.fetcher()
        items, votes, stats = lg.crawl_items("hillsboroughcounty", [self.EV], f, today=date(2026, 11, 8))
        cont = next(i for i in items if i["number"] == "A.1.")
        self.assertEqual((cont["action"], cont["result"], cont["mover"], cont["seconder"]),
                         ("Continued", "Pass", "Gwen Myers", "Chris Boles"))
        self.assertEqual(cont["file_number"], "MM 26-0062")
        # LegislationDetail links built from API ids are rejected by Legistar ("Invalid parameters!")
        self.assertEqual(cont["matter_url"], "")
        self.assertIn("MeetingDetail.aspx", cont["portal_url"])
        self.assertTrue(cont["attachments"])
        self.assertNotIn("\t", cont["title"])
        self.assertEqual(len([v for v in votes if v["item_key"] == cont["key"]]), 7)
        self.assertEqual({v["vote"] for v in votes}, {"In Favor"})
        self.assertEqual(stats["fetched"], 1)
        # no request ever goes to the robots-disallowed file server
        self.assertFalse([u for u in f.requested if "legistar1.com" in u])

    def test_unchanged_old_event_is_reused(self):
        items, votes, _ = lg.crawl_items("hillsboroughcounty", [self.EV], self.fetcher(), today=date(2026, 11, 8))
        again, again_votes, stats = lg.crawl_items(
            "hillsboroughcounty", [self.EV], FixtureFetcher({}), previous_items=items, previous_votes=votes,
            today=date(2027, 3, 1))  # meeting is now > 60 days old
        self.assertEqual((stats["reused"], stats["requests"]), (1, 0))
        self.assertEqual((len(again), len(again_votes)), (len(items), len(votes)))

    def test_budget_defers_and_keeps_previous(self):
        items, votes, _ = lg.crawl_items("hillsboroughcounty", [self.EV], self.fetcher(), today=date(2026, 11, 8))
        changed = {**self.EV, "last_modified": "2026-11-01T00:00:00"}
        again, _, stats = lg.crawl_items("hillsboroughcounty", [changed], FixtureFetcher({}), previous_items=items,
                                         previous_votes=votes, max_requests=0, today=date(2026, 11, 8))
        self.assertEqual((stats["deferred"], len(again)), (1, len(items)))

    def test_fetch_error_keeps_previous(self):
        items, votes, _ = lg.crawl_items("hillsboroughcounty", [self.EV], self.fetcher(), today=date(2026, 11, 8))
        again, _, stats = lg.crawl_items("hillsboroughcounty", [self.EV], FixtureFetcher({}), previous_items=items,
                                         previous_votes=votes, today=date(2026, 11, 8))
        self.assertEqual((stats["errors"], len(again)), (1, len(items)))

    def test_hernando_items(self):
        ev = lg.parse_event("hernandocountyfl", load("hernandocountyfl-events.json")[0])
        raw = load("hernandocountyfl-event-1488-items.json")
        ev = {**ev, "event_id": 1488}
        rows = [lg.parse_item("hernandocountyfl", ev, r) for r in raw]
        agenda = next(r for r in rows if r["title"] == "AGENDA")
        self.assertEqual((agenda["mover"], agenda["seconder"], agenda["result"]), ("Steve Champion", "Ryan Amsler", "Pass"))
        self.assertEqual(sum(lg.wants_votes(r) for r in raw), sum(1 for r in rows if r["result"]) + sum(
            1 for r in raw if r["EventItemPassedFlag"] is None and r["EventItemRollCallFlag"] == 1))


if __name__ == "__main__":
    unittest.main()


class ItemLinks(unittest.TestCase):
    PAGE = (FIX / "meetingdetail-hernando-1399-rows.html").read_text()
    MEETING = "https://hernandocountyfl.legistar.com/MeetingDetail.aspx?LEGID=1399&GID=881&G=6D9E70B1"

    def test_rows_give_each_file_its_page(self):
        links = lg.parse_item_links("hernandocountyfl", self.PAGE)
        # File 15403 appears on two rows with the same link: one entry
        self.assertEqual(links["15403"], "https://hernandocountyfl.legistar.com/LegislationDetail.aspx"
                                         "?ID=7086147&GUID=090C0A00-1EFF-4D05-A97A-487554A63E88")
        self.assertIn("15187", links)
        self.assertTrue(all("&amp;" not in u and "Options" not in u for u in links.values()))

    def test_ambiguous_file_number_is_left_out(self):
        self.assertIn(">15187<", self.PAGE)
        page = self.PAGE.replace(">15187<", ">15403<")  # now 15403 points at two different item pages
        links = lg.parse_item_links("hernandocountyfl", page)
        self.assertNotIn("15403", links)
        self.assertIn("15252", links)

    def test_recent_meetings_reread_older_reused(self):
        events = [{"event_id": 1, "date": "2025-02-04", "portal_url": self.MEETING},
                  {"event_id": 2, "date": "2026-11-03", "portal_url": self.MEETING + "2"},
                  {"event_id": 3, "date": "2026-11-04", "portal_url": ""}]
        prev = [{"event_id": 1, "date": "2025-02-04", "links": {"1": "u"}, "checked": "2025-02-05"}]
        fx = FixtureFetcher({self.MEETING + "2": FIX / "meetingdetail-hernando-1399-rows.html"})
        rows, stats = lg.crawl_links("hernandocountyfl", events, fx, previous=prev, today=date(2026, 11, 11))
        self.assertEqual((stats["reused"], stats["fetched"], stats["events"]), (1, 1, 2))
        self.assertEqual(rows[0]["links"], {"1": "u"})
        self.assertIn("15403", rows[1]["links"])
        # a page that can't be read keeps the last reading
        rows, stats = lg.crawl_links("hernandocountyfl", events[1:2], FixtureFetcher({}),
                                     previous=[{**rows[1]}], today=date(2026, 11, 11))
        self.assertEqual((stats["errors"], len(rows)), (1, 1))
