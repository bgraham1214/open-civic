# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
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

from .jurisdictions import COUNTIES, jurisdiction_of

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
  event_id INTEGER PRIMARY KEY, date TEXT, start TEXT, name TEXT, category TEXT, video TEXT,
  location TEXT, agenda_note TEXT, portal_url TEXT);
CREATE TABLE videos (
  published TEXT, title TEXT, url TEXT, minutes INTEGER, meeting_date TEXT, meeting TEXT,
  matched_by TEXT, event_id INTEGER, description TEXT, video_id TEXT UNIQUE);
CREATE TABLE documents (
  date TEXT, kind TEXT, title TEXT, body TEXT, city_url TEXT, our_copy TEXT, pages INTEGER,
  ocr_pages INTEGER, sha256 TEXT, bytes INTEGER, first_seen TEXT, last_changed TEXT,
  still_listed INTEGER, source TEXT, page_url TEXT, key TEXT UNIQUE);
CREATE TABLE pages (
  id INTEGER PRIMARY KEY, date TEXT, kind TEXT, title TEXT, page INTEGER, method TEXT,
  text TEXT, link TEXT, document_key TEXT);
CREATE TABLE agenda_items (
  date TEXT, outline TEXT, title TEXT, description TEXT, agenda_link TEXT, video TEXT, section TEXT,
  meeting TEXT, category TEXT, item_number TEXT, fiscal_impact TEXT, resolution_number TEXT,
  ordinance_number TEXT, attachments INTEGER, attachment_names TEXT, key TEXT UNIQUE);
CREATE TABLE officials (
  name TEXT, roles TEXT, kind TEXT, meetings_present INTEGER, meetings_absent INTEGER,
  absent_dates TEXT, first_seen TEXT, last_seen TEXT);
CREATE TABLE votes (
  date TEXT, item TEXT, item_title TEXT, result TEXT, tally TEXT, nays TEXT, ayes TEXT,
  mover TEXT, seconder TEXT, roll_call INTEGER, record_number TEXT, action TEXT, minutes_link TEXT,
  page_read_by TEXT, motion_text TEXT, agenda_item_key TEXT, key TEXT UNIQUE);
CREATE TABLE contracts (
  date TEXT, title TEXT, vendors TEXT, amount_stated REAL, council_vote TEXT, agenda_link TEXT,
  cooperative_contract TEXT, solicitation TEXT, description TEXT, outline TEXT, item_number TEXT, key TEXT UNIQUE);
CREATE TABLE vendors (
  vendor TEXT, contracts INTEGER, first_date TEXT, last_date TEXT, amounts_stated_when_sole_vendor REAL,
  contract_titles TEXT);
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


def _city_state(data: Path) -> dict[str, dict]:
    """Temple Terrace's documents: everything except what belongs to a county."""
    return {k: e for k, e in json.loads((data / "state.json").read_text("utf-8")).items()
            if jurisdiction_of(k) not in COUNTIES}


def build_db(data: Path, db_path: Path) -> dict:
    if db_path.exists():
        db_path.unlink()
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)
    state = _city_state(data)
    counts = {}

    videos = _jsonl(data / "listings" / "youtube-videos.jsonl")
    video_by_event = {}
    for v in sorted(videos, key=lambda v: v["published_at"]):  # latest upload wins
        if v.get("event_id"):
            video_by_event[v["event_id"]] = v["url"]
    con.executemany("INSERT INTO videos VALUES (?,?,?,?,?,?,?,?,?,?)", [
        (v["published_at"][:10], v["title"], v["url"], round(v.get("duration_seconds", 0) / 60) or None,
         v["meeting_date"], v["meeting"], v["matched_by"], v["event_id"], v["description"][:2000], v["video_id"])
        for v in videos])
    counts["videos"] = len(videos)

    meetings = _jsonl(data / "listings" / "civicclerk-meetings.jsonl")
    con.executemany("INSERT INTO meetings VALUES (?,?,?,?,?,?,?,?,?)", [
        (m["event_id"], m["date"], m["start"].replace("Z", "")[:16].replace("T", " "), m["name"], m["category"],
         video_by_event.get(m["event_id"]) or (f"https://www.youtube.com/watch?v={m['youtube_video_id']}"
                                               if m["youtube_video_id"] else None),
         m["location"], m["agenda_note"], m["portal_url"]) for m in meetings])
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
            e["date"], e["kind"], e["title"], e.get("body", ""), e["url"], e.get("copy_url", ""),
            len(pages) or None, sum(1 for p in pages if p["method"] == "ocr") if text else None,
            e["sha256"], e.get("bytes"), e.get("first_seen"), e.get("last_changed"),
            int(e.get("listed", True)), e["source"], e.get("page", ""), e["key"]))
        n_docs += 1
        link_base = e.get("copy_url") or e["url"]
        for p in pages:
            t = p["text"].strip()
            if not t:
                continue
            con.execute("INSERT INTO pages (date,kind,title,page,method,text,link,document_key) VALUES (?,?,?,?,?,?,?,?)",
                        (e["date"], e["kind"], e["title"], p["n"], p["method"], t,
                         f"{link_base}#page={p['n']}", e["key"]))
            n_pages += 1
    counts["documents"], counts["pages"] = n_docs, n_pages

    items = [i for i in _jsonl(data / "listings" / "civicclerk-items.jsonl") if not i["is_section"]]
    items = list({i["key"]: i for i in items}.values())
    con.executemany("INSERT INTO agenda_items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        (i["date"], i["outline"], i["title"], i["description"], i["portal_url"], video_by_event.get(i["event_id"]),
         i["section"], i["meeting"],
         i["category"], i["item_number"], i["fiscal_impact"], i["resolution_number"], i["ordinance_number"],
         len(i["attachments"]), "; ".join(a["name"] for a in i["attachments"]), i["key"]) for i in items])
    counts["agenda_items"] = len(items)

    ev = [x for x in _jsonl(data / "manifest.jsonl") if jurisdiction_of(x["key"]) not in COUNTIES]
    con.executemany("INSERT INTO changes (at,event,document_key,date,kind,title,sha256,previous_sha256,bytes,city_url,our_copy) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
        (x["at"], x["event"], x["key"], x.get("date"), x.get("kind"), x.get("title"), x.get("sha256"),
         x.get("previous_sha256"), x.get("bytes"), x.get("url"), x.get("copy_url")) for x in ev])
    counts["changes"] = len(ev)

    counts.update(_entity_tables(con, data))

    con.executescript("""
      CREATE VIRTUAL TABLE votes_fts USING fts5(item_title, motion_text, content='votes', tokenize='porter');
      INSERT INTO votes_fts(rowid, item_title, motion_text) SELECT rowid, item_title, motion_text FROM votes;
      CREATE VIRTUAL TABLE contracts_fts USING fts5(title, vendors, description, content='contracts', tokenize='porter');
      INSERT INTO contracts_fts(rowid, title, vendors, description) SELECT rowid, title, vendors, description FROM contracts;
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


def _entity_tables(con: sqlite3.Connection, data: Path) -> dict:
    ent = data / "entities"
    officials = _jsonl(ent / "officials.jsonl")
    con.executemany("INSERT INTO officials VALUES (?,?,?,?,?,?,?,?)", [
        (o["name"], "; ".join(o["roles"]), "elected" if o["group"] == "elected" else "appointed officer",
         o["meetings_present"], o["meetings_absent"], "; ".join(o["absent_dates"]), o["first_seen"], o["last_seen"])
        for o in officials])
    votes = _jsonl(ent / "votes.jsonl")
    con.executemany("INSERT INTO votes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        (v["date"], v["item"], v["item_title"], v["result"], v["tally"], "; ".join(v["nays"]), "; ".join(v["ayes"]),
         v["mover"], v["seconder"], int(v["roll_call"]), v["record_number"], v["action"], v["minutes_link"],
         v["page_method"], v["text"], v["agenda_item_key"], v["key"]) for v in votes])
    contracts = _jsonl(ent / "contracts.jsonl")
    con.executemany("INSERT INTO contracts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [
        (c["date"], c["title"], "; ".join(c["vendors"]), c["amount_stated"], c.get("vote", ""), c["agenda_link"],
         c["cooperative_contract"], c["solicitation"], c["description"], c["outline"], c["item_number"], c["key"])
        for c in contracts])
    from .entities import vendor_key
    agg: dict[str, dict] = {}
    for c in contracts:
        for v in c["vendors"]:
            a = agg.setdefault(vendor_key(v), {"names": {}, "dates": [], "amount": 0.0, "titles": []})
            a["names"][v] = a["names"].get(v, 0) + 1
            a["dates"].append(c["date"])
            a["titles"].append(f"{c['date']}: {c['title']}")
            if c["amount_stated"] and len(c["vendors"]) == 1:
                a["amount"] += c["amount_stated"]
    con.executemany("INSERT INTO vendors VALUES (?,?,?,?,?,?)", [
        (max(a["names"], key=a["names"].get), len(a["dates"]), min(a["dates"]), max(a["dates"]),
         round(a["amount"], 2) or None, "\n".join(sorted(a["titles"]))) for a in agg.values()])
    return {"officials": len(officials), "votes": len(votes), "contracts": len(contracts), "vendors": len(agg)}


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
                "votes": {"description": "Every motion recorded in the minutes: who moved and seconded it, who "
                          "voted aye and nay, and the result. Machine-read from the minutes (some pages by OCR); "
                          "minutes_link opens the page it came from. roll_call = 0 means the minutes only say "
                          "\"unanimously carried\", so ayes lists the members recorded as present.",
                          "fts_table": "votes_fts", "sort_desc": "date"},
                "contracts": {"description": "Agenda items that approve a purchase, contract or agreement. Vendor "
                              "names and amounts are machine-extracted from the item's wording and may be missing or "
                              "incomplete; amount_stated is the first dollar figure in the text. council_vote comes "
                              "from the minutes. Always check the agenda_link.",
                              "fts_table": "contracts_fts", "sort_desc": "date"},
                "vendors": {"description": "Vendors named in agenda items, with how many items name them. "
                            "amounts_stated_when_sole_vendor adds stated amounts only for items naming one vendor. "
                            "Machine-extracted; spelling variants of one company may appear separately.",
                            "sort_desc": "contracts"},
                "officials": {"description": "Elected officials and charter officers, with attendance as recorded "
                              "in the minutes we hold (Nov 2025 onward)."},
                "votes_fts": {"hidden": True}, "contracts_fts": {"hidden": True},
                "changes": {"description": "Log of documents appearing, changing, or disappearing from the "
                            "city's listings, from data/manifest.jsonl.", "sort_desc": "at"},
                "meetings": {"description": "CivicClerk events. Times are local (Eastern). video links the city's "
                             "YouTube recording when one was matched.", "sort_desc": "date"},
                "videos": {"description": "Uploads on the city's YouTube channel (@cityoftempleterrace), matched to "
                           "meetings by the CivicClerk link in the description, the date in the title, or the live "
                           "stream's start date. matched_by says which.", "sort_desc": "published"},
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
    state = _city_state(data)
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

    state = _city_state(data)
    recent = sorted((e for e in state.values() if e.get("sha256")), key=lambda e: e["date"], reverse=True)[:15]
    gone = sorted((e for e in state.values() if e.get("sha256") and not e.get("listed", True)),
                  key=lambda e: e.get("unlisted_at", ""), reverse=True)
    (out / "templeterrace.html").write_text(city_page(site_url, built, counts, recent, gone, feed_links, out), "utf-8")
    ftm = data / "entities" / "templeterrace.ftm.jsonl"
    if ftm.exists():
        (out / "templeterrace.ftm.jsonl").write_bytes(ftm.read_bytes())
    (out / ".nojekyll").write_text("")
    return counts


def city_summary(data: Path) -> dict:
    """For the front door: the newest Temple Terrace record and how many the city has removed."""
    state = [e for e in _city_state(data).values() if e.get("sha256")]
    return {"latest": max((e["date"] for e in state), default=""),
            "removed": sum(1 for e in state if not e.get("listed", True))}


def city_page(site_url: str, built: str, counts: dict, recent: list[dict], gone: list[dict],
              feed_links: list[str], out: Path) -> str:
    from . import site
    from .site import e, long_date

    def record(x: dict, removed: bool = False) -> str:
        links = ([] if removed else [f'<a href="{e(x["url"])}">City\'s copy</a>']) + (
            [f'<a href="{e(x["copy_url"])}">Our archived copy</a>'] if x.get("copy_url") else [])
        when = (f' · removed from the city\'s site by {e(long_date(x["unlisted_at"]))}'
                if removed and x.get("unlisted_at") else "")
        return (f'<li><p class="title">{e(x["title"])}</p><p>{e(x["kind"])} · meeting of {e(long_date(x["date"]))}{when}</p>'
                f'<p>{" · ".join(links)}</p></li>')
    L = lambda path: _lite(site_url, path)  # noqa: E731
    removed = ""
    if gone:
        removed = (f'<h2 id="removed">Removed from the city\'s website</h2>'
                   f'<p>The city no longer lists {"this document" if len(gone) == 1 else f"these {len(gone)} documents"}. '
                   f'Our archived copies are still here, unchanged.</p><ul class="records">'
                   + "".join(record(x, True) for x in gone) + "</ul>")
    size = site._size(out / "templeterrace.db")
    body = f"""<h1>Temple Terrace City Council records</h1>
<p class="role">Agendas, packets and minutes from October 2025 on</p>
<p class="lede">Every City Council agenda, packet and set of minutes the city still publishes, plus copies of the
ones it has taken down: <mark>{counts['documents']:,} documents</mark>, {counts['pages']:,} searchable pages.</p>
<p class="fair">Plain-language meeting pages for Temple Terrace, like the ones for the counties, are next. For now
you can search the documents and see every recorded council vote.</p>
<form class="search" id="f" role="search"><label for="q">Search Temple Terrace council records</label>
<div class="row"><input type="search" id="q" name="q" required autocomplete="off" placeholder="for example: annexation"><button>Search</button></div>
<fieldset><legend>Search in</legend>
<label><input type="radio" name="w" value="pages" checked> Every page of every document</label>
<label><input type="radio" name="w" value="items"> Agenda items</label></fieldset></form>
<p class="small">Search opens in Datasette Lite, which runs in your browser{f" and downloads the database (about {size}) first" if size else ""}.
Text from scanned pages (marked <code>ocr</code>) was machine-read and can contain errors; follow the page
link to check the original.</p>
<h2>Who decided what</h2>
<ul class="links">
<li><a href="{L('/templeterrace/votes')}">Every council vote</a> (<a href="{L('/templeterrace/votes?_where=nays%3C%3E%27%27&_sort_desc=date')}">split votes only</a>)</li>
<li><a href="{L('/templeterrace/contracts')}">Contracts and purchases</a> and <a href="{L('/templeterrace/vendors')}">the companies</a></li>
<li><a href="{L('/templeterrace/officials')}">Council members and attendance</a></li>
<li><a href="{L('/templeterrace/meetings?_sort_desc=date')}">Meetings</a></li></ul>
<p class="small">Votes, vendors and amounts are read from the minutes and agendas by software and can be wrong.
Each row links to the page it came from.</p>
<h2>Latest documents</h2>
<ul class="records">{"".join(record(x) for x in recent)}</ul>
{removed}
<h2>Browse everything</h2>
<ul class="links"><li><a href="{L('/templeterrace/documents')}">All documents</a></li>
<li><a href="{L('/templeterrace/agenda_items')}">All agenda items</a></li>
<li><a href="{L('/templeterrace/changes')}">Change log</a>: documents the city added, edited or removed</li></ul>
<h2>Get updates</h2>
<p>RSS feeds: <a href="feed.xml">everything new</a> · {" · ".join(feed_links)}.</p>
<script>
document.getElementById('f').addEventListener('submit', function (ev) {{
  ev.preventDefault();
  var q = document.getElementById('q').value.trim();
  var items = document.querySelector('input[name=w]:checked').value === 'items';
  location.href = (items ? {json.dumps(L("/templeterrace/agenda_items"))} : {json.dumps(L("/templeterrace/pages"))}) + '?_search=' + encodeURIComponent(q) + '&_sort_desc=date';
}});
</script>"""
    note = ("<p>Public records from the City of Temple Terrace's CivicClerk portal and Archive Center, collected nightly. "
            "Each document is fingerprinted (SHA-256) and archived, so changes and removals are visible. "
            f'<a href="{_lite(site_url)}">Full database</a> · <a href="templeterrace.db">download</a>.</p>')
    org = {"@type": "GovernmentOrganization", "name": "Temple Terrace City Council",
           "parentOrganization": {"@type": "GovernmentOrganization", "name": "City of Temple Terrace"},
           "areaServed": {"@type": "City", "name": "Temple Terrace, Florida"}}
    return site.page("Temple Terrace City Council records", body, 0, path="templeterrace.html",
                     description=("Search every Temple Terrace City Council agenda, packet and set of minutes, see "
                                  "every recorded council vote, and find documents the city has removed."),
                     note=note, feeds=[("Temple Terrace: new records", "feed.xml")],
                     jsonld=[{"@type": "CollectionPage", "about": org}])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m opencivic.build")
    ap.add_argument("--data-dir", type=Path, default=Path("data"))
    ap.add_argument("--out", type=Path, default=Path("site"))
    ap.add_argument("--site-url", default="https://bgraham1214.github.io/open-civic/")
    args = ap.parse_args(argv)
    site_url = args.site_url.rstrip("/") + "/"
    from . import site
    built = _now().isoformat().replace("+00:00", "Z")
    site.configure(site_url, built)
    site.write_assets(args.out)
    counts = write_site(args.data_dir, args.out, site_url)
    print(json.dumps(counts))
    from . import region
    try:  # a county problem must not stop the city site from publishing
        from . import people
        print(json.dumps({"commissioner_pages": people.write(args.data_dir, args.out, site_url)}))
        from . import meetings
        print(json.dumps({"meeting_pages": meetings.write(args.data_dir, args.out)}))
        print(json.dumps({"counties": region.write(args.data_dir, args.out, site_url, built, _rss)}))
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print(f"::warning::county pages not built: {e}")
    today = site.to_eastern(built).date().isoformat()
    lite = {"templeterrace.db": _lite(site_url), "counties.db": region.lite(site_url)}
    print(json.dumps({"common": site.write_common(args.out, today=today, tt=city_summary(args.data_dir), lite=lite)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
