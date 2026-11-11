# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
import json
import tempfile
import unittest
from pathlib import Path

from opencivic import indexnow

PAGE = ('<html><body><main>{}</main><footer><p>Open Civic Web is a free project.'
        ' Updated Tuesday, November 10, 2026, 5:43 PM Eastern.</p></footer></body></html>')


class IndexNow(unittest.TestCase):
    def test_build_time_alone_is_not_a_change(self):
        a = indexnow.fingerprint(PAGE.format("x"))
        b = indexnow.fingerprint(PAGE.format("x").replace("5:43 PM", "3:12 AM").replace("10", "11"))
        self.assertEqual(a, b)
        self.assertNotEqual(a, indexnow.fingerprint(PAGE.format("y")))

    def test_changed_pages_and_payload(self):
        with tempfile.TemporaryDirectory() as d:
            site = Path(d)
            (site / "meetings").mkdir()
            (site / "index.html").write_text(PAGE.format("home"))
            (site / "meetings" / "a.html").write_text(PAGE.format("a"))
            self.assertEqual(indexnow.prepare(site), 2)
            self.assertEqual((site / f"{indexnow.KEY}.txt").read_text(), indexnow.KEY)
            old = json.loads((site / indexnow.HASHES).read_text())
            (site / "meetings" / "a.html").write_text(PAGE.format("a, changed"))
            (site / "meetings" / "b.html").write_text(PAGE.format("b"))
            indexnow.prepare(site)
            new = json.loads((site / indexnow.HASHES).read_text())
            paths = indexnow.changed(old, new)
            self.assertEqual(paths, ["meetings/a.html", "meetings/b.html"])
            p = indexnow.payload(paths, "https://bgraham1214.github.io/open-civic/")
            self.assertEqual(p["host"], "bgraham1214.github.io")
            self.assertEqual(p["keyLocation"], f"https://bgraham1214.github.io/open-civic/{indexnow.KEY}.txt")
            self.assertEqual(p["urlList"][0], "https://bgraham1214.github.io/open-civic/meetings/a.html")

    def test_submit_batches(self):
        sent = []

        class R:
            status = 202
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def opener(req, timeout):
            sent.append(json.loads(req.data))
            return R()
        out = indexnow.submit([f"p{i}.html" for i in range(10_001)], "https://x.github.io/open-civic/", opener)
        self.assertEqual(out, [202, 202])
        self.assertEqual([len(s["urlList"]) for s in sent], [10_000, 1])

    def test_waits_for_the_key_file(self):
        calls = []

        class R:
            def __init__(self, body): self.status, self.body = 200, body
            def read(self): return self.body
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def opener(req, timeout):
            calls.append(req.full_url)
            if len(calls) < 3:
                raise OSError("404")
            return R(indexnow.KEY.encode())
        self.assertTrue(indexnow.key_served("https://x.github.io/open-civic/", opener, tries=5, sleep=lambda s: None))
        self.assertEqual(len(calls), 3)
        self.assertFalse(indexnow.key_served("https://x.github.io/open-civic/", lambda r, timeout: (_ for _ in ()).throw(OSError()),
                                             tries=2, sleep=lambda s: None))

    def test_failed_night_is_sent_again(self):
        with tempfile.TemporaryDirectory() as d:
            site, rec = Path(d) / "site", Path(d) / "rec.json"
            site.mkdir()
            (site / "a.html").write_text(PAGE.format("a"))
            indexnow.prepare(site)
            orig = indexnow.key_served
            indexnow.key_served = lambda *a, **k: False   # the site isn't serving the key: nothing is sent
            try:
                indexnow.main(["submit", "--site", str(site), "--record", str(rec)])
            finally:
                indexnow.key_served = orig
            self.assertEqual(json.loads(rec.read_text()), {})   # so the next run sends a.html again


if __name__ == "__main__":
    unittest.main()
