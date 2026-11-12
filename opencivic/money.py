# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Public money to companies: who the governments we follow agreed to pay, from the decisions themselves.

Built from the same decisions as the meeting pages (meetings.decisions_by_meeting): every agenda item
whose wording names a company or organization (Inc, LLC, Corp, Company, LP, P.A., ...) together with a
dollar amount, where the money goes from the government to the company (a contract, award, purchase,
task or change order, grant or incentive). Rezoning applicants and companies that pay the government
(leases of public land, franchise fees, grants received) are listed on a company's page but never
counted as money paid to it.

What the amounts are: the figure the agenda wording names for that company, usually a contract's
not-to-exceed ceiling. They are what a board approved, not what was paid; payment records aren't
collected (the user's call, Nov 12, 2026). Totals count only approved decisions.

"Worth a second look" flags state plain facts in the record (Claude's selection, the user's
delegation, Nov 12, 2026). None says anything improper happened, and none names a person:
  no-bid     sole source, single source, emergency purchase, or exempt from competitive bidding
  added      more money added to an existing contract (change order, amendment, added authority)
  split      approved over at least one no vote
  consent    $1 million or more approved on the consent agenda (in one vote with routine items),
             where the record marks consent items (Edgewater, Hernando, Pasco)
  conflict   a member abstained or was recused, citing a conflict of interest (Florida law requires
             it when a vote would benefit them or a relative or business associate)

Pages: companies.html (index, flags, how it works) and companies/<slug>.html (one per company paid).
"""

from __future__ import annotations

import html
import re
from collections import defaultdict
from pathlib import Path

from .explain import dollars, money
from .jurisdictions import JURISDICTIONS

# Like explain.COMPANY_RX, with more joining words, so "Area Agency on Aging of Pasco-Pinellas, Inc."
# stays whole instead of becoming "Aging of Pasco-Pinellas, Inc.".
PAYEE_RX = re.compile(
    r"((?:(?:[A-Z][\w&.'’/-]*|\d+[A-Za-z][\w&.'’/-]*|&|of|and|for|the|on|at|in|de|del|la)\s){0,10}?[A-Z][\w&.'’-]*,?\s"
    r"(?:Inc|Incorporated|LLC|L\.L\.C|Corp|Corporation|Company|Co|LP|L\.P|LLP|LLLP|P\.A|PA|PLLC|Ltd|N\.A)\.?)(?=\W|$)")
SUFFIXES = r"(?:inc|incorporated|llc|l\.l\.c|corp|corporation|company|co|lp|l\.p|llp|lllp|p\.a|pa|pllc|ltd|n\.a)\.?"
# Words that start a sentence or a clause, not a name.
LEAD_WORDS = re.compile(
    r"^(?:(?:award(?:ed)?|approv\w*|authoriz\w*|execut\w*|enter\w*|accept\w*|agreement|contract|with|to|and|from|"
    r"by|between|the|for|of|a|an|on|in|at|vendor|consultant|contractor|firm|company|provider|purchase|utilization|"
    r"amendment|change|order|task|renewal|extension|piggyback|including|plus|per|via|use|dba|d/b/a|"
    r"as[- ]needed|select\w*|rank\w*|highest[- ]ranked|annual|term|continuing|exempt|ratif\w*|funding|"
    r"sole|single|source|emergency|cooperative|multiple|budget|resolution|"
    r"first|second|third|fourth|fifth|no\.?|number|and/or|its|their|that|this|which|subject)\s+)+", re.I)
# A person introduced before the company ("Mark Keschl of Meridien Development, LLC"): keep the company only.
PERSON_OF = re.compile(r"^(?:Mr\.|Ms\.|Mrs\.|Dr\.)?\s*[A-Z][a-z]+(?:\s[A-Z]\.)?\s[A-Z][a-z'’-]+\s(?:of|with|for|representing)\s")
NOT_COMPANY = re.compile(
    r"^(?:hills\.?|hillsborough|pasco|hernando|volusia|pinellas|polk|citrus|sumter|manatee)(?:\s+co\.?|\s+county)\b|"
    r"\bcounty(?: of)?$|^(?:city|town|state|county|school|board|department|florida department|united states)\b|"
    r"^(?:the )?(?:[A-Z]\w*\s)?(?:co|inc|llc)\.?$", re.I)

OUT_RX = re.compile(
    r"\b(?:award\w*|contract\w*|agreement\w*|purchas\w*|task order|change order|work order|services?|construction|"
    r"design|consult\w*|engineer\w*|grant (?:agreement )?(?:to|with)|subrecipient|funding (?:agreement|for)|"
    r"payment to|pay\b|incentive|amendment|renewal|extension|piggyback|utiliz\w+|acquir\w+|acquisition|"
    r"lease (?:agreement )?(?:with|from)\b.{0,80}\blandlord|not[- ]to[- ]exceed|expenditure|cost)\b", re.I)
IN_RX = re.compile(
    r"\b(?:revenue|grant (?:award )?from|accept\w*\b[^.]{0,50}\b(?:grant|donation|funds|payment|check|offer)|"
    r"receiv\w+ (?:a |the )?(?:grant|funds|payment|donation)|franchise|sale of (?:county|city|surplus)|surplus|"
    r"lease (?:of|for) (?:county|city)[- ]owned|(?:county|city) as (?:landlord|lessor)|pay(?:s|ing)? the (?:county|city)|"
    r"reimburs\w+ (?:to )?the (?:county|city)|donat\w+ to the (?:county|city)|"
    r"release of (?:the )?(?:maintenance |performance |site |utility )*(?:guarantee|bond|surety|security)|"
    r"(?:county|city)[- ]owned (?:real )?(?:property|land|parcel)|revenue to (?:the )?(?:county|city)|"
    r"(?:rezon\w*|zoning|planned development|variance|plat|vacat\w+|special use|conditional use|site plan)\b)", re.I)

NO_BID_RX = re.compile(r"\bsole[- ]source|\bsingle[- ]source|\bexempt\w* from (?:the )?competitive|"
                       r"\bwithout competitive (?:bid|solicit)|\bno-bid\b|\bemergency (?:purchase|procurement|repair|contract)|"
                       r"\bexempt purchase", re.I)
ADDED_RX = re.compile(r"\bchange (?:order|directive)\b|\badditional (?:purchase |spending |contract )?(?:authority|funding|funds)\b|"
                      r"\bincreas\w+ (?:the )?(?:existing )?(?:contract|purchase|not[- ]to[- ]exceed|spending|compensation|amount)|"
                      r"\b(?:amendment|modification)\b[^.]{0,120}\b(?:increas|additional|add)\w*", re.I)
CONSENT_FLOOR = 1_000_000
# A close-out restates a contract's final total; counting it again would double the award.
CLOSEOUT_RX = re.compile(r"\bclose[- ]?out\b|\bfinal (?:payment|acceptance)\b|\brelease of retainage\b", re.I)
# Buying power, water or phone service from the utility is exempt from bidding by nature; not flagged.
UTILITY_SERVICE_RX = re.compile(r"\b(?:electric|electrical|power|natural gas|water|sewer|telephone|utility) service\b", re.I)

FLAGS = {
    "no-bid": ("No competitive bidding", "The wording says the purchase was sole source, single source, an emergency "
               "purchase, or exempt from competitive bidding. These can be legal and necessary; they're also where "
               "price and choice get the least outside checking."),
    "added": ("Money added to an existing contract", "A change order, amendment or added spending authority on a "
              "contract approved earlier."),
    "split": ("Approved over a no vote", "At least one member voted no."),
    "consent": ("$1 million or more on the consent agenda", "Approved in one vote together with routine items, "
                "without its own discussion. Only some governments' records mark consent items (Edgewater, "
                "Hernando, Pasco)."),
    "conflict": ("A member stepped aside for a conflict of interest", "A member abstained or was recused, citing a "
                 "conflict of interest. Florida law requires this when a vote would benefit the member or a relative "
                 "or business associate (Fla. Stat. 112.3143)."),
}
FLAG_ORDER = list(FLAGS)


def _e(s: str) -> str:
    return html.escape(str(s or ""), quote=True)


def clean_name(raw: str) -> str:
    """'Award to Comanco Environmental Corporation' -> 'Comanco Environmental Corporation';
    'Mark Keschl of Meridien Development, LLC' -> 'Meridien Development, LLC'. '' when it isn't a company."""
    n = re.sub(r"\s+", " ", raw).strip(" ,;:–-")
    n = PERSON_OF.sub("", n)
    prev = None
    while prev != n:
        prev = n
        n = LEAD_WORDS.sub("", n).strip(" ,;:–-")
        n = re.sub(r"^(?:(?:inc|llc|corp|co)\.?,?\s+(?:and\s+)?|[a-z]\s+|&\s*|[\d,.]+\s+)", "", n, flags=re.I)
        n = re.split(r"\s(?:[–-]|from|with|w/|to|by|between|and/or)\s(?=[A-Z])", n, flags=re.I)[-1]
    n = re.sub(r",?\s+a\s+(?:Florida|Delaware|foreign)\s.*$", "", n).strip(" ,")
    if len(n) < 5 or len(n) > 80 or NOT_COMPANY.search(n) or not re.search(SUFFIXES + r"$", n, re.I):
        return ""
    if len(re.sub(SUFFIXES + "$", "", n, flags=re.I).strip(" ,").split()) < 1:
        return ""
    return n


def key(name: str) -> str:
    """One company however it's spelled: 'Lennar Homes, LLC' and 'Lennar Homes LLC' -> 'lennar homes'."""
    k = name.lower().replace("&", " and ").replace("’", "'")
    k = re.sub(r"\bu\.?\s?s\.?\b", "us", k)
    k = re.sub(r"[.,'()]", " ", k)
    k = re.sub(r"\b(?:inc|incorporated|llc|l l c|corp|corporation|company|co|lp|l p|llp|lllp|p a|pa|pllc|ltd|n a|the)\b", " ", k)
    return re.sub(r"\s+", " ", k).strip()


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", key(name)).strip("-")[:70] or "company"


def payees(text: str) -> list[tuple[str, int, int]]:
    """[(name, start, end)] of each company named, in order, first mention only."""
    out, seen = [], set()
    for m in PAYEE_RX.finditer(text):
        n = clean_name(m.group(1))
        if n and key(n) not in seen:
            seen.add(key(n))
            at = m.group(1).find(n)  # where the cleaned name starts; the raw match can begin inside "$2,433,000 and"
            out.append((n, m.start(1) + max(at, 0), m.end()))
    return out


def amount_for(text: str, names: list[tuple[str, int, int]], i: int) -> float | None:
    """The figure that belongs to the i-th company: the first dollar amount after its name and before the
    next company's; with one company, the first amount after it, else the first in the text."""
    end = names[i][2]
    stop = names[i + 1][1] if i + 1 < len(names) else len(text)
    if len(names) > 1 and len(money(text)) < len(names):
        each = re.search(r"\$\s?[\d,.]+(?:\s?(?:million|billion))?\s+each\b", text, re.I)
        if each and len(money(text)) == 1:
            return money(text)[0]  # "... in amt of $4 million each"
        return None  # a joint agreement: one total for several parties, nobody's share is stated
    after = money(text[end:stop])
    if after:
        return after[0]
    if len(names) == 1:
        found = money(text)
        return found[0] if found else None
    return None


def direction(text: str) -> str:
    """'out' (government pays), 'in' (company pays, or an applicant), or ''."""
    if IN_RX.search(text) and not re.search(r"\b(?:award|task order|change order|purchase order|services agreement)\b", text, re.I):
        return "in"
    return "out" if OUT_RX.search(text) else ""


def flags_for(item: dict, votes: list[dict], facts: dict | None, amount: float | None, text: str) -> list[str]:
    out = []
    if NO_BID_RX.search(text) and not UTILITY_SERVICE_RX.search(text):
        out.append("no-bid")
    if ADDED_RX.search(text):
        out.append("added")
    if facts and facts.get("passed") and facts.get("no"):
        out.append("split")
    if item.get("consent") and (amount or 0) >= CONSENT_FLOOR:
        out.append("consent")
    if any(re.search(r"conflict|recus", v.get("vote") or "", re.I) for v in votes):
        out.append("conflict")
    return out


def collect(by_meeting: dict[str, dict[str, list[dict]]]) -> dict[str, dict]:
    """key -> {name, names: {spelling: n}, rows: [...]} from meetings.decisions_by_meeting."""
    companies: dict[str, dict] = {}
    for county, by_date in by_meeting.items():
        for d, rows in by_date.items():
            for r in rows:
                it = r["item"]
                text = re.sub(r"\s+", " ", " ".join(x for x in (it["title"], it.get("motion") or "",
                                                                    it.get("action_text") or "") if x))
                names = payees(text)
                if not names or not money(text):
                    continue
                way = direction(text)
                for i, (n, _, _) in enumerate(names):
                    amt = amount_for(text, names, i)
                    c = companies.setdefault(key(n), {"names": defaultdict(int), "rows": []})
                    c["names"][n] += 1
                    c["rows"].append({"county": county, "date": d, "row": r, "amount": amt, "direction": way,
                                      "shared": len(names) > 1, "counted": not CLOSEOUT_RX.search(text),
                                      "flags": flags_for(it, r["votes"], r["facts"], amt, text) if way == "out" else []})
    for k, c in companies.items():
        c["name"] = max(c["names"].items(), key=lambda kv: (kv[1], -len(kv[0])))[0]
        c["rows"].sort(key=lambda x: (x["date"], x["row"]["item"]["key"]), reverse=True)
        paid = [x for x in c["rows"] if x["direction"] == "out"]
        approved = [x for x in paid if x["row"]["facts"] and x["row"]["facts"].get("passed")]
        c["paid"] = paid
        c["approved_total"] = sum(x["amount"] or 0 for x in approved if x["counted"])
        c["approved_n"] = len(approved)
        c["governments"] = sorted({x["county"] for x in paid})
        c["latest"] = paid[0]["date"] if paid else ""
    return {k: c for k, c in companies.items() if c["paid"]}


def _slugs(companies: dict[str, dict]) -> dict[str, str]:
    out, used = {}, defaultdict(int)
    for k in sorted(companies, key=lambda k: (-companies[k]["approved_total"], k)):
        s = slug(companies[k]["name"])
        used[s] += 1
        out[k] = s if used[s] == 1 else f"{s}-{used[s]}"
    return out


def _gov(county: str) -> str:
    return JURISDICTIONS[county]["short"]


def _flag_tags(flags: list[str], depth: int) -> str:
    if not flags:
        return ""
    up = "../" * depth
    return ('<p class="spot">' + " ".join(
        f'<a class="tag look" href="{up}companies.html#how" title="{_e(FLAGS[f][1])}">{_e(FLAGS[f][0])}</a>'
        for f in flags) + "</p>")


def decision_html(x: dict, depth: int, show_company: str = "", company_href: str = "") -> str:
    from .meetings import _vote_line
    from .people import long_date, plain, record_link
    r, it = x["row"], x["row"]["item"]
    up = "../" * depth
    j = JURISDICTIONS[x["county"]]
    meeting = f'{up}meetings/{x["county"]}/{x["date"]}.html'
    amt = ""
    if x["amount"]:
        amt = (f'<p class="amount">{_e(dollars(x["amount"]))}'
               + (" (this company's share, as the wording lists it)" if x["shared"] else "")
               + (" (a close-out: the contract's final total, not added to the total again)" if not x["counted"] else "")
               + "</p>")
    elif x["direction"] == "out":
        amt = '<p class="amount">Amount not stated for this company in the wording.</p>'
    who = (f'<p class="title"><a href="{company_href}">{_e(show_company)}</a></p>' if show_company and company_href
           else f'<p class="title">{_e(show_company)}</p>' if show_company else "")
    vote = _vote_line(r) if r["votes"] else ('<p class="outcome">On the agenda; no vote recorded.</p>')
    return (f'<li>{who}<p class="when"><a href="{meeting}">{_e(long_date(it["date"]))}, {_e(j["board"])}</a></p>'
            + _flag_tags(x["flags"], depth) + amt + plain(it, depth, r["facts"]) + vote + record_link(it) + "</li>")


HOW = """<section id="how" aria-labelledby="h-how"><h2 id="h-how">How this works</h2>
<p>Every agenda item on this site whose official wording names a company or organization (a name ending in
Inc., LLC, Corp., Company, P.A. and similar) together with a dollar amount is read by fixed rules, not AI.
When the money goes from the government to the company (a contract, award, purchase, task order, change order,
grant or incentive), the decision is listed on the company's page.</p>
<ul>
<li><strong>Amounts are what a board approved, not what was paid.</strong> They're the figure the wording
names for that company, usually a contract's ceiling ("not to exceed"). A contract can end up costing less, or
more after change orders. Payment records aren't collected yet.</li>
<li><strong>Totals count only decisions that passed.</strong> Items still on an agenda, or that failed, are
listed but not counted.</li>
<li>When one item names several companies, each gets the amount written after its name; if the wording
doesn't say, no amount is counted for it.</li>
<li>A contract's close-out or final payment restates its final total, so it's listed but not added again.</li>
<li>Spellings are joined ("Lennar Homes, LLC" and "Lennar Homes LLC" are one company). Different companies
with similar names stay separate. A company's own name is all we match on, so a company that changed its name
appears twice.</li>
<li>Companies that pay the government (leases of public land, franchise fees) and builders asking for a
rezoning are not counted as being paid.</li>
<li>Many agendas don't name the company in the item's title (Edgewater's often don't); those decisions
aren't here yet.</li>
</ul>
<h3>Worth a second look</h3>
<p>These tags state plain facts from the official record. <strong>None of them means anything improper
happened</strong>, and none of them is about a person. They mark the decisions people most often want to
read closely.</p>
<dl>{flags}</dl>
<p>Each decision links to the official record. If something here is wrong, <a href="{repo}/issues">tell us</a>.</p>
</section>"""


def _compact(x: dict, slugs: dict[str, str]) -> str:
    """One line for an older flagged decision, linking to its company's page."""
    from . import site
    flags = ", ".join(FLAGS[f][0].lower() for f in x["flags"])
    return (f'<li><a href="companies/{slugs[x["ck"]]}.html">{_e(x["company"])}</a>: '
            f'{_e(dollars(x["amount"])) + ", " if x["amount"] else ""}{_e(_gov(x["county"]))}, '
            f'{_e(site.long_date(x["date"]))} ({_e(flags)})</li>')


def index_html(companies: dict[str, dict], slugs: dict[str, str]) -> str:
    from . import site
    ranked = sorted(companies, key=lambda k: (-companies[k]["approved_total"], companies[k]["name"].lower()))
    rows = []
    for k in ranked:
        c = companies[k]
        n_flags = sum(1 for x in c["paid"] for _ in x["flags"])
        rows.append(
            f'<li data-name="{_e(c["name"].lower())}"><p class="title"><a href="companies/{slugs[k]}.html">{_e(c["name"])}</a></p>'
            f'<p>{_e(dollars(c["approved_total"]) if c["approved_total"] else "No amount counted")} approved in '
            f'{c["approved_n"]:,} {"decision" if c["approved_n"] == 1 else "decisions"} · '
            f'{_e(", ".join(_gov(g) for g in c["governments"]))} · latest {_e(site.long_date(c["latest"]))}'
            + (f' · <span class="hl">{n_flags} worth a second look</span>' if n_flags else "") + "</p></li>")
    flagged = sorted((dict(x, company=companies[k]["name"], ck=k) for k in companies for x in companies[k]["paid"] if x["flags"]),
                     key=lambda x: (x["date"], x["row"]["item"]["key"]), reverse=True)
    seen, recent = set(), []
    for x in flagged:  # one entry per decision, even when it names several companies
        if x["row"]["item"]["key"] in seen:
            continue
        seen.add(x["row"]["item"]["key"])
        recent.append(x)
    total = sum(c["approved_total"] for c in companies.values())
    flag_dl = "".join(f"<dt>{_e(t)}</dt><dd>{_e(d)}</dd>" for t, d in FLAGS.values())
    counts = {f: sum(1 for x in recent if f in x["flags"]) for f in FLAG_ORDER}
    body = f"""<h1>Public money to companies</h1>
<p class="role">Who our local governments agreed to pay, decision by decision</p>
<p class="lede">The record names <mark>{len(companies):,} companies and organizations</mark> the governments we follow
agreed to pay, with <mark>{_e(dollars(total))}</mark> in approved amounts. These are amounts approved, not money paid.</p>
<p class="fair">Amounts and names are read by fixed rules from each agenda's wording, which can be misread. Each
decision links to the official record. <a href="#how">How this works</a>.</p>
<h2 id="look">Worth a second look</h2>
<p>{" · ".join(f"{_e(FLAGS[f][0])}: {counts[f]:,}" for f in FLAG_ORDER if counts[f])}. Newest first, including
items still on an agenda; none of these means anything improper happened.</p>
<ol class="decisions">{''.join(decision_html(x, 0, x["company"], f"companies/{slugs[x['ck']]}.html") for x in recent[:10])}</ol>
{f'<details><summary>Show {len(recent) - 10:,} more</summary><ul class="links">' + "".join(_compact(x, slugs) for x in recent[10:]) + "</ul></details>" if len(recent) > 10 else ""}
<h2 id="all">Every company, by amount approved</h2>
<form class="search" role="search" onsubmit="return false"><label for="cq">Find a company</label>
<div class="row"><input type="search" id="cq" autocomplete="off" placeholder="for example: construction"></div></form>
<ol class="records" id="clist">{''.join(rows)}</ol>
{HOW.format(flags=flag_dl, repo=site.REPO)}
<script>
document.getElementById('cq').addEventListener('input', function () {{
  var q = this.value.trim().toLowerCase();
  document.querySelectorAll('#clist li').forEach(function (li) {{
    li.hidden = q && li.getAttribute('data-name').indexOf(q) < 0;
  }});
}});
</script>"""
    return site.page("Public money to companies", body, 0, path="companies.html",
                     description=(f"{len(companies):,} companies and organizations Tampa Bay and southeast Volusia "
                                  "governments agreed to pay, with each decision, its vote and the official record."),
                     jsonld=[{"@type": "CollectionPage", "name": "Public money to companies"}])


def company_html(c: dict, s: str) -> str:
    from . import site
    paid = c["paid"]
    others = [x for x in c["rows"] if x["direction"] != "out"]
    spellings = sorted(c["names"], key=lambda n: -c["names"][n])
    n_flags = sum(1 for x in paid for _ in x["flags"])
    lede = (f'{_e(", ".join(_gov(g) for g in c["governments"]))} approved <mark>'
            f'{_e(dollars(c["approved_total"]) if c["approved_total"] else "no counted amount")}</mark> for '
            f'{_e(c["name"])} in {c["approved_n"]:,} {"decision" if c["approved_n"] == 1 else "decisions"}'
            f'{f", from {site.long_date(paid[-1]["date"])} to {site.long_date(paid[0]["date"])}" if len(paid) > 1 else ""}.')
    body = f"""<h1>{_e(c["name"])}</h1>
<p class="role">Public money approved for this company or organization</p>
<p class="lede">{lede}</p>
<p class="fair">Amounts are what a board approved, usually a contract's ceiling, not money paid.
{f"{n_flags} {'item is' if n_flags == 1 else 'items are'} marked worth a second look; none means anything improper happened. " if n_flags else ""}<a href="../companies.html#how">How this works</a>.</p>
{f'<p class="small">Also written as: {_e("; ".join(spellings[1:]))}.</p>' if len(spellings) > 1 else ""}
<h2>Decisions to pay {_e(c["name"])}</h2>
<ol class="decisions">{''.join(decision_html(x, 1) for x in paid)}</ol>
{f'<h2>Other decisions that name it</h2><p>Items where the company asked for something or pays the government, '
 f'not counted above.</p><ol class="decisions">' + "".join(decision_html(x, 1) for x in others) + "</ol>" if others else ""}"""
    org = {"@type": "Organization", "name": c["name"], "alternateName": spellings[1:] or None}
    return site.page(f"{c['name']}: public money approved", body, 1, path=f"companies/{s}.html",
                     crumbs=[("Money to companies", "companies.html")], here=c["name"],
                     description=(f"{c['name']}: {dollars(c['approved_total'])} approved in {c['approved_n']} decisions "
                                  f"by {', '.join(_gov(g) for g in c['governments'])}, each with its vote and official record."),
                     jsonld=[{"@type": "AboutPage", "about": org}])


def write(by_meeting: dict, out: Path) -> dict:
    companies = collect(by_meeting)
    slugs = _slugs(companies)
    (out / "companies").mkdir(parents=True, exist_ok=True)
    (out / "companies.html").write_text(index_html(companies, slugs), "utf-8")
    for k, c in companies.items():
        (out / "companies" / f"{slugs[k]}.html").write_text(company_html(c, slugs[k]), "utf-8")
    flagged = {x["row"]["item"]["key"] for c in companies.values() for x in c["paid"] if x["flags"]}
    return {"companies": len(companies), "approved_total": round(sum(c["approved_total"] for c in companies.values())),
            "flagged_decisions": len(flagged)}
