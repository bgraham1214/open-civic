"""Agenda items (CivicClerk Meetings API) and text extraction."""

import gzip
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from opencivic import civicclerk as cc
from opencivic import extract as ex

FIX = Path(__file__).parent / "fixtures"
TENANT = "templeterracefl"
AGENDA_PDF = FIX / "pdf" / "agenda-2025-11-04.pdf"  # City Council Agenda V3, fileId 1047


def meeting(agenda_id: int) -> cc.Meeting:
    page = json.loads((FIX / "templeterracefl" / "Events.json").read_text("utf-8"))
    raw = next(e for e in page["value"] if e["agendaId"] == agenda_id)
    return cc.parse_event(TENANT, raw)


class AgendaItems(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = json.loads((FIX / "templeterracefl" / "meetings" / "meeting-21.json").read_text("utf-8"))
        cls.items = cc.parse_agenda_items(TENANT, meeting(21), raw)
        cls.by_outline = {i["outline"]: i for i in cls.items}

    def test_structure(self):
        self.assertEqual(len(self.items), 29)
        self.assertEqual(sum(1 for i in self.items if i["is_section"]), 17)
        item = self.by_outline["11.A."]
        self.assertFalse(item["is_section"])
        self.assertEqual(item["section"], "Consent Agenda")
        self.assertEqual(item["item_number"], "2025-48")
        self.assertTrue(item["title"].startswith("Resolution Approving the Purchase of Playground Equipment"))
        self.assertEqual(len(item["attachments"]), 4)
        self.assertEqual(item["date"], "2025-11-04")
        self.assertEqual(item["portal_url"], "https://templeterracefl.portal.civicclerk.com/event/8/agenda")

    def test_text_is_clean(self):
        for i in self.items:
            for field in ("title", "description"):
                self.assertNotIn("<", i[field])
                self.assertNotIn(" ", i[field])

    def test_no_storage_urls_kept(self):
        blob = json.dumps(self.items)
        self.assertNotIn("blob.core.windows.net", blob)
        self.assertNotIn("stream/", blob)

    def test_cli_offline(self):
        with tempfile.TemporaryDirectory() as d:
            mpath, out = Path(d) / "m.jsonl", Path(d) / "items.jsonl"
            cc.main(["meetings", "--input", str(FIX / "templeterracefl" / "Events.json"), "-o", str(mpath)])
            rc = cc.main(["items", "--meetings", str(mpath),
                          "--meetings-dir", str(FIX / "templeterracefl" / "meetings"), "-o", str(out)])
            rows = [json.loads(x) for x in out.read_text().splitlines()]
        # Only agenda 21 is both in the saved Events page and saved as a Meetings response;
        # the other six agendas with files are missing offline, so they count as errors.
        self.assertEqual(rc, 0)
        self.assertEqual({r["agenda_id"] for r in rows}, {21})


@unittest.skipUnless(shutil.which("pdftotext"), "poppler-utils not installed")
class Extract(unittest.TestCase):
    def test_text_layer(self):
        pages, used = ex.extract(AGENDA_PDF, ocr_budget=0, ocr_available=False)
        self.assertEqual(used, 0)
        self.assertEqual(len(pages), 3)
        self.assertTrue(all(p["method"] == "pdftotext" for p in pages))
        self.assertIn("TEMPLE TERRACE", " ".join(p["text"] for p in pages).upper())

    @unittest.skipUnless(shutil.which("tesseract") and shutil.which("pdftoppm"), "tesseract not installed")
    def test_scanned_page_is_ocred_and_labelled(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            ex._run(["pdftoppm", "-r", "150", "-f", "1", "-l", "1", "-png", str(AGENDA_PDF), str(d / "p")])
            img = Image.open(next(d.glob("p*.png"))).convert("RGB")
            scanned = d / "scanned.pdf"
            img.save(scanned, "PDF", resolution=150)  # image only, no text layer
            pages, used = ex.extract(scanned, ocr_budget=5, ocr_available=True)
            self.assertEqual(used, 1)
            self.assertEqual(pages[0]["method"], "ocr")
            self.assertIn("TEMPLE TERRACE", pages[0]["text"].upper())
            self.assertEqual(ex.extract(scanned, ocr_budget=0, ocr_available=True), (None, 0))

    def test_run_writes_one_file_per_hash(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            files = d / "files"
            files.mkdir()
            sha = "a" * 64
            shutil.copy(AGENDA_PDF, files / f"{sha}.pdf")
            state = {"k1": {"key": "k1", "sha256": sha, "ext": "pdf", "kind": "Agenda", "title": "A",
                            "date": "2025-11-04", "bytes": 1},
                     "k2": {"key": "k2", "sha256": sha, "ext": "pdf", "kind": "Agenda", "title": "A copy",
                            "date": "2025-11-04", "bytes": 1}}
            (d / "state.json").write_text(json.dumps(state))
            s = ex.run(d, files, max_ocr_pages=0)
            self.assertEqual((s["done"], s["errors"]), (1, 0))
            with gzip.open(d / "text" / f"{sha}.json.gz", "rt") as fh:
                doc = json.load(fh)
            self.assertEqual(len(doc["pages"]), 3)
            self.assertEqual(ex.run(d, files, max_ocr_pages=0)["already"], 1)


if __name__ == "__main__":
    unittest.main()
