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
