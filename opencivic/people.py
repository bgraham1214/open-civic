# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Plain-language pages about each county commissioner's recorded votes.

Written for residents who have never read an agenda: every page says in one sentence what
the record shows, then lists the decisions, with clerk shorthand explained.

  site/commissioners/<county>.html          who is on the board, and who used to be
  site/commissioners/<county>/<person>.html one commissioner's votes

Sources: the Hillsborough Clerk's Master Voting Record (complete for the Commission) and
Hernando's Legistar. Pasco publishes no votes in a form we can read yet.

These pages count recorded votes. They say nothing about why anyone voted as they did,
and they never call a vote good or bad.
"""

from __future__ import annotations

import html
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
    """Per county: the County Commission's decisions and each member's votes.

    Hillsborough: the Clerk's record only (it covers every Commission meeting, so Legistar's
    land-use votes would count twice). Hernando: Legistar, County Commission meetings only.
    """
    d = load(data)
    items = {i["key"]: i for i in d["items"]}
    out: dict[str, dict] = {}
    for v in d["votes"]:
        c = v["county"]
        if c == "hillsborough" and not v["item_key"].startswith("hillsclerk:"):
            continue
        if board_of(v["body"]) != BOCC or v["item_key"] not in items:
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
    return {"yes": yes, "no": no, "passed": passed}


def outcome(f: dict) -> str:
    if f["passed"] is None:
        return f"Tied, {f['yes']} to {f['no']}"
    return f"{'Passed' if f['passed'] else 'Failed'} {max(f['yes'], f['no'])} to {min(f['yes'], f['no'])}"


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


def plain(item: dict, depth: int) -> str:
    """Plain headline, decoded facts, what the terms mean, and the official wording (folded)."""
    from .explain import TERMS, TOPICS, explain
    e = explain(item["title"], item.get("matter_type") or "")
    facts = "".join(f"<li>{_e(f)}</li>" for f in e["facts"])
    means = ""
    for t in e["terms"]:
        name, text, src = TERMS[t]
        more = f' <a href="{_e(src)}">Source</a>.' if src else ""
        means += (f'<details class="means"><summary>What does “{_e(name)}” mean?</summary>'
                  f'<p>{_e(text)}{more} <a href="{"../" * depth}learn/{"money" if t in ("millage", "contract", "grant", "budget", "cdd") else "land"}.html">More</a></p></details>')
    full = re.sub(r"\s+", " ", item["title"] or "").strip()
    official = (f'<details class="official"><summary>Official wording</summary><p>{_e(full[:4000])}'
                f'{"…" if len(full) > 4000 else ""}</p></details>')
    return (f'<p class="headline">{_e(e["headline"])}</p>'
            + (f'<p class="subject">{_e(e["subject"])}</p>' if e["subject"] else "")
            + (f'<ul class="facts">{facts}</ul>' if facts else "") + means + official)


def record_link(it: dict) -> str:
    """Link to the official record. For Legistar that's the meeting page, so name the item to look for."""
    link = it.get("matter_url") or it.get("portal_url") or ""
    if not link:
        return ""
    if "MeetingDetail.aspx" in link:
        ref = it.get("file_number") or it.get("number") or ""
        hint = f" (look for item {_e(ref)})" if ref else ""
        return f'<p class="src"><a href="{_e(link)}">Official meeting record</a>{hint}</p>'
    if "hillsclerk" in link:
        return f'<p class="src"><a href="{_e(link)}">Official record</a> (the Clerk\'s vote report, {_e(it.get("file_number", ""))})</p>'
    return f'<p class="src"><a href="{_e(link)}">Official record</a></p>'


def decision(row: dict, me: str) -> str:
    it = row["item"]
    return (f'<li><p class="when">{_e(long_date(it["date"]))}</p>'
            + plain(it, 2) + tally(row, me) + record_link(it) + "</li>")


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

XNOTE = {"hillsborough": " The Hillsborough Clerk marks this “X” (and rarely “A”) without saying which."}

KEY = """<ul class="key" aria-label="How to read the squares">
<li><span class="m yes"></span> voted yes</li><li><span class="m no"></span> voted no</li>
<li><span class="m none"></span> didn't vote</li><li><span class="m yes me"></span> this commissioner</li></ul>"""


def page(title: str, body: str, depth: int, **kw) -> str:
    """The shared page shell (opencivic.site.page)."""
    return site.page(title, body, depth, **kw)


def person_page(county: str, p: dict, footer: str, site_url: str = "") -> str:
    from urllib.parse import quote
    from .region import lite
    search_url = lite(site_url, f"/counties/votes?person={quote(p['name'])}&county={county}&_sort_desc=date")
    j = JURISDICTIONS[county]
    name, last = p["name"], p["name"].split()[-1]
    n = len(p["rows"])
    areas = j["areas"]
    lede = (f'{_e(name)} has been recorded voting on <mark>{n:,} decisions</mark> of the {_e(j["name"])} '
            f'Commission, from {month_year(p["first"])} to {month_year(p["last"])}. '
            f'{_e(last)} voted no {_times(p["no"])} and didn\'t vote {_times(p["none"])}.')
    no_rows = [r for r in p["rows"] if r["kind"] == "no"]
    area_rows = [r for r in p["rows"] if areas_in(r["item"]["title"] + " " + (r["item"].get("action_text") or ""))]
    body = f"""<h1>{_e(name)}</h1>
<p class="role">{_e(j['name'])} Commission</p>
<p class="lede">{lede}</p>
<p class="fair">These are counts from the county's official vote records. They don't say why anyone voted the
way they did. A no vote can mean many things, so open the official record to read more.</p>
{KEY}
<h2>When {_e(last)} voted no</h2>
<p>{len(no_rows):,} {"decision" if len(no_rows) == 1 else "decisions"}, newest first.</p>
{listing(no_rows, name, f"{name} hasn't voted no on any recorded decision.")}
<h2>When the board went the other way</h2>
<p>Decisions where {_e(last)} voted on the losing side: {len(p['lost']):,}.</p>
{listing(p['lost'], name, f"{name} was never on the losing side of a recorded vote.")}
<h2>Decisions that mention {_e(' or '.join(areas))}</h2>
<p>Items whose official wording names {_e(' or '.join(areas))}: {len(area_rows):,}. Other decisions can
affect these areas too without naming them.</p>
{listing(area_rows, name, f"No recorded decision names {' or '.join(areas)} yet.")}
<h2>Most recent votes</h2>
<p>The latest 25. <a href="{_e(search_url)}">Search all {n:,} of {_e(last)}'s votes</a>. This opens a
searchable table of every county vote. It's a large download (about 45 MB), so it's best on Wi-Fi.</p>
{listing(p['rows'][:25], name, "", show=25)}
{GLOSSARY.format(areas=_e(' and '.join(areas)), xnote=XNOTE.get(county, ""))}
"""
    sl = slug(name)
    current = p.get("current")
    person = {"@type": "Person", "name": name, "url": absolute(f"commissioners/{county}/{sl}.html") or None,
              "jobTitle": "County Commissioner" if current else "Former County Commissioner",
              ("worksFor" if current else "alumniOf"): {"@type": "GovernmentOrganization",
                                                        "name": f"{j['name']} Board of County Commissioners"}}
    return page(f"{name}: votes on the {j['name']} Commission", body, 2,
                path=f"commissioners/{county}/{sl}.html",
                crumbs=[("County records", "counties.html"), (f"{j['short']} commissioners", f"commissioners/{county}.html")],
                description=(f"How {name} voted on the {j['name']} Commission: {n:,} recorded votes from "
                             f"{month_year(p['first'])} to {month_year(p['last'])}, every no vote, and decisions naming "
                             f"{' or '.join(areas)}."),
                note=footer, jsonld=[{"@type": "ProfilePage", "mainEntity": person}], og_type="profile", here=name)


def county_page(county: str, ppl: dict[str, dict], footer: str) -> str:
    j = JURISDICTIONS[county]
    newest = max(p["last"] for p in ppl.values())
    current = sorted((p for p in ppl.values() if p.get("current")), key=lambda p: p["name"].split()[-1])
    former = sorted((p for p in ppl.values() if p not in current), key=lambda p: p["last"], reverse=True)

    def entry(p: dict) -> str:
        return (f'<li><a href="{county}/{slug(p["name"])}.html">{_e(p["name"])}</a>'
                f'<p>Voted on {len(p["rows"]):,} decisions from {month_year(p["first"])} to {month_year(p["last"])}. '
                f'<span class="hl">Voted no {_times(p["no"])}</span>; didn\'t vote {_times(p["none"])}.</p></li>')
    areas = " and ".join(j["areas"])
    plural = "doesn't" if len(j["areas"]) == 1 else "don't"
    body = f"""<h1>{_e(j['name'])} Commission</h1>
<p class="role">How each commissioner voted</p>
<p class="lede">{_e(areas)} {plural} have a city government. Decisions about zoning, roads and county taxes
there are made by these {len(current)} commissioners.</p>
<p class="fair">Records through {long_date(newest)}. Counts come from official vote records and say nothing about
why anyone voted the way they did.</p>
<h2>On the Commission now</h2>
<ul class="people">{''.join(entry(p) for p in current)}</ul>
{('<h2>Former commissioners</h2><ul class="people">' + ''.join(entry(p) for p in former) + '</ul>') if former else ''}
"""
    org = {"@type": "GovernmentOrganization", "name": f"{j['name']} Board of County Commissioners",
           "areaServed": [{"@type": "Place", "name": f"{a}, Florida"} for a in j["areas"]],
           "member": [{"@type": "Person", "name": p["name"], "jobTitle": "County Commissioner",
                       "url": absolute(f"commissioners/{county}/{slug(p['name'])}.html") or None} for p in current]}
    return page(f"{j['name']} Commission: how each commissioner voted", body, 1,
                path=f"commissioners/{county}.html", crumbs=[("County records", "counties.html")], here=f"{j['short']} commissioners",
                description=(f"How each {j['name']} commissioner voted, in plain language: who is on the board, "
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
}


def write(data: Path, out: Path, site_url: str = "") -> dict:
    d = out / "commissioners"
    d.mkdir(parents=True, exist_ok=True)
    write_assets(out)
    counts = {}
    for county, rec in commission_votes(data).items():
        ppl = people(rec)
        if not ppl:
            continue
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
