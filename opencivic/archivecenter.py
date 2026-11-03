"""Adapter for the CivicPlus Archive Center (`{site}/Archive.aspx`).

Temple Terrace keeps minutes and pre-Oct 2025 agendas here. The page is rendered on
the server: a browser recording (HAR, Nov 3 2026) showed no listing API, so this
adapter reads the HTML itself.

CivicPlus convention (to confirm on the first live run):
  * `Archive.aspx` links to each archive module as `Archive.aspx?AMID=<module id>`.
  * A module page links to each document as `Archive.aspx?ADID=<document id>`,
    and that URL serves the file.

The parser looks only for those two link patterns, not page layout, so styling
changes don't break it. Use `--save-raw` on live runs to keep the HTML as fixtures.

Usage:
  python -m opencivic.archivecenter items --site https://www.templeterrace.gov --save-raw raw/
  python -m opencivic.archivecenter items --input-dir raw/          # offline, from saved pages
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit

from .fetch import FetchError, FixtureFetcher, HttpFetcher

DEFAULT_SITE = "https://www.templeterrace.gov"


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            text = re.sub(r"\s+", " ", "".join(self._text)).strip()
            self.links.append((self._href, text))
            self._href = None


def _param(href: str, name: str) -> int | None:
    qs = {k.lower(): v for k, v in parse_qs(urlsplit(html.unescape(href)).query).items()}
    vals = qs.get(name.lower())
    return int(vals[0]) if vals and vals[0].isdigit() else None


def links(page_html: str) -> list[tuple[str, str]]:
    p = _Links()
    p.feed(page_html)
    return p.links


@dataclass
class Module:
    amid: int
    name: str
    url: str


@dataclass
class ArchiveItem:
    source: str
    site: str
    amid: int
    module: str
    adid: int
    title: str
    date: str          # YYYY-MM-DD parsed from the title, "" if none found
    url: str           # Archive.aspx?ADID=N serves the document
    module_url: str


def parse_modules(page_html: str, site: str) -> list[Module]:
    seen: dict[int, Module] = {}
    for href, text in links(page_html):
        amid = _param(href, "AMID")
        if amid is not None and _param(href, "ADID") is None and text:
            seen.setdefault(amid, Module(amid, text, f"{site}/Archive.aspx?AMID={amid}"))
    return sorted(seen.values(), key=lambda m: m.amid)


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_date(title: str) -> str:
    """Best-effort date from a document title; '' when none is clear."""
    t = title.lower()
    m = re.search(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{2}|\d{4})\b", t)
    if m:
        mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y += 2000 if y < 100 else 0
    else:
        m = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})\b", t)
        if not m:
            return ""
        mo, d, y = _MONTHS[m.group(1)], int(m.group(2)), int(m.group(3))
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return ""


def parse_items(page_html: str, module: Module, site: str) -> list[ArchiveItem]:
    out: dict[int, ArchiveItem] = {}
    for href, text in links(page_html):
        adid = _param(href, "ADID")
        if adid is None or not text:
            continue
        out.setdefault(adid, ArchiveItem(
            source="civicplus_archive", site=site, amid=module.amid, module=module.name,
            adid=adid, title=text, date=parse_date(text),
            url=f"{site}/Archive.aspx?ADID={adid}", module_url=module.url,
        ))
    return list(out.values())


def crawl(site: str, fetcher, module_filter: str | None = None, save_raw: Path | None = None):
    def get(url: str, name: str) -> str:
        text = fetcher.get_text(url)
        if save_raw:
            save_raw.mkdir(parents=True, exist_ok=True)
            (save_raw / name).write_text(text, "utf-8")
        return text

    modules = parse_modules(get(f"{site}/Archive.aspx", "index.html"), site)
    if module_filter:
        rx = re.compile(module_filter, re.I)
        modules = [m for m in modules if rx.search(m.name)]
    items: list[ArchiveItem] = []
    for m in modules:
        items += parse_items(get(m.url, f"amid-{m.amid}.html"), m, site)
    items.sort(key=lambda i: (i.module, i.date, i.adid))
    return modules, items


def fixture_fetcher(site: str, raw_dir: Path) -> FixtureFetcher:
    pages = {f"{site}/Archive.aspx": raw_dir / "index.html"}
    for p in raw_dir.glob("amid-*.html"):
        pages[f"{site}/Archive.aspx?AMID={p.stem.split('-')[1]}"] = p
    return FixtureFetcher(pages)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m opencivic.archivecenter")
    ap.add_argument("what", choices=["modules", "items"])
    ap.add_argument("--site", default=DEFAULT_SITE)
    ap.add_argument("--input-dir", type=Path, help="saved pages (index.html, amid-N.html); omit to fetch live")
    ap.add_argument("--module", help="regex on module names, e.g. 'council|minutes'")
    ap.add_argument("--save-raw", type=Path, help="keep fetched HTML here")
    ap.add_argument("-o", "--output")
    args = ap.parse_args(argv)
    site = args.site.rstrip("/")

    fetcher = fixture_fetcher(site, args.input_dir) if args.input_dir else HttpFetcher()
    try:
        modules, items = crawl(site, fetcher, args.module, args.save_raw)
    except FetchError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    rows = [asdict(m) for m in modules] if args.what == "modules" else [asdict(i) for i in items]
    out = open(args.output, "w", encoding="utf-8") if args.output else sys.stdout
    try:
        for r in rows:
            out.write(json.dumps(r, ensure_ascii=False) + "\n")
    finally:
        if args.output:
            out.close()
    undated = sum(1 for i in items if not i.date)
    print(f"{len(modules)} modules, {len(items)} documents ({undated} without a date in the title)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
