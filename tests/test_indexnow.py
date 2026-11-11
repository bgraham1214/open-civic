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


if __name__ == "__main__":
    unittest.main()
