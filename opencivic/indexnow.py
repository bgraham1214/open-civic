# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Tell search engines which pages changed, through IndexNow (https://www.indexnow.org).

Bing, Yandex, Naver, Seznam and Yep take IndexNow pings; DuckDuckGo and several AI search tools use Bing's
index. Google doesn't use IndexNow; it reads sitemap.xml, best submitted once in Search Console.

Every page's footer carries the build time, so every page "changes" every night. To send only real changes,
each page is fingerprinted with that line removed and the fingerprints are published as page-hashes.json.
The next build compares against the published copy.

  python -m opencivic.indexnow prepare --site site      # key file + page-hashes.json (after the build)
  python -m opencivic.indexnow submit --site site --previous prev.json --site-url https://.../open-civic/

The key is public by design: IndexNow checks that the key file is served from the site it names, and a key
file under /open-civic/ only covers URLs under /open-civic/.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

KEY = "2923b92dc770555947e9d119eb84853b"
ENDPOINT = "https://api.indexnow.org/indexnow"
HASHES = "page-hashes.json"
BATCH = 10_000
UPDATED_RX = re.compile(r" Updated [^<]{0,60}?\.(?=</p>)")


def fingerprint(html: str) -> str:
    return hashlib.sha256(UPDATED_RX.sub("", html).encode("utf-8")).hexdigest()


def hashes(site: Path) -> dict[str, str]:
    return {p.relative_to(site).as_posix(): fingerprint(p.read_text("utf-8"))
            for p in sorted(site.rglob("*.html"))}


def prepare(site: Path) -> int:
    (site / f"{KEY}.txt").write_text(KEY, "utf-8")
    h = hashes(site)
    (site / HASHES).write_text(json.dumps(h, indent=0, sort_keys=True), "utf-8")
    return len(h)


def changed(previous: dict[str, str], current: dict[str, str]) -> list[str]:
    """Pages that are new or whose content changed. Removed pages aren't sent (they answer 404 already)."""
    return sorted(p for p, h in current.items() if previous.get(p) != h)


def payload(paths: list[str], site_url: str) -> dict:
    base = site_url.rstrip("/") + "/"
    return {"host": urlparse(base).netloc, "key": KEY, "keyLocation": f"{base}{KEY}.txt",
            "urlList": [base + p for p in paths]}


def submit(paths: list[str], site_url: str, opener=urllib.request.urlopen) -> list[int]:
    statuses = []
    for i in range(0, len(paths), BATCH):
        body = json.dumps(payload(paths[i:i + BATCH], site_url)).encode("utf-8")
        req = urllib.request.Request(ENDPOINT, data=body, method="POST",
                                     headers={"Content-Type": "application/json; charset=utf-8",
                                              "User-Agent": "open-civic (+https://github.com/bgraham1214/open-civic)"})
        with opener(req, timeout=60) as r:
            statuses.append(r.status)
    return statuses


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m opencivic.indexnow")
    ap.add_argument("action", choices=["prepare", "submit"])
    ap.add_argument("--site", type=Path, default=Path("site"))
    ap.add_argument("--previous", type=Path, help="the published page-hashes.json from the last build")
    ap.add_argument("--site-url", default="https://bgraham1214.github.io/open-civic/")
    args = ap.parse_args(argv)
    if args.action == "prepare":
        print(json.dumps({"indexnow_pages": prepare(args.site)}))
        return 0
    current = json.loads((args.site / HASHES).read_text("utf-8"))
    previous = {}
    if args.previous and args.previous.exists() and args.previous.stat().st_size:
        previous = json.loads(args.previous.read_text("utf-8"))
    paths = changed(previous, current)
    if not paths:
        print(json.dumps({"indexnow": "no changed pages"}))
        return 0
    try:
        statuses = submit(paths, args.site_url)
    except Exception as e:  # noqa: BLE001 - a ping failure must never fail the run
        print(f"::warning::IndexNow submit failed: {e}", file=sys.stderr)
        return 0
    print(json.dumps({"indexnow_submitted": len(paths), "status": statuses, "sample": paths[:5]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
