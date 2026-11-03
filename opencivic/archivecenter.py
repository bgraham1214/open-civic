"""Adapter for the CivicPlus Archive Center (`{site}/Archive.aspx`).

Temple Terrace keeps minutes and pre-Oct 2025 agendas here. The page is rendered on
the server: a browser recording (HAR, Nov 3 2026) showed no listing API, so this
adapter reads the HTML itself.

Seen live (Nov 3 2026): `Archive.aspx` shows one dropdown per module,
`<select id="amidDDN44">` labelled "Archived City Council Minutes", whose options carry
values like `1_1_0_9540` (flags, then the document id). The dropdown holds only recent
items; `Archive.aspx?AMID=44` lists them all. A document is served at
`Archive.aspx?ADID=9540`.

By default only the City Council modules are read: the pilot's scope, and the other
modules include police activity logs that name private residents.

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


class _Page(HTMLParser):
    """Collects <a> links, plus the module dropdowns CivicPlus uses on Archive.aspx."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.labels: dict[str, str] = {}               # label for= -> text
        self.options: list[tuple[int, str, str]] = []  # (amid, value, text)
        self._href: str | None = None
        self._label_for: str | None = None
        self._amid: int | None = None
        self._opt: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a":
            self._href, self._text = a.get("href"), []
        elif tag == "label":
            self._label_for, self._text = a.get("for"), []
        elif tag == "select":
            m = re.fullmatch(r"amidDDN(\d+)", a.get("id") or "")
            self._amid = int(m.group(1)) if m else None
        elif tag == "option" and self._amid is not None:
            self._opt, self._text = a.get("value") or "", []

    def handle_data(self, data):
        if self._href is not None or self._label_for is not None or self._opt is not None:
            self._text.append(data)

    def _flush(self) -> str:
        return re.sub(r"\s+", " ", "".join(self._text)).strip()

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, self._flush()))
            self._href = None
        elif tag == "label" and self._label_for is not None:
            self.labels[self._label_for] = self._flush().rstrip(":").strip()
            self._label_for = None
        elif tag == "option" and self._opt is not None:
            self.options.append((self._amid, self._opt, self._flush()))
            self._opt = None
        elif tag == "select":
            self._amid = None


def _param(href: str, name: str) -> int | None:
    qs = {k.lower(): v for k, v in parse_qs(urlsplit(html.unescape(href)).query).items()}
    vals = qs.get(name.lower())
    return int(vals[0]) if vals and vals[0].isdigit() else None


def _parse(page_html: str) -> _Page:
    p = _Page()
    p.feed(page_html)
    p.close()
    return p


def links(page_html: str) -> list[tuple[str, str]]:
    return _parse(page_html).links


# Dropdown option values look like "1_1_0_9540": external-file flag, new-window flag,
# "most recent" flag, then the document id (ADID). "-1"/"-2" are menu entries.
_OPTION = re.compile(r"^\d_\d_(\d)_(\d+)$")


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
    page = _parse(page_html)
    seen: dict[int, Module] = {}
    for amid in dict.fromkeys(a for a, _, _ in page.options):
        name = page.labels.get(f"amidDDN{amid}", f"Archive {amid}")
        seen[amid] = Module(amid, name, f"{site}/Archive.aspx?AMID={amid}")
    for href, text in page.links:
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
    """Documents for one module, from ADID links and from that module's dropdown."""
    page = _parse(page_html)
    found: list[tuple[int, str]] = []
    for href, text in page.links:
        adid = _param(href, "ADID")
        if adid is not None and text:
            found.append((adid, text))
    for amid, value, text in page.options:
        m = _OPTION.match(value)
        if amid == module.amid and m and m.group(1) == "0" and text:
            found.append((int(m.group(2)), text))
    out: dict[int, ArchiveItem] = {}
    for adid, text in found:
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

    index = get(f"{site}/Archive.aspx", "index.html")
    modules = parse_modules(index, site)
    if module_filter:
        rx = re.compile(module_filter, re.I)
        modules = [m for m in modules if rx.search(m.name)]
    by_adid: dict[int, ArchiveItem] = {}
    for m in modules:
        # The full module page first, then the index dropdown (recent items) as a backstop.
        for item in parse_items(get(m.url, f"amid-{m.amid}.html"), m, site) + parse_items(index, m, site):
            by_adid.setdefault(item.adid, item)
    items = sorted(by_adid.values(), key=lambda i: (i.module, i.date, i.adid))
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
    ap.add_argument("--module", default="City Council",
                    help="regex on module names (default: City Council; '.' for all)")
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
