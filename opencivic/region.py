# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Regional records: one search database and hub page per region in jurisdictions.REGIONS.

Produces, in the site directory, for each region (counties: the Tampa Bay county commissions;
volusia: the southeast Volusia cities):
  <db>.db                  SQLite: meetings, agenda_items, votes, documents, pages, changes
  <db>-metadata.json       Datasette descriptions
  <region page>.html       One section per government, with search and feeds
  feeds/<slug>.xml         New meetings, agenda items and documents for that government
  feeds/area-<name>.xml    Agenda items and pages that mention an area (Brandon, Lutz, ...)

The column named "county" holds the government's slug (a city's too), so every table and page
builder can treat cities and counties alike. Kept apart from templeterrace.db so each database
stays well under GitHub's 100 MB file limit.
"""

from __future__ import annotations

import gzip
import json
import re
import sqlite3
from pathlib import Path

from .civicclerk import viewer_for, viewer_links
from .jurisdictions import (JURISDICTIONS, REGIONAL, REGIONS, civicclerk_tenants, jurisdiction_of, legistar_clients,
                            weblinks_sites)
from .legistar import is_private_body

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
  county TEXT, date TEXT, person TEXT, vote TEXT, item_number TEXT, item_title TEXT, item_key TEXT);
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
            for slug in REGIONAL for a in JURISDICTIONS[slug]["areas"]}


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


def _vote_key(v: dict) -> str:
    """Unique per item. Listings saved before Nov 9, 2026 keyed votes by VoteId alone, which
    repeats when one roll call covers several items."""
    k = v["key"]
    if not k.startswith("legistar:"):
        return k
    item_id = v["item_key"].rsplit(":", 1)[-1]
    parts = k.split(":")
    return k if len(parts) == 5 else ":".join(parts[:3] + [item_id, parts[3]])


def _days(a: str, b: str) -> int:
    from datetime import date
    return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)


def name_resolver(known: dict[str, tuple[str, str]]):
    """Resolve a printed name ("Hagan", "C. Miller", "Cameron Cepeda") on a given date to a full
    name, using full names with the dates they were seen ({name: (first, last)}; ("", "") = any).

    A candidate must share the printed surname (and first initial, if printed). If several
    fit, the one seen nearest that date wins, but only by at least 180 days; otherwise the printed
    name stands. Example: "Miller" in 2019 is Lesley Miller (seen to 2017), not Christine
    Miller (from 2024); "C. Miller" is Christine Miller.
    """
    def resolve(printed: str, on: str) -> str:
        if printed in known:
            return printed
        m = re.match(r"^([A-Z])\. (.+)$", printed)
        initial, rest = (m.group(1), m.group(2)) if m else ("", printed)
        cands = [f for f in known if (f.endswith(" " + rest)) and (not initial or f.startswith(initial))]
        if not cands:
            return printed

        def dist(f: str) -> int:
            a, b = known[f]
            if not a:
                return 0
            return 0 if a <= on <= b else min(_days(on, a), _days(on, b))
        ranked = sorted(cands, key=dist)
        if len(ranked) == 1 or dist(ranked[1]) - dist(ranked[0]) >= 180:
            return ranked[0]
        return printed
    return resolve


def full_names(short: list[str], full: set[str]) -> dict[str, str]:
    """Printed names -> full names when exactly one full name fits (no dates)."""
    r = name_resolver({f: ("", "") for f in full})
    return {s: r(s, "2000-01-01") for s in short}


def inline_report_url(url: str, page: int | None = None) -> str:
    """The Clerk's report URL that opens in the browser, at the page when known."""
    url = re.sub(r"[?&]download=true\b", "", url or "")
    return f"{url}#page={page}" if url and page else url


def _load_hillsclerk(lst: Path, out: dict) -> None:
    """Roll calls from the Hillsborough Clerk's Master Voting Record (hillsclerk.py)."""
    rows = _jsonl(lst / "hillsclerk-bocc-votes.jsonl")
    if not rows:
        return
    from .hillsclerk import BODY, CODES, EXTRA_FULL_NAMES, PAGE
    known: dict[str, tuple[str, str]] = {}

    def seen(name: str, d: str) -> None:
        a, b = known.get(name, (d, d))
        known[name] = (min(a, d), max(b, d))
    for v in out["votes"]:
        if v["county"] == "hillsborough":
            seen(v["person"], v["date"])
    for r in rows:
        if r.get("layout") == "legacy":
            for v in r["votes"]:
                seen(v["name"], r["date"])
    for n in EXTRA_FULL_NAMES:
        known.setdefault(n, ("", ""))
    resolve = name_resolver(known)
    for d in sorted({r["date"] for r in rows}):
        n = sum(1 for r in rows if r["date"] == d)
        out["meetings"].append({
            "county": "hillsborough", "key": f"hillsclerk:bocc-votes:meeting:{d}", "date": d, "time": "",
            "body": f"{BODY} ({n} roll calls, Clerk's voting record)", "location": "",
            "agenda_status": "", "minutes_status": "", "agenda_url": "", "minutes_url": "",
            "portal_url": PAGE, "comment": ""})
    for r in rows:
        out["items"].append({
            "county": "hillsborough", "key": r["key"], "date": r["date"], "body": BODY,
            "number": r["item"] or f"RCS {r['rcs']}", "title": r["subject"], "file_number": f"RCS {r['rcs']}",
            "matter_type": r["category_name"], "action": "Roll call", "result": "", "mover": "", "seconder": "",
            "action_text": "", "consent": False, "attachments": [], "portal_url": PAGE,
            # without ?download=true the Clerk's site opens the PDF in the browser (Content-Disposition:
            # inline, checked Nov 11, 2026), so #page lands on the roll call instead of a downloaded year
            "matter_url": inline_report_url(r["doc_url"], r.get("page")), "record_page": r.get("page"),
            "record_year": r["date"][:4]})
        for v in r["votes"]:
            out["votes"].append({
                "county": "hillsborough", "key": f"{r['key']}:{v['name']}", "item_key": r["key"], "date": r["date"],
                "body": BODY, "person": resolve(v["name"], r["date"]), "vote": CODES.get(v["code"], v["code"]),
                "sort": 0})


def load(data: Path) -> dict:
    """Everything county-level from data/listings and data/state.json."""
    lst = data / "listings"
    out = {"meetings": [], "items": [], "votes": [], "docs": [], "changes": []}
    for client, slug in legistar_clients().items():
        hidden = set()  # agenda status "Hidden": the county took the meeting's web page down (HTTP 410)
        for e in _jsonl(lst / f"legistar-{client}-events.jsonl"):
            if (e.get("agenda_status") or "").lower() == "hidden":
                hidden.add(e["event_id"])
                e = {**e, "portal_url": ""}
            if not is_private_body(e["body"]):
                out["meetings"].append({**e, "county": slug})
        # each item's own page, read from the meeting's web page by `legistar links`; matched by File #
        links = {r["event_id"]: r["links"] for r in _jsonl(lst / f"legistar-{client}-links.jsonl")}
        for i in _jsonl(lst / f"legistar-{client}-items.jsonl"):
            # listings saved before Nov 9, 2026 carry LegislationDetail links built from API ids, which
            # Legistar rejects; only links read from the meeting page are used
            own = links.get(i.get("event_id"), {}).get((i.get("file_number") or "").strip(), "")
            if i.get("event_id") in hidden:
                out["items"].append({**i, "county": slug, "matter_url": "", "portal_url": "", "source_hidden": True})
                continue
            out["items"].append({**i, "county": slug, "matter_url": own})
        for v in _jsonl(lst / f"legistar-{client}-votes.jsonl"):
            out["votes"].append({**v, "county": slug})
        if JURISDICTIONS[slug]["govt"] == "city":
            _legistar_outline(slug, out)
    viewers: dict[int, str] = {}
    for tenant, slug in civicclerk_tenants().items():
        if slug not in REGIONAL:
            continue
        private_events = set()
        cc_meetings = _jsonl(lst / f"civicclerk-{tenant}-meetings.jsonl")
        by_file, agenda_at = viewer_links(cc_meetings)
        viewers.update(by_file)
        for m in cc_meetings:
            if is_private_body(m.get("category", "")) or is_private_body(m.get("name", "")):
                private_events.add(m["event_id"])
                continue
            files = {f["kind"]: f for f in m["files"]}
            out["meetings"].append({
                "county": slug, "key": f"civicclerk:{tenant}:event:{m['event_id']}", "date": m["date"],
                "time": m["start"].replace("Z", "")[11:16], "body": f"{m['name']} ({m['category']})",
                "location": m["location"], "agenda_status": "Published" if "Agenda" in files else "",
                "minutes_status": "Published" if "Minutes" in files else "",
                "agenda_url": agenda_at[m["event_id"]] if "Agenda" in files else "",
                "minutes_url": by_file[int(files["Minutes"]["file_id"])] if "Minutes" in files else "",
                "portal_url": m["portal_url"], "comment": ""})
        for i in _jsonl(lst / f"civicclerk-{tenant}-items.jsonl"):
            if i.get("is_section") or i.get("event_id") in private_events or is_private_body(i.get("category", "")):
                continue
            out["items"].append({
                "county": slug, "key": i["key"], "date": i["date"], "body": i["meeting"],
                "number": i["outline"], "title": i["title"], "file_number": i.get("item_number", ""),
                "matter_type": i.get("section", ""), "action": "", "result": "", "mover": "", "seconder": "",
                "action_text": i.get("description", ""), "consent": "consent" in (i.get("section", "").lower()),
                "attachments": [a["name"] for a in i.get("attachments", [])], "matter_url": "",
                "portal_url": agenda_at.get(i.get("event_id"), i["portal_url"].replace("/agenda", "/files"))})
    _load_pasco_minutes(lst, out, viewers)
    _load_hillsclerk(lst, out)
    state = json.loads((data / "state.json").read_text("utf-8")) if (data / "state.json").exists() else {}
    out["docs"] = [{**e, "county": jurisdiction_of(k)} for k, e in state.items()
                   if jurisdiction_of(k) in REGIONAL and e.get("sha256") and not is_private_body(e.get("body", ""))]
    out["meetings"] += weblinks_meetings(state)
    events = [x for x in _jsonl(data / "manifest.jsonl") if jurisdiction_of(x["key"]) in REGIONAL]
    # Documents excluded under the public-roles rule: hide their earlier events (titles, links to
    # copies) and keep only the exclusion itself, with its reason.
    excluded = {x["key"] for x in events if x["event"] == "excluded"}
    out["changes"] = [{**x, "county": jurisdiction_of(x["key"]),
                       **({"title": x.get("reason", ""), "url": "", "copy_url": ""} if x["event"] == "excluded" else {})}
                      for x in events if x["key"] not in excluded or x["event"] == "excluded"]
    return out


def _legistar_outline(slug: str, out: dict) -> None:
    """A city's Legistar agenda (Edgewater) numbers sub-items "a.", "b." under sections "8.", "9.", and
    votes the consent agenda once, on its section line ("8. CONSENT AGENDA", approve, Pass); the
    items under it carry no action or roll call of their own.

    Each sub-item gets its full number ("8.a."), and each item under a consent section that has no
    action of its own takes the section's action, mover, seconder and roll call, marked consent; the
    section line is then marked consent_section, so the vote isn't counted twice. Section headings with
    no action ("6. CITIZEN COMMENTS") and unnumbered notices ("Pursuant to Chapter 286, F.S. …") are
    left out: they aren't items anyone decides on.
    """
    items = [i for i in out["items"] if i["county"] == slug]
    votes_by_item: dict[str, list[dict]] = {}
    for v in out["votes"]:
        if v["county"] == slug:
            votes_by_item.setdefault(v["item_key"], []).append(v)
    by_event: dict[int, list[dict]] = {}
    for i in items:
        by_event.setdefault(i.get("event_id"), []).append(i)
    for ev_items in by_event.values():
        section, consent_head = "", None
        for i in sorted(ev_items, key=lambda i: (i.get("sequence", 0), i.get("item_id", 0))):
            n = (i.get("number") or "").strip()
            if not n and not i.get("action"):
                i["_drop"] = True
                continue
            if re.fullmatch(r"\d+\.", n):
                section = n
                consent_head = i if re.search(r"\bconsent agenda\b", i["title"], re.I) and i.get("action") else None
                if not i.get("action"):
                    i["_drop"] = True
                continue
            if section and re.fullmatch(r"[a-z]\.", n):
                i["number"] = f"{section}{n}"
            if consent_head and section and not i.get("action") and n:
                head_votes = votes_by_item.get(consent_head["key"], [])
                if not head_votes:
                    continue
                i.update(consent=True, action=consent_head["action"], result=consent_head.get("result", ""),
                         mover=consent_head.get("mover", ""), seconder=consent_head.get("seconder", ""),
                         consent_of=consent_head["key"])
                consent_head["consent_section"] = True
                # same roll call, filed under this item: legistar:<client>:vote:<item id>:<VoteId>
                out["votes"] += [{**v, "key": ":".join(v["key"].split(":")[:3] + [str(i["item_id"]), v["key"].split(":")[-1]]),
                                  "item_key": i["key"], "consent_of": consent_head["key"]} for v in head_votes]
    out["items"] = [i for i in out["items"] if not i.pop("_drop", False)]


def weblinks_meetings(state: dict) -> list[dict]:
    """Meetings of governments that post documents as web-page links (Oak Hill), one per date and
    meeting type, built from the documents themselves. An amended agenda or minutes wins."""
    accounts = weblinks_sites()
    groups: dict[tuple, list[dict]] = {}
    for k, e in state.items():
        parts = k.split(":")
        if parts[0] != "weblinks" or parts[1] not in accounts or not e.get("listed", True):
            continue
        groups.setdefault((accounts[parts[1]], parts[1], e["date"], e.get("body", "")), []).append(e)
    out = []
    for (slug, account, d, body), docs in sorted(groups.items()):
        def best(kind: str) -> dict:
            ds = [x for x in docs if x["kind"] == kind]
            return next((x for x in ds if re.search(r"amend", x["title"], re.I)), ds[0] if ds else {})
        ag, mn = best("Agenda"), best("Minutes")
        out.append({"county": slug, "key": f"weblinks:{account}:meeting:{d}:{re.sub(r'[^a-z]+', '-', body.lower()).strip('-')}",
                    "date": d, "time": "", "body": body, "location": "",
                    "agenda_status": "Published" if ag else "", "minutes_status": "Published" if mn else "",
                    "agenda_url": ag.get("url", ""), "minutes_url": mn.get("url", ""),
                    "agenda_copy_url": ag.get("copy_url", ""), "minutes_copy_url": mn.get("copy_url", ""),
                    "portal_url": "", "comment": ""})
    return out


def _load_pasco_minutes(lst: Path, out: dict, viewers: dict[int, str] | None = None) -> None:
    """Pasco's votes, read from the Clerk's minutes by opencivic.pascominutes, joined to their agenda items.
    The minutes link opens the portal's viewer (the API URL downloads the file); the page goes in the text."""
    actions = {a["item_key"]: a for a in _jsonl(lst / "pasco-minutes-actions.jsonl")}
    if not actions:
        return
    for i in out["items"]:
        a = actions.get(i["key"])
        if a:
            i.update(action=a["action"], result=a["result"], mover=a.get("mover", ""), seconder=a.get("seconder", ""),
                     minutes_url=viewer_for(a.get("minutes_url", "").split("#")[0], viewers or {}) if a.get("minutes_url") else "",
                     minutes_copy_url=a.get("minutes_copy_url", ""),
                     minutes_code=a.get("code", ""), minutes_page=a.get("page"))
    keys = {i["key"] for i in out["items"]}
    out["votes"] += [{**v, "county": "pasco"} for v in _jsonl(lst / "pasco-minutes-votes.jsonl") if v["item_key"] in keys]


def _only(d: dict, members: list[str]) -> dict:
    return {k: [x for x in v if x.get("county") in members] for k, v in d.items()}


def build_db(data: Path, db_path: Path, members: list[str] | None = None) -> dict:
    members = members or REGIONS["counties"]["members"]
    if db_path.exists():
        db_path.unlink()
    rx = _area_rx()
    d = _only(load(data), members)
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
    # Slim on purpose: 70,000+ rows, and Datasette Lite downloads the whole file to the browser.
    # The full title and links live once per decision in agenda_items (join on item_key).
    vote_rows = {}
    for v in d["votes"]:
        it = item_by_key.get(v["item_key"], {})
        title = (it.get("title") or "").replace("\n", " ")
        vote_rows[_vote_key(v)] = (v["county"], v["date"], v["person"], v["vote"], it.get("number", ""),
                                   title[:100] + ("…" if len(title) > 100 else ""), v["item_key"])
    con.executemany("INSERT INTO votes VALUES (?,?,?,?,?,?,?)", list(vote_rows.values()))
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
        # Oak Hill's own copies open in the browser; elsewhere our copy is the stable link
        base = e["url"] if e["key"].startswith("weblinks:") else (e.get("copy_url") or e["url"])
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
      CREATE INDEX votes_person ON votes(person, date);
      CREATE INDEX items_key ON agenda_items(key);
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
    } for slug in members}
    con.execute("VACUUM")
    con.close()
    return counts


def metadata(built_at: str, region: str = "counties") -> dict:
    r = REGIONS[region]
    tables = {
        "meetings": {"description": "Every public meeting we list, per county. agenda_link and minutes_link go to "
                     "the county's own copies.", "sort_desc": "date"},
        "agenda_items": {"description": "Agenda items with the action taken, result, mover and seconder, as the "
                         "county recorded them. votes summarises the roll call; nays names anyone voting no. "
                         "areas lists Brandon, Lutz, Wesley Chapel or Spring Hill when the item's text names them.",
                         "fts_table": "agenda_items_fts", "sort_desc": "date"},
        "votes": {"description": "Each commissioner's or member's vote on each item (item_title is shortened; "
                  "the full wording and links are in agenda_items, matched by item_key), from the county's Legistar "
                  "or, for Hillsborough's full Commission, the Clerk's Master Voting Record. The Clerk's report "
                  "uses Y and N (shown as Yes and No) and also X and A, which it does not define; they are "
                  "shown exactly as printed.",
                  "sort_desc": "date"},
        "documents": {"description": "County documents we archive (Pasco agendas and minutes). our_copy is our "
                      "copy; sha256 is its fingerprint.", "sort_desc": "date"},
        "pages": {"description": "One row per page of every archived county document. method = ocr means "
                  "machine-read from a scan.", "fts_table": "pages_fts", "sort_desc": "date"},
        "changes": {"description": "County documents appearing, changing or disappearing.", "sort_desc": "at"},
        "agenda_items_fts": {"hidden": True}, "pages_fts": {"hidden": True},
    }
    if region != "counties":
        tables = {
            "meetings": {"description": "Every public meeting we list, per city. agenda_link and minutes_link go to "
                         "the city's own copies.", "sort_desc": "date"},
            "agenda_items": {"description": "Agenda items with the action taken, result, mover and seconder, as the "
                             "city recorded them. votes summarises the roll call; nays names anyone voting no. Items "
                             "under a consent agenda carry the consent agenda's single vote.",
                             "fts_table": "agenda_items_fts", "sort_desc": "date"},
            "votes": {"description": "Each council member's vote on each item, from the city's Legistar (item_title is "
                      "shortened; the full wording and links are in agenda_items, matched by item_key).",
                      "sort_desc": "date"},
            "documents": {"description": "City documents we archive (Oak Hill agendas and minutes). our_copy is our "
                          "copy; sha256 is its fingerprint.", "sort_desc": "date"},
            "pages": {"description": "One row per page of every archived city document. method = ocr means "
                      "machine-read from a scan.", "fts_table": "pages_fts", "sort_desc": "date"},
            "changes": {"description": "City documents appearing, changing or disappearing.", "sort_desc": "at"},
            "agenda_items_fts": {"hidden": True}, "pages_fts": {"hidden": True},
        }
    src = "; ".join(f"{JURISDICTIONS[s]['name']}: {JURISDICTIONS[s].get('coverage') or JURISDICTIONS[s].get('blocked', '')}"
                    for s in r["members"])
    return {"title": r["place"], "license": "Public records",
            "about": "Open Civic Web", "about_url": "https://github.com/bgraham1214/open-civic",
            "source": src, "databases": {r["db"]: {"description": f"Built {built_at}. Updated nightly.",
                                                   "tables": tables}}}


def lite(site_url: str, path: str = "", db: str = "counties") -> str:
    q = f"?url={site_url}{db}.db&metadata={site_url}{db}-metadata.json"
    return f"{LITE}{q}{'#' + path if path else ''}"


def lite_for(slug: str, site_url: str, path: str = "") -> str:
    """Datasette Lite for the region holding this government; path names its tables as /<db>/..."""
    from .jurisdictions import region_of
    return lite(site_url, path, REGIONS[region_of(slug) or "counties"]["db"])


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


def page_html(counts: dict, site_url: str, built: str, recent: dict[str, list[dict]], out: Path | None = None,
              region: str = "counties") -> str:
    from . import site
    from .site import e, long_date
    r = REGIONS[region]
    db = r["db"]
    county_hub = region == "counties"
    sections = []
    for slug in r["members"]:
        j = JURISDICTIONS[slug]
        if j.get("blocked"):
            sections.append(f"""
<section id="{slug}" aria-labelledby="h-{slug}"><h2 id="h-{slug}">{e(j['name'])}</h2>
<p>{e(j['blocked'])}</p>
<ul class="links"><li><a href="{e(j['official_records'])}">The city's own agendas and minutes page</a></li>
<li><a href="{e(j['website'])}">The city's website</a></li></ul></section>""")
            continue
        c = counts["by_county"][slug]
        areas = " and ".join(j["areas"])

        def meeting(m: dict) -> str:
            ours = out is not None and (out / "meetings" / slug / f"{m['date']}.html").exists()
            copy = lambda k: f' (<a href="{e(m[k])}">our copy</a>, downloads)' if m.get(k) else ""
            links = [x for x in (
                f'<a href="meetings/{slug}/{m["date"]}.html">What happened, in plain words</a>' if ours else "",
                f'<a href="{e(m["agenda_url"])}">Agenda</a>{copy("agenda_copy_url")}' if m.get("agenda_url") else "",
                f'<a href="{e(m["minutes_url"])}">Minutes</a>{copy("minutes_copy_url")}' if m.get("minutes_url") else "",
                f'<a href="{e(m["portal_url"])}">Official meeting page</a>' if m.get("portal_url") else "") if x]
            return (f'<li><p class="title">{e(site.weekday_date(m["date"]))}</p><p>{e(m["body"])}</p>'
                    f'<p>{" · ".join(links)}</p></li>')
        w = f"county%3D%27{slug}%27"
        plain_links = []
        if out is None or (out / "meetings" / f"{slug}.html").exists():
            plain_links.append(f'<li><a href="meetings/{slug}.html">What happened at each meeting</a></li>')
        if out is not None and (out / j["people_dir"] / f"{slug}.html").exists():
            plain_links.append(f'<li><a href="{j["people_dir"]}/{slug}.html">How each {e(j["member"])} voted</a></li>')
        deep = ([
            f'<a href="{lite(site_url, f"/{db}/agenda_items?_where={w}&_sort_desc=date", db)}">agenda items</a>',
            f'<a href="{lite(site_url, f"/{db}/votes?_where={w}&_sort_desc=date", db)}">votes</a>',
            f'<a href="{lite(site_url, f"/{db}/agenda_items?_where={w}%20and%20nays%3C%3E%27%27&_sort_desc=date", db)}">items with a no vote</a>',
        ] if c["agenda_items"] else []) + [
            f'<a href="{lite(site_url, f"/{db}/meetings?_where={w}&_sort_desc=date", db)}">meetings</a>',
        ] + ([f'<a href="{lite(site_url, f"/{db}/pages?_where={w}&_sort_desc=date", db)}">document pages</a>'] if c["documents"] else [])
        deep += [f'<a href="{lite(site_url, f"/{db}/agenda_items?areas__contains=" + a.replace(" ", "+") + "&_sort_desc=date", db)}">'
                 f'items naming {e(a)}</a>' for a in j["areas"]]
        feeds = [f'<a href="feeds/{slug}.xml">everything new in {e(j["short"])}</a>'] + [
            f'<a href="feeds/area-{a.lower().replace(" ", "-")}.xml">items naming {e(a)}</a>' for a in j["areas"]]
        def n(k: int, one: str, many: str) -> str:
            return f"{k:,} {one if k == 1 else many}"
        counted = [n(c["meetings"], "meeting", "meetings")] + (
            [n(c["agenda_items"], "agenda item", "agenda items"), n(c["votes"], "recorded vote", "recorded votes")]
            if county_hub or c["agenda_items"] else []) + [n(c["documents"], "archived document", "archived documents")]
        span = f" · {e(long_date(c['first']))} to {e(long_date(c['last']))}" if c.get('first') and c.get('last') else ''
        sections.append(f"""
<section id="{slug}" aria-labelledby="h-{slug}"><h2 id="h-{slug}">{e(j['name'])}{f' <span class="topic-count">({e(areas)})</span>' if areas else ''}</h2>
<p class="small">{" · ".join(counted)}{span}</p>
{f'<ul class="links">{"".join(plain_links)}</ul>' if plain_links else ''}
<details><summary>What we collect from {"the " if j["govt"] == "city" else ""}{e(j['name'])}</summary><p>{e(j['coverage'])}</p></details>
<h3>Recent meetings</h3>
<ul class="records">{''.join(meeting(m) for m in recent[slug])}</ul>
<h3>Dig deeper</h3>
<p class="small">Searchable tables (they open in Datasette Lite): {" · ".join(deep)}.</p>
<p class="small">RSS feeds: {" · ".join(feeds)}.</p></section>""")
    size = site._size(out / f"{db}.db") if out is not None else ""
    collected = [s_ for s_ in r["members"] if not JURISDICTIONS[s_].get("blocked")]
    if county_hub:
        top = """<h1>County commission records</h1>
<p class="role">Brandon and Lutz (Hillsborough) · Wesley Chapel (Pasco) · Spring Hill (Hernando)</p>
<p class="lede">Brandon, Lutz, Wesley Chapel and Spring Hill have no city government of their own. Their local
decisions are made by their county commission, so we follow those commissions.</p>
<p class="learn">New to this? <a href="learn/land.html">How building and land decisions work</a> ·
<a href="learn/money.html">How county money works</a> · <a href="learn/index.html">Words you'll see</a></p>"""
        search_label, who = "Search all three counties", "each county"
        description = ("Meetings, agenda items and commissioners' votes for the Hillsborough, Pasco and "
                       "Hernando county commissions, which govern Brandon, Lutz, Wesley Chapel and Spring Hill.")
        note = ("<p>Public records from Hillsborough County (Legistar), Pasco County (CivicClerk) and Hernando County "
                "(Legistar), plus the Hillsborough Clerk's Master Voting Record, collected nightly. "
                f'<a href="{lite(site_url, "", db)}">Full database</a> · <a href="{db}.db">download</a>.</p>')
    else:
        names = [JURISDICTIONS[x]["short"] for x in r["members"]]
        top = f"""<h1>{e(r['title'])}</h1>
<p class="role">{" · ".join(e(n) for n in names)} (Volusia County)</p>
<p class="lede">{e(", ".join(names[:-1]) + " and " + names[-1])} each have their own city government. City
councils and commissions decide zoning, city services and city taxes inside city limits.</p>
<p class="learn">New to this? <a href="learn/land.html">How building and land decisions work</a> ·
<a href="learn/money.html">How public money works</a> · <a href="learn/index.html">Words you'll see</a></p>"""
        search_label, who = "Search these cities' records", "each city"
        description = (f"Meetings, agenda items, votes and archived agendas and minutes for {', '.join(names[:-1])} and "
                       f"{names[-1]}, Florida.")
        note = (f"<p>Public records from {' and '.join(JURISDICTIONS[x]['name'] for x in collected)}, collected nightly. "
                f'<a href="{lite(site_url, "", db)}">Full database</a> · <a href="{db}.db">download</a>.</p>')
    body = f"""{top}
<form class="search" id="f" role="search"><label for="q">{search_label}</label>
<div class="row"><input type="search" id="q" name="q" required autocomplete="off" placeholder="for example: rezoning"><button>Search</button></div>
<fieldset><legend>Search in</legend>
<label><input type="radio" name="w" value="items" checked> Agenda items</label>
<label><input type="radio" name="w" value="pages"> Pages of archived documents</label></fieldset></form>
<p class="small">Search opens in Datasette Lite, which runs in your browser. The first search downloads the whole
database{f" (about {size})" if size else ""}, so it's best on Wi-Fi. Actions, results and votes are as {who}
recorded them; follow the links to check the official record.</p>
{"".join(sections)}
<script>
document.getElementById('f').addEventListener('submit', function (ev) {{
  ev.preventDefault();
  var q = document.getElementById('q').value.trim();
  var items = document.querySelector('input[name=w]:checked').value === 'items';
  location.href = (items ? {json.dumps(lite(site_url, f"/{db}/agenda_items", db))} : {json.dumps(lite(site_url, f"/{db}/pages", db))}) + '?_search=' + encodeURIComponent(q) + '&_sort_desc=date';
}});
</script>"""
    return site.page(r["title"], body, 0, path=r["page"], description=description, note=note,
                     feeds=[(f"{JURISDICTIONS[x]['name']}: new records", f"feeds/{x}.xml") for x in collected])


def write(data: Path, out: Path, site_url: str, built: str, rss) -> dict:
    """rss(title, link, desc, entries) -> str, from build.py, with entries carrying 'pub'.
    Returns {region: counts}."""
    from .build import _pub
    (out / "feeds").mkdir(parents=True, exist_ok=True)

    def with_pub(entries):
        return [{**x, "pub": _pub(x["sort"] + "T00:00:00Z")} for x in entries[:200]]

    d = load(data)
    result = {}
    for region, r in REGIONS.items():
        counts = build_db(data, out / f"{r['db']}.db", r["members"])
        ftm = data / "entities" / f"{r['db']}.ftm.jsonl"
        if ftm.exists():
            (out / f"{r['db']}.ftm.jsonl").write_bytes(ftm.read_bytes())
        (out / f"{r['db']}-metadata.json").write_text(json.dumps(metadata(built, region), indent=1), "utf-8")
        members = [x for x in r["members"] if not JURISDICTIONS[x].get("blocked")]
        for slug in members:
            j = JURISDICTIONS[slug]
            (out / "feeds" / f"{slug}.xml").write_text(rss(
                f"{j['name']}: new records", f"{site_url}{r['page']}#{slug}",
                f"New agenda items and documents from {j['name']}.", with_pub(feed_entries(data, county=slug))), "utf-8")
            for a in j["areas"]:
                (out / "feeds" / f"area-{a.lower().replace(' ', '-')}.xml").write_text(rss(
                    f"{a}: county agenda items", f"{site_url}{r['page']}#{slug}",
                    f"{j['name']} agenda items whose text names {a}.", with_pub(feed_entries(data, area=a))), "utf-8")
        recent = {slug: sorted((m for m in d["meetings"] if m["county"] == slug and m["date"] <= built[:10]),
                               key=lambda m: (m["date"], m["key"]), reverse=True)[:10] for slug in members}
        (out / r["page"]).write_text(page_html(counts, site_url, built, recent, out, region), "utf-8")
        result[region] = counts
    return result
