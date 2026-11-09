# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""County site: database, area tags, feeds and page, from saved Legistar responses."""

import gzip
import json
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from opencivic import build, legistar as lg, region
from opencivic.fetch import FixtureFetcher

FIX = Path(__file__).parent / "fixtures" / "legistar"
SITE = "https://example.github.io/open-civic/"


def jl(rows):
    return "".join(json.dumps(r) + "\n" for r in rows)


def make_data(d: Path) -> Path:
    data = d / "data"
    (data / "listings").mkdir(parents=True)
    (data / "text").mkdir()
    ev = lg.parse_event("hillsboroughcounty", json.loads((FIX / "hillsboroughcounty-event-1412.json").read_text()))
    f = FixtureFetcher({
        lg.items_url("hillsboroughcounty", 1412): FIX / "hillsboroughcounty-event-1412-items.json",
        lg.votes_url("hillsboroughcounty", 131875): FIX / "hillsboroughcounty-item-131875-votes.json",
        lg.votes_url("hillsboroughcounty", 131876): FIX / "empty-votes.json",
        lg.votes_url("hillsboroughcounty", 131869): FIX / "empty-votes.json"})
    items, votes, _ = lg.crawl_items("hillsboroughcounty", [ev], f, today=date(2026, 11, 8))
    a1 = next(i for i in items if i["number"] == "A.1.")
    a1["title"] += "\nLocation: Bloomingdale Ave east of Brandon Blvd"  # area tagging
    next(v for v in votes if v["person"] == "Ken Hagan")["vote"] = "Nay"
    lst = data / "listings"
    (lst / "legistar-hillsboroughcounty-events.jsonl").write_text(jl([ev]))
    (lst / "legistar-hillsboroughcounty-items.jsonl").write_text(jl(items))
    (lst / "legistar-hillsboroughcounty-votes.jsonl").write_text(jl(votes))
    (lst / "civicclerk-pascocofl-meetings.jsonl").write_text(jl([{
        "tenant": "pascocofl", "event_id": 9, "date": "2025-03-04", "start": "2025-03-04T10:00:00Z",
        "name": "Board of County Commissioners", "category": "BOCC", "location": "Dade City",
        "portal_url": "https://pascocofl.portal.civicclerk.com/event/9/files",
        "files": [{"kind": "Agenda", "file_id": 1}]}]))
    sha = "c" * 64
    state = {
        "civicclerk:pascocofl:1": {"key": "civicclerk:pascocofl:1", "source": "civicclerk", "kind": "Agenda",
                                   "date": "2025-03-04", "title": "BOCC Agenda", "body": "BOCC", "url": "https://p/1",
                                   "copy_url": "https://c/" + sha + ".pdf", "sha256": sha, "bytes": 5,
                                   "first_seen": "2026-11-09T00:00:00Z", "listed": True},
        "civicclerk:templeterracefl:5": {"key": "civicclerk:templeterracefl:5", "source": "civicclerk",
                                         "kind": "Agenda", "date": "2026-10-20", "title": "TT", "url": "u",
                                         "sha256": "d" * 64, "first_seen": "2026-11-03T00:00:00Z", "listed": True}}
    (data / "state.json").write_text(json.dumps(state))
    with gzip.open(data / "text" / f"{sha}.json.gz", "wt") as fh:
        json.dump({"pages": [{"n": 1, "text": "Wesley Chapel Blvd road widening", "method": "pdftotext"}]}, fh)
    (data / "manifest.jsonl").write_text(jl([{"event": "new", "key": "civicclerk:pascocofl:1", "at": "x"},
                                             {"event": "new", "key": "civicclerk:templeterracefl:5", "at": "y"}]))
    return data


class Region(unittest.TestCase):
    def test_db_feeds_page(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            data, out = make_data(d), d / "site"
            out.mkdir()
            counts = region.write(data, out, SITE, "2026-11-09T02:00:00Z", build._rss)
            bc = counts["by_county"]
            self.assertEqual((bc["hillsborough"]["meetings"], bc["hillsborough"]["votes"]), (1, 7))
            self.assertEqual((bc["pasco"]["meetings"], bc["pasco"]["documents"]), (1, 1))
            self.assertEqual(counts["changes"], 1)  # Temple Terrace's change stays out
            con = sqlite3.connect(out / "counties.db")
            row = con.execute("SELECT areas, votes, nays, mover FROM agenda_items WHERE number='A.1.'").fetchone()
            self.assertEqual(row[0], "Brandon")
            self.assertEqual(row[1], "6 in favor, 1 nay")
            self.assertEqual(row[2], "Ken Hagan")
            self.assertEqual(row[3], "Gwen Myers")
            self.assertEqual(con.execute("SELECT areas FROM pages").fetchone()[0], "Wesley Chapel")
            self.assertEqual(con.execute("SELECT count(*) FROM agenda_items_fts WHERE agenda_items_fts MATCH 'withdrawn'")
                             .fetchone()[0], 1)
            con.close()
            self.assertIn("MM 26-0062", (out / "feeds" / "area-brandon.xml").read_text())
            self.assertNotIn("PRS 26-0610", (out / "feeds" / "area-brandon.xml").read_text())
            self.assertIn("BOCC Agenda", (out / "feeds" / "pasco.xml").read_text())
            page = (out / "counties.html").read_text()
            for s in ("Hillsborough County", "Wesley Chapel", "Spring Hill", "areas__contains=Brandon",
                      "lite.datasette.io/?url=" + SITE + "counties.db"):
                self.assertIn(s, page)

    def test_one_roll_call_on_several_items_keeps_every_vote(self):
        # Seen live: Legistar returns the same VoteId under each item a single motion covers.
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            data, out = make_data(d), d / "site"
            out.mkdir()
            lst = data / "listings" / "legistar-hillsboroughcounty-votes.jsonl"
            votes = [json.loads(x) for x in lst.read_text().splitlines()]
            other = "legistar:hillsboroughcounty:item:131876"
            old_style = [{**v, "key": "legistar:hillsboroughcounty:vote:" + v["key"].rsplit(":", 1)[-1]} for v in votes]
            lst.write_text(jl(votes + [{**v, "item_key": other} for v in old_style]))
            counts = region.write(data, out, SITE, "2026-11-09T02:00:00Z", build._rss)
            self.assertEqual(counts["votes"], 14)
            self.assertTrue(all(len(v["key"].split(":")) == 5 for v in votes))

    def test_clerk_roll_calls(self):
        from opencivic import hillsclerk as hc
        fx = Path(__file__).parent / "fixtures" / "hillsclerk" / "bocc-vote-comparison-2025-p1-2-69.txt"
        rows, _ = hc.parse_report(fx.read_text(), "hillsclerk:bocc-votes:2025", "https://www.hillsclerk.com/r.pdf")
        rows[1]["subject"] += " Bloomingdale Ave, Brandon."
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            data, out = make_data(d), d / "site"
            out.mkdir()
            (data / "listings" / "hillsclerk-bocc-votes.jsonl").write_text(jl(rows))
            region.write(data, out, SITE, "2026-11-09T02:00:00Z", build._rss)
            con = sqlite3.connect(out / "counties.db")
            people = {r[0] for r in con.execute("SELECT person FROM votes WHERE key LIKE 'hillsclerk%'")}
            # names matched to Legistar's full names where one fits; others kept as printed
            self.assertIn("Ken Hagan", people)
            self.assertIn("Gwen Myers", people)
            self.assertEqual(con.execute("SELECT count(*) FROM agenda_items WHERE key LIKE 'hillsclerk%'").fetchone()[0],
                             len(rows))
            self.assertEqual(con.execute("SELECT areas FROM agenda_items WHERE file_number='RCS 4693'").fetchone()[0],
                             "Brandon")
            self.assertEqual({r[0] for r in con.execute("SELECT DISTINCT vote FROM votes WHERE key LIKE 'hillsclerk%'")},
                             {"Yes", "X"})
            con.close()

    def test_private_boards_never_shown(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            data, out = make_data(d), d / "site"
            out.mkdir()
            lst = data / "listings"
            vab = {"tenant": "pascocofl", "event_id": 77, "date": "2025-06-02", "start": "2025-06-02T09:00:00Z",
                   "name": "Value Adjustment Board 2024 Final Meeting", "category": "Value Adjustment Board",
                   "location": "", "portal_url": "p", "files": [{"kind": "Agenda", "file_id": 8613}]}
            with (lst / "civicclerk-pascocofl-meetings.jsonl").open("a") as fh:
                fh.write(json.dumps(vab) + "\n")
            (lst / "civicclerk-pascocofl-items.jsonl").write_text(jl([{
                "key": "civicclerk:pascocofl:item:1", "event_id": 77, "is_section": False, "date": "2025-06-02",
                "meeting": "VAB", "category": "Value Adjustment Board", "outline": "1", "title": "Petition 123",
                "portal_url": "p"}]))
            with (data / "manifest.jsonl").open("a") as fh:
                fh.write(json.dumps({"event": "new", "key": "civicclerk:pascocofl:8613", "at": "a",
                                     "title": "VAB Agenda", "copy_url": "https://c/x.pdf"}) + "\n")
                fh.write(json.dumps({"event": "excluded", "key": "civicclerk:pascocofl:8613", "at": "b",
                                     "reason": "Value Adjustment Board hearing"}) + "\n")
            counts = region.write(data, out, SITE, "2026-11-09T02:00:00Z", build._rss)
            self.assertEqual(counts["by_county"]["pasco"]["meetings"], 1)
            self.assertEqual(counts["by_county"]["pasco"]["agenda_items"], 0)
            con = sqlite3.connect(out / "counties.db")
            rows = con.execute("SELECT event, title, our_copy FROM changes WHERE document_key='civicclerk:pascocofl:8613'").fetchall()
            self.assertEqual(rows, [("excluded", "Value Adjustment Board hearing", "")])
            con.close()
            # and the manifest never lists them again
            from opencivic import manifest as mf
            only_vab = d / "vab.jsonl"
            only_vab.write_text(json.dumps({**vab, "files": [{**vab["files"][0], "name": "Agenda",
                                                               "download_url": "u"}]}) + "\n")
            self.assertEqual(mf.docs_from_civicclerk(only_vab), [])

    def test_full_names(self):
        full = {"Christine Miller", "Donna Cameron Cepeda", "Ken Hagan", "Kevin Hagan"}
        m = region.full_names(["C. Miller", "Cameron Cepeda", "Hagan", "Cohen"], full)
        self.assertEqual(m, {"C. Miller": "Christine Miller", "Cameron Cepeda": "Donna Cameron Cepeda",
                             "Hagan": "Hagan", "Cohen": "Cohen"})  # two Hagans: ambiguous, kept

    def test_name_resolver_by_date(self):
        known = {"Lesley Miller": ("2014-01-08", "2017-09-20"), "Christine Miller": ("2025-01-07", "2026-11-03"),
                 "Ken Hagan": ("2014-01-08", "2026-11-03"), "Mariella Smith": ("", "")}
        r = region.name_resolver(known)
        self.assertEqual(r("Miller", "2019-05-01"), "Lesley Miller")
        self.assertEqual(r("Miller", "2020-11-16"), "Lesley Miller")
        self.assertEqual(r("C. Miller", "2024-12-10"), "Christine Miller")
        self.assertEqual(r("Miller", "2021-05-15"), "Miller")       # midway between the two: left as printed
        self.assertEqual(r("Hagan", "2019-01-01"), "Ken Hagan")
        self.assertEqual(r("Smith", "2020-01-01"), "Mariella Smith")
        self.assertEqual(r("Owen", "2023-01-01"), "Owen")           # no full name known: as printed

    def test_city_site_ignores_county_records(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            data = make_data(d)
            con_path = d / "tt.db"
            build.build_db(data, con_path)
            con = sqlite3.connect(con_path)
            self.assertEqual([r[0] for r in con.execute("SELECT key FROM documents")], ["civicclerk:templeterracefl:5"])
            self.assertEqual(con.execute("SELECT count(*) FROM changes").fetchone()[0], 1)
            con.close()


if __name__ == "__main__":
    unittest.main()
