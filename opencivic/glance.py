# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Florida at a glance: the same subject coming up in many places (the user, Nov 18, 2026: "grouping of similar
measures or measures about similar topics into something eye catching. The purpose is to see what's happening
state wide in just a glance").

    at-a-glance.html          every subject that came up in 3 or more governments in the last 90 days (or on an
                              agenda already posted for the next 60), most places first: how many, which, and a
                              stage word for each; six rule-type subjects are split into kinds (KINDS)
    issues/<slug>.html        one subject since Jan 2025: how it spread, then each government's items, newest first
    feeds/issue-<slug>.xml    one RSS feed per subject (titles only)
    meetings/<gov>.html       gains "Subjects this government took up" (reverse_html)

Stage words (stage_word) come only from recorded votes and meeting dates, never from wording (Nov 18, 2026):
"passed", "passed; more coming up", "coming up", "motion failed", "tie vote", or none (on the agenda). A vote
that passed a motion to deny, or to put an item off, is not "passed" (Nov 19, 2026: North Port's continued
golf-cart ordinance, Fort Lauderdale's tabled protest, Pasco's continued rental hearing). A kind says what an
item is (talks first, laws only with the law's name), and "passed" on a kind means a vote passed on an item of
that kind, not that a law took effect.

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

from .privacy import resident_speaker

WINDOW_DAYS = 90
AHEAD_DAYS = 60     # agendas already posted for the coming weeks count in the window, as "coming up"
MIN_PLACES = 3
SINCE = "2025-01-01"  # subject pages and feeds; Hillsborough's Clerk record reaches back to 2014
KNOWN_DAYS = 365    # "first time in our records" only where a government's records start this long before the window
HEAD = 400          # kinds read the start of the wording: long titles recite whole statutes (Pembroke Park)
TALK_HEAD = 120
# Subjects every government takes up each year: "for the first time" would only find holes in our records
# (Escambia County's 2025 budget hearings aren't in its CivicClerk record; Nov 19, 2026), so it isn't said.
YEARLY = {"property-tax-rates", "legislative-priorities"}

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
        # Seminole County's gym-programs contract with Flock Fitness, LLC (Nov 19, 2026)
        re.compile(r"\bflock fitness\b", re.I)),
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
        # St. Augustine's homeless day-center updates: the presenter is the "Vacation Rental Manager" (Nov 18)
        re.compile(r"\bmicromobility\b|\brentals? manager\b", re.I)),
}


def _text(item: dict) -> str:
    """The item's title only: motion text can be a whole meeting's report (Broward's "Mayor and Commissioner
    Reports ... thank you" motions name a dozen subjects). Hillsborough's titles already carry the motion."""
    return item.get("title") or ""


def subjects(item: dict) -> list[str]:
    """The subjects one agenda item is about (usually none)."""
    t = _text(item)
    if CEREMONY.search(t) or NEVER.search(t) or resident_speaker(item):
        return []
    return [slug for slug, (_, _, inc, exc) in ISSUES.items() if inc.search(t) and not (exc and exc.search(t))]


def _norm(s: str) -> str:
    return re.sub(r"\W+", " ", (s or "").lower()).strip()


# --- kinds within a subject -----------------------------------------------------------------------------------
# Read only the start of the wording (HEAD, TALK_HEAD). Talks come first, so a direction to *draft* a moratorium
# never reads as a moratorium (Hillsborough, Aug 5, 2026), and a law kind needs the law's name (LAW), so a council
# member's agenda item titled "Data Center Moratorium (Mayor Pachota)" isn't one either (Venice). Every item in the
# six subjects since Jan 2025 was read for these rules (Nov 18, 2026; again Nov 19, 2026, 450 items).
TALK = re.compile(
    r"\bdiscuss\w*|\bpresentations?\b|\bworkshops?\b|\bupdates?\b|\breports?\b|\bstud(?:y|ies)\b|\boverview\b|"
    r"\bdirect(?:ed|ion|ing|s)?\b(?! to public hearing)|\bevaluat\w*|\bdraft\w*|\bintent to\b|\bintroduction\b|"
    r"\binitiative\b|\bresearch\b|\binstruct(?:s|ed|ing)?\b|\bfact[- ]finding\b|\bprogress report\b|\bnext steps\b|\bconsider new\b|"
    r"\brecommendations\b|\bschedul(?:e|ing)\b(?: and advertise)?(?: an?| the)? (?:public hearings?|workshop|special meeting)|"
    # an item a member put on the agenda: "Commissioner Smith - 12-Month Data Center Moratorium", "... (Mayor Pachota)"
    r"^\W*(?:vice[- ])?(?:mayor|commissioner|councilmember|council member|councilor)\b|"
    r"\((?:vice[- ])?(?:mayor|commissioner|councilmember|council member|councilor)\b[^)]*\)\s*\.?\s*$", re.I)
LAW = re.compile(r"\bordinances?\b|\bord\b\.?|\bresolutions?\b|\breso\b\.?|\bpublic hearings?\b|\breadings?\b|"
                 r"\bzoning in progress\b|\bmotion to (?:enact|adopt)\b|\btext amendment\b", re.I)
_ORD_FIRST = re.compile(r"^\W*(?:public hearing\W+)?(?:(?:first|second|final|1st|2nd) reading\W+(?:of\W+)?)?(?:an? )?ordinance\b", re.I)

# slug: [(kind, label, rule, needs the law's name)], first match wins; "talk" is checked where it's listed
KINDS: dict[str, list[tuple[str, str, re.Pattern | None, bool]]] = {
    "data-centers": [
        ("talk", "Talks, studies and directions", None, False),
        ("position", "Resolutions stating a position", re.compile(r"\bexpressing (?:support|concern|opposition)|\burging\b|"
                                                                   r"\b(?:supporting|opposing) (?:florida )?(?:senate|house) bill\b", re.I), True),
        ("incentive", "Tax breaks and incentives", re.compile(r"\btax exemptions?\b|\bad valorem\b|\beconomic development grant\b|"
                                                              r"\bincentives?\b|\babatement\b", re.I), False),
        # one project's approvals (Flagler Beach's grounding beds for the DC Blox project), not a rule for all
        ("project", "Single projects", re.compile(r"\bdata cent\w* project\b|\bsite plan\b|\bgrounding beds?\b|"
                                                  r"\bdevelopment agreement\b", re.I), False),
        ("ban", "Bans", re.compile(r"\bprohibit\w*|\bbans?\b|\bpermanent moratorium\b", re.I), True),
        ("pause", "Pauses (moratoriums)", re.compile(r"\bmoratori\w*|\bsuspen(?:d|ding|sion)\b|\bzoning in progress\b|"
                                                     r"\binterim planning\b", re.I), True),
        ("rules", "Zoning and building rules", re.compile(r"\bland development (?:code|regulations)\b|\bLDC\b|\bzoning\b|"
                                                          r"\btext amendment\b|\bclassification of uses\b|\bpermitted\b|"
                                                          r"\bregulat\w*|\bstandards\b|\bdefinitions\b|\bdata cent\w*|"
                                                          r"\bfee schedule\b|\bschedule fee\b", re.I), True),
    ],
    "license-plate-cameras": [
        ("talk", "Talks, reports and directions", None, False),
        ("end", "Ending or limiting cameras", re.compile(r"\bterminat\w*|\bcancel\w*|\brescind\w*|\bremov\w*|\blimitations? on\b|"
                                                         r"\bprohibit\w*", re.I), False),
        ("rules", "Local rules on their use", re.compile(r"(?<!code of )\bordinances?\b|\bpolicy\b", re.I), True),
        ("contract", "Contracts, purchases and permissions", re.compile(
            r"\bagreements?\b|\bcontracts?\b|\bpurchas\w*|\brenew\w*|\bsubscription\b|\bpayment\b|\binterlocal\b|"
            r"\bmemorandum\b|\bupgrade\b|\breplace\w*|\bmaintenance\b|\brequests? for\b|\bexecut\w*|\badditional\b|"
            r"\bservices?\b|\blicense agreement\b", re.I), False),
    ],
    "school-zone-speed-cameras": [
        ("report", "Annual reports", re.compile(r"\bannual (?:summary )?(?:report|summary)\b|\bsummary report\b", re.I), False),
        ("talk", "Talks, studies and directions", None, False),
        # Broward's resolution urging its cities to pass camera ordinances (Apr 22, 2025)
        ("position", "Resolutions stating a position", re.compile(r"\burging\b", re.I), True),
        ("contract", "Contracts and vendors", re.compile(
            r"\bagreements?\b|\bcontracts?\b|\bRFP\b|\bproposals?\b|\bvendor\b|\bbid(?:ding)?\b|\branking\b|"
            r"\bamendment no\b|\bservices\b|\bprotest\b|\butiliz\w*", re.I), False),
        ("rules", "Local laws allowing cameras", re.compile(r"\bordinances?\b|\bcode\b|\bresolutions?\b|\bprogram\b|"
                                                            r"\bspeed detection systems?\b", re.I), True),
    ],
    "e-bikes": [
        ("talk", "Talks, studies and directions", None, False),
        ("state", "Asking the state", re.compile(r"\burging the (?:florida |state )?legislature\b", re.I), True),
        ("rules", "Riding rules and fines", re.compile(r"\bordinances?\b|\bcode amendment\b|\bfines?\b|\bregulat\w*|"
                                                       r"\bprohibit\w*|\bage restriction\b", re.I), True),
    ],
    "golf-carts": [
        ("talk", "Talks, studies and directions", None, False),
        ("event", "Golf carts for one event", re.compile(r"\bwaterfest\b|\btournament\b|\bfestival\b|\bevent\b", re.I), False),
        ("parking", "Parking for golf carts", re.compile(r"\bparking\b", re.I), False),
        # one club's or one company's approval (Palm Beach Country Club, Beache Carts LLC), not a road rule
        ("property", "Single properties and businesses", re.compile(r"\bspecial exception\b|\bsite plan\b|\bvariance\b|"
                                                                    r"\bcertificate of public convenience\b", re.I), False),
        ("rules", "Where golf carts may drive", re.compile(r"\bordinances?\b|\bresolutions?\b|\bdesignat\w*|\bdistrict\b|"
                                                           r"\bcommunity\b|\bpolicy\b|\bpublic roads?\b|\bregulations?\b", re.I), False),
    ],
    "short-term-rentals": [
        ("talk", "Talks, studies and directions", None, False),
        ("fees", "Registration fees", re.compile(r"\bfees?\b|\brates? charged\b|\bbase rate\b", re.I), False),
        ("property", "Single properties", re.compile(r"\bconditional use\b|\bsite plan\b|\bzoning map\b|\brezon\w*|"
                                                     r"\bspecial exception\b|\bparcel\b", re.I), False),
        ("software", "Monitoring software and contracts", re.compile(r"\bsoftware\b|\bRFP\b|\bmonitoring\b|\bcompliance solution\b", re.I), False),
        ("rules", "Registration and rental rules", re.compile(r"\bordinances?\b|\bregistrations?\b|\bregulat\w*|\bcode\b|"
                                                              r"\btext amendment\b|\brequirements\b|\bpermits?\b", re.I), True),
    ],
}
OTHER = ("other", "Other items")


def kind(slug: str, item: dict) -> tuple[str, str]:
    """(kind, label) of one item within a subject; ("other", "Other items") when no rule fits, ("", "") for a
    subject without kinds."""
    if slug not in KINDS:
        return ("", "")
    t = re.sub(r"\s+", " ", _text(item)).strip()
    head = t[:HEAD]
    for k, label, rx, needs_law in KINDS[slug]:
        if k == "talk":
            if TALK.search(t[:TALK_HEAD]):
                return (k, label)
            continue
        if slug == "school-zone-speed-cameras" and k == "contract" and _ORD_FIRST.search(head):
            continue  # an ordinance that names its vendor is still the ordinance
        if rx.search(head) and (not needs_law or LAW.search(head)):
            return (k, label)
    return OTHER


def _stage(row: dict) -> str:
    """One item's stage from its recorded vote only: passed, denied, put off, failed, tied, or agenda."""
    if not row["votes"] or not row["facts"]:
        return "agenda"
    f = row["facts"]
    act = (f.get("action") or "").lower()
    if f.get("passed") is None:
        return "tied" if f.get("yes") and f.get("yes") == f.get("no") else "agenda"
    if not f["passed"]:
        return "failed"
    if act.startswith(("denied", "deny")):
        return "denied"
    if re.match(r"(?:continu|postpon|tabl|defer|withdr)", act):
        return "put off"
    return "passed"


def stage_word(xs: list[dict], today: str) -> str:
    """One government's items (in a subject or a kind): "passed", "passed; more coming up", "coming up",
    "motion failed", "tie vote", or "" (on the agenda). Never from wording."""
    passed = any(x["stage"] == "passed" for x in xs)
    coming = any(x["date"] > today and x["stage"] == "agenda" for x in xs)
    if passed:
        return "passed; more coming up" if coming else "passed"
    if coming:
        return "coming up"
    if any(x["stage"] == "failed" for x in xs):
        return "motion failed"
    if any(x["stage"] == "tied" for x in xs):
        return "tie vote"
    return ""


def _gather_all(by_meeting: dict) -> dict[str, list[dict]]:
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
                    kd, kl = kind(s, r["item"])
                    out[s][k] = {"county": county, "date": d, "row": r, "stage": _stage(r), "kind": kd, "kind_label": kl,
                                 "outcome": outcome(f) if f else "On the agenda; no vote recorded"}
    return {s: sorted(v.values(), key=lambda x: (x["date"], x["county"]), reverse=True) for s, v in out.items()}


def gather(by_meeting: dict, since: str = SINCE) -> dict[str, list[dict]]:
    """slug -> [{county, date, row, stage, kind, kind_label, outcome}] newest first, from `since`; an item listed
    twice in one meeting (each reading or roll call) counts once, a voted row first."""
    return {s: [x for x in xs if x["date"] >= since] for s, xs in _gather_all(by_meeting).items()
            if any(x["date"] >= since for x in xs)}


def starts(by_meeting: dict) -> dict[str, str]:
    """Each government's first meeting date we hold (any item)."""
    return {c: min(v) for c, v in by_meeting.items() if v}


def firsts(by_meeting: dict) -> dict[str, dict[str, str]]:
    """slug -> government -> its first item on the subject in all our records (not only since SINCE)."""
    out: dict[str, dict[str, str]] = defaultdict(dict)
    for s, xs in _gather_all(by_meeting).items():
        for x in xs:
            if x["date"] < out[s].get(x["county"], "9999"):
                out[s][x["county"]] = x["date"]
    return out


def window(today: str) -> tuple[str, str]:
    t = date.fromisoformat(today)
    return (t - timedelta(days=WINDOW_DAYS)).isoformat(), (t + timedelta(days=AHEAD_DAYS)).isoformat()


def summarize(gathered: dict[str, list[dict]], today: str, first: dict | None = None, start: dict | None = None) -> list[dict]:
    """Subjects in 3+ governments in the window (last 90 days and agendas up to 60 days ahead), most governments
    first. first/start (firsts(), starts()) give each subject's governments new to it in our records."""
    lo, hi = window(today)
    known_by = (date.fromisoformat(lo) - timedelta(days=KNOWN_DAYS)).isoformat()
    out = []
    for slug, xs in gathered.items():
        recent = [x for x in xs if lo <= x["date"] <= hi]
        places: dict[str, dict] = {}
        for x in recent:  # newest first, so the first seen is each government's latest
            p = places.setdefault(x["county"], {"county": x["county"], "latest": x, "xs": []})
            p["xs"].append(x)
        for p in places.values():
            p["items"] = len(p["xs"])
            p["stage"] = stage_word(p["xs"], today)
            p["passed"] = any(x["stage"] == "passed" for x in p["xs"])
            # its place among the kinds: its newest item that is more than a talk, else its newest item
            kx = next((x for x in p["xs"] if x["kind"] not in ("talk", "other")), p["xs"][0])
            p["kind"], p["kind_label"] = kx["kind"], kx["kind_label"]
            p["kind_stage"] = stage_word([x for x in p["xs"] if x["kind"] == kx["kind"]], today)
        if len(places) >= MIN_PLACES:
            new = [c for c in places if first and start and slug not in YEARLY
                   and lo <= first.get(slug, {}).get(c, "") and start.get(c, "9999") <= known_by]
            out.append({"slug": slug, "places": sorted(places.values(), key=lambda p: p["latest"]["date"], reverse=True),
                        "items": len(recent), "all": len(xs), "new": new})
    return sorted(out, key=lambda s: (-len(s["places"]), -s["items"], s["slug"]))


def monthly(xs: list[dict], today: str) -> list[tuple[str, int]]:
    """Governments with an item on the subject, per month from SINCE to this month."""
    by: dict[str, set] = defaultdict(set)
    for x in xs:
        if x["date"] <= today:
            by[x["date"][:7]].add(x["county"])
    y, m = int(SINCE[:4]), int(SINCE[5:7])
    out = []
    while f"{y:04d}-{m:02d}" <= today[:7]:
        k = f"{y:04d}-{m:02d}"
        out.append((k, len(by.get(k, ()))))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def spread(xs: list[dict], today: str) -> list[tuple[str, str]]:
    """[(first date since SINCE, government)] in order: when each government first took the subject up."""
    f: dict[str, str] = {}
    for x in xs:
        if x["date"] <= today and x["date"] < f.get(x["county"], "9999"):
            f[x["county"]] = x["date"]
    return sorted((d, c) for c, d in f.items())


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
    cells = "".join(f'<span class="sq{" yes" if p["passed"] else ""}"></span>' for p in places)
    return f'<div class="sqs" aria-hidden="true">{cells}</div>'


def _spark(series: list[tuple[str, int]]) -> str:
    """Governments per month since January 2025, as a small line (decorative: the words around it carry it)."""
    if not series:
        return ""
    w, h, top = 160, 34, max(n for _, n in series) or 1
    step = w / max(len(series) - 1, 1)
    pts = " ".join(f"{i * step:.1f},{h - 2 - (n / top) * (h - 4):.1f}" for i, (_, n) in enumerate(series))
    return (f'<svg class="spark" width="{w}" height="{h}" viewBox="0 0 {w} {h}" aria-hidden="true" focusable="false">'
            f'<polyline points="{pts}" fill="none" stroke="currentColor" stroke-width="2"/></svg>')


def _name(slug: str, p: dict, stage: str, up: str = "") -> str:
    return (f'<a href="{up}issues/{_e(slug)}.html#{_e(p["county"])}">{_e(_gov(p["county"]))}</a>'
            + (f" ({_e(stage)})" if stage else ""))


def _card_places(slug: str, places: list[dict]) -> str:
    if slug not in KINDS:
        return f'<p class="places">{", ".join(_name(slug, p, p["stage"]) for p in places)}.</p>'
    order = [k for k, *_ in KINDS[slug]] + [OTHER[0]]
    labels = {k: lab for k, lab, *_ in KINDS[slug]} | {OTHER[0]: OTHER[1]}
    groups: dict[str, list[dict]] = defaultdict(list)
    for p in places:
        groups[p["kind"]].append(p)
    rows = "".join(
        f'<li><span class="kind">{_e(labels[k])}</span> ({len(groups[k])}): '
        f'{", ".join(_name(slug, p, p["kind_stage"]) for p in groups[k])}</li>'
        for k in sorted(groups, key=lambda k: (k == "talk", k == OTHER[0], order.index(k))))
    return f'<ul class="kinds places">{rows}</ul>'


def page_glance(summary: list[dict], today: str, counts: dict) -> str:
    from .site import absolute, long_date, page
    lo, hi = window(today)
    tiles = "".join(
        f'<li><a href="#{_e(s["slug"])}"><span class="big">{len(s["places"])}</span>'
        f'<span class="lbl">{_e(ISSUES[s["slug"]][0])}<span class="vh"> ({len(s["places"])} governments)</span></span></a></li>'
        for s in summary)
    cards = []
    for s in summary:
        slug = s["slug"]
        title, what, _, _ = ISSUES[slug]
        n, passed = len(s["places"]), sum(p["passed"] for p in s["places"])
        coming = sum(1 for p in s["places"] if "coming up" in p["stage"])
        nc = _counties(s["places"])
        new = len(s["new"])
        newline = (f" {new} of them took it up for the first time in our records, which for each go back at least a "
                   "year before that." if new else "")
        cards.append(f"""<section class="issue" id="{_e(slug)}" aria-labelledby="{_e(slug)}-h">
<h2 id="{_e(slug)}-h"><span class="big">{n}</span> {_e(title)}<span class="vh">: {n} governments</span></h2>
<p>{_e(what)}</p>
<p class="small">{n} governments in {nc} {"county" if nc == 1 else "counties"},
{s["items"]} agenda {"item" if s["items"] == 1 else "items"}; a vote passed in {passed} of them{f", and {coming} have it on an agenda still to come" if coming else ""}.{newline}</p>
{_squares(s["places"])}
{_card_places(slug, s["places"])}
<p class="more">{_spark(s["series"])} <a href="issues/{_e(slug)}.html">How it spread, and every item since January 2025</a> ({s["all"]})
· <a href="feeds/issue-{_e(slug)}.xml">Follow this subject (RSS feed)</a></p>
</section>""")
    key = ('<p class="key small"><span><span class="sq yes" aria-hidden="true"></span> a vote passed</span> '
           '<span><span class="sq" aria-hidden="true"></span> on the agenda; no vote recorded (or not yet)</span></p>')
    body = f"""<h1>Florida at a glance</h1>
<p class="role">The same subjects coming up across the state, {_e(long_date(lo))} to {_e(long_date(today))}, and on
agendas already posted through {_e(long_date(hi))}</p>
<p class="lede">In the last {WINDOW_DAYS} days, <mark>{counts["governments"]} of the local governments we follow</mark>
put {counts["items"]:,} items on their agendas. These subjects came up in {MIN_PLACES} or more places.</p>
<p class="fair">Each square is one city or county government, filled where a vote passed. Each name opens that
government's items on the subject. A word after a name says where it stands, read only from recorded votes and
meeting dates: <strong>passed</strong> (a vote passed), <strong>coming up</strong> (on an agenda for a meeting still to
come), <strong>motion failed</strong> or <strong>tie vote</strong>; no word means it was on an agenda and no vote is
recorded online, which for many governments we follow is always the case. Subjects are found by fixed rules that
read each item's official wording; they say what an item is about, never whether a decision was right.
<a href="#how">How this works</a>.</p>
<p class="small" id="tiles-h">Number of governments that took up each subject:</p>
<ul class="tiles" role="list" aria-labelledby="tiles-h">{tiles}</ul>
{key}
{"".join(cards)}
<h2 id="how">How this works</h2>
<p>Every agenda item from the {counts["all_governments"]} governments we follow is read against a fixed list of subjects,
each a set of words in the official wording, with exceptions found by reading real items: a county's own server
room isn't a data center decision, and buying a golf cart isn't a golf-cart rule. Proclamations and awareness
weeks don't count, and neither do residents' own requests. An item can be about more than one subject. The list was
drawn up on November 18, 2026 from the phrases that appeared in the most governments' agendas; subjects with fewer
than {MIN_PLACES} governments in the last {WINDOW_DAYS} days (or on agendas posted for the next {AHEAD_DAYS}) aren't shown here
but keep their own pages. The rules can miss an item or, rarely, include one that doesn't fit.
<a href="https://github.com/bgraham1214/open-civic/issues">Report a mistake</a>.</p>
<p>Some subjects are split into kinds, also by fixed rules over the start of the wording: talks, studies and
directions to staff are kept apart from laws, and an item counts as a pause or a ban only when it names an
ordinance or resolution. Each government is listed once, under the kind of its newest item that is more than a
talk. <strong>"Passed" means a vote passed on an item of that kind, not that a law took effect</strong>: many
ordinances need two readings, and a vote to deny, or to put an item off to a later meeting, is not counted as
passed. "For the first time" counts only governments whose records with us start at least a year earlier.</p>
<p>Only governments we collect are counted: see <a href="florida.html">what we cover in Florida</a>. A subject
missing here may be on agendas we can't read.</p>"""
    desc = ("Which subjects are coming up across Florida's local governments right now: data centers, license-plate "
            "cameras, property taxes and more, with every city and county that took each one up.")
    return page("Florida at a glance: the same subjects across local governments", body, 0, path="at-a-glance.html",
                description=desc, here="Florida at a glance",
                feeds=[(f"Florida at a glance: {ISSUES[s['slug']][0]}", f"feeds/issue-{s['slug']}.xml") for s in summary],
                jsonld=[{"@type": "CollectionPage", "name": "Florida at a glance", "description": desc,
                         "url": absolute("at-a-glance.html") or None}])


def spread_text(sp: list[tuple[str, str]], today: str) -> str:
    from .site import long_date
    if not sp:
        return ""
    lo, _ = window(today)
    before = sum(1 for d, _ in sp if d < lo)
    out = f"The first item we hold since January 2025 is from {_gov(sp[0][1])}, on {long_date(sp[0][0])}."
    if len(sp) > 1:
        recent = len(sp) - before
        out += (f" By {long_date(today)}, {len(sp)} governments had put it on an agenda since then"
                + (f"; {recent} of them first did so in the last {WINDOW_DAYS} days." if recent else "."))
    return out


def _timeline(sp: list[tuple[str, str]], today: str) -> str:
    """Governments that had taken the subject up, over time (a step line), last 90 days shaded. Decorative: the
    sentence above it and the table below it carry the same facts."""
    if len(sp) < 2:
        return ""
    w, h, l, r, t, b = 400, 210, 34, 10, 12, 30
    d0, d1 = date.fromisoformat(SINCE), date.fromisoformat(today)
    span = max((d1 - d0).days, 1)

    def x(d: str) -> float:
        return l + (date.fromisoformat(d) - d0).days / span * (w - l - r)

    top = len(sp)
    def y(n: int) -> float:
        return h - b - n / top * (h - t - b)
    pts, n = [f"{l:.1f},{y(0):.1f}"], 0
    for d, _ in sp:
        pts.append(f"{x(d):.1f},{y(n):.1f}")
        n += 1
        pts.append(f"{x(d):.1f},{y(n):.1f}")
    pts.append(f"{x(today):.1f},{y(n):.1f}")
    lo, _ = window(today)
    shade = f'<rect class="tl-recent" x="{x(lo):.1f}" y="{t}" width="{x(today) - x(lo):.1f}" height="{h - t - b}"/>'
    ticks = "".join(f'<text class="tl-lab" x="{x(f"{yy}-01-01"):.1f}" y="{h - 10}" text-anchor="middle">{yy}</text>'
                    for yy in range(d0.year, d1.year + 1) if f"{yy}-01-01" <= today)
    axis = (f'<line class="tl-axis" x1="{l}" y1="{h - b}" x2="{w - r}" y2="{h - b}"/>'
            f'<text class="tl-lab" x="{l - 6}" y="{y(top) + 5:.1f}" text-anchor="end">{top}</text>'
            f'<text class="tl-lab" x="{l - 6}" y="{y(0) + 5:.1f}" text-anchor="end">0</text>')
    return (f'<svg class="tl" viewBox="0 0 {w} {h}" aria-hidden="true" focusable="false">{shade}{axis}{ticks}'
            f'<polyline class="tl-line" points="{" ".join(pts)}" fill="none"/></svg>')


def page_issue(slug: str, xs: list[dict], today: str, start: dict | None = None) -> str:
    from .people import plain, record_link
    from .site import absolute, long_date, page
    title, what, _, _ = ISSUES[slug]
    start = start or {}
    by_gov: dict[str, list[dict]] = defaultdict(list)
    for x in xs:
        by_gov[x["county"]].append(x)
    order = sorted(by_gov, key=lambda g: (max(x["date"] for x in by_gov[g]), g), reverse=True)

    def li(x: dict) -> str:
        r = x["row"]
        k = f'<p class="kind small">Kind: {_e(x["kind_label"])}</p>' if x["kind"] else ""
        when = " (coming up)" if x["date"] > today and x["stage"] == "agenda" else ""
        return (f'<li><p class="when"><a href="../meetings/{_e(x["county"])}/{_e(x["date"])}.html">'
                f'{_e(long_date(x["date"]))}</a>{when}</p>' + k + plain(r["item"], 1, r["facts"] if r["votes"] else None)
                + f'<p class="outcome">{_e(x["outcome"])}.</p>' + record_link(r["item"]) + "</li>")

    sections = []
    for g in order:
        items = by_gov[g]
        sw = stage_word(items, today)
        head = (f'<h2 id="{_e(g)}-h">{_e(_gov(g))} <span class="topic-count">({len(items)})</span></h2>'
                + (f'<p class="small">Where it stands: {_e(sw)}.</p>' if sw else ""))
        first, rest = items[:3], items[3:]
        more = (f'<details><summary>Show all {len(items)} items</summary><ol class="decisions" start="4">'
                f'{"".join(li(x) for x in rest)}</ol></details>' if rest else "")
        sections.append(f'<section id="{_e(g)}" aria-labelledby="{_e(g)}-h">{head}'
                        f'<ol class="decisions">{"".join(li(x) for x in first)}</ol>{more}</section>')
    passed = sum(1 for x in xs if x["stage"] == "passed")
    sp = spread(xs, today)
    rows = "".join(f'<tr><th scope="row"><a href="#{_e(c)}">{_e(_gov(c))}</a></th><td>{_e(long_date(d))}</td>'
                   f'<td>{_e(long_date(start[c])) if c in start else ""}</td></tr>' for d, c in sp)
    how = ""
    if sp:
        how = f"""<h2 id="spread">How it spread</h2>
<figure class="tl-fig">
<p>{_e(spread_text(sp, today))}</p>
{_timeline(sp, today)}
<figcaption class="small">Number of governments that had put it on an agenda, from January 2025 to {_e(long_date(today))};
the shaded part is the last {WINDOW_DAYS} days. A government's line starts at the first item we hold, which can be
later than its first item ever: our records for most governments start in January 2025, and for a few later.</figcaption>
</figure>
<details><summary>When each government first took it up</summary>
<table class="tl-table"><caption class="vh">When each government first took it up</caption>
<thead><tr><th scope="col">Government</th><th scope="col">First item since January 2025</th><th scope="col">Our records start</th></tr></thead>
<tbody>{rows}</tbody></table></details>"""
    kinds = ""
    if slug in KINDS:
        labels = [lab for _, lab, *_ in KINDS[slug]] + [OTHER[1]]
        kinds = (f'<p class="small">Each item is marked with its kind: {_e(", ".join(labels))}. "Passed" means a '
                 'vote passed on that item, not that a law took effect.</p>')
    body = f"""<h1>{_e(title)}</h1>
<p class="role">{_e(what)}</p>
<p class="lede"><mark>{len(by_gov)} {"government" if len(by_gov) == 1 else "governments"}</mark> we follow put
{len(xs)} {"item" if len(xs) == 1 else "items"} about this on their agendas since January 2025; a vote passed on {passed}.</p>
<p class="fair">Found by fixed rules from each item's official wording (<a href="../at-a-glance.html#how">how</a>).
Newest first, by government. "On the agenda" means no vote is recorded online, which for many governments we
follow is always the case. <a href="../feeds/issue-{_e(slug)}.xml">Follow this subject (RSS feed)</a>.</p>
{kinds}
{how}
{"".join(sections)}"""
    return page(f"{title} across Florida local governments", body, 1, path=f"issues/{slug}.html",
                crumbs=[("Florida at a glance", "at-a-glance.html")], here=title,
                feeds=[(f"Florida at a glance: {title}", f"feeds/issue-{slug}.xml")],
                description=f"{title}: every agenda item from the Florida local governments we follow since January 2025. {what}",
                jsonld=[{"@type": "CollectionPage", "name": f"{title} across Florida local governments",
                         "url": absolute(f"issues/{slug}.html") or None}])


def feed(slug: str, xs: list[dict], rss) -> str:
    """The newest 100 items on one subject. Titles only: memo text never goes into a subject feed, and names the
    privacy rules find show as [name left out], as in every feed (Nov 19, 2026: a guest speaker, a presenter)."""
    from email.utils import format_datetime
    from .privacy import scrub_text
    from datetime import datetime, timezone
    from .jurisdictions import JURISDICTIONS
    from .site import absolute
    title = ISSUES[slug][0]
    entries = []
    for x in xs[:100]:
        it = x["row"]["item"]
        j = JURISDICTIONS.get(x["county"], {})
        words = scrub_text(re.sub(r"\s+", " ", _text(it)).strip(), addresses=False)
        head = words if len(words) <= 110 else words[:110].rsplit(" ", 1)[0] + "…"
        y, m, d = (int(v) for v in x["date"].split("-"))
        kd = f"Kind: {x['kind_label']}. " if x["kind"] else ""
        entries.append({"title": f"{j.get('short') or _gov(x['county'])}: {head}",
                        "link": absolute(f"meetings/{x['county']}/{x['date']}.html"),
                        "guid": f"{it['key']}|issue|{slug}",
                        "pub": format_datetime(datetime(y, m, d, 12, tzinfo=timezone.utc)),
                        "desc": f"{j.get('board') or _gov(x['county'])}, {x['date']}. {kd}{x['outcome']}. {words[:600]}"})
    return rss(f"Florida at a glance: {title}", absolute(f"issues/{slug}.html"),
               f"Agenda items about {title.lower()} across the Florida local governments we follow, found by fixed "
               "rules; see at-a-glance.html#how.", entries)


def by_government(gathered: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """government -> [{slug, items, latest}] most recent subject first."""
    out: dict[str, dict[str, dict]] = defaultdict(dict)
    for slug, xs in gathered.items():
        for x in xs:
            e = out[x["county"]].setdefault(slug, {"slug": slug, "items": 0, "latest": x["date"]})
            e["items"] += 1
            e["latest"] = max(e["latest"], x["date"])
    return {c: sorted(v.values(), key=lambda e: (e["latest"], e["slug"]), reverse=True) for c, v in out.items()}


def reverse_html(county: str, subs: list[dict]) -> str:
    """'Subjects this government took up', for its meetings index page (one folder down)."""
    from .site import long_date
    if not subs:
        return ""
    lis = "".join(f'<li><a href="../issues/{_e(e["slug"])}.html#{_e(county)}">{_e(ISSUES[e["slug"]][0])}</a>: '
                  f'{e["items"]} {"item" if e["items"] == 1 else "items"}, latest {_e(long_date(e["latest"]))}</li>'
                  for e in subs)
    return (f'<h2 id="subjects">Subjects this government took up</h2>'
            f'<p class="small">From <a href="../at-a-glance.html">Florida at a glance</a>: subjects that come up across the '
            f'state, found by fixed rules from the official wording, since January 2025.</p><ul class="links">{lis}</ul>')


def write(by_meeting: dict, out, today: str, rss=None, gathered: dict | None = None) -> dict:
    gathered = gather(by_meeting) if gathered is None else gathered
    start, first = starts(by_meeting), firsts(by_meeting)
    summary = summarize(gathered, today, first, start)
    for s in summary:
        s["series"] = monthly(gathered[s["slug"]], today)
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
        (out / "issues" / f"{slug}.html").write_text(page_issue(slug, xs, today, start), "utf-8")
    feeds = 0
    if rss:
        (out / "feeds").mkdir(exist_ok=True)
        for slug, xs in gathered.items():
            (out / "feeds" / f"issue-{slug}.xml").write_text(feed(slug, xs, rss), "utf-8")
            feeds += 1
    return {"subjects_shown": [s["slug"] for s in summary], "subject_pages": len(gathered),
            "governments_in_window": len(govs), "feeds": feeds}
