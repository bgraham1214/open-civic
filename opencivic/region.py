# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""County records: one search database and page for every county in jurisdictions.py.

Produces, in the site directory:
  counties.db              SQLite: meetings, agenda_items, votes, documents, pages, changes
  counties-metadata.json   Datasette descriptions
  counties.html            One section per county, with search and feeds
  feeds/<county>.xml       New meetings, agenda items and documents for that county
  feeds/area-<name>.xml    Agenda items and pages that mention an area (Brandon, Lutz, ...)

Kept apart from templeterrace.db so each stays well under GitHub's 100 MB file limit.
"""

from __future__ import annotations

import gzip
import html
import json
import re
import sqlite3
from pathlib import Path

from .jurisdictions import COUNTIES, JURISDICTIONS, civicclerk_tenants, jurisdiction_of, legistar_clients

LITE = "https://lite.datasette.io/"

SCHEMA = """
CREATE TABLE meetings (
  county TEXT, date TEXT, time TEXT, body TEXT, location TEXT, agenda_status TEXT, minutes_status TEXT,
  agenda_link TEXT, minutes_link TEXT, meeting_page TEXT, note TEXT, key TEXT UNIQUE);
CREATE TABLE agenda_items (
  county TEXT, date TEXT, body TEXT, number TEXT, title TEXT, file_number TEXT, item_type TEXT,
  action TEXT, result TEXT, mover TEXT, seconder TEXT, votes TEXT, nays TEXT, action_text TEXT,
  consent INTEGER, attachments TEXT, areas TEXT, item_link TEXT, meeting_page TEXT, key TEXT UNIQUE);
CREATE TABLE votes (
  county TEXT, date TEXT, body TEXT, person TEXT, vote TEXT, item_number TEXT, item_title TEXT,
  result TEXT, item_link TEXT, item_key TEXT, key TEXT UNIQUE);
CREATE TABLE documents (
  county TEXT, date TEXT, kind TEXT, title TEXT, body TEXT, county_url TEXT, our_copy TEXT, pages INTEGER,
  ocr_pages INTEGER, sha256 TEXT, bytes INTEGER, first_seen TEXT, last_changed TEXT, still_listed INTEGER,
  page_url TEXT, key TEXT UNIQUE);
CREATE TABLE pages (
  id INTEGER PRIMARY KEY, county TEXT, date TEXT, kind TEXT, title TEXT, page INTEGER, method TEXT,
  text TEXT, areas TEXT, link TEXT, document_key TEXT);
CREATE TABLE changes (
  id INTEGER PRIMARY KEY, county TEXT, at TEXT, event TEXT, document_key TEXT, date TEXT, kind TEXT,
  title TEXT, sha256 TEXT, previous_sha256 TEXT, bytes INTEGER, county_url TEXT, our_copy TEXT);
"""


def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text("utf-8").splitlines() if x.strip()]


def _area_rx() -> dict[str, re.Pattern]:
    return {a: re.compile(r"\b" + re.escape(a).replace(r"\ ", r"\s+") + r"\b", re.I)
            for slug in COUNTIES for a in JURISDICTIONS[slug]["areas"]}


def areas_in(text: str, rx: dict[str, re.Pattern] | None = None) -> list[str]:
    rx = rx or _area_rx()
    return [a for a, r in rx.items() if r.search(text or "")]


def _vote_summary(votes: list[dict]) -> tuple[str, str]:
    """('7 in favor, 1 opposed', 'Name') from a list of per-person votes."""
    if not votes:
        return "", ""
    counts: dict[str, int] = {}
    for v in votes:
        counts[v["vote"]] = counts.get(v["vote"], 0) + 1
    nays = [v["person"] for v in votes if v["vote"].lower() in ("nay", "no", "opposed", "against")]
    return ", ".join(f"{n} {k.lower()}" for k, n in sorted(counts.items(), key=lambda kv: -kv[1])), "; ".join(nays)


def load(data: Path) -> dict:
    """Everything county-level from data/listings and data/state.json."""
    lst = data / "listings"
    out = {"meetings": [], "items": [], "votes": [], "docs": [], "changes": []}
    for client, slug in legistar_clients().items():
        for e in _jsonl(lst / f"legistar-{client}-events.jsonl"):
            out["meetings"].append({**e, "county": slug})
        for i in _jsonl(lst / f"legistar-{client}-items.jsonl"):
            out["items"].append({**i, "county": slug})
        for v in _jsonl(lst / f"legistar-{client}-votes.jsonl"):
            out["votes"].append({**v, "county": slug})
    for tenant, slug in civicclerk_tenants().items():
        if slug not in COUNTIES:
            continue
        for m in _jsonl(lst / f"civicclerk-{tenant}-meetings.jsonl"):
            files = {f["kind"]: f for f in m["files"]}
            out["meetings"].append({
                "county": slug, "key": f"civicclerk:{tenant}:event:{m['event_id']}", "date": m["date"],
                "time": m["start"].replace("Z", "")[11:16], "body": f"{m['name']} ({m['category']})",
                "location": m["location"], "agenda_status": "Published" if "Agenda" in files else "",
                "minutes_status": "Published" if "Minutes" in files else "",
                "agenda_url": m["portal_url"] if "Agenda" in files else "",
                "minutes_url": m["portal_url"] if "Minutes" in files else "",
                "portal_url": m["portal_url"], "comment": ""})
        for i in _jsonl(lst / f"civicclerk-{tenant}-items.jsonl"):
            if i.get("is_section"):
                continue
            out["items"].append({
                "county": slug, "key": i["key"], "date": i["date"], "body": i["meeting"],
                "number": i["outline"], "title": i["title"], "file_number": i.get("item_number", ""),
                "matter_type": i.get("section", ""), "action": "", "result": "", "mover": "", "seconder": "",
                "action_text": i.get("description", ""), "consent": "consent" in (i.get("section", "").lower()),
                "attachments": [a["name"] for a in i.get("attachments", [])], "matter_url": "",
                "portal_url": i["portal_url"]})
    state = json.loads((data / "state.json").read_text("utf-8")) if (data / "state.json").exists() else {}
    out["docs"] = [{**e, "county": jurisdiction_of(k)} for k, e in state.items()
                   if jurisdiction_of(k) in COUNTIES and e.get("sha256")]
    out["changes"] = [{**x, "county": jurisdiction_of(x["key"])} for x in _jsonl(data / "manifest.jsonl")
                      if jurisdiction_of(x["key"]) in COUNTIES]
    return out


def build_db(data: Path, db_path: Path) -> dict:
    if db_path.exists():
        db_path.unlink()
    rx = _area_rx()
    d = load(data)
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)
    con.executemany("INSERT OR REPLACE INTO meetings VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [
        (m["county"], m["date"], m.get("time", ""), m["body"], m.get("location", ""), m.get("agenda_status", ""),
         m.get("minutes_status", ""), m.get("agenda_url", ""), m.get("minutes_url", ""), m.get("portal_url", ""),
         m.get("comment", ""), m["key"]) for m in d["meetings"]])
    votes_by_item: dict[str, list[dict]] = {}
    for v in d["votes"]:
        votes_by_item.setdefault(v["item_key"], []).append(v)
    item_by_key = {}
    rows = []
    for i in d["items"]:
        summary, nays = _vote_summary(votes_by_item.get(i["key"], []))
        item_by_key[i["key"]] = i
        rows.append((i["county"], i["date"], i["body"], i.get("number", ""), i["title"], i.get("file_number", ""),
                     i.get("matter_type", ""), i.get("action", ""), i.get("result", ""), i.get("mover", ""),
                     i.get("seconder", ""), summary, nays, i.get("action_text", ""), int(bool(i.get("consent"))),
                     "; ".join(i.get("attachments", [])), "; ".join(areas_in(f"{i['title']} {i.get('action_text', '')}", rx)),
                     i.get("matter_url", "") or i.get("portal_url", ""), i.get("portal_url", ""), i["key"]))
    con.executemany("INSERT OR REPLACE INTO agenda_items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.executemany("INSERT OR REPLACE INTO votes VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
        (v["county"], v["date"], v["body"], v["person"], v["vote"],
         item_by_key.get(v["item_key"], {}).get("number", ""), item_by_key.get(v["item_key"], {}).get("title", "")[:500],
         item_by_key.get(v["item_key"], {}).get("result", ""),
         item_by_key.get(v["item_key"], {}).get("matter_url", "") or item_by_key.get(v["item_key"], {}).get("portal_url", ""),
         v["item_key"], v["key"]) for v in d["votes"]])
    n_pages = 0
    for e in sorted(d["docs"], key=lambda e: (e.get("date", ""), e["key"])):
        text = None
        tp = data / "text" / f"{e['sha256']}.json.gz"
        if tp.exists():
            with gzip.open(tp, "rt", encoding="utf-8") as fh:
                text = json.load(fh)
        pages = text["pages"] if text else []
        con.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            e["county"], e["date"], e["kind"], e["title"], e.get("body", ""), e["url"], e.get("copy_url", ""),
            len(pages) or None, sum(1 for p in pages if p["method"] == "ocr") if text else None, e["sha256"],
            e.get("bytes"), e.get("first_seen"), e.get("last_changed"), int(e.get("listed", True)),
            e.get("page", ""), e["key"]))
        base = e.get("copy_url") or e["url"]
        for p in pages:
            t = p["text"].strip()
            if not t:
                continue
            con.execute("INSERT INTO pages (county,date,kind,title,page,method,text,areas,link,document_key) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (e["county"], e["date"], e["kind"], e["title"], p["n"], p["method"], t,
                         "; ".join(areas_in(t, rx)), f"{base}#page={p['n']}", e["key"]))
            n_pages += 1
    con.executemany("INSERT INTO changes (county,at,event,document_key,date,kind,title,sha256,previous_sha256,bytes,"
                    "county_url,our_copy) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [
        (x["county"], x["at"], x["event"], x["key"], x.get("date"), x.get("kind"), x.get("title"), x.get("sha256"),
         x.get("previous_sha256"), x.get("bytes"), x.get("url"), x.get("copy_url")) for x in d["changes"]])
    con.executescript("""
      CREATE VIRTUAL TABLE agenda_items_fts USING fts5(title, action_text, file_number, content='agenda_items', tokenize='porter');
      INSERT INTO agenda_items_fts(rowid, title, action_text, file_number) SELECT rowid, title, action_text, file_number FROM agenda_items;
      CREATE VIRTUAL TABLE pages_fts USING fts5(title, text, content='pages', content_rowid='id', tokenize='porter');
      INSERT INTO pages_fts(rowid, title, text) SELECT id, title, text FROM pages;
      CREATE INDEX items_county_date ON agenda_items(county, date);
      CREATE INDEX votes_person ON votes(person);
      CREATE INDEX meetings_county_date ON meetings(county, date);
    """)
    con.commit()
    counts = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
              for t in ("meetings", "agenda_items", "votes", "documents", "pages", "changes")}
    counts["by_county"] = {slug: {
        "meetings": con.execute("SELECT count(*) FROM meetings WHERE county=?", (slug,)).fetchone()[0],
        "agenda_items": con.execute("SELECT count(*) FROM agenda_items WHERE county=?", (slug,)).fetchone()[0],
        "votes": con.execute("SELECT count(*) FROM votes WHERE county=?", (slug,)).fetchone()[0],
        "documents": con.execute("SELECT count(*) FROM documents WHERE county=?", (slug,)).fetchone()[0],
        "first": con.execute("SELECT min(date) FROM meetings WHERE county=?", (slug,)).fetchone()[0] or "",
        "last": con.execute("SELECT max(date) FROM meetings WHERE county=? AND date <= date('now')", (slug,)).fetchone()[0] or "",
    } for slug in COUNTIES}
    con.execute("VACUUM")
    con.close()
    return counts


def metadata(built_at: str) -> dict:
    tables = {
        "meetings": {"description": "Every public meeting we list, per county. agenda_link and minutes_link go to "
                     "the county's own copies.", "sort_desc": "date"},
        "agenda_items": {"description": "Agenda items with the action taken, result, mover and seconder, as the "
                         "county recorded them. votes summarises the roll call; nays names anyone voting no. "
                         "areas lists Brandon, Lutz, Wesley Chapel or Spring Hill when the item's text names them.",
                         "fts_table": "agenda_items_fts", "sort_desc": "date"},
        "votes": {"description": "Each commissioner's or member's vote on each item, from the county's Legistar.",
                  "sort_desc": "date"},
        "documents": {"description": "County documents we archive (Pasco agendas and minutes). our_copy is our "
                      "copy; sha256 is its fingerprint.", "sort_desc": "date"},
        "pages": {"description": "One row per page of every archived county document. method = ocr means "
                  "machine-read from a scan.", "fts_table": "pages_fts", "sort_desc": "date"},
        "changes": {"description": "County documents appearing, changing or disappearing.", "sort_desc": "at"},
        "agenda_items_fts": {"hidden": True}, "pages_fts": {"hidden": True},
    }
    src = "; ".join(f"{JURISDICTIONS[s]['name']}: {JURISDICTIONS[s]['coverage']}" for s in COUNTIES)
    return {"title": "Tampa Bay county records", "license": "Public records",
            "about": "Open Civic Web", "about_url": "https://github.com/bgraham1214/open-civic",
            "source": src, "databases": {"counties": {"description": f"Built {built_at}. Updated nightly.",
                                                      "tables": tables}}}


def lite(site_url: str, path: str = "") -> str:
    q = f"?url={site_url}counties.db&metadata={site_url}counties-metadata.json"
    return f"{LITE}{q}{'#' + path if path else ''}"


def feed_entries(data: Path, county: str | None = None, area: str | None = None) -> list[dict]:
    d = load(data)
    rx = _area_rx()
    out = []
    for i in d["items"]:
        if county and i["county"] != county:
            continue
        text = f"{i['title']} {i.get('action_text', '')}"
        if area and area not in areas_in(text, rx):
            continue
        name = JURISDICTIONS[i["county"]]["short"]
        out.append({"title": f"{name} · {i['date']} · {i['body']}: {i['title'][:200]}",
                    "link": i.get("matter_url") or i.get("portal_url", ""), "guid": i["key"],
                    "sort": i["date"], "desc": " ".join(x for x in (i.get("action", ""), i.get("result", ""),
                                                                   i.get("action_text", "")[:800]) if x)})
    if not area:
        for e in d["docs"]:
            if county and e["county"] != county:
                continue
            out.append({"title": f"{JURISDICTIONS[e['county']]['short']} · {e['date']} · {e['kind']}: {e['title']}",
                        "link": e.get("copy_url") or e["url"], "guid": f"{e['key']}:{e['sha256']}",
                        "sort": e["date"], "desc": f"{e.get('body', '')}. County link: {e['url']}"})
    out.sort(key=lambda x: (x["sort"], x["guid"]), reverse=True)
    return out


def page_html(counts: dict, site_url: str, built: str, recent: dict[str, list[dict]]) -> str:
    sections = []
    for slug in COUNTIES:
        j, c = JURISDICTIONS[slug], counts["by_county"][slug]
        areas = ", ".join(j["areas"])
        rows = "".join(
            f"<tr><td>{m['date']}</td><td>{html.escape(m['body'])}</td><td>"
            + " · ".join(x for x in (
                f"<a href=\"{html.escape(m['agenda_url'])}\">agenda</a>" if m.get("agenda_url") else "",
                f"<a href=\"{html.escape(m['minutes_url'])}\">minutes</a>" if m.get("minutes_url") else "",
                f"<a href=\"{html.escape(m['portal_url'])}\">meeting page</a>" if m.get("portal_url") else "") if x)
            + "</td></tr>" for m in recent[slug])
        w = f"county%3D%27{slug}%27"
        area_feeds = " · ".join(f'<a href="feeds/area-{a.lower().replace(" ", "-")}.xml">{html.escape(a)}</a>'
                                for a in j["areas"])
        area_search = " · ".join(
            f'<a href="{lite(site_url, "/counties/agenda_items?areas__contains=" + a.replace(" ", "+") + "&_sort_desc=date")}">'
            f'items mentioning {html.escape(a)}</a>' for a in j["areas"])
        sections.append(f"""
<section id="{slug}"><h2>{html.escape(j['name'])} <span class="areas">({html.escape(areas)})</span></h2>
<p class="sub">{c['meetings']} meetings · {c['agenda_items']} agenda items · {c['votes']} recorded votes ·
{c['documents']} archived documents · {c['first']} to {c['last']}</p>
<p class="note">{html.escape(j['coverage'])}</p>
<p><a href="{lite(site_url, f'/counties/agenda_items?_where={w}&_sort_desc=date')}">Agenda items</a> ·
<a href="{lite(site_url, f'/counties/votes?_where={w}&_sort_desc=date')}">Votes</a> ·
<a href="{lite(site_url, f'/counties/agenda_items?_where={w}%20and%20nays%3C%3E%27%27&_sort_desc=date')}">Items with a no vote</a> ·
<a href="{lite(site_url, f'/counties/meetings?_where={w}&_sort_desc=date')}">Meetings</a>
{(' · <a href="' + lite(site_url, f'/counties/pages?_where={w}&_sort_desc=date') + '">Document pages</a>') if c['documents'] else ''}</p>
<p>{area_search}</p>
<p>RSS: <a href="feeds/{slug}.xml">everything new in {html.escape(j['short'])}</a> · {area_feeds}</p>
<table><tr><th>Date</th><th>Meeting</th><th>Links</th></tr>{rows}</table></section>""")
    return COUNTIES_PAGE.format(sections="".join(sections), lite=lite(site_url), built=built[:16].replace("T", " "),
                                items_js=json.dumps(lite(site_url, "/counties/agenda_items")),
                                pages_js=json.dumps(lite(site_url, "/counties/pages")))


COUNTIES_PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hillsborough, Pasco and Hernando county records</title>
<style>
 body{{font:16px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;max-width:860px;margin:2rem auto;padding:0 1rem;color:#1d1d1f}}
 h1{{font-size:1.6rem;margin-bottom:.2rem}} h2{{margin-top:2.2rem}} .sub{{color:#555;margin-top:0}} .areas{{font-weight:normal;color:#555}}
 form{{display:flex;gap:.5rem;margin:1.2rem 0}} input[type=search]{{flex:1;font-size:1rem;padding:.6rem;border:1px solid #bbb;border-radius:6px}}
 button{{font-size:1rem;padding:.6rem 1rem;border:0;border-radius:6px;background:#1f5fbf;color:#fff;cursor:pointer}}
 label{{margin-right:1rem}} table{{border-collapse:collapse;width:100%;font-size:.92rem}} td,th{{text-align:left;padding:.35rem .5rem;border-bottom:1px solid #e5e5e5;vertical-align:top}}
 .note{{background:#f6f6f2;border-left:4px solid #c9a227;padding:.6rem .9rem;font-size:.92rem}} footer{{color:#666;font-size:.85rem;margin-top:2rem}}
</style></head><body>
<p><a href="index.html">← Temple Terrace City Council</a></p>
<h1>County commission records</h1>
<p class="sub">Brandon and Lutz (Hillsborough) · Wesley Chapel (Pasco) · Spring Hill (Hernando) · updated {built} UTC</p>
<p>Brandon, Lutz, Wesley Chapel and Spring Hill have no city government of their own. Their local decisions
are made by their county commission, so this page follows those commissions.</p>
<form id="f"><input type="search" id="q" placeholder="Search all three counties, e.g. rezoning" required>
<button>Search</button></form>
<p><label><input type="radio" name="w" value="items" checked> Agenda items</label>
<label><input type="radio" name="w" value="pages"> Pages of archived documents</label></p>
<p class="note">Search opens in Datasette Lite, which runs in your browser and takes a few seconds to load.
Actions, results and votes are as each county recorded them; follow the links to check the county's own record.</p>
{sections}
<footer>Public records from Hillsborough County (Legistar), Pasco County (CivicClerk) and Hernando County
(Legistar), collected nightly. <a href="{lite}">Full database</a> · <a href="counties.db">download</a> ·
<a href="https://github.com/bgraham1214/open-civic">Source and data</a>.</footer>
<script>
document.getElementById('f').addEventListener('submit', function (e) {{
  e.preventDefault();
  var q = document.getElementById('q').value.trim();
  var items = document.querySelector('input[name=w]:checked').value === 'items';
  location.href = (items ? {items_js} : {pages_js}) + '?_search=' + encodeURIComponent(q) + '&_sort_desc=date';
}});
</script></body></html>
"""


def write(data: Path, out: Path, site_url: str, built: str, rss) -> dict:
    """rss(title, link, desc, entries) -> str, from build.py, with entries carrying 'pub'."""
    from .build import _pub
    counts = build_db(data, out / "counties.db")
    (out / "counties-metadata.json").write_text(json.dumps(metadata(built), indent=1), "utf-8")
    (out / "feeds").mkdir(parents=True, exist_ok=True)

    def with_pub(entries):
        return [{**x, "pub": _pub(x["sort"] + "T00:00:00Z")} for x in entries[:200]]

    for slug in COUNTIES:
        j = JURISDICTIONS[slug]
        (out / "feeds" / f"{slug}.xml").write_text(rss(
            f"{j['name']}: new records", f"{site_url}counties.html#{slug}",
            f"New agenda items and documents from {j['name']}.", with_pub(feed_entries(data, county=slug))), "utf-8")
        for a in j["areas"]:
            (out / "feeds" / f"area-{a.lower().replace(' ', '-')}.xml").write_text(rss(
                f"{a}: county agenda items", f"{site_url}counties.html#{slug}",
                f"{j['name']} agenda items whose text names {a}.", with_pub(feed_entries(data, area=a))), "utf-8")
    d = load(data)
    recent = {slug: sorted((m for m in d["meetings"] if m["county"] == slug and m["date"] <= built[:10]),
                           key=lambda m: (m["date"], m["key"]), reverse=True)[:10] for slug in COUNTIES}
    (out / "counties.html").write_text(page_html(counts, site_url, built, recent), "utf-8")
    return counts
