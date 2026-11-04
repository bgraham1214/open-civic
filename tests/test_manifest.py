# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Manifest tests: listings come from the saved Temple Terrace fixtures; downloads are faked."""

import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from opencivic import archivecenter as ac
from opencivic import civicclerk as cc
from opencivic import manifest as mf
from opencivic.fetch import FetchError

FIX = Path(__file__).parent / "fixtures"
SITE = "https://www.templeterrace.gov"


class FakeFetcher:
    def __init__(self, bodies: dict[str, bytes]):
        self.bodies = bodies
        self.calls: list[str] = []

    def download(self, url):
        self.calls.append(url)
        if url not in self.bodies:
            raise FetchError(f"HTTP 404 for {url}")
        return self.bodies[url], "application/pdf"


def write_listings(d: Path) -> tuple[Path, Path]:
    page = json.loads((FIX / "templeterracefl" / "Events.json").read_text("utf-8"))
    cc_path = d / "cc.jsonl"
    cc_path.write_text("".join(json.dumps(asdict(cc.parse_event("templeterracefl", e))) + "\n"
                               for e in page["value"]))
    html = (FIX / "templeterrace_archive" / "amid-44.html").read_text("utf-8")
    mod = ac.Module(44, "Archived City Council Minutes", SITE + "/Archive.aspx?AMID=44")
    ar_path = d / "ar.jsonl"
    ar_path.write_text("".join(json.dumps(asdict(i)) + "\n" for i in ac.parse_items(html, mod, SITE)))
    return cc_path, ar_path


def events(data: Path) -> list[dict]:
    return [json.loads(x) for x in (data / "manifest.jsonl").read_text().splitlines()]


class Manifest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        cc_path, ar_path = write_listings(self.d)
        self.docs = mf.docs_from_civicclerk(cc_path) + mf.docs_from_archive(ar_path)
        self.bodies = {doc.url: b"%PDF-1.7 " + doc.key.encode() for doc in self.docs}
        self.data = self.d / "data"

    def tearDown(self):
        self.tmp.cleanup()

    def run_update(self, docs=None, **kw):
        return mf.update(docs if docs is not None else self.docs, self.data, FakeFetcher(self.bodies), **kw)

    def test_doc_keys(self):
        self.assertEqual(len(self.docs), 14 + 24)
        keys = {d.key for d in self.docs}
        self.assertIn("civicclerk:templeterracefl:1047", keys)
        self.assertIn("civicplus_archive:www.templeterrace.gov:9540", keys)
        minutes = [d for d in self.docs if d.source == "civicplus_archive"]
        self.assertTrue(all(d.kind == "Minutes" for d in minutes))

    def test_first_run_logs_everything_new(self):
        s = self.run_update(store_dir=self.d / "files", copy_base="https://example.org/files")
        self.assertEqual((s["new"], s["downloaded"], s["errors"]), (38, 38, 0))
        ev = events(self.data)
        self.assertEqual({e["event"] for e in ev}, {"new"})
        e = next(e for e in ev if e["key"] == "civicclerk:templeterracefl:1047")
        self.assertEqual(len(e["sha256"]), 64)
        self.assertTrue(e["copy_url"].startswith("https://example.org/files/") and e["copy_url"].endswith(".pdf"))
        self.assertEqual(len(list((self.d / "files").glob("*.pdf"))), 38)

    def test_second_run_not_due_downloads_nothing(self):
        self.run_update()
        s = self.run_update()
        self.assertEqual((s["downloaded"], s["skipped_not_due"]), (0, 38))
        self.assertEqual(len(events(self.data)), 38)

    def test_changed_file_is_logged_with_previous_hash(self):
        self.run_update()
        url = next(d.url for d in self.docs if d.key == "civicplus_archive:www.templeterrace.gov:9480")
        self.bodies[url] = b"%PDF-1.7 edited"
        s = self.run_update(recheck_days=0)
        self.assertEqual((s["changed"], s["unchanged"]), (1, 37))
        ch = [e for e in events(self.data) if e["event"] == "changed"]
        self.assertEqual(len(ch), 1)
        self.assertEqual(len(ch[0]["previous_sha256"]), 64)
        self.assertNotEqual(ch[0]["previous_sha256"], ch[0]["sha256"])

    def test_unlisted_then_relisted(self):
        self.run_update()
        gone = self.docs[0]
        self.run_update(docs=self.docs[1:])
        self.assertEqual([e["key"] for e in events(self.data) if e["event"] == "unlisted"], [gone.key])
        state = json.loads((self.data / "state.json").read_text())
        self.assertFalse(state[gone.key]["listed"])
        self.run_update()
        self.assertEqual([e["key"] for e in events(self.data) if e["event"] == "relisted"], [gone.key])

    def test_shrunken_listing_does_not_unlist(self):
        self.run_update()
        cc_docs = [d for d in self.docs if d.source == "civicclerk"]
        self.run_update(docs=cc_docs[:3] + [d for d in self.docs if d.source != "civicclerk"])
        self.assertFalse([e for e in events(self.data) if e["event"] == "unlisted"])

    def test_failed_source_is_not_unlisted(self):
        self.run_update()
        archive_only = [d for d in self.docs if d.source == "civicplus_archive"]
        self.run_update(docs=archive_only, sources_ok={"civicplus_archive"})
        self.assertFalse([e for e in events(self.data) if e["event"] == "unlisted"])

    def test_download_error_retried_next_run(self):
        missing = self.docs[0].url
        del self.bodies[missing]
        s = self.run_update()
        self.assertEqual((s["errors"], s["new"]), (1, 37))
        state = json.loads((self.data / "state.json").read_text())
        self.assertIn("last_error", state[self.docs[0].key])
        self.bodies[missing] = b"%PDF-1.7 back"
        s = self.run_update()
        self.assertEqual((s["new"], s["downloaded"]), (1, 1))

    def test_max_downloads_defers(self):
        s = self.run_update(max_downloads=10)
        self.assertEqual((s["downloaded"], s["deferred"]), (10, 28))
        s = self.run_update()
        self.assertEqual(s["new"], 28)


if __name__ == "__main__":
    unittest.main()
