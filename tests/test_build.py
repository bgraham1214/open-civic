"""Site build: database, full-text search, feeds, landing page."""

import gzip
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from opencivic import build

SITE = "https://example.github.io/open-civic/"


def make_data(d: Path) -> Path:
    data = d / "data"
    (data / "text").mkdir(parents=True)
    (data / "listings").mkdir()
    sha = "b" * 64
    state = {"civicclerk:t:1": {
        "key": "civicclerk:t:1", "source": "civicclerk", "kind": "Agenda", "date": "2026-10-20",
        "title": "City Council Agenda 10-20-26", "body": "City Council Meeting (City Council)",
        "url": "https://city.example/f/1", "page": "https://city.example/event/1/files",
        "copy_url": "https://github.com/x/y/releases/download/files/" + sha + ".pdf",
        "sha256": sha, "bytes": 10, "first_seen": "2026-11-03T21:00:00Z", "last_changed": "2026-11-03T21:00:00Z",
        "listed": True, "ext": "pdf"}}
    (data / "state.json").write_text(json.dumps(state))
    with gzip.open(data / "text" / f"{sha}.json.gz", "wt") as fh:
        json.dump({"sha256": sha, "pages": [
            {"n": 1, "text": "Resolution approving an annexation agreement", "method": "pdftotext"},
            {"n": 2, "text": "Minutes read from a scan: zoning hearing", "method": "ocr"},
            {"n": 3, "text": "   ", "method": "pdftotext"}]}, fh)
    item = {"date": "2026-10-20", "meeting": "City Council Meeting", "category": "City Council",
            "section": "Consent Agenda", "fiscal_impact": "", "resolution_number": "", "ordinance_number": "",
            "portal_url": "https://city.example/event/1/agenda"}
    (data / "listings" / "civicclerk-items.jsonl").write_text("\n".join(json.dumps(x) for x in [
        {**item, "key": "civicclerk:t:item:1", "is_section": True, "outline": "11.", "item_number": "",
         "title": "Consent Agenda", "description": "", "attachments": []},
        {**item, "key": "civicclerk:t:item:2", "is_section": False, "outline": "11.D.", "item_number": "2026-257",
         "title": "Resolution Approving Contract Renewal for Audit Services",
         "description": "Staff recommends approval.",
         "attachments": [{"id": 1, "name": "Resolution", "content_type": "x", "bytes": 1}]}]) + "\n")
    (data / "manifest.jsonl").write_text(json.dumps({
        "event": "new", "key": "civicclerk:t:1", "at": "2026-11-03T21:00:00Z", "date": "2026-10-20",
        "kind": "Agenda", "title": "City Council Agenda 10-20-26", "sha256": sha, "bytes": 10,
        "url": "https://city.example/f/1", "copy_url": state["civicclerk:t:1"]["copy_url"]}) + "\n")
    return data


class Build(unittest.TestCase):
    def test_site(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            counts = build.write_site(make_data(d), d / "site", SITE)
            self.assertEqual(counts, {"meetings": 0, "documents": 1, "pages": 2, "agenda_items": 1, "changes": 1})
            con = sqlite3.connect(d / "site" / "templeterrace.db")
            hit = con.execute("SELECT p.page, p.method, p.link FROM pages_fts JOIN pages p ON p.id = pages_fts.rowid "
                              "WHERE pages_fts MATCH 'zoning'").fetchall()
            self.assertEqual(len(hit), 1)
            self.assertEqual(hit[0][1], "ocr")
            self.assertTrue(hit[0][2].endswith(".pdf#page=2"))
            self.assertEqual(con.execute("SELECT count(*) FROM agenda_items_fts WHERE agenda_items_fts MATCH 'audit'")
                             .fetchone()[0], 1)
            # porter stemming: "annex" finds "annexation"
            self.assertEqual(con.execute("SELECT count(*) FROM pages_fts WHERE pages_fts MATCH 'annex*'").fetchone()[0], 1)
            con.close()
            contracts = (d / "site" / "feeds" / "contracts.xml").read_text()
            self.assertIn("Audit Services", contracts)
            self.assertIn("lite.datasette.io/?url=" + SITE + "templeterrace.db", (d / "site" / "index.html").read_text())
            meta = json.loads((d / "site" / "metadata.json").read_text())
            self.assertIn("ocr", meta["databases"]["templeterrace"]["tables"]["pages"]["description"])


if __name__ == "__main__":
    unittest.main()
