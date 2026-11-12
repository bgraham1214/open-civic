# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Documents a government posts as plain links on a web page (Oak Hill, FL).

Oak Hill's website (Webflow) lists City Commission agendas and minutes as links whose text starts
with the meeting date: "11-09-2026 Commission Agenda", "2-23-26 Special Commission Meeting Minutes",
"12-01-2025 Amended Commission Workshop Agenda". The PDFs are on Webflow's file server
(cdn.prod.website-files.com/<site id>/<file id>_<name>.pdf). A replaced file gets a new file id, so the
file id is the document's key: weblinks:<account>:<file id>.

Checked Nov 12, 2026: www.oakhillfl.gov/robots.txt names only a sitemap (everything allowed);
cdn.prod.website-files.com/robots.txt answers HTTP 403, which robots.txt rules (RFC 9309) treat as
no restrictions. The minutes are scans; extract.py reads them by OCR.

The listing has the same shape as hillsclerk's report listing, so manifest.py reads it with --links.

Usage:
  python -m opencivic.weblinks list --account oakhillfl -o out/weblinks-oakhillfl.jsonl
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .fetch import FetchError, HttpFetcher
from .jurisdictions import JURISDICTIONS, weblinks_sites

_LINK = re.compile(r'<a\b[^>]*\bhref="([^"]+)"[^>]*>(.*?)</a>', re.S | re.I)
_DATE = re.compile(r"^\s*(\d{1,2})[-./](\d{1,2})[-./](\d{2}|\d{4})\b")


def parse_date(text: str) -> str:
    """'5-11-2026 …' or '2-23-26 …' -> '2026-05-11'; '' when the text doesn't start with a date."""
    m = _DATE.match(text)
    if not m:
        return ""
    mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    y += 2000 if y < 100 else 0
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return ""


def meeting_kind(text: str, body: str = "City Commission") -> str:
    """The meeting a document belongs to, from its link text and file name (Oak Hill sometimes
    titles a budget workshop's minutes "Commission Meeting Minutes" but names the file correctly)."""
    t = re.sub(r"[_%20.]+", " ", text.lower())
    if re.search(r"\btrc\b|technical review", t):
        return "Technical Review Committee"
    if "shade" in t:  # a closed attorney-client session; its agenda is public
        return f"{body} Shade Meeting"
    if re.search(r"budget\s*(workshop|hearing)", t):
        return f"{body} Budget {'Workshop' if 'workshop' in t else 'Hearing'}"
    if "workshop" in t:
        return f"{body} Workshop"
    if "special" in t:
        return f"{body} Special Meeting"
    if "neighborhood meeting" in t:
        return f"{body} Neighborhood Meeting"
    return body


def file_id(url: str) -> str:
    """Webflow's id for one uploaded file: the part of the file name before the first underscore."""
    name = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
    m = re.match(r"([0-9a-f]{16,32})_", name)
    return m.group(1) if m else ""


def parse_page(account: str, page_url: str, page: str, since: str = "", body: str = "City Commission") -> list[dict]:
    out = []
    for href, inner in _LINK.findall(page):
        href = html.unescape(href)
        text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", inner))).strip()
        if "website-files.com" not in href or not href.lower().split("?")[0].endswith(".pdf"):
            continue  # agenda packets are a OneDrive folder, not files
        d, fid = parse_date(text), file_id(href)
        if not d or not fid or (since and d < since):
            continue
        out.append({"key": f"weblinks:{account}:{fid}", "url": href, "title": text,
                    "kind": "Minutes" if re.search(r"\bminutes\b", text, re.I) else "Agenda",
                    "date": d, "body": meeting_kind(f"{text} {unquote(urlsplit(href).path.rsplit('/', 1)[-1])}", body),
                    "page": page_url})
    return out


def crawl(account: str, fetcher, pages: list[str], since: str = "", body: str = "City Commission") -> list[dict]:
    """Every dated document on the listing pages, newest first. Raises FetchError if a page fails,
    so a partial listing is never mistaken for documents the city removed."""
    seen: dict[str, dict] = {}
    for url in pages:
        for d in parse_page(account, url, fetcher.get_text(url), since, body):
            seen.setdefault(d["key"], d)
    return sorted(seen.values(), key=lambda d: (d["date"], d["kind"], d["key"]), reverse=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m opencivic.weblinks")
    ap.add_argument("what", choices=["list"])
    ap.add_argument("--account", required=True, help="e.g. oakhillfl")
    ap.add_argument("-o", "--out", type=Path, required=True)
    args = ap.parse_args(argv)
    slug = weblinks_sites().get(args.account)
    if not slug:
        print(f"unknown account {args.account}", file=sys.stderr)
        return 2
    j = JURISDICTIONS[slug]
    try:
        docs = crawl(args.account, HttpFetcher(), j["listing_pages"], j.get("since", ""), j["body"])
    except FetchError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps(d, ensure_ascii=False) + "\n" for d in docs), "utf-8")
    kinds = {k: sum(1 for d in docs if d["kind"] == k) for k in ("Agenda", "Minutes")}
    print(json.dumps({"account": args.account, "documents": len(docs), **kinds}), file=sys.stderr)
    return 0 if docs else 1


if __name__ == "__main__":
    sys.exit(main())
