# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Archive Center tests.

The HTML below is SYNTHETIC, written to the CivicPlus link convention. Replace it with
real pages saved by the live workflow (`--save-raw`) once the first run completes.
"""

import json
import tempfile
import unittest
from pathlib import Path

from opencivic import archivecenter as ac

SITE = "https://www.templeterrace.gov"

INDEX = """<html><body><div id="archive">
<h2>Archive Center</h2>
<a href="/Archive.aspx?AMID=37">Archived City Council Agendas</a>
<a href="Archive.aspx?AMID=38&amp;Type=">Minutes</a>
<a href="/Archive.aspx?AMID=39">Workshop Agendas &amp; Minutes</a>
<a href="/Archive.aspx?AMID=37">Archived City Council Agendas</a>
<a href="/Calendar.aspx">Calendar</a>
</div></body></html>"""

MINUTES = """<html><body><table>
<tr><td><a href="Archive.aspx?ADID=5001">City Council Regular Meeting Minutes 10/07/2025</a></td></tr>
<tr><td><a href="/Archive.aspx?ADID=5002"><span>Council Minutes</span> September 16, 2025</a></td></tr>
<tr><td><a href="Archive.aspx?ADID=5003">Special Meeting Minutes</a></td></tr>
<tr><td><a href="Archive.aspx?ADID=5001">City Council Regular Meeting Minutes 10/07/2025</a></td></tr>
<tr><td><a href="Archive.aspx?AMID=38&amp;Type=&amp;ADID=">Back</a></td></tr>
</table></body></html>"""


class Parse(unittest.TestCase):
    def test_modules_dedup_and_ignore_others(self):
        mods = ac.parse_modules(INDEX, SITE)
        self.assertEqual([(m.amid, m.name) for m in mods],
                         [(37, "Archived City Council Agendas"), (38, "Minutes"), (39, "Workshop Agendas & Minutes")])
        self.assertEqual(mods[1].url, SITE + "/Archive.aspx?AMID=38")

    def test_items(self):
        mod = ac.Module(38, "Minutes", SITE + "/Archive.aspx?AMID=38")
        items = ac.parse_items(MINUTES, mod, SITE)
        self.assertEqual([i.adid for i in items], [5001, 5002, 5003])
        self.assertEqual(items[0].url, SITE + "/Archive.aspx?ADID=5001")
        self.assertEqual(items[1].title, "Council Minutes September 16, 2025")
        self.assertEqual([i.date for i in items], ["2025-10-07", "2025-09-16", ""])

    def test_dates(self):
        self.assertEqual(ac.parse_date("Agenda 3-3-26"), "2026-03-03")
        self.assertEqual(ac.parse_date("Minutes Sept. 2, 2025"), "2025-09-02")
        self.assertEqual(ac.parse_date("Minutes 13/45/2025"), "")
        self.assertEqual(ac.parse_date("Budget workshop"), "")


class Offline(unittest.TestCase):
    def test_crawl_from_saved_dir(self):
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d)
            (raw / "index.html").write_text(INDEX)
            (raw / "amid-37.html").write_text("<html></html>")
            (raw / "amid-38.html").write_text(MINUTES)
            (raw / "amid-39.html").write_text("<html></html>")
            out = raw / "items.jsonl"
            rc = ac.main(["items", "--input-dir", str(raw), "--module", "minutes", "-o", str(out)])
            self.assertEqual(rc, 0)
            rows = [json.loads(x) for x in out.read_text().splitlines()]
        self.assertEqual({r["amid"] for r in rows}, {38})  # "Workshop ... Minutes" has no items here
        self.assertEqual(len(rows), 3)

    def test_missing_page_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "index.html").write_text(INDEX)
            self.assertEqual(ac.main(["items", "--input-dir", d]), 1)


if __name__ == "__main__":
    unittest.main()


REAL = Path(__file__).parent / "fixtures" / "templeterrace_archive" / "index.html"


class RealIndex(unittest.TestCase):
    """Temple Terrace's real Archive.aspx, saved by the live workflow on Nov 3, 2026."""

    @classmethod
    def setUpClass(cls):
        cls.html = REAL.read_text("utf-8")
        cls.mods = {m.amid: m for m in ac.parse_modules(cls.html, SITE)}

    def test_modules(self):
        self.assertEqual(len(self.mods), 23)
        self.assertEqual(self.mods[43].name, "Archived City Council Agendas")
        self.assertEqual(self.mods[44].name, "Archived City Council Minutes")
        self.assertEqual(self.mods[45].name, "Archived City Council Workshop Agendas & Minutes")

    def test_minutes_dropdown(self):
        items = ac.parse_items(self.html, self.mods[44], SITE)
        self.assertEqual(len(items), 15)  # the "Most Recent" duplicate is skipped
        first = {i.adid: i for i in items}[9540]
        self.assertEqual(first.title, "September 15, 2026")
        self.assertEqual(first.date, "2026-09-15")
        self.assertEqual(first.url, SITE + "/Archive.aspx?ADID=9540")
        self.assertTrue(all(i.amid == 44 for i in items))
        self.assertTrue(all(i.date for i in items))

    def test_default_filter_is_city_council(self):
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d)
            (raw / "index.html").write_text(self.html)
            for amid in (43, 44, 45):
                (raw / f"amid-{amid}.html").write_text("<html></html>")
            out = raw / "items.jsonl"
            self.assertEqual(ac.main(["items", "--input-dir", str(raw), "-o", str(out)]), 0)
            rows = [json.loads(x) for x in out.read_text().splitlines()]
        self.assertEqual({r["amid"] for r in rows}, {43, 44, 45})


class RealModulePage(unittest.TestCase):
    """Archive.aspx?AMID=44 (all City Council minutes), saved live on Nov 3, 2026."""

    def test_all_minutes(self):
        html_ = (REAL.parent / "amid-44.html").read_text("utf-8")
        mod = ac.Module(44, "Archived City Council Minutes", SITE + "/Archive.aspx?AMID=44")
        items = ac.parse_items(html_, mod, SITE)
        self.assertEqual(len(items), 24)
        dates = sorted(i.date for i in items)
        self.assertEqual((dates[0], dates[-1]), ("2025-11-04", "2026-10-06"))
