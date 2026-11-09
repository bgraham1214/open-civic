# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
""""What happened" pages: every County Commission meeting in plain language, free.

  site/meetings/<county>.html          every meeting, newest first, with what it covered
  site/meetings/<county>/<date>.html   one meeting: decisions grouped by topic, each with a
                                       plain headline, decoded facts, the outcome, who voted no,
                                       and the official wording one tap away
  site/learn/land.html, money.html     short explainers for zoning and county money

Hillsborough and Hernando come with each member's vote. Pasco publishes agendas but no
votes we can read yet, so its pages list what was on the agenda and say so.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from pathlib import Path

from .explain import TERMS, TOPICS, dollars, explain, money
from .jurisdictions import JURISDICTIONS
from .people import _e, _times, commission_votes, decision_facts, kind, long_date, outcome, page, plain
from .region import load


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


def decisions_by_meeting(data: Path) -> dict[str, dict[str, list[dict]]]:
    """county -> date -> [{item, votes, facts, explained}] for County Commission meetings."""
    out: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for county, rec in commission_votes(data).items():
        for key, item in rec["items"].items():
            vs = rec["votes"][key]
            out[county][item["date"]].append({"item": item, "votes": vs, "facts": decision_facts(item, vs),
                                              "x": explain(item["title"], item.get("matter_type") or "")})
    # Pasco: Commission agenda items, no votes
    for i in load(data)["items"]:
        if i["county"] == "pasco" and "board of county commissioners" in (i.get("body") or "").lower():
            out["pasco"][i["date"]].append({"item": i, "votes": [], "facts": None,
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
    return (f'<div class="tally" role="img" aria-label="{_e(outcome(f))}">{marks}</div>'
            f'<p class="outcome">{_e(outcome(f))}.</p>' + (f'<p class="who-voted">{who}</p>' if who else ""))


def _people_link(county: str, name: str) -> str:
    from .people import slug
    return f'../../commissioners/{county}/{slug(name)}.html'


def meeting_page(county: str, d: str, rows: list[dict], has_people: bool, prev_next: tuple[str, str]) -> str:
    j = JURISDICTIONS[county]
    by_topic: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_topic[r["x"]["topic"]].append(r)
    voted = bool(rows and rows[0]["votes"])
    counts = _topic_phrase({t: len(by_topic[t]) for t in TOPICS if by_topic.get(t) and t != "routine"})
    biggest = max(((max(money(r["x"]["official"]) or [0]), r) for r in rows), key=lambda t: t[0], default=(0, None))
    nos = [r for r in rows if r["votes"] and any(kind(v["vote"]) == "no" for v in r["votes"])]
    if voted:
        lede = (f'The {_e(j["name"])} Commission voted on <mark>{_plural(len(rows), "decision")}</mark>'
                + (f': {_e(counts)}' if counts else "") + ". "
                + (f'{_plural(len(nos), "decision")} had at least one no vote.' if nos else "Every recorded vote was unanimous."))
    else:
        lede = (f'<mark>{_plural(len(rows), "item")}</mark> were on the {_e(j["name"])} Commission\'s agenda'
                + (f': {_e(counts)}' if counts else "") + ".")
    note = ("" if voted else
            f'<p class="fair">{_e(j["name"])} publishes its agendas but not each commissioner\'s vote in a form we can '
            "read yet, so this page shows what was on the agenda, not what was decided. Open the official record "
            "for the outcome.</p>")
    big = ""
    if biggest[0] >= 100_000 and biggest[1]:
        big = (f'<p class="learn">Largest dollar amount at this meeting: <strong>{dollars(biggest[0])}</strong>, '
               f'in “{_e(biggest[1]["x"]["headline"])}”. <a href="../../learn/money.html">How county money works</a></p>')
    sections = []
    for t in TOPICS:
        items = by_topic.get(t)
        if not items:
            continue
        lis = []
        for r in items:
            link = r["item"].get("matter_url") or r["item"].get("portal_url") or ""
            lis.append("<li>" + plain(r["item"], 2) + _vote_line(r)
                       + (f'<p class="src"><a href="{_e(link)}">Official record</a></p>' if link else "") + "</li>")
        block = f'<ol class="decisions">{"".join(lis)}</ol>'
        if t == "routine":
            sections.append(f'<h2>{TOPICS[t]}</h2><details><summary>Show {len(items)} routine '
                            f'{"item" if len(items) == 1 else "items"}</summary>{block}</details>')
        else:
            sections.append(f'<h2>{TOPICS[t]} <span class="topic-count">({len(items)})</span></h2>'
                            + (f'<p class="learn">New to this? <a href="../../learn/land.html">How building and land '
                               f'decisions work</a></p>' if t == "land" else "") + block)
    prev, nxt = prev_next
    nav = " ".join(x for x in (
        f'<a href="{prev}.html">Earlier meeting</a>' if prev else "",
        f'<a href="{nxt}.html">Later meeting</a>' if nxt else "") if x)
    people = (f' <a href="../../commissioners/{county}.html">How each commissioner voted</a>' if has_people else "")
    body = f"""<p class="back"><a href="../{county}.html">All {_e(j['name'])} Commission meetings</a></p>
<h1>{_e(weekday_date(d))}</h1>
<p class="role">{_e(j['name'])} Commission meeting</p>
<p class="lede">{lede}</p>
{note}{big}
<p class="fair">Headlines are our plain-language reading of the official wording, made by fixed rules, not AI.
The official wording is under each one. Outcomes count the recorded votes.{people}</p>
{"<ul class='key' aria-label='How to read the squares'><li><span class='m yes'></span> voted yes</li><li><span class='m no'></span> voted no</li><li><span class='m none'></span> didn't vote</li></ul>" if voted else ""}
{''.join(sections)}
<p class="back">{nav}</p>
<footer>Built by Open Civic Web, a free public project, from {_e(j['name'])}'s official records.
<a href="https://github.com/bgraham1214/open-civic">How it works</a>.</footer>"""
    return page(f"{j['name']} Commission, {long_date(d)}: what happened", body, 2)


def county_index(county: str, by_date: dict[str, list[dict]], has_people: bool) -> str:
    j = JURISDICTIONS[county]
    today = date.today().isoformat()
    years: dict[str, list[str]] = defaultdict(list)
    for d in sorted(by_date, reverse=True):
        years[d[:4]].append(d)

    def entry(d: str) -> str:
        rows = by_date[d]
        topics = defaultdict(int)
        for r in rows:
            topics[r["x"]["topic"]] += 1
        what = _topic_phrase({t: n for t, n in topics.items() if t != "routine"})
        nos = sum(1 for r in rows if r["votes"] and any(kind(v["vote"]) == "no" for v in r["votes"]))
        coming = " (coming up)" if d > today else ""
        noun = "decision" if rows and rows[0]["votes"] else "agenda item"
        return (f'<li><a href="{county}/{d}.html">{_e(weekday_date(d))}</a>{coming}'
                f'<p>{_plural(len(rows), noun)}' + (f": {_e(what)}" if what else "")
                + (f". {nos} with a no vote." if nos else ".") + "</p></li>")
    blocks = []
    for i, (y, ds) in enumerate(sorted(years.items(), reverse=True)):
        inner = f'<ul class="meetings">{"".join(entry(d) for d in ds)}</ul>'
        blocks.append(f"<h2>{y}</h2>{inner}" if i < 2 else
                      f"<details><summary>{y} ({_plural(len(ds), 'meeting')})</summary>{inner}</details>")
    areas = " and ".join(j["areas"])
    people = (f'<p><a href="../commissioners/{county}.html">How each commissioner voted</a></p>' if has_people else "")
    body = f"""<p class="back"><a href="../counties.html">County records</a></p>
<h1>{_e(j['name'])} Commission meetings</h1>
<p class="role">What happened, in plain language</p>
<p class="lede">The County Commission makes the local decisions for {_e(areas)}. Pick a meeting to see what it
decided, explained without the jargon.</p>
{people}
<p class="learn"><a href="../learn/land.html">How building and land decisions work</a> ·
<a href="../learn/money.html">How county money works</a></p>
{''.join(blocks)}
<footer>Built by Open Civic Web, a free public project. <a href="https://github.com/bgraham1214/open-civic">How it works</a>.</footer>"""
    return page(f"{j['name']} Commission meetings", body, 1)


def _term_block(keys: list[str]) -> str:
    out = []
    for k in keys:
        name, text, src = TERMS[k]
        out.append(f"<dt>{_e(name)}</dt><dd>{_e(text)}" + (f' <a href="{_e(src)}">Source</a>' if src else "") + "</dd>")
    return '<dl class="words">' + "".join(out) + "</dl>"


def learn_pages() -> dict[str, str]:
    land = f"""<p class="back"><a href="../counties.html">County records</a></p>
<h1>How building and land decisions work</h1>
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
<footer>Plain-language explanations by Open Civic Web, with a source for each where one exists. They describe how
the process works; they don't say whether any decision was right.</footer>"""
    money_ = f"""<p class="back"><a href="../counties.html">County records</a></p>
<h1>How county money works</h1>
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
<footer>Plain-language explanations by Open Civic Web, with a source for each where one exists. They describe how
the process works; they don't say whether any decision was right.</footer>"""
    return {"land": page("How building and land decisions work", land, 1),
            "money": page("How county money works", money_, 1)}


def write(data: Path, out: Path) -> dict:
    from .people import commission_votes as _cv
    have_people = set(_cv(data))
    (out / "learn").mkdir(parents=True, exist_ok=True)
    for name, html_ in learn_pages().items():
        (out / "learn" / f"{name}.html").write_text(html_, "utf-8")
    d = out / "meetings"
    d.mkdir(parents=True, exist_ok=True)
    counts = {}
    for county, by_date in decisions_by_meeting(data).items():
        if not by_date:
            continue
        (d / county).mkdir(exist_ok=True)
        dates = sorted(by_date)
        for i, day in enumerate(dates):
            rows = sorted(by_date[day], key=lambda r: (r["item"].get("number") or "", r["item"]["key"]))
            pn = (dates[i - 1] if i else "", dates[i + 1] if i + 1 < len(dates) else "")
            (d / county / f"{day}.html").write_text(meeting_page(county, day, rows, county in have_people, pn), "utf-8")
        (d / f"{county}.html").write_text(county_index(county, by_date, county in have_people), "utf-8")
        counts[county] = len(dates)
    return counts
