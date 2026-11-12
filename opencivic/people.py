# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Plain-language pages about each county commissioner's recorded votes.

Written for residents who have never read an agenda: every page says in one sentence what
the record shows, then lists the decisions, with clerk shorthand explained.

  site/commissioners/<county>.html          who is on the board, and who used to be
  site/commissioners/<county>/<person>.html one commissioner's votes

Sources: the Hillsborough Clerk's Master Voting Record (complete for the Commission) and
Hernando's Legistar, and Pasco's Clerk's minutes (opencivic/pascominutes.py).

These pages count recorded votes. They say nothing about why anyone voted as they did,
and they never call a vote good or bad.
"""

from __future__ import annotations

import html
import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

from .county_entities import BOCC, board_of
from .jurisdictions import JURISDICTIONS
from .region import areas_in, load
from .site import absolute, write_assets
from . import site

YES = {"yes", "aye", "in favor", "yea", "y"}
NO = {"no", "nay", "opposed", "n"}

CATEGORY_WORDS = {  # the Clerk's categories, in plain words
    "Zoning": "Zoning (what can be built where)",
    "Comprehensive Plan Amendments": "Change to the county's long-range land plan",
    "Ordinances": "Local law (ordinance)",
    "Taxation": "Taxes",
    "Transportation": "Roads and transportation",
    "Environmental Protection Commission": "Environmental Protection Commission",
    "Miscellaneous": "",
}


def kind(vote: str) -> str:
    v = (vote or "").strip().lower()
    return "yes" if v in YES else "no" if v in NO else "none"


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def long_date(d: str) -> str:
    y, m, dd = (int(x) for x in d.split("-"))
    return f"{date(y, m, dd):%B} {dd}, {y}"


def month_year(d: str) -> str:
    y, m, _ = (int(x) for x in d.split("-"))
    return f"{date(y, m, 1):%B %Y}"


def split_motion(text: str) -> tuple[str, str]:
    """Clerk subjects end with the motion: "PRS 25-0077; ...; 13420 Boyette Rd. Moved approval."."""
    m = re.search(r"\s(Moved\b.*|So moved\.?|Motion\b.*)$", text, re.I)
    if m and m.start() > 15:
        return text[:m.start()].strip(), m.group(1).strip()
    return text.strip(), ""


def commission_votes(data: Path) -> dict[str, dict]:
    """Per government: its main board's decisions and each member's votes (the County Commission,
    or a city's council, by its board_rx in jurisdictions.py).

    Hillsborough: the Clerk's record only (it covers every Commission meeting, so Legistar's
    land-use votes would count twice). Hernando: Legistar, County Commission meetings only.
    Edgewater: Legistar, City Council meetings (regular, special, workshops).
    """
    d = load(data)
    items = {i["key"]: i for i in d["items"]}
    out: dict[str, dict] = {}
    for v in d["votes"]:
        c = v["county"]
        if c == "hillsborough" and not v["item_key"].startswith("hillsclerk:"):
            continue
        rx = JURISDICTIONS.get(c, {}).get("board_rx")
        if (not re.match(rx, (v["body"] or "").strip()) if rx else board_of(v["body"]) != BOCC) or v["item_key"] not in items:
            continue
        if items[v["item_key"]].get("consent_section"):  # each consent item carries this vote
            continue
        rec = out.setdefault(c, {"items": {}, "votes": defaultdict(list)})
        rec["items"][v["item_key"]] = items[v["item_key"]]
        rec["votes"][v["item_key"]].append(v)
    return out


def decision_facts(item: dict, votes: list[dict]) -> dict:
    yes = sum(kind(v["vote"]) == "yes" for v in votes)
    no = sum(kind(v["vote"]) == "no" for v in votes)
    res = (item.get("result") or "").lower()
    if res in ("pass", "passed"):
        passed = True
    elif res in ("fail", "failed"):
        passed = False
    else:
        passed = None if yes == no else yes > no
    return {"yes": yes, "no": no, "passed": passed, "action": (item.get("action") or "").strip()}


def outcome(f: dict) -> str:
    """'Passed 5 to 0'; for a motion to deny or to put off, say what the vote did."""
    if f["passed"] is None:
        return f"Tied, {f['yes']} to {f['no']}"
    count = f"{max(f['yes'], f['no'])} to {min(f['yes'], f['no'])}"
    act = (f.get("action") or "").lower()
    if f["passed"] and act.startswith("denied"):
        return f"Denied, {count}"
    if f["passed"] and act.startswith(("continued", "postponed", "tabled", "deferred")):
        return f"Moved to a later meeting, {count}"
    return f"{'Passed' if f['passed'] else 'Failed'} {count}"


def people(rec: dict) -> dict[str, dict]:
    ppl: dict[str, dict] = {}
    for key, vs in rec["votes"].items():
        item = rec["items"][key]
        facts = decision_facts(item, vs)
        for v in vs:
            p = ppl.setdefault(v["person"], {"name": v["person"], "rows": []})
            p["rows"].append({"item": item, "vote": v, "kind": kind(v["vote"]), "facts": facts, "all": vs})
    for p in ppl.values():
        p["rows"].sort(key=lambda r: (r["item"]["date"], r["item"]["key"]), reverse=True)
        dates = [r["item"]["date"] for r in p["rows"]]
        p["first"], p["last"] = min(dates), max(dates)
        p["yes"] = sum(r["kind"] == "yes" for r in p["rows"])
        p["no"] = sum(r["kind"] == "no" for r in p["rows"])
        p["none"] = sum(r["kind"] == "none" for r in p["rows"])
        p["lost"] = [r for r in p["rows"] if r["facts"]["passed"] is not None and r["kind"] != "none"
                     and (r["kind"] == "yes") != r["facts"]["passed"]]
    return ppl


# --- HTML -------------------------------------------------------------------------------

def _e(s: str) -> str:
    return html.escape(s or "", quote=True)


def tally(row: dict, me: str) -> str:
    marks = []
    for v in sorted(row["all"], key=lambda v: v["person"]):
        k = kind(v["vote"])
        label = {"yes": "yes", "no": "no", "none": "didn't vote"}[k]
        mine = " me" if v["person"] == me else ""
        marks.append(f'<span class="m {k}{mine}" title="{_e(v["person"])}: {_e(v["vote"] or label)}"></span>')
    f = row["facts"]
    said = {"yes": "voted yes", "no": "voted no", "none": "didn't vote"}[row["kind"]]
    return (f'<div class="tally" aria-hidden="true">{"".join(marks)}</div>'
            f'<p class="outcome">{_e(outcome(f))}. <span class="said {row["kind"]}">{_e(me.split()[-1])} {said}</span>'
            + (f' <span class="raw">(recorded as “{_e(row["vote"]["vote"])}”)</span>'
               if row["kind"] == "none" and row["vote"]["vote"] else "") + "</p>")


COUNTY_SOURCE = re.compile(r"hcfl\.gov|planhillsborough|hillsborough_county", re.I)


def cityify(text: str, council: bool = True) -> str:
    """A definition written for the counties, worded for a city (its City Council, or for a city with a
    City Commission, council=False, which keeps "the Commission")."""
    for a, b in (("county law", "city law"), ("County gives up", "City gives up"), ("County leadership", "City leadership"),
                 ("the county area", "the city"), ("the county's", "the city's"), ("the county", "the city"), ("The county", "The city"),
                 ("county area", "city"), ("any commissioner", "any council member"), ("Any commissioner", "Any council member"),
                 ("the Commission", "the Council"), ("county budget", "city budget"), ("to the county", "to the city"),
                 ("from the county", "from the city")):
        if not council and "ommission" in a:
            continue
        text = text.replace(a, b)
    return text


def plain(item: dict, depth: int, vote: dict | None = None) -> str:
    """Spotlight tags, plain headline, decoded facts, what the terms mean, and the official wording (folded).
    vote: the vote (decision_facts), so a tag can say whether it passed; None for an item with no vote."""
    from .explain import TERMS, explain
    # When an agenda item carried several motions, each decision is the motion itself; the item is context.
    e = explain(item.get("motion") or item["title"], item.get("matter_type") or "")
    facts = "".join(f"<li>{_e(f)}</li>" for f in e["facts"])
    means = ""
    j = JURISDICTIONS.get(item.get("county", ""), {})
    city = j.get("govt") == "city"
    council = j.get("body_short", "Council") == "Council"
    for t in e["terms"]:
        name, text, src = TERMS[t]
        if city:
            text, src = cityify(text, council), ("" if COUNTY_SOURCE.search(src or "") else src)
        more = f' <a href="{_e(src)}">Source</a>.' if src else ""
        means += (f'<details class="means"><summary>What does “{_e(name)}” mean?</summary>'
                  f'<p>{_e(text)}{more} <a href="{"../" * depth}learn/{"money" if t in ("millage", "contract", "grant", "budget", "cdd", "incentive") else "land"}.html">More</a></p></details>')
    full = re.sub(r"\s+", " ", item["title"] or "").strip()
    official = (f'<details class="official"><summary>Official wording</summary><p>'
                + (f'Motion: {_e(item["motion"])}</p><p>Agenda item: ' if item.get("motion") else "")
                + f'{_e(full[:4000])}{"…" if len(full) > 4000 else ""}</p></details>')
    headline = cityify(e["headline"], council) if city else e["headline"]
    from .spotlight import badges
    return (badges(item, vote, depth) + f'<p class="headline">{_e(headline)}</p>'
            + (f'<p class="subject">{_e(e["subject"])}</p>' if e["subject"] else "")
            + (f'<p class="subject"><strong>Agenda item {_e(item.get("number", ""))}</strong> {_e(full[:320])}</p>'
               if item.get("motion") else "")
            + (f'<ul class="facts">{facts}</ul>' if facts else "") + means + official)


def record_link(it: dict) -> str:
    """Where to check this decision on the government's own site, said plainly: what the link opens,
    and what to look for once there. Every link here was checked to open in a browser (Nov 11, 2026);
    our backup copies are GitHub release files, which download, so the text says so."""
    link = it.get("matter_url") or it.get("portal_url") or ""
    j = JURISDICTIONS.get(it.get("county", ""), {})
    govt = j.get("govt", "county")
    page = it.get("minutes_page")

    def src(body: str) -> str:
        return f'<p class="src">Official record: {body}</p>'
    if it.get("source_hidden"):
        return src(f"the {govt} has since hidden this meeting's page on its website, so there is no link to give.")
    if not link and not it.get("minutes_url") and not it.get("minutes_copy_url"):
        return ""
    if "LegislationDetail.aspx" in link:
        ref = it.get("file_number") or it.get("number") or ""
        return src(f'<a href="{_e(link)}">{f"File # {_e(ref)}" if ref else "This item"} on the {govt}\'s meeting site</a>.')
    if "MeetingDetail.aspx" in link:
        ref, num = it.get("file_number") or "", it.get("number") or ""
        hint = (f". Find File # {_e(ref)}" + (f" (agenda item {_e(num)})" if num else "") if ref
                else f". Find agenda item {_e(num)}" if num else "")
        return src(f'<a href="{_e(link)}">the {govt}\'s page for this meeting</a>{hint} in its list.' if hint
                   else f'<a href="{_e(link)}">the {govt}\'s page for this meeting</a>.')
    where = f", page {page}" if page else ""
    if it.get("minutes_removed") and it.get("minutes_copy_url"):
        return src(f'the {govt} has taken its copy of these minutes down. <a href="{_e(it["minutes_copy_url"])}">Our '
                   f'backup copy{where}</a> (downloads a PDF).')
    if it.get("minutes_url"):
        code = f", item {_e(it['minutes_code'])}" if it.get("minutes_code") else ""
        copy = (f' · <a href="{_e(it["minutes_copy_url"])}">our backup copy</a> (downloads a PDF)'
                if it.get("minutes_copy_url") else "")
        return src(f'<a href="{_e(it["minutes_url"])}">{_e(j.get("body_short", "Commission"))} minutes{where}</a>'
                   f'{code}{copy}. Votes are read from these minutes.')
    if "hillsclerk" in link:
        year = f"{_e(it['record_year'])} " if it.get("record_year") else ""
        rcs = re.sub(r"^RCS\s*", "", it.get("file_number", ""))
        if it.get("record_page"):
            return src(f'<a href="{_e(link)}">the Clerk\'s {year}voting record, page {it["record_page"]}</a>. '
                       f'Look for roll call (RCS) {_e(rcs)}.')
        return src(f'<a href="{_e(link)}">the Clerk\'s {year}voting record</a> (a long PDF). Search it for RCS {_e(rcs)}.')
    if "civicclerk.com" in link:
        what = "the meeting agenda" if "/files/agenda/" in link else f"the {govt}\'s page for this meeting"
        return src(f'<a href="{_e(link)}">{what}</a>.')
    return src(f'<a href="{_e(link)}">the {govt}\'s website</a>.')


def decision(row: dict, me: str) -> str:
    it = row["item"]
    return (f'<li><p class="when">{_e(long_date(it["date"]))}</p>'
            + plain(it, 2, row["facts"]) + tally(row, me) + record_link(it) + "</li>")


def listing(rows: list[dict], me: str, empty: str, show: int = 15) -> str:
    if not rows:
        return f'<p class="empty">{_e(empty)}</p>'
    first = "".join(decision(r, me) for r in rows[:show])
    rest = rows[show:]
    more = (f'<details><summary>Show {len(rest)} more</summary><ol class="decisions">'
            + "".join(decision(r, me) for r in rest) + "</ol></details>") if rest else ""
    return f'<ol class="decisions">{first}</ol>{more}'


GLOSSARY = """
<section class="words" aria-labelledby="words">
<h2 id="words">What these words mean</h2>
<dl>
<dt>County Commission</dt><dd>The elected board that runs county government. In places without a city
government of their own, like {areas}, it makes the local decisions: zoning, roads, parks, the budget and
county taxes.</dd>
<dt>Motion</dt><dd>A formal proposal by one commissioner for what the board should do. “Moved approval” means
a commissioner proposed approving the item. The board then votes on it.</dd>
<dt>Consent agenda</dt><dd>A group of routine items approved together in one vote, to save time.</dd>
<dt>Rezoning</dt><dd>Changing the rules for what can be built on a piece of land. Codes like PRS, RZ and MM
are the county's case numbers for these requests.</dd>
<dt>Long-range land plan</dt><dd>The county's Comprehensive Plan: a map and rules for how land can be used in
the future. Changing it usually comes before a rezoning.</dd>
<dt>Vacating petition</dt><dd>A request for the county to give up a public road, alley or easement it no
longer needs.</dd>
<dt>Didn't vote</dt><dd>The member was recorded as absent, excused, recused or not voting.{xnote}</dd>
</dl>
</section>"""

CITY_GLOSSARY = """
<section class="words" aria-labelledby="words">
<h2 id="words">What these words mean</h2>
<dl>
<dt>City Council</dt><dd>The elected board that runs city government: the mayor and the council members. It
decides the city's laws, budget, taxes, zoning and contracts. In {short} the mayor votes too.</dd>
<dt>Motion</dt><dd>A formal proposal by one member for what the council should do. Another member seconds it,
then the council votes.</dd>
<dt>Consent agenda</dt><dd>A group of routine items approved together in one vote, to save time. Any member can
ask to pull an item off it for a separate discussion and vote.</dd>
<dt>Resolution</dt><dd>A formal decision of the council, such as approving a contract or a purchase.</dd>
<dt>Ordinance</dt><dd>A city law. It is usually read and voted on at two meetings (first and second reading)
before it takes effect.</dd>
<dt>Didn't vote</dt><dd>The member was absent from the meeting, or {record}.</dd>
</dl>
</section>"""

XNOTE = {"hillsborough": " The Hillsborough Clerk marks this “X” (and rarely “A”) without saying which."}

KEY = """<ul class="key" aria-label="How to read the squares">
<li><span class="m yes"></span> voted yes</li><li><span class="m no"></span> voted no</li>
<li><span class="m none"></span> didn't vote</li><li><span class="m yes me"></span> this member</li></ul>"""


def page(title: str, body: str, depth: int, **kw) -> str:
    """The shared page shell (opencivic.site.page)."""
    return site.page(title, body, depth, **kw)


def person_page(county: str, p: dict, footer: str, site_url: str = "") -> str:
    from urllib.parse import quote
    from .region import lite
    j = JURISDICTIONS[county]
    d_ = j["people_dir"]
    if county == "templeterrace":
        from .build import _lite
        search_url = _lite(site_url, f"/templeterrace/votes?_search={quote(p['name'].split()[-1])}&_sort_desc=date")
    else:
        from .jurisdictions import REGIONS, region_of
        db = REGIONS[region_of(county)]["db"]
        search_url = lite(site_url, f"/{db}/votes?person={quote(p['name'])}&county={county}&_sort_desc=date", db)
    name, last = p["name"], p["name"].split()[-1]
    n = len(p["rows"])
    areas = j["areas"]
    span = (f'in {month_year(p["first"])}' if month_year(p["first"]) == month_year(p["last"])
            else f'from {month_year(p["first"])} to {month_year(p["last"])}')
    lede = (f'The record covers <mark>{n:,} {"decision" if n == 1 else "decisions"}</mark> of the '
            f'{_e(j["board"])} while {_e(name)} was a member, {span}. '
            + (f'{_e(last)} voted no {_times(p["no"])}' if p["no"] else f'{_e(last)} never voted no')
            + (f' and didn\'t vote {_times(p["none"])}.' if p["none"] else " and was recorded on every vote."))
    no_rows = [r for r in p["rows"] if r["kind"] == "no"]
    from .spotlight import for_item
    spot_rows = [r for r in p["rows"] if for_item(r["item"])]
    area_rows = [r for r in p["rows"] if areas_in(r["item"]["title"] + " " + (r["item"].get("action_text") or ""))]
    role_line = ", ".join(p.get("roles") or []) + (", " if p.get("roles") else "") + j["board"]
    area_block = (f"""<h2>Decisions that mention {_e(' or '.join(areas))}</h2>
<p>Items whose official wording names {_e(' or '.join(areas))}: {len(area_rows):,}. Other decisions can
affect these areas too without naming them.</p>
{listing(area_rows, name, f"No recorded decision names {' or '.join(areas)} yet.")}
""" if areas else "")
    glossary = (CITY_GLOSSARY.format(short=_e(j["short"]), record=("the minutes don't record their vote" if county == "templeterrace"
                                                                  else "the city's record doesn't show their vote"))
                if j["govt"] == "city" else
                GLOSSARY.format(areas=_e(' and '.join(areas)), xnote=XNOTE.get(county, "")))
    body = f"""<h1>{_e(name)}</h1>
<p class="role">{_e(role_line)}</p>
<p class="lede">{lede}</p>
<p class="fair">These are counts from the {j['govt']}'s official vote records. They don't say why anyone voted the
way they did. A no vote can mean many things, so open the official record to read more.</p>
{KEY}
<h2>When {_e(last)} voted no</h2>
<p>{len(no_rows):,} {"decision" if len(no_rows) == 1 else "decisions"}, newest first.</p>
{listing(no_rows, name, f"{name} hasn't voted no on any recorded decision.")}
<h2>When the board went the other way</h2>
<p>Decisions where {_e(last)} voted on the losing side: {len(p['lost']):,}.</p>
{listing(p['lost'], name, f"{name} was never on the losing side of a recorded vote.")}
<h2>Votes in the spotlight</h2>
<p>Decisions tagged as new restrictions, or as money, land or breaks for companies: {len(spot_rows):,}.
<a href="../../spotlight.html#how">How the tags work</a>. Tags say what a decision does, not whether it was right.</p>
{listing(spot_rows, name, f"No decision {name} voted on has a spotlight tag.")}
{area_block}<h2>Most recent votes</h2>
<p>The latest 25. <a href="{_e(search_url)}">Search all of {_e(last)}'s votes</a>. This opens a
searchable table of every {j['govt']} vote. It's a large download, so it's best on Wi-Fi.</p>
{listing(p['rows'][:25], name, "", show=25)}
{glossary}
"""
    sl = slug(name)
    current = p.get("current")
    title = ", ".join(p.get("roles") or []) or j["member_title"]
    person = {"@type": "Person", "name": name, "url": absolute(f"{d_}/{county}/{sl}.html") or None,
              "jobTitle": title if current else f"Former {title}",
              ("worksFor" if current else "alumniOf"): {"@type": "GovernmentOrganization", "name": j["board_formal"]}}
    return page(f"{name}: votes on the {j['board']}", body, 2,
                path=f"{d_}/{county}/{sl}.html",
                crumbs=[j["hub"], (f"{j['short']} {j['members']}", f"{d_}/{county}.html")],
                description=(f"How {name} voted on the {j['board']}: {n:,} recorded "
                             f"{'vote' if n == 1 else 'votes'} {span}, and every no vote"
                             + (f", and decisions naming {' or '.join(areas)}." if areas else ".")),
                note=footer, jsonld=[{"@type": "ProfilePage", "mainEntity": person}], og_type="profile", here=name)


def county_page(county: str, ppl: dict[str, dict], footer: str) -> str:
    j = JURISDICTIONS[county]
    newest = max(p["last"] for p in ppl.values())
    current = sorted((p for p in ppl.values() if p.get("current")), key=lambda p: p["name"].split()[-1])
    former = sorted((p for p in ppl.values() if p not in current), key=lambda p: p["last"], reverse=True)

    def entry(p: dict) -> str:
        roles = ", ".join(p.get("roles") or [])
        return (f'<li><a href="{county}/{slug(p["name"])}.html">{_e(p["name"])}</a>'
                + (f'<p>{_e(roles)}</p>' if roles else "")
                + f'<p>{len(p["rows"]):,} recorded decisions while a member, {month_year(p["first"])} to {month_year(p["last"])}. '
                + (f'<span class="hl">Voted no {_times(p["no"])}</span>' if p["no"] else "Never voted no")
                + (f'; didn\'t vote {_times(p["none"])}.' if p["none"] else "; recorded on every vote.") + '</p></li>')
    areas = " and ".join(j["areas"])
    plural = "doesn't" if len(j["areas"]) == 1 else "don't"
    if j["govt"] == "city":
        lede = (f"{_e(j['short'])}'s local decisions are made by its {_e(j['body'])}: these {len(current)} members. "
                "The mayor runs the meetings and votes too.")
    else:
        lede = (f"{_e(areas)} {plural} have a city government. Decisions about zoning, roads and county taxes "
                f"there are made by these {len(current)} commissioners.")
    body = f"""<h1>{_e(j['board'])}</h1>
<p class="role">How each {j['member']} voted</p>
<p class="lede">{lede}</p>
<p class="fair">Records through {long_date(newest)}. Counts come from official vote records and say nothing about
why anyone voted the way they did.</p>
<h2>On the {j['body_short']} now</h2>
<ul class="people">{''.join(entry(p) for p in current)}</ul>
{(f'<h2>Former {j["members"]}</h2><ul class="people">' + ''.join(entry(p) for p in former) + '</ul>') if former else ''}
"""
    d_ = j["people_dir"]
    org = {"@type": "GovernmentOrganization", "name": j["board_formal"],
           "areaServed": [{"@type": "Place", "name": f"{a}, Florida"} for a in (j["areas"] or [j["short"]])],
           "member": [{"@type": "Person", "name": p["name"], "jobTitle": ", ".join(p.get("roles") or []) or j["member_title"],
                       "url": absolute(f"{d_}/{county}/{slug(p['name'])}.html") or None} for p in current]}
    return page(f"{j['board']}: how each {j['member']} voted", body, 1,
                path=f"{d_}/{county}.html", crumbs=[j["hub"]], here=f"{j['short']} {j['members']}",
                description=(f"How each {j['board']} member voted, in plain language: who is on the board, "
                             f"how often each voted no, and every recorded decision."),
                note=footer, jsonld=[{"@type": "CollectionPage", "about": org}])


def _times(n: int) -> str:
    return "once" if n == 1 else f"{n:,} times"


def _minus_days(d: str, n: int) -> str:
    from datetime import timedelta
    return (date.fromisoformat(d) - timedelta(days=n)).isoformat()


FOOTERS = {
    "hillsborough": ("Votes from the Hillsborough County Clerk's BOCC Master Voting Record (2014 on), which the "
                     "Clerk updates about monthly, so the newest meetings can be a few weeks behind. Names are "
                     "printed by surname in the record; we match them to full names by date."),
    "hernando": "Votes from Hernando County's Legistar meeting records, County Commission meetings from 2025 on.",
    "edgewater": ("Votes from the City of Edgewater's Legistar meeting records, City Council meetings from 2025 on. "
                  "The consent agenda is approved in one vote, so each item on it shows that vote."),
    "templeterrace": ("Votes read from the City Clerk's minutes of each City Council meeting (from November 2025; the "
                      "city keeps its minutes online for about a year, and we keep copies). When a member didn't vote, "
                      "each decision says whether the minutes recorded them absent."),
    "pasco": ("Votes read from the Pasco Clerk's minutes (County Commission meetings from 2025 on). The Clerk names "
              "only members who voted no, abstained or were absent; everyone else present is counted as yes. "
              "Items whose minutes we couldn't read with confidence (several motions on one item, for example) "
              "are left out."),
}


def all_votes(data: Path) -> dict[str, dict]:
    """Every jurisdiction's decisions and votes: the county commissions, and the Temple Terrace City Council."""
    from .council import SLUG, council_votes
    out = commission_votes(data)
    tt = council_votes(data)
    if tt["items"]:
        out[SLUG] = tt
    return out


def city_roles(data: Path, county: str = "templeterrace") -> dict[str, list[str]]:
    """City member -> ['Mayor'] or ['Council Member'] (or ['City Commissioner']). The vice-mayor seat
    rotates, so it isn't shown. Temple Terrace: officials.jsonl. A Legistar city: its office records
    (legistar-<client>-officers.jsonl), latest seat on the main board; "Councilwoman" and
    "Councilman" both read "Council Member"."""
    j = JURISDICTIONS[county]
    if county == "templeterrace":
        from .council import members
        return {o["name"]: ["Mayor"] if "Mayor" in o.get("roles", []) else ["Council Member"] for o in members(data)}
    from .jurisdictions import legistar_clients
    out: dict[str, tuple[str, list[str]]] = {}
    for client, slug_ in legistar_clients().items():
        if slug_ != county:
            continue
        path = data / "listings" / f"legistar-{client}-officers.jsonl"
        rows = [json.loads(x) for x in path.read_text("utf-8").splitlines() if x.strip()] if path.exists() else []
        for o in rows:
            if j.get("board_rx") and not re.match(j["board_rx"], o["body"]):
                continue
            t = o["title"].lower()
            role = "Mayor" if t == "mayor" else j["member_title"] if re.match(r"council|commission", t) else ""
            if role and (o["name"] not in out or o["start"] >= out[o["name"]][0]):
                out[o["name"]] = (o["start"], [role])
    return {k: v for k, (_, v) in out.items()}


def write(data: Path, out: Path, site_url: str = "") -> dict:
    write_assets(out)
    counts = {}
    for county, rec in all_votes(data).items():
        ppl = people(rec)
        if not ppl:
            continue
        d = out / JURISDICTIONS[county]["people_dir"]
        d.mkdir(parents=True, exist_ok=True)
        if JURISDICTIONS[county]["govt"] == "city":
            roles = city_roles(data, county)
            for p in ppl.values():
                p["roles"] = roles.get(p["name"], [])
        footer = f'<p>{_e(FOOTERS.get(county, ""))}</p>'
        newest = max(p["last"] for p in ppl.values())
        for p in ppl.values():
            p["current"] = p["last"] >= _minus_days(newest, 120)
        (d / f"{county}.html").write_text(county_page(county, ppl, footer), "utf-8")
        (d / county).mkdir(exist_ok=True)
        for p in ppl.values():
            (d / county / f"{slug(p['name'])}.html").write_text(person_page(county, p, footer, site_url), "utf-8")
        counts[county] = len(ppl)
    return counts
