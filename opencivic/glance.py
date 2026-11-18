# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Florida at a glance: the same subject coming up in many places (the user, Nov 18, 2026: "grouping of similar
measures or measures about similar topics into something eye catching. The purpose is to see what's happening
state wide in just a glance").

    at-a-glance.html          every subject that came up in 3 or more governments in the last 90 days, most
                              places first: how many, which, and whether a vote passed or it was only on the agenda
    issues/<slug>.html        one subject: every agenda item since Jan 2025, newest first, grouped by government

Subjects are fixed rules over each item's official wording (title and motion), chosen Nov 18, 2026 by counting
which phrases appeared in the most governments in the 90 days before (data centers: 20 governments, up from
none), then read item by item: every matched item in the window was read before publishing, and each rule's
exclusions come from that reading (tests/test_glance.py). Like the spotlight, a subject says what an item is
about, never whether it was right, and ceremonial items (proclamations, awareness weeks) never count.
"""

from __future__ import annotations

import html
import re
from collections import defaultdict
from datetime import date, timedelta

WINDOW_DAYS = 90
MIN_PLACES = 3

# Proclamations, awareness days, presentations of plaques: about a subject, but not a decision on it.
CEREMONY = re.compile(r"\bproclam|\bawareness (?:day|week|month)\b|\bin recognition\b|\brecogni[sz]ing\b.{0,60}\b(?:week|month|day)\b|"
                      r"\bheritage month\b|\b(?:national|international|world)\b[^.;:]{0,80}\b(?:week|month|day)\b", re.I)
# Never counted (Nov 18, 2026, from reading every matched item): a resident speaking ("DELEGATION: <name> RE:
# Homelessness"), appointments to boards (they name people and aren't a decision on the subject), a resident's own
# lien, minutes, meeting reminders and hearing announcements, and the commissioners' end-of-meeting report items.
NEVER = re.compile(r"^\W*(?:[A-Z]\.\s*)?delegation\b|\b(?:re)?appoint\w*\b|\b(?:release|satisfaction) of (?:a )?lien\b|"
                   r"\bminutes\b|\breminder of upcoming\b|\bcommissioner reports\b|\bset(?:ting)? (?:a |the )?public hearing\b|"
                   r"^\W*announce\b", re.I)

# slug: (title, what it covers, include, exclude)
ISSUES: dict[str, tuple[str, str, re.Pattern, re.Pattern | None]] = {
    "data-centers": (
        "Data centers",
        "Pauses (moratoriums), bans, zoning rules and workshops on building data centers.",
        re.compile(r"\bdata[- ]cent(?:er|re)s?\b|\bAI (?:facilit|campus)|hyperscale", re.I),
        # a government's own server room is not the issue
        re.compile(r"(?:government center|county|city|town|disaster recovery|emergency operations|courthouse|police|"
                   r"sheriff'?s?|library|primary|backup|secondary|(?:town|city|county)['’]s|\bIT\b|information technology)"
                   r"\s+(?:\(IT\)\s+)?data cent|data cent\w*\s+modernization|\bfirewalls?\b|\bcore switch|data cent\w*\s+(?:ac\b|hvac|air|"
                   r"replacement|equipment|upgrade|cooling|ups\b|generator|migration|relocation|hosting|colocation|"
                   r"services? (?:agreement|contract)|network|switch|storage|server|renovation|fire suppression)|"
                   r"colocation", re.I)),
    "license-plate-cameras": (
        "License-plate cameras",
        "Automated license-plate readers (Flock and others): contracts, renewals, cancellations, policies and reports.",
        re.compile(r"license[- ]plate (?:reader|recognition|camera)|\bA?LPRs?\b|\bflock\b", re.I),
        None),
    "school-zone-speed-cameras": (
        "School-zone speed cameras",
        "Speed cameras in school zones, allowed by state law since 2023: ordinances, contracts and annual reports.",
        re.compile(r"school(?:[- ]zone| speed zone)s? speed|speed detection system|school speed zone|"
                   r"speed (?:zone )?(?:enforcement )?cameras?", re.I),
        None),
    "e-bikes": (
        "E-bikes and scooters",
        "Rules for electric bikes, scooters and other small electric vehicles, and studies of their safety.",
        re.compile(r"\be-?bikes?\b|\belectric bicycles?\b|\bmicromobility\b|\b(?:motorized|electric|e-)scooters?\b", re.I),
        re.compile(r"\b(?:purchase|procure\w*|lease|acquisition|buy)\b", re.I)),
    "golf-carts": (
        "Golf carts on public roads",
        "Ordinances and resolutions allowing or limiting golf carts and low-speed vehicles on public roads.",
        re.compile(r"\bgolf carts?\b|\blow[- ]speed vehicles?\b", re.I),
        re.compile(r"\b(?:purchase|procure\w*|lease\w*|acquisition|fuel|trust fund|LETF|manufactur\w*|parade|special event)\b", re.I)),
    "live-local": (
        "Live Local Act housing",
        "Projects, tax exemptions and local rules under the state's Live Local Act, which lets affordable housing "
        "be built where zoning otherwise wouldn't allow it.",
        re.compile(r"\blive local\b", re.I),
        None),
    "homelessness": (
        "Homelessness",
        "Shelters, outreach contracts, camping rules and advisory boards about people without housing.",
        re.compile(r"\bhomeless\w*|\bunsheltered\b|\b(?:public|unauthorized|illegal) camping\b|\bsleeping in public\b", re.I),
        None),
    "property-tax-rates": (
        "Property tax rates",
        "Hearings and votes setting the property tax rate (millage) and the budget it pays for.",
        re.compile(r"\bmillage\b", re.I),
        re.compile(r"\b(?:community development district|cdd|special district|fire (?:control )?district|"
                   r"(?:mstu|msbu)\b.{0,30}\bnon[- ]ad valorem)", re.I)),
    "impact-fees": (
        "Impact fees",
        "Setting or changing the fees new construction pays toward roads, schools, parks and other public services.",
        re.compile(r"\bimpact fees?\b", re.I),
        # one developer's credit or refund, or passing collected fees on, isn't a change to the fees
        re.compile(r"\bcredit agreement\b|\brefund\b|\bdisbursement of\b|\bimpact fee credits?\b|\bdeferral\b|"
                   r"\bimpact fees?\b[^.;]{0,30}\bfunds?\b\s*-", re.I)),
    "hurricanes": (
        "Hurricanes and storm recovery",
        "Storm debris, FEMA reimbursement, repairs after hurricanes and storm preparations.",
        # FEMA also funds port security and generators; only its disaster programs count (Nov 18, 2026, Nassau)
        re.compile(r"\bhurricanes?\b|\btropical storms?\b|\bdebris (?:removal|monitoring|management|hauling|collection)\b|"
                   r"\bFEMA\b[^.;]{0,80}\b(?:reimburs\w*|hazard mitigation|public assistance|disaster|recovery|damage)|"
                   r"\b(?:hazard mitigation|disaster|recovery|damage)\b[^.;]{0,80}\bFEMA\b", re.I),
        re.compile(r"\bhurricane (?:preparedness|season)\b.{0,40}\b(?:week|month)\b|\bhurricane shutters?\b", re.I)),
    "affordable-housing": (
        "Affordable housing",
        "Affordable, workforce and attainable housing: projects, grants, land and rules.",
        re.compile(r"\baffordable housing\b|\bworkforce housing\b|\battainable housing\b", re.I),
        None),
    "annexation": (
        "Annexation",
        "Cities taking land into their limits, usually at the owner's request.",
        re.compile(r"\bannex(?:ation|ations|ing|ed|es)?\b", re.I),
        re.compile(r"\bannex (?:building|facility|office|renovation|roof|parking|lot|south|north|east|west|sewer)\b|"
                   r"\b(?:building|facility|courthouse|library|city hall|county|works|public works) annex\b", re.I)),
    "flooding-resilience": (
        "Flooding and sea-level rise",
        "Resilience plans, vulnerability studies and grants for flooding and rising seas.",
        re.compile(r"\bsea[- ]level\b|\bvulnerability (?:assessment|analysis|study)\b|\bresilient (?:florida|broward)\b|"
                   r"\b(?:flood\w*|coast\w*|storm\w*|beach|shoreline|seawall|stormwater|drainage|wastewater)\b[^.;]{0,80}"
                   r"\bresilien\w*|\bresilien\w*[^.;]{0,80}\b(?:flood\w*|coast\w*|beach|shoreline|seawall|stormwater|drainage)\b", re.I),
        re.compile(r"\bcyber\w*|\benergy resilien|\bmental\b", re.I)),
    "utility-rates": (
        "Water, sewer and trash rates",
        "Changes to what residents pay for water, sewer, stormwater and garbage service.",
        re.compile(r"\b(?:water|sewer|wastewater|utility|utilities|stormwater|solid waste|garbage|refuse|sanitation|"
                   r"reclaimed)\b[^.;]{0,60}\brates?\b[^.;]{0,40}\b(?:increase|adjust\w*|chang\w*|stud(?:y|ies)|"
                   r"schedule|amend\w*|set\w*|establish\w*|revis\w*)|\brate (?:increase|study|adjustment)\b", re.I),
        re.compile(r"\binterest rate\b|\bmillage rate\b|\bhourly rates?\b|\brates? of pay\b|\bpay rates?\b|\bmobility fee\b", re.I)),
    "septic-to-sewer": (
        "Septic to sewer",
        "Projects and grants moving homes off septic tanks onto central sewer.",
        re.compile(r"\bseptic\b", re.I),
        None),
    "legislative-priorities": (
        "Asking the Legislature",
        "Each government's list of what it wants from the state Legislature, and resolutions urging a state "
        "law be passed or repealed.",
        re.compile(r"\blegislative (?:priorit\w*|program|agenda|platform|package|requests?|appropriation requests?)|"
                   r"\burging the (?:florida )?legislature\b", re.I),
        re.compile(r"\bthis legislative agenda item\b", re.I)),
    "fluoride": (
        "Fluoride in drinking water",
        "Ending or keeping fluoride in public water supplies.",
        re.compile(r"\bfluorid\w*", re.I),
        None),
    "kratom": (
        "Kratom and 7-OH",
        "Bans and limits on kratom and the concentrated form 7-OH (7-hydroxymitragynine).",
        re.compile(r"\bkratom\b|\b7-?oh\b|hydroxymitragynine", re.I),
        None),
    "short-term-rentals": (
        "Short-term and vacation rentals",
        "Registration, inspection and limits on short-term and vacation rentals.",
        re.compile(r"\bshort[- ]term (?:vacation )?rentals?\b|\bvacation rentals?\b", re.I),
        re.compile(r"\bmicromobility\b", re.I)),
}


def _text(item: dict) -> str:
    """The item's title only: motion text can be a whole meeting's report (Broward's "Mayor and Commissioner
    Reports ... thank you" motions name a dozen subjects). Hillsborough's titles already carry the motion."""
    return item.get("title") or ""


def subjects(item: dict) -> list[str]:
    """The subjects one agenda item is about (usually none)."""
    t = _text(item)
    if CEREMONY.search(t) or NEVER.search(t):
        return []
    return [slug for slug, (_, _, inc, exc) in ISSUES.items() if inc.search(t) and not (exc and exc.search(t))]


def _norm(s: str) -> str:
    return re.sub(r"\W+", " ", (s or "").lower()).strip()


def gather(by_meeting: dict) -> dict[str, list[dict]]:
    """slug -> [{county, date, row, stage}] newest first; an item listed twice in one meeting (each reading or
    roll call) counts once, a voted row first."""
    from .people import outcome
    out: dict[str, dict[tuple, dict]] = defaultdict(dict)
    for county, by_date in by_meeting.items():
        for d, rows in by_date.items():
            for r in rows:
                for s in subjects(r["item"]):
                    k = (county, d, _norm(r["item"].get("title"))[:200])
                    if k in out[s] and (out[s][k]["row"]["votes"] or not r["votes"]):
                        continue
                    f = r["facts"] if r["votes"] else None
                    stage = ("passed" if f and f.get("passed") else "failed" if f and f.get("passed") is False
                             else "tied" if f else "agenda")
                    out[s][k] = {"county": county, "date": d, "row": r, "stage": stage,
                                 "outcome": outcome(f) if f else "On the agenda; no vote recorded"}
    return {s: sorted(v.values(), key=lambda x: (x["date"], x["county"]), reverse=True) for s, v in out.items()}


def summarize(gathered: dict[str, list[dict]], today: str) -> list[dict]:
    """Subjects in 3+ governments in the window, most governments first."""
    lo = (date.fromisoformat(today) - timedelta(days=WINDOW_DAYS)).isoformat()
    out = []
    for slug, xs in gathered.items():
        recent = [x for x in xs if lo <= x["date"] <= today]
        places: dict[str, dict] = {}
        for x in recent:  # newest first, so the first seen is each government's latest
            p = places.setdefault(x["county"], {"county": x["county"], "latest": x, "passed": False, "items": 0})
            p["items"] += 1
            p["passed"] = p["passed"] or x["stage"] == "passed"
        if len(places) >= MIN_PLACES:
            out.append({"slug": slug, "places": sorted(places.values(), key=lambda p: p["latest"]["date"], reverse=True),
                        "items": len(recent), "all": len(xs)})
    return sorted(out, key=lambda s: (-len(s["places"]), -s["items"], s["slug"]))


# --- pages ---------------------------------------------------------------------------------------------------
def _e(s) -> str:
    return html.escape(str(s), quote=True)


def _gov(county: str) -> str:
    from .jurisdictions import JURISDICTIONS
    j = JURISDICTIONS.get(county, {})
    return j.get("name") or county


def _counties(places: list[dict]) -> int:
    from .jurisdictions import JURISDICTIONS
    return len({JURISDICTIONS.get(p["county"], {}).get("county") or p["county"] for p in places})


def _squares(places: list[dict]) -> str:
    """One square per government, filled where a vote passed: a picture of the list of names that follows it
    (which carries the links and the words), so it's hidden from screen readers."""
    cells = "".join(f'<span class="sq{" yes" if p["passed"] else ""}" title="{_e(_gov(p["county"]))}"></span>'
                    for p in places)
    return f'<div class="sqs" aria-hidden="true">{cells}</div>'


def page_glance(summary: list[dict], today: str, counts: dict) -> str:
    from .site import absolute, long_date, page
    lo = (date.fromisoformat(today) - timedelta(days=WINDOW_DAYS)).isoformat()
    tiles = "".join(
        f'<li><a href="#{_e(s["slug"])}"><span class="big">{len(s["places"])}</span>'
        f'<span class="lbl">{_e(ISSUES[s["slug"]][0])}<span class="vh"> ({len(s["places"])} governments)</span></span></a></li>'
        for s in summary)
    cards = []
    for s in summary:
        title, what, _, _ = ISSUES[s["slug"]]
        n, passed = len(s["places"]), sum(p["passed"] for p in s["places"])
        names = ", ".join(
            f'<a href="meetings/{_e(p["county"])}/{_e(p["latest"]["date"])}.html">{_e(_gov(p["county"]))}</a>'
            + (" (passed)" if p["passed"] else "") for p in s["places"])
        cards.append(f"""<section class="issue" id="{_e(s["slug"])}" aria-labelledby="{_e(s["slug"])}-h">
<h2 id="{_e(s["slug"])}-h"><span class="big">{n}</span> {_e(title)}<span class="vh">: {n} governments</span></h2>
<p>{_e(what)}</p>
<p class="small">{n} governments in {_counties(s["places"])} {"county" if _counties(s["places"]) == 1 else "counties"},
{s["items"]} agenda {"item" if s["items"] == 1 else "items"}; a vote passed in {passed} of them.</p>
{_squares(s["places"])}
<p class="places">{names}.</p>
<p><a href="issues/{_e(s["slug"])}.html">Every item on {_e(title.lower())} since January 2025</a> ({s["all"]})</p>
</section>""")
    key = ('<p class="key small"><span><span class="sq yes" aria-hidden="true"></span> a vote passed</span> '
           '<span><span class="sq" aria-hidden="true"></span> on the agenda; no vote recorded (or not yet)</span></p>')
    body = f"""<h1>Florida at a glance</h1>
<p class="role">The same subjects coming up across the state, {_e(long_date(lo))} to {_e(long_date(today))}</p>
<p class="lede">In the last {WINDOW_DAYS} days, <mark>{counts["governments"]} of the local governments we follow</mark>
put {counts["items"]:,} items on their agendas. These subjects came up in {MIN_PLACES} or more places.</p>
<p class="fair">Each square is one city or county government, filled where a vote passed; the names below each
row link to that government's latest meeting on the subject. Subjects
are found by fixed rules that read each item's official wording; they say what an item is about, never whether a
decision was right. Many governments we follow record no votes online, so "on the agenda" can mean it was
decided and the record doesn't say. <a href="#how">How this works</a>.</p>
<p class="small" id="tiles-h">Number of governments that took up each subject in the last {WINDOW_DAYS} days:</p>
<ul class="tiles" role="list" aria-labelledby="tiles-h">{tiles}</ul>
{key}
{"".join(cards)}
<h2 id="how">How this works</h2>
<p>Every agenda item from the {counts["all_governments"]} governments we follow is read against a fixed list of subjects,
each a set of words in the official wording, with exceptions found by reading real items: a county's own server
room isn't a data center decision, and buying a golf cart isn't a golf-cart rule. Proclamations and awareness
weeks don't count. An item can be about more than one subject. The list was drawn up on November 18, 2026 from
the phrases that appeared in the most governments' agendas; subjects with fewer than {MIN_PLACES} governments in the
last {WINDOW_DAYS} days aren't shown here but keep their own pages. The rules can miss an item or, rarely, include
one that doesn't fit. <a href="https://github.com/bgraham1214/open-civic/issues">Report a mistake</a>.</p>
<p>Only governments we collect are counted: see <a href="florida.html">what we cover in Florida</a>. A subject
missing here may be on agendas we can't read.</p>"""
    desc = ("Which subjects are coming up across Florida's local governments right now: data centers, license-plate "
            "cameras, property taxes and more, with every city and county that took each one up.")
    return page("Florida at a glance: the same subjects across local governments", body, 0, path="at-a-glance.html",
                description=desc, here="Florida at a glance",
                jsonld=[{"@type": "CollectionPage", "name": "Florida at a glance", "description": desc,
                         "url": absolute("at-a-glance.html") or None}])


def page_issue(slug: str, xs: list[dict], today: str) -> str:
    from .people import plain, record_link
    from .site import absolute, long_date, page
    title, what, _, _ = ISSUES[slug]
    by_gov: dict[str, list[dict]] = defaultdict(list)
    for x in xs:
        by_gov[x["county"]].append(x)
    order = sorted(by_gov, key=lambda g: (max(x["date"] for x in by_gov[g]), g), reverse=True)

    def li(x: dict) -> str:
        r = x["row"]
        return (f'<li><p class="when"><a href="../meetings/{_e(x["county"])}/{_e(x["date"])}.html">'
                f'{_e(long_date(x["date"]))}</a></p>' + plain(r["item"], 1, r["facts"] if r["votes"] else None)
                + f'<p class="outcome">{_e(x["outcome"])}.</p>' + record_link(r["item"]) + "</li>")

    sections = "".join(
        f'<h2 id="{_e(g)}">{_e(_gov(g))} <span class="topic-count">({len(by_gov[g])})</span></h2>'
        f'<ol class="decisions">{"".join(li(x) for x in by_gov[g])}</ol>' for g in order)
    passed = sum(1 for x in xs if x["stage"] == "passed")
    body = f"""<h1>{_e(title)}</h1>
<p class="role">{_e(what)}</p>
<p class="lede"><mark>{len(by_gov)} {"government" if len(by_gov) == 1 else "governments"}</mark> we follow put
{len(xs)} {"item" if len(xs) == 1 else "items"} about this on their agendas since January 2025; a vote passed on {passed}.</p>
<p class="fair">Found by fixed rules from each item's official wording (<a href="../at-a-glance.html#how">how</a>).
Newest first, by government. "On the agenda" means no vote is recorded online, which for many governments we
follow is always the case.</p>
{sections}"""
    return page(f"{title} across Florida local governments", body, 1, path=f"issues/{slug}.html",
                crumbs=[("Florida at a glance", "at-a-glance.html")], here=title,
                description=f"{title}: every agenda item from the Florida local governments we follow since January 2025. {what}",
                jsonld=[{"@type": "CollectionPage", "name": f"{title} across Florida local governments",
                         "url": absolute(f"issues/{slug}.html") or None}])


def write(by_meeting: dict, out, today: str) -> dict:
    gathered = gather(by_meeting)
    summary = summarize(gathered, today)
    lo = (date.fromisoformat(today) - timedelta(days=WINDOW_DAYS)).isoformat()
    govs, items = set(), 0
    for county, by_date in by_meeting.items():
        for d, rows in by_date.items():
            if lo <= d <= today and rows:
                govs.add(county)
                items += len(rows)
    counts = {"governments": len(govs), "items": items, "all_governments": len(by_meeting)}
    (out / "at-a-glance.html").write_text(page_glance(summary, today, counts), "utf-8")
    (out / "issues").mkdir(exist_ok=True)
    for slug, xs in gathered.items():
        (out / "issues" / f"{slug}.html").write_text(page_issue(slug, xs, today), "utf-8")
    return {"subjects_shown": [s["slug"] for s in summary], "subject_pages": len(gathered),
            "governments_in_window": len(govs)}
