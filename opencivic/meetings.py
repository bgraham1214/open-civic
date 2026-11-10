# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
""""What happened" pages: every County Commission meeting in plain language, free.

  site/meetings/<county>.html          every meeting, newest first, with what it covered
  site/meetings/<county>/<date>.html   one meeting: decisions grouped by topic, each with a
                                       plain headline, decoded facts, the outcome, who voted no,
                                       and the official wording one tap away
  site/learn/land.html, money.html     short explainers for zoning and county money

Every county comes with each member's vote: Hillsborough from the Clerk's Master Voting
Record, Hernando from Legistar, Pasco from the Clerk's minutes (opencivic/pascominutes.py).
A Pasco meeting whose minutes aren't out yet (or couldn't be read) lists what was on the
agenda and says so; items with no recorded vote are folded under the decisions.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from pathlib import Path

from .county_entities import BOCC, board_of
from .explain import TERMS, TOPICS, dollars, explain, money
from .jurisdictions import JURISDICTIONS
from .people import _e, cityify, decision_facts, kind, long_date, outcome, page, plain, record_link
from .region import load
from .site import absolute


def weekday_date(d: str) -> str:
    y, m, dd = (int(x) for x in d.split("-"))
    return f"{date(y, m, dd):%A}, {long_date(d)}"


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n:,} {one if n == 1 else (many or one + 's')}"


def _topic_phrase(counts: dict[str, int]) -> str:
    """{'land': 8, 'other': 2} -> '8 on building and land use and 2 others'."""
    parts = []
    for t in TOPICS:
        n = counts.get(t)
        if not n:
            continue
        parts.append(f"{n} {'other' + ('s' if n > 1 else '') if t == 'other' else 'on ' + TOPICS[t].lower()}")
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1] if parts else ""


def _commission(body: str) -> bool:
    """A County Commission meeting. Pasco adds the place after a comma ("Board of County Commissioners,
    Dade City"), which board_of would otherwise read as a joint meeting."""
    b = re.sub(r",\s*(Dade City|New Port Richey)\b.*$", "", (body or "").strip())
    return board_of(b) == BOCC


def meeting_info(data: Path) -> dict[tuple[str, str], dict]:
    """(county, date) -> the County Commission meeting record: time, place, status, official page.
    When a day has several Commission meetings, the one with a published agenda wins."""
    out: dict[tuple[str, str], dict] = {}
    for m in load(data)["meetings"]:
        if not _commission(m.get("body") or ""):
            continue
        k = (m["county"], m["date"])
        rank = (bool(m.get("agenda_url")), (m.get("agenda_status") or "").lower() != "cancelled")
        if k not in out or rank > out[k]["_rank"]:
            out[k] = {**m, "_rank": rank}
    from .council import meeting_info as city_info
    out.update(city_info(data))
    return out


def decisions_by_meeting(data: Path) -> dict[str, dict[str, list[dict]]]:
    """county -> date -> [{item, votes, facts, explained}] for County Commission meetings."""
    out: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    from .people import all_votes
    for county, rec in all_votes(data).items():
        for key, item in rec["items"].items():
            vs = rec["votes"][key]
            out[county][item["date"]].append({"item": item, "votes": vs, "facts": decision_facts(item, vs),
                                              "x": explain(item.get("motion") or item["title"], item.get("matter_type") or "")})
    # The rest of each Commission agenda: items with no recorded vote. For Pasco that's every meeting
    # (its votes come item by item from the minutes). For Hillsborough and Hernando it's only meetings
    # with no votes at all (upcoming, or not yet in the vote records), because their land-use agenda
    # items are the same decisions the vote records already cover.
    voted = {r["item"].get("agenda_key", r["item"]["key"]) for c in out.values() for rs in c.values() for r in rs}
    voted_dates = {c: set(by_date) for c, by_date in out.items()}
    from .council import agenda_items as city_items
    city = city_items(data)
    for i in load(data)["items"] + city:
        c = i["county"]
        if (c != "templeterrace" and not _commission(i.get("body") or "")) or i["key"] in voted:
            continue
        if c not in ("pasco", "templeterrace") and i["date"] in voted_dates.get(c, set()):
            continue
        out[c][i["date"]].append({"item": i, "votes": [], "facts": None,
                                  "x": explain(i["title"], i.get("matter_type") or "")})
    return out


def _vote_line(r: dict) -> str:
    if not r["votes"]:
        return ""
    f = r["facts"]
    nos = sorted(v["person"] for v in r["votes"] if kind(v["vote"]) == "no")
    absent = sorted(v["person"] for v in r["votes"] if kind(v["vote"]) == "none")
    marks = "".join(f'<span class="m {kind(v["vote"])}" title="{_e(v["person"])}: {_e(v["vote"])}"></span>'
                    for v in sorted(r["votes"], key=lambda v: v["person"]))
    who = ""
    if nos:
        who += f'<span class="said no">Voted no: {_e(", ".join(nos))}</span>. '
    if absent:
        who += f'Didn\'t vote: {_e(", ".join(absent))}.'
    return (f'<div class="tally" aria-hidden="true">{marks}</div>'
            f'<p class="outcome">{_e(outcome(f))}.</p>' + (f'<p class="who-voted">{who}</p>' if who else ""))


def _people_link(county: str, name: str) -> str:
    from .people import slug
    return f'../../commissioners/{county}/{slug(name)}.html'


def _iso_time(t: str) -> str:
    """'9:00 AM' -> 'T09:00' (local time; no zone, since the clerk gives none)."""
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*([AP])\.?M\.?", t or "", re.I)
    if not m:
        return ""
    h = int(m.group(1)) % 12 + (12 if m.group(3).upper() == "P" else 0)
    return f"T{h:02d}:{m.group(2)}"


def _days_between(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def meeting_page(county: str, d: str, rows: list[dict], has_people: bool, prev_next: tuple[str, str],
                 info: dict | None = None, today: str = "") -> str:
    j = JURISDICTIONS[county]
    info = info or {}
    today = today or date.today().isoformat()
    upcoming = d > today
    cancelled = (info.get("agenda_status") or "").lower() == "cancelled"
    voted = any(r["votes"] for r in rows)
    others = [r for r in rows if not r["votes"]] if voted else []
    if voted:
        rows = [r for r in rows if r["votes"]]
    by_topic: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_topic[r["x"]["topic"]].append(r)
    counts = _topic_phrase({t: len(by_topic[t]) for t in TOPICS if by_topic.get(t) and t != "routine"})
    biggest = max(((max(money(r["x"]["official"]) or [0]), r) for r in rows), key=lambda t: t[0], default=(0, None))
    nos = [r for r in rows if r["votes"] and any(kind(v["vote"]) == "no" for v in r["votes"])]
    if voted:
        lede = (f'The {_e(j["board"])} voted on <mark>{_plural(len(rows), "decision")}</mark>'
                + (f': {_e(counts)}' if counts else "") + ". "
                + (f'{_plural(len(nos), "decision")} had at least one no vote.' if nos else "Every recorded vote was unanimous."))
    elif upcoming and not cancelled:
        lede = (f'This meeting is coming up. <mark>{_plural(len(rows), "item")}</mark> '
                f'{"is" if len(rows) == 1 else "are"} on the agenda' + (f': {_e(counts)}' if counts else "") + ".")
    else:
        lede = (f'<mark>{_plural(len(rows), "item")}</mark> {"was" if len(rows) == 1 else "were"} on the '
                f'{_e(j["board"])}\'s agenda' + (f': {_e(counts)}' if counts else "") + ".")
    if voted:
        note = ""
    elif cancelled:
        note = (f'<p class="fair">The {j["govt"]} lists this meeting as cancelled. Items on its agenda may come back at a '
                "later meeting.</p>")
    elif upcoming:
        note = ('<p class="fair">Agendas can change up to the day of the meeting, so check the official meeting page '
                f"before you go. {j['body_short']} meetings are open to the public.</p>")
    elif _days_between(d, today) <= 90:
        note = ('<p class="fair">The recorded votes for this meeting aren\'t out yet (they usually come a few weeks '
                "later), so this page shows what was on the agenda, not what was decided. Open the official record "
                "for the outcome.</p>")
    else:
        note = ('<p class="fair">No votes were recorded for this meeting in the records we collect, so this page '
                "shows what was on the agenda, not what was decided. Open the official record for the outcome.</p>")
    when = ""
    if info and (upcoming or not voted):
        place = ", ".join(x for x in (info.get("time", "").strip(), (info.get("location") or "").strip()) if x)
        official = info.get("portal_url") or info.get("agenda_url") or ""
        when = ('<p class="learn"><strong>When and where:</strong> ' + _e(weekday_date(d))
                + (f", {_e(place)}" if place else "") + "."
                + (f' <a href="{_e(official)}">Official meeting page</a>' if official else "") + "</p>")
    big = ""
    if biggest[0] >= 100_000 and biggest[1]:
        big = (f'<p class="learn">Largest dollar amount at this meeting: <strong>{dollars(biggest[0])}</strong>, '
               f'in “{_e(cityify(biggest[1]["x"]["headline"]) if j["govt"] == "city" else biggest[1]["x"]["headline"])}”. '
               f'<a href="../../learn/money.html">How {"public" if j["govt"] == "city" else "county"} money works</a></p>')
    sections = []
    for t in TOPICS:
        items = by_topic.get(t)
        if not items:
            continue
        lis = []
        for r in items:
            lis.append("<li>" + plain(r["item"], 2) + _vote_line(r) + record_link(r["item"]) + "</li>")
        block = f'<ol class="decisions">{"".join(lis)}</ol>'
        if t == "routine":
            sections.append(f'<h2>{TOPICS[t]}</h2><details><summary>Show {len(items)} routine '
                            f'{"item" if len(items) == 1 else "items"}</summary>{block}</details>')
        else:
            sections.append(f'<h2>{TOPICS[t]} <span class="topic-count">({len(items)})</span></h2>'
                            + (f'<p class="learn">New to this? <a href="../../learn/land.html">How building and land '
                               f'decisions work</a></p>' if t == "land" else "") + block)
    if others:
        lis = "".join("<li>" + plain(r["item"], 2) + record_link(r["item"]) + "</li>" for r in others)
        sections.append(f'<h2>Also on the agenda <span class="topic-count">({len(others)})</span></h2>'
                        f'<p>Items with no recorded vote: reports the board only noted, items withdrawn or put off, '
                        f'presentations, and anything the minutes didn\'t record clearly enough for us to read.</p>'
                        f'<details><summary>Show {_plural(len(others), "item")}</summary>'
                        f'<ol class="decisions">{lis}</ol></details>')
    prev, nxt = prev_next
    nav = "".join(x for x in (
        f'<li><a href="{prev}.html" rel="prev">Earlier meeting: {_e(weekday_date(prev))}</a></li>' if prev else "",
        f'<li><a href="{nxt}.html" rel="next">Later meeting: {_e(weekday_date(nxt))}</a></li>' if nxt else "") if x)
    people = (f' <a href="../../{j["people_dir"]}/{county}.html">How each {j["member"]} voted</a>' if has_people else "")
    body = f"""<h1>{_e(weekday_date(d))}</h1>
<p class="role">{_e(j['board'])} meeting</p>
<p class="lede">{lede}</p>
{note}{when}{big}
<p class="fair">Headlines are our plain-language reading of the official wording, made by fixed rules, not AI.
The official wording is under each one. Outcomes count the recorded votes.{people}</p>
{"<ul class='key' aria-label='How to read the squares'><li><span class='m yes'></span> voted yes</li><li><span class='m no'></span> voted no</li><li><span class='m none'></span> didn't vote</li></ul>" if voted else ""}
{''.join(sections)}
{f'<nav class="pager" aria-label="Other meetings"><ul>{nav}</ul></nav>' if nav else ''}"""
    plain_lede = re.sub(r"<[^>]+>", "", lede)
    event = {"@type": "Event", "name": f"{j['board']} meeting",
             "startDate": d + _iso_time(info.get("time", "")),
             "eventStatus": f"https://schema.org/{'EventCancelled' if cancelled else 'EventScheduled'}",
             **({"location": {"@type": "Place", "name": info["location"]}} if info.get("location") else {}),
             "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
             "isAccessibleForFree": True, "description": plain_lede,
             "organizer": {"@type": "GovernmentOrganization", "name": j["board_formal"]},
             "url": absolute(f"meetings/{county}/{d}.html") or None}
    title = f"{j['board']}, {long_date(d)}: " + ("what's on the agenda" if upcoming and not voted else "what happened")
    return page(title, body, 2,
                path=f"meetings/{county}/{d}.html",
                crumbs=[j["hub"], (f"{j['short']} meetings", f"meetings/{county}.html")],
                description=f"{j['board']} meeting of {long_date(d)}, in plain language. {plain_lede}",
                note=f"<p>From {_e(j['name'])}'s official records.</p>", jsonld=[event], here=long_date(d))


def county_index(county: str, by_date: dict[str, list[dict]], has_people: bool, today: str = "") -> str:
    j = JURISDICTIONS[county]
    today = today or date.today().isoformat()
    years: dict[str, list[str]] = defaultdict(list)
    for d in sorted(by_date, reverse=True):
        years[d[:4]].append(d)

    def entry(d: str) -> str:
        rows = by_date[d]
        if any(r["votes"] for r in rows):
            rows = [r for r in rows if r["votes"]]
        topics = defaultdict(int)
        for r in rows:
            topics[r["x"]["topic"]] += 1
        what = _topic_phrase({t: n for t, n in topics.items() if t != "routine"})
        nos = sum(1 for r in rows if r["votes"] and any(kind(v["vote"]) == "no" for v in r["votes"]))
        coming = " (coming up)" if d > today else ""
        noun = "decision" if any(r["votes"] for r in rows) else "agenda item"
        return (f'<li><a href="{county}/{d}.html">{_e(weekday_date(d))}</a>{coming}'
                f'<p>{_plural(len(rows), noun)}' + (f": {_e(what)}" if what else "")
                + (f". {nos} with a no vote." if nos else ".") + "</p></li>")
    blocks = []
    for i, (y, ds) in enumerate(sorted(years.items(), reverse=True)):
        inner = f'<ul class="meetings">{"".join(entry(d) for d in ds)}</ul>'
        blocks.append(f"<h2>{y}</h2>{inner}" if i < 2 else
                      f"<details><summary>{y} ({_plural(len(ds), 'meeting')})</summary>{inner}</details>")
    areas = " and ".join(j["areas"])
    people = (f'<p><a href="../{j["people_dir"]}/{county}.html">How each {j["member"]} voted</a></p>' if has_people else "")
    who = (f"The City Council makes {_e(j['short'])}'s local decisions." if j["govt"] == "city"
           else f"The County Commission makes the local decisions for {_e(areas)}.")
    body = f"""<h1>{_e(j['board'])} meetings</h1>
<p class="role">What happened, in plain language</p>
<p class="lede">{who} Pick a meeting to see what it
decided, explained without the jargon.</p>
{people}
<p class="learn"><a href="../learn/land.html">How building and land decisions work</a> ·
<a href="../learn/money.html">How county money works</a></p>
{''.join(blocks)}"""
    return page(f"{j['board']} meetings", body, 1, path=f"meetings/{county}.html", here=f"{j['short']} meetings",
                crumbs=[j["hub"]],
                description=(f"Every {j['board']} meeting we have, explained in plain language: what was "
                             f"decided" + (f", for {areas}." if areas else ".")),
                feeds=[(f"{j['name']}: new records", "feed.xml" if j["govt"] == "city" else f"feeds/{county}.xml")],
                jsonld=[{"@type": "CollectionPage", "name": f"{j['board']} meetings",
                         "about": {"@type": "GovernmentOrganization", "name": j["board_formal"]}}])


def _term_block(keys: list[str]) -> str:
    out = []
    for k in keys:
        name, text, src = TERMS[k]
        out.append(f"<dt>{_e(name)}</dt><dd>{_e(text)}" + (f' <a href="{_e(src)}">Source</a>' if src else "") + "</dd>")
    return '<dl class="words">' + "".join(out) + "</dl>"


def learn_pages() -> dict[str, str]:
    land = f"""<h1>How building and land decisions work</h1>
<p class="lede">Most of what a County Commission decides is about land: what can be built, where, and how much
of it. Two sets of rules matter.</p>
<h2>1. The long-range land plan</h2>
<p>Each county keeps a Comprehensive Plan with a future land-use map. It sets the most that may ever be built in
each area, usually as homes per acre. In Hillsborough the number is in the label: <strong>RES-4</strong> means
residential, up to 4 homes per acre; <strong>A/R-1/5</strong> means agricultural/rural, up to 1 home per
5 acres. <a href="https://archive.planhillsborough.org/wp-content/uploads/2019/03/FLU-Reference-Guide.pdf">Source</a></p>
<h2>2. Zoning</h2>
<p>Zoning is the rule for a specific piece of land today: single-family homes, shops, offices, and so on. It
has to fit within the land plan. That is why a big change often comes in two steps: first the plan is changed,
then the land is rezoned.</p>
<h2>Who decides, and when you can speak</h2>
<p>In Hillsborough, rezonings and big changes to planned developments get a public hearing before a hearing
officer, the Zoning Hearing Master. Then the County Commission makes the decision.
<a href="https://hcfl.gov/businesses/zoning/zoning-applications-requiring-a-hearing/apply-for-a-major-modification-to-planned-development">Source</a>.
Anyone can sign up to speak at these hearings; each hearing's page on
<a href="https://hcfl.gov/events">hcfl.gov</a> explains how.</p>
<h2>The words you'll see</h2>
{_term_block(["cpa-map", "cpa-text", "rezoning", "rz-std", "rz-pd", "prs", "mm", "usa", "ldc", "vacate", "cdd"])}
"""
    money_ = f"""<h1>How county money works</h1>
<p class="lede">The County Commission sets the property tax rate, passes the budget, and approves the bigger
contracts and grants. Here is what those decisions mean.</p>
<h2>Property taxes</h2>
<p>Florida property taxes are set in mills. One mill is $1 for every $1,000 of a property's taxable value, so
a home with $200,000 of taxable value pays $200 for each mill. Each year the Commission proposes a rate, mails the
proposed tax to owners (the TRIM notice), holds public hearings and then sets the final rate.
<a href="https://www.floridarevenue.com/property/Documents/homeowner_guide_millage.pdf">Source: Florida Department of Revenue</a></p>
<h2>The budget</h2>
<p>The budget decides how the county spends its money for the year. During the year the Commission also moves
money between uses and adds money that comes in later, such as grants. These show up as budget changes.</p>
<h2>Contracts</h2>
<p>When the county buys goods or hires a company for work, larger contracts come to the Commission. The county
usually makes companies compete through an invitation to bid (ITB) or a request for proposals (RFP). Our pages
show the dollar amount and the company named in the official wording.</p>
<h2>The words you'll see</h2>
{_term_block(["millage", "budget", "contract", "grant", "cdd"])}
"""
    note = ("<p>Plain-language explanations, with a source for each where one exists. They describe how the "
            "process works; they don't say whether any decision was right.</p>")

    def art(title: str, body: str, name: str, desc: str) -> str:
        return page(title, body, 1, path=f"learn/{name}.html", crumbs=[("Learn", "learn/index.html")],
                    description=desc, note=note, og_type="article",
                    jsonld=[{"@type": "Article", "headline": title, "description": desc, "inLanguage": "en",
                             "publisher": {"@type": "Organization", "name": "Open Civic Web"},
                             "url": absolute(f"learn/{name}.html") or None}])
    return {"land": art("How building and land decisions work", land, "land",
                        "A plain-language guide to land-use plans, zoning, rezonings and public hearings in Florida counties."),
            "money": art("How county money works", money_, "money",
                         "A plain-language guide to property tax rates (millage), county budgets, contracts and grants.")}


def write(data: Path, out: Path) -> dict:
    from .people import all_votes
    have_people = set(all_votes(data))
    (out / "learn").mkdir(parents=True, exist_ok=True)
    for name, html_ in learn_pages().items():
        (out / "learn" / f"{name}.html").write_text(html_, "utf-8")
    d = out / "meetings"
    d.mkdir(parents=True, exist_ok=True)
    from . import site
    today = site.to_eastern(site.BUILT).date().isoformat() if site.BUILT else date.today().isoformat()
    info = meeting_info(data)
    counts = {}
    for county, by_date in decisions_by_meeting(data).items():
        if not by_date:
            continue
        (d / county).mkdir(exist_ok=True)
        dates = sorted(by_date)
        for i, day in enumerate(dates):
            rows = sorted(by_date[day], key=lambda r: (r["item"].get("number") or "", r["item"]["key"]))
            pn = (dates[i - 1] if i else "", dates[i + 1] if i + 1 < len(dates) else "")
            (d / county / f"{day}.html").write_text(meeting_page(county, day, rows, county in have_people, pn,
                                                                info.get((county, day)), today), "utf-8")
        (d / f"{county}.html").write_text(county_index(county, by_date, county in have_people, today), "utf-8")
        counts[county] = len(dates)
    return counts
