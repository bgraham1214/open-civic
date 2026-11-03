"""Build the public search database and static site (Phase 1, step 5).

Produces, in --out (default site/):
  templeterrace.db   SQLite with full-text search over every page and agenda item
  metadata.json      Datasette titles, descriptions and source/OCR labels
  index.html         Landing page: search box, recent documents, links into Datasette Lite
  feed.xml           RSS of new documents and agenda items
  feeds/<topic>.xml  Keyword RSS feeds (KEYWORD_FEEDS below)

The database opens in Datasette Lite (https://lite.datasette.io), which runs Datasette
in the browser, so GitHub Pages can host the whole thing for free.
"""

from __future__ import annotations

import argparse
import gzip
import html
import json
import re
import sqlite3
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path

LITE = "https://lite.datasette.io/"

# Topic feeds: an item or document matches if any term appears in its title/description.
KEYWORD_FEEDS = {
    "contracts": ["contract", "agreement", "purchase", "bid", "rfp", "procurement", "vendor"],
    "zoning-land-use": ["zoning", "rezoning", "annexation", "site plan", "land use", "variance", "plat"],
    "budget-taxes": ["budget", "millage", "tax", "fee", "rate increase", "appropriat"],
    "ordinances": ["ordinance"],
    "water-utilities": ["water", "sewer", "wastewater", "utility", "pfas", "stormwater"],
}

SCHEMA = """
CREATE TABLE meetings (
  event_id INTEGER PRIMARY KEY, date TEXT, start TEXT, name TEXT, category TEXT,
  location TEXT, agenda_note TEXT, portal_url TEXT, youtube_video_id TEXT);
CREATE TABLE documents (
  key TEXT PRIMARY KEY, source TEXT, kind TEXT, date TEXT, title TEXT, body TEXT,
  city_url TEXT, page_url TEXT, our_copy TEXT, sha256 TEXT, bytes INTEGER,
  first_seen TEXT, last_changed TEXT, still_listed INTEGER, pages INTEGER, ocr_pages INTEGER);
CREATE TABLE pages (
  id INTEGER PRIMARY KEY, document_key TEXT REFERENCES documents(key), date TEXT, kind TEXT,
  title TEXT, page INTEGER, method TEXT, text TEXT, link TEXT);
CREATE TABLE agenda_items (
  key TEXT PRIMARY KEY, date TEXT, meeting TEXT, category TEXT, section TEXT, outline TEXT,
  item_number TEXT, title TEXT, description TEXT, fiscal_impact TEXT, resolution_number TEXT,
  ordinance_number TEXT, attachments INTEGER, attachment_names TEXT, agenda_link TEXT);
CREATE TABLE changes (
  id INTEGER PRIMARY KEY, at TEXT, event TEXT, document_key TEXT, date TEXT, kind TEXT,
  title TEXT, sha256 TEXT, previous_sha256 TEXT, bytes INTEGER, city_url TEXT, our_copy TEXT);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text("utf-8").splitlines() if x.strip()]


def build_db(data: Path, db_path: Path) -> dict:
    if db_path.exists():
        db_path.unlink()
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)
    state = json.loads((data / "state.json").read_text("utf-8"))
    counts = {}

    meetings = _jsonl(data / "listings" / "civicclerk-meetings.jsonl")
    con.executemany("INSERT INTO meetings VALUES (?,?,?,?,?,?,?,?,?)", [
        (m["event_id"], m["date"], m["start"].replace("Z", "")[:16].replace("T", " "), m["name"], m["category"],
         m["location"], m["agenda_note"], m["portal_url"], m["youtube_video_id"] or None) for m in meetings])
    counts["meetings"] = len(meetings)

    n_docs = n_pages = 0
    for e in sorted(state.values(), key=lambda e: (e.get("date", ""), e["key"])):
        if not e.get("sha256"):
            continue
        text = None
        tp = data / "text" / f"{e['sha256']}.json.gz"
        if tp.exists():
            with gzip.open(tp, "rt", encoding="utf-8") as fh:
                text = json.load(fh)
        pages = text["pages"] if text else []
        con.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            e["key"], e["source"], e["kind"], e["date"], e["title"], e.get("body", ""),
            e["url"], e.get("page", ""), e.get("copy_url", ""), e["sha256"], e.get("bytes"),
            e.get("first_seen"), e.get("last_changed"), int(e.get("listed", True)),
            len(pages) or None, sum(1 for p in pages if p["method"] == "ocr") if text else None))
        n_docs += 1
        link_base = e.get("copy_url") or e["url"]
        for p in pages:
            t = p["text"].strip()
            if not t:
                continue
            con.execute("INSERT INTO pages (document_key,date,kind,title,page,method,text,link) VALUES (?,?,?,?,?,?,?,?)",
                        (e["key"], e["date"], e["kind"], e["title"], p["n"], p["method"], t,
                         f"{link_base}#page={p['n']}"))
            n_pages += 1
    counts["documents"], counts["pages"] = n_docs, n_pages

    items = [i for i in _jsonl(data / "listings" / "civicclerk-items.jsonl") if not i["is_section"]]
    con.executemany("INSERT OR REPLACE INTO agenda_items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        (i["key"], i["date"], i["meeting"], i["category"], i["section"], i["outline"], i["item_number"],
         i["title"], i["description"], i["fiscal_impact"], i["resolution_number"], i["ordinance_number"],
         len(i["attachments"]), "; ".join(a["name"] for a in i["attachments"]), i["portal_url"]) for i in items])
    counts["agenda_items"] = len(items)

    ev = _jsonl(data / "manifest.jsonl")
    con.executemany("INSERT INTO changes (at,event,document_key,date,kind,title,sha256,previous_sha256,bytes,city_url,our_copy) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
        (x["at"], x["event"], x["key"], x.get("date"), x.get("kind"), x.get("title"), x.get("sha256"),
         x.get("previous_sha256"), x.get("bytes"), x.get("url"), x.get("copy_url")) for x in ev])
    counts["changes"] = len(ev)

    con.executescript("""
      CREATE VIRTUAL TABLE pages_fts USING fts5(title, text, content='pages', content_rowid='id', tokenize='porter');
      INSERT INTO pages_fts(rowid, title, text) SELECT id, title, text FROM pages;
      CREATE VIRTUAL TABLE agenda_items_fts USING fts5(title, description, section, content='agenda_items', tokenize='porter');
      INSERT INTO agenda_items_fts(rowid, title, description, section) SELECT rowid, title, description, section FROM agenda_items;
      CREATE INDEX pages_doc ON pages(document_key);
      CREATE INDEX docs_date ON documents(date);
      CREATE INDEX items_date ON agenda_items(date);
    """)
    con.commit()
    con.execute("VACUUM")
    con.close()
    return counts


def metadata(built_at: str) -> dict:
    src = "City of Temple Terrace: CivicClerk portal and CivicPlus Archive Center"
    return {
        "title": "Temple Terrace City Council records",
        "description_html": (
            "<p>Every City Council agenda, agenda packet and set of minutes Temple Terrace has published online "
            "since Oct 2025, searchable. Each document links to the city's copy and to ours, with its SHA-256 "
            "fingerprint and the date we retrieved it.</p><p><strong>Machine-read text:</strong> pages marked "
            "<code>ocr</code> were read from scans by software and can contain errors. Always check the "
            "original page before quoting.</p>"),
        "source": src,
        "license": "Public records",
        "about": "Open Civic Web",
        "about_url": "https://github.com/bgraham1214/open-civic",
        "databases": {"templeterrace": {
            "description": f"Built {built_at}. Updated nightly.",
            "tables": {
                "pages": {"description": "One row per page of every document. method = pdftotext (the "
                          "document's own text) or ocr (machine-read from a scan; may contain errors). "
                          "link opens that page.", "fts_table": "pages_fts", "fts_pk": "id",
                          "sort_desc": "date"},
                "agenda_items": {"description": "Every item on every CivicClerk agenda, with the city's item "
                                 "number. agenda_link opens the agenda on the city's portal.",
                                 "fts_table": "agenda_items_fts", "sort_desc": "date"},
                "documents": {"description": "Every document version we hold. our_copy is our archived copy; "
                              "sha256 is its fingerprint. still_listed = 0 means the city removed it from "
                              "its listing.", "sort_desc": "date"},
                "changes": {"description": "Log of documents appearing, changing, or disappearing from the "
                            "city's listings, from data/manifest.jsonl.", "sort_desc": "at"},
                "meetings": {"description": "CivicClerk events. Times are local (Eastern).", "sort_desc": "date"},
                "pages_fts": {"hidden": True}, "agenda_items_fts": {"hidden": True},
            }}},
    }


def _lite(site_url: str, path: str = "") -> str:
    q = f"?url={site_url}templeterrace.db&metadata={site_url}metadata.json"
    return f"{LITE}{q}{'#' + path if path else ''}"


def _rss(title: str, link: str, desc: str, entries: list[dict]) -> str:
    items = "".join(
        f"<item><title>{html.escape(x['title'])}</title><link>{html.escape(x['link'])}</link>"
        f"<guid isPermaLink=\"false\">{html.escape(x['guid'])}</guid>"
        f"<pubDate>{x['pub']}</pubDate><description>{html.escape(x['desc'])}</description></item>"
        for x in entries)
    return (f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
            f"<title>{html.escape(title)}</title><link>{html.escape(link)}</link>"
            f"<description>{html.escape(desc)}</description>{items}</channel></rss>\n")


def _pub(ts: str | None) -> str:
    try:
        dt = datetime.fromisoformat((ts or "").replace("Z", "+00:00"))
    except ValueError:
        dt = _now()
    return format_datetime(dt)


def feed_entries(data: Path) -> list[dict]:
    """New documents (from the manifest) and agenda items, newest first."""
    state = json.loads((data / "state.json").read_text("utf-8"))
    out = []
    for e in state.values():
        if not e.get("first_seen"):
            continue
        out.append({"title": f"{e['date']} · {e['kind']}: {e['title']}", "link": e.get("copy_url") or e["url"],
                    "guid": f"{e['key']}:{e['sha256']}", "pub": _pub(e["first_seen"]), "sort": e["first_seen"],
                    "desc": f"{e.get('body', '')}. City link: {e['url']}", "match": f"{e['title']} {e.get('body', '')}"})
    for i in _jsonl(data / "listings" / "civicclerk-items.jsonl"):
        if i["is_section"]:
            continue
        out.append({"title": f"{i['date']} · Agenda item {i['outline']} {i['title']}"[:300],
                    "link": i["portal_url"], "guid": i["key"], "pub": _pub(i["date"] + "T00:00:00Z"),
                    "sort": i["date"], "desc": i["description"][:1000],
                    "match": f"{i['title']} {i['description']}"})
    out.sort(key=lambda x: x["sort"], reverse=True)
    return out


def write_site(data: Path, out: Path, site_url: str) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    built = _now().isoformat().replace("+00:00", "Z")
    counts = build_db(data, out / "templeterrace.db")
    (out / "metadata.json").write_text(json.dumps(metadata(built), indent=1), "utf-8")

    entries = feed_entries(data)
    (out / "feed.xml").write_text(_rss("Temple Terrace City Council: new records", site_url,
                                       "New agendas, packets, minutes and agenda items.", entries[:200]), "utf-8")
    (out / "feeds").mkdir(exist_ok=True)
    feed_links = []
    for topic, terms in KEYWORD_FEEDS.items():
        rx = re.compile("|".join(re.escape(t) for t in terms), re.I)
        sel = [x for x in entries if rx.search(x["match"])][:200]
        (out / "feeds" / f"{topic}.xml").write_text(_rss(
            f"Temple Terrace City Council: {topic.replace('-', ' ')}", site_url,
            f"Agenda items and documents mentioning: {', '.join(terms)}.", sel), "utf-8")
        feed_links.append(f'<a href="feeds/{topic}.xml">{topic.replace("-", " ")}</a>')

    state = json.loads((data / "state.json").read_text("utf-8"))
    recent = sorted((e for e in state.values() if e.get("sha256")), key=lambda e: e["date"], reverse=True)[:15]
    rows = "".join(
        f"<tr><td>{e['date']}</td><td>{html.escape(e['kind'])}</td><td>{html.escape(e['title'])}</td>"
        f"<td><a href=\"{html.escape(e['url'])}\">city</a> · <a href=\"{html.escape(e.get('copy_url', ''))}\">our copy</a></td></tr>"
        for e in recent)
    search_pages = _lite(site_url, "/templeterrace/pages")
    search_items = _lite(site_url, "/templeterrace/agenda_items")
    page = INDEX.format(
        lite=_lite(site_url), pages=search_pages, items=search_items,
        changes=_lite(site_url, "/templeterrace/changes"), docs=_lite(site_url, "/templeterrace/documents"),
        items_js=json.dumps(search_items), pages_js=json.dumps(search_pages),
        rows=rows, feeds=" · ".join(feed_links), built=built[:16].replace("T", " "),
        n_docs=counts["documents"], n_pages=counts["pages"], n_items=counts["agenda_items"])
    (out / "index.html").write_text(page, "utf-8")
    (out / ".nojekyll").write_text("")
    return counts


INDEX = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Temple Terrace City Council records</title>
<link rel="alternate" type="application/rss+xml" title="New records" href="feed.xml">
<style>
 body{{font:16px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;max-width:860px;margin:2rem auto;padding:0 1rem;color:#1d1d1f}}
 h1{{font-size:1.6rem;margin-bottom:.2rem}} .sub{{color:#555;margin-top:0}}
 form{{display:flex;gap:.5rem;margin:1.2rem 0}} input[type=search]{{flex:1;font-size:1rem;padding:.6rem;border:1px solid #bbb;border-radius:6px}}
 button{{font-size:1rem;padding:.6rem 1rem;border:0;border-radius:6px;background:#1f5fbf;color:#fff;cursor:pointer}}
 label{{margin-right:1rem}} table{{border-collapse:collapse;width:100%;font-size:.92rem}} td,th{{text-align:left;padding:.35rem .5rem;border-bottom:1px solid #e5e5e5;vertical-align:top}}
 .note{{background:#f6f6f2;border-left:4px solid #c9a227;padding:.6rem .9rem;font-size:.92rem}} footer{{color:#666;font-size:.85rem;margin-top:2rem}}
</style></head><body>
<h1>Temple Terrace City Council records</h1>
<p class="sub">{n_docs} documents · {n_pages} searchable pages · {n_items} agenda items · updated {built} UTC</p>
<form id="f"><input type="search" id="q" placeholder="Search agendas, packets and minutes, e.g. annexation" required>
<button>Search</button></form>
<p><label><input type="radio" name="w" value="pages" checked> Every page of every document</label>
<label><input type="radio" name="w" value="items"> Agenda items</label></p>
<p class="note">Search opens in Datasette Lite, which runs in your browser and takes a few seconds to load.
Text from scanned pages (marked <code>ocr</code>) was machine-read and can contain errors; follow the
page link to check the original.</p>
<h2>Latest documents</h2>
<table><tr><th>Date</th><th>Type</th><th>Title</th><th>Links</th></tr>{rows}</table>
<h2>Browse</h2>
<p><a href="{docs}">All documents</a> · <a href="{items}">All agenda items</a> · <a href="{changes}">Change log</a>
(documents added, edited, or removed by the city) · <a href="{lite}">Full database</a></p>
<h2>Alerts</h2>
<p>RSS: <a href="feed.xml">everything new</a> · {feeds}</p>
<footer>Public records from the City of Temple Terrace's CivicClerk portal and Archive Center, collected
nightly. Each document is fingerprinted (SHA-256) and archived so changes are visible.
<a href="https://github.com/bgraham1214/open-civic">Source and data</a>.</footer>
<script>
document.getElementById('f').addEventListener('submit', function (e) {{
  e.preventDefault();
  var q = document.getElementById('q').value.trim();
  var items = document.querySelector('input[name=w]:checked').value === 'items';
  var base = items ? {items_js} : {pages_js};
  location.href = base + '?_search=' + encodeURIComponent(q) + '&_sort_desc=date';
}});
</script></body></html>
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m opencivic.build")
    ap.add_argument("--data-dir", type=Path, default=Path("data"))
    ap.add_argument("--out", type=Path, default=Path("site"))
    ap.add_argument("--site-url", default="https://bgraham1214.github.io/open-civic/")
    args = ap.parse_args(argv)
    counts = write_site(args.data_dir, args.out, args.site_url.rstrip("/") + "/")
    print(json.dumps(counts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
