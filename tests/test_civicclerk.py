"""Offline tests: run against Temple Terrace's saved CivicClerk responses.

    python -m unittest discover -s tests -v
"""

import copy
import io
import json
import tempfile
import unittest
from pathlib import Path

from opencivic import civicclerk as cc
from opencivic.fetch import FetchError, FixtureFetcher

FIX = Path(__file__).parent / "fixtures" / "templeterracefl"
TENANT = "templeterracefl"
BASE = cc.api_base(TENANT)


def sample_page() -> dict:
    return json.loads((FIX / "Events.json").read_text("utf-8"))


class ParseSample(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        page = sample_page()
        cls.page = page
        cls.meetings = {m.event_id: m for m in (cc.parse_event(TENANT, e) for e in page["value"])}

    def test_counts(self):
        self.assertEqual(len(self.meetings), 15)
        with_files = [m for m in self.meetings.values() if m.files]
        self.assertEqual(len(with_files), 7)
        self.assertEqual(sum(len(m.files) for m in with_files), 14)

    def test_nov_4_2025_meeting(self):
        m = self.meetings[8]
        self.assertEqual(m.name, "City Council Meeting")
        self.assertEqual(m.category, "City Council")
        self.assertEqual(m.date, "2025-11-04")
        self.assertEqual(m.agenda_id, 21)
        self.assertTrue(m.has_agenda)
        self.assertEqual(m.agenda_note, "Amended on October 31, 2025 4:23 PM")
        self.assertEqual(m.location, "11250 N. 56th Street, Temple Terrace, FL 33617")
        self.assertEqual(m.portal_url, "https://templeterracefl.portal.civicclerk.com/event/8/files")
        self.assertEqual([f.kind for f in m.files], ["Agenda", "Agenda Packet"])
        agenda = m.files[0]
        self.assertEqual(agenda.file_id, 1047)
        self.assertEqual(agenda.name, "City Council Agenda V3")
        self.assertEqual(agenda.storage_path, "stream/TEMPLETERRACEFL/56036c2b-1cd8-4e69-bb8b-2c556fc1618c.pdf")
        self.assertEqual(agenda.download_url,
                         BASE + "Meetings/GetMeetingFileStream(fileId=1047,plainText=false)")
        self.assertTrue(agenda.text_url.endswith("plainText=true)"))

    def test_location_without_city(self):
        self.assertEqual(self.meetings[2].location, "City Hall Council Chambers")

    def test_file_ids_unique(self):
        ids = [f.file_id for m in self.meetings.values() for f in m.files]
        self.assertEqual(len(ids), len(set(ids)))

    def test_dates_look_valid(self):
        for m in self.meetings.values():
            self.assertRegex(m.date, r"^20\d\d-\d\d-\d\d$")


class Pagination(unittest.TestCase):
    def _two_pages(self, tmp: Path) -> FixtureFetcher:
        page1 = sample_page()
        next_url = page1["@odata.nextLink"]
        extra = copy.deepcopy(page1["value"][7])  # event 10 as a template
        extra.update(id=18, eventDate="2026-02-17T18:00:00Z", startDateTime="2026-02-17T18:00:00Z")
        for f in extra["publishedFiles"]:
            f["fileId"] += 10000
        dup = copy.deepcopy(page1["value"][0])  # an id already seen, renamed on page 2
        dup["eventName"] = "Renamed on page 2"
        page2 = {"value": [extra, dup]}
        (tmp / "p1.json").write_text(json.dumps(page1))
        (tmp / "p2.json").write_text(json.dumps(page2))
        return FixtureFetcher({BASE + "Events": tmp / "p1.json", next_url: tmp / "p2.json"})

    def test_follows_next_link_and_dedups(self):
        with tempfile.TemporaryDirectory() as d:
            fetcher = self._two_pages(Path(d))
            crawl = cc.crawl_events(TENANT, fetcher)
        self.assertEqual(crawl.pages, 2)
        self.assertIsNone(crawl.unfollowed_next_link)
        ids = [m.event_id for m in crawl.meetings]
        self.assertEqual(len(ids), 16)
        self.assertEqual(len(set(ids)), 16)
        by_id = {m.event_id: m for m in crawl.meetings}
        self.assertEqual(by_id[2].name, "Renamed on page 2")
        self.assertEqual(ids, [m.event_id for m in sorted(crawl.meetings, key=lambda m: (m.date, m.event_id))])

    def test_max_pages_reports_unfollowed_link(self):
        fetcher = FixtureFetcher({BASE + "Events": FIX / "Events.json"})
        crawl = cc.crawl_events(TENANT, fetcher, max_pages=1)
        self.assertEqual(crawl.unfollowed_next_link, BASE + "Events?$skiptoken=id-17")
        self.assertEqual(fetcher.requested, [BASE + "Events"])

    def test_missing_page_raises_offline(self):
        fetcher = FixtureFetcher({BASE + "Events": FIX / "Events.json"})
        with self.assertRaises(FetchError):
            cc.crawl_events(TENANT, fetcher)

    def test_loop_guard(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "loop.json"
            p.write_text(json.dumps({"value": [], "@odata.nextLink": BASE + "Events"}))
            with self.assertRaises(FetchError):
                cc.crawl_events(TENANT, FixtureFetcher({BASE + "Events": p}))


class Schema(unittest.TestCase):
    def test_saved_metadata_matches(self):
        xml = (FIX / "metadata.xml").read_text("utf-8")
        self.assertEqual(cc.schema_problems(xml), [])

    def test_detects_drift(self):
        xml = (FIX / "metadata.xml").read_text("utf-8").replace('Name="fileId"', 'Name="fileID"')
        self.assertIn("PublishFileModel.fileId missing", cc.schema_problems(xml))


class Cli(unittest.TestCase):
    def test_files_csv_offline(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "files.csv"
            rc = cc.main(["files", "--input", str(FIX / "Events.json"), "--format", "csv", "-o", str(out)])
            self.assertEqual(rc, 0)
            lines = out.read_text("utf-8").splitlines()
        self.assertEqual(lines[0].split(","), cc.FILE_COLUMNS)
        self.assertEqual(len(lines), 15)  # header + 14 files

    def test_meetings_jsonl_filters(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "m.jsonl"
            cc.main(["meetings", "--input", str(FIX / "Events.json"), "--category", "city council",
                     "--with-files-only", "-o", str(out)])
            rows = [json.loads(line) for line in out.read_text("utf-8").splitlines()]
        self.assertEqual(len(rows), 7)
        self.assertEqual(rows[0]["date"], "2025-11-04")
        self.assertEqual(len(rows[0]["files"]), 2)

    def test_check_schema_offline(self):
        self.assertEqual(cc.main(["check-schema", "--metadata", str(FIX / "metadata.xml")]), 0)


if __name__ == "__main__":
    unittest.main()


class Redaction(unittest.TestCase):
    def test_signed_urls_redacted(self):
        from opencivic.fetch import redact_signed_urls
        s = '{"p":"https://civicclerk.blob.core.windows.net/stream/T/a.pdf?sv=1&sp=rw&sig=AB%3D","q":"https://x.org/a?b=1"}'
        out = redact_signed_urls(s)
        self.assertNotIn("sig=", out)
        self.assertIn("https://civicclerk.blob.core.windows.net/stream/T/a.pdf?[signed-url-redacted]", out)
        self.assertIn("https://x.org/a?b=1", out)
