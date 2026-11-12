# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""The shared page shell, the front door, and the files for machines."""

import json
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from opencivic import site

SITE = "https://example.github.io/open-civic/"


def jsonld(html_: str) -> list[dict]:
    return [json.loads(m) for m in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html_, re.S)]


class Shell(unittest.TestCase):
    def setUp(self):
        site.configure(SITE, "2026-11-10T02:49:00Z")

    def tearDown(self):
        site.configure("", "")

    def test_every_page_has_the_accessible_frame(self):
        p = site.page("Wednesday: what happened", "<h1>Hi</h1>", 2, path="meetings/x/2026-09-16.html",
                      description="  A   meeting. ", crumbs=[("County records", "counties.html")], here="Sept 16")
        self.assertIn('<html lang="en">', p)
        self.assertIn('<a class="skip" href="#main">', p)
        self.assertEqual(p.count("<main"), 1)
        self.assertIn('<main id="main"', p)
        self.assertIn('<nav aria-label="Site">', p)
        self.assertIn('<meta name="description" content="A meeting.">', p)
        self.assertIn(f'<link rel="canonical" href="{SITE}meetings/x/2026-09-16.html">', p)
        self.assertIn('href="../../counties.html">County records</a>', p)
        self.assertIn('<span aria-current="page">Sept 16</span>', p)
        self.assertIn('href="../../plain.css"', p)
        self.assertIn("November 9, 2026 at 9:49 PM Eastern", p)
        crumbs = [b for b in jsonld(p) if b["@type"] == "BreadcrumbList"][0]["itemListElement"]
        self.assertEqual([c["name"] for c in crumbs], ["Home", "County records", "Sept 16"])
        self.assertEqual(crumbs[-1]["item"], SITE + "meetings/x/2026-09-16.html")

    def test_home_has_no_breadcrumb(self):
        self.assertNotIn('aria-label="You are here"', site.page("Home", "", 0, path="index.html"))

    def test_jsonld_cannot_break_out_of_its_script(self):
        block = site.ld({"@type": "Thing", "name": "</script><script>alert(1)</script>", "url": None})
        self.assertEqual(block.count("</script>"), 1)
        self.assertNotIn('"url"', block)   # unknown values are left out, not published as null
        self.assertEqual(json.loads(block[block.index(">") + 1:-9])["name"], "</script><script>alert(1)</script>")

    def test_eastern_time_follows_daylight_saving(self):
        self.assertEqual(site.eastern("2026-07-04T16:00:00Z"), "July 4, 2026 at 12:00 PM Eastern")
        self.assertEqual(site.eastern("2026-03-08T07:00:00Z"), "March 8, 2026 at 3:00 AM Eastern")
        self.assertEqual(site.eastern("2026-11-01T06:00:00Z"), "November 1, 2026 at 1:00 AM Eastern")
        self.assertEqual(site.to_eastern("2026-11-10T02:49:00Z").date().isoformat(), "2026-11-09")


class Common(unittest.TestCase):
    def setUp(self):
        site.configure(SITE, "2026-11-10T02:49:00Z")

    def tearDown(self):
        site.configure("", "")

    def test_front_door_glossary_data_sitemap_llms(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            for day in ("2026-10-01", "2026-11-20"):
                (out / "meetings" / "hernando").mkdir(parents=True, exist_ok=True)
                (out / "meetings" / "hernando" / f"{day}.html").write_text("x")
            (out / "meetings" / "hernando.html").write_text("x")
            (out / "commissioners").mkdir()
            (out / "commissioners" / "hernando.html").write_text("x")
            (out / "counties.db").write_bytes(b"x" * 2_500_000)
            counts = site.write_common(out, today="2026-11-09", tt={"latest": "2026-11-02", "removed": 1},
                                       lite={"counties.db": "https://lite.datasette.io/?url=c"})
            home = (out / "index.html").read_text()
            for area in ("Temple Terrace", "Brandon", "Lutz", "Wesley Chapel", "Spring Hill"):
                self.assertIn(f"<h3>{area}</h3>", home)
            self.assertIn('Latest meeting: <a href="meetings/hernando/2026-10-01.html">Thursday, October 1, 2026</a>', home)
            self.assertIn('Next on the calendar: <a href="meetings/hernando/2026-11-20.html">', home)
            self.assertIn("taken down 1 document we archived", home)
            self.assertIn('href="feeds/area-wesley-chapel.xml"', home)
            self.assertEqual(jsonld(home)[0]["@type"], "WebSite")
            gloss = (out / "learn" / "index.html").read_text()
            self.assertIn('<dt id="prs">', gloss)
            self.assertEqual(jsonld(gloss)[0]["@type"], "DefinedTermSet")
            data = (out / "data.html").read_text()
            self.assertIn("SQLite, 2 MB", data)
            self.assertIn("https://lite.datasette.io/?url=c", data)
            catalog = jsonld(data)[0]
            self.assertEqual(catalog["@type"], "DataCatalog")
            self.assertEqual(len(catalog["dataset"]), 3)
            urls = [u[0].text for u in ET.parse(out / "sitemap.xml").getroot()]
            self.assertEqual(urls[0], SITE + "index.html")
            self.assertIn(SITE + "meetings/hernando/2026-11-20.html", urls)
            self.assertEqual(counts["pages"], len(urls))
            llms = (out / "llms.txt").read_text()
            self.assertTrue(llms.startswith("# Open Civic Web\n\n> "))
            self.assertIn(f"[Hernando County Commission members]({SITE}commissioners/hernando.html)", llms)
            self.assertNotIn("Pasco County Commission meetings", llms)   # only pages that exist
            self.assertTrue((out / "plain.css").exists())


if __name__ == "__main__":
    unittest.main()
