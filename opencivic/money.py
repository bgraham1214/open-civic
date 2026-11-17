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
    r"((?:(?:[A-Z][\w&.'’/-]*|[a-z][A-Z][\w&.'’/-]*|\d[\w&.'’/-]*|&|of|and|for|the|on|at|in|de|del|la)\s){0,10}?"
    r"(?:[A-Z]|[a-z](?=[A-Z]))[\w&.'’-]*,?\s"
    r"(?:Inc|Incorporated|LLC|L\.L\.C|Corp|Corporation|Company|Co|LP|L\.P|LLP|LLLP|P\.A|PA|PLLC|Ltd|N\.A)\.?)(?=\W|$)")
SUFFIXES = r"(?:inc|incorporated|llc|l\.l\.c|corp|corporation|company|co|lp|l\.p|llp|lllp|p\.a|pa|pllc|ltd|n\.a)\.?"
# Words that start a sentence or a clause, not a name.
LEAD_WORDS = re.compile(
    r"^(?:(?:award(?:ed|s|ing)?|approv(?:e|ed|es|al|ing)|authoriz(?:e|ed|es|ing|ation)|execut(?:e|ed|es|ing|ion)|"
    r"enter(?:ed|ing|s)?|accept(?:ed|s|ing)?|agreement|contract|with|to|and|from|"
    r"by|between|the|for|of|a|an|on|in|at|vendor|consultant|contractor|firm|company|provider|purchase|utilization|"
    r"amendment|change|order|task|renewal|extension|piggyback|including|plus|per|via|use|dba|d/b/a|"
    r"as[- ]needed|select(?:ed|s|ing|ion)?|rank(?:ed|ing)?|highest[- ]ranked|annual|term|continuing|exempt|"
    r"ratif(?:y|ied|ies|ication)|funding|"
    r"sole|single|source|emergency|cooperative|multiple|budget|resolution|"
    r"first|second|third|fourth|fifth|no\.?|number|and/or|its|their|that|this|which|subject)\s+)+", re.I)
# A person introduced before the company ("Mark Keschl of Meridien Development, LLC"): keep the company only.
PERSON_OF = re.compile(r"^(?:Mr\.|Ms\.|Mrs\.|Dr\.)?\s*([A-Z][a-z]+)(?:\s[A-Z]\.)?\s([A-Z][a-z'’-]+)\s(?:of|with|for|representing)\s")
# ... unless those two words are the start of an organization's own name ("Schaer Development of Central
# Florida Inc." was listed as "Central Florida Inc.", Nov 16, 2026)
ORG_WORDS = re.compile(
    r"^(?:development|construction|services?|management|industries|enterprises|systems|solutions|group|partners|"
    r"associates|bank|homes|builders|contracting|contractors|engineering|consulting|consultants|society|agency|"
    r"church|center|centre|clubs?|way|league|council|alliance|coalition|ministries|foundation|association|institute|"
    r"university|college|hospital|health|care|company|products|supply|equipment|paving|electric|roofing|plumbing|"
    r"utilities|waste|water|svcs?|inds?|bros|sons|title|realty|properties|holdings|investments|capital|communities|housing|habitat|"
    r"recovery|the|diocese|archdiocese|parish|temple|chabad|goodwill|united|american|national|florida|community|family|children|youth|senior|boys|girls|friends|"
    r"city|county|town|village|bay|coast|gulf|central|south|north|east|west|tampa|pasco|hernando|pinellas|"
    r"school|schools|academy|museum|library|chamber|arts|theatre|theater|ymca|legal|medical|dental|animal|"
    r"environmental|landscaping|landscape|lawn|tree|pest|security|fire|rescue|emergency|truck|auto|motors?|"
    r"ford|chevrolet|toyota|technologies|technology|software|communications|media|marketing|design|architects?)$", re.I)
# A government whose contract is being used, written before the company: "Gainesville Regional Utilities and
# Atlantic Pipe Services, LLC" (a piggyback purchase) names one company.
# Words that only say where: "… of Central Florida Inc.", "Westcare Gulfcoast - Florida, Inc."
PLACE_WORDS = re.compile(r"^(?:florida|fl|central|south|southwest|southeast|north|northeast|northwest|east|west|"
                         r"tampa|bay|orlando|miami|jacksonville|largo|pasco|pinellas|hillsborough|hernando|polk|"
                         r"volusia|county|america|usa|us|the|of|gulf|coast|greater|area)$", re.I)


def _core(n: str) -> list[str]:
    return re.sub(SUFFIXES + "$", "", n.strip(" ,"), flags=re.I).strip(" ,").replace(",", " ").split()


def _place_only(n: str) -> bool:
    c = _core(n)
    return bool(c) and all(PLACE_WORDS.match(w) for w in c)


CREDENTIAL = re.compile(r"^(?:P\.?E\.?|D\.?O\.?|M\.?D\.?|C\.?P\.?A\.?|A\.?I\.?A\.?|D\.?D\.?S\.?|D\.?V\.?M\.?|Esq\.?|P\.?L\.?S\.?)$")
GOV_AND = re.compile(r"^.*\b(?:Utilities|Agency|Authority|County|City|District|Department|Board|Commission|Office|"
                     r"Sheriff|Government|Schools|University|Florida|State)\s+(?:and|&)\s+(?=[A-Z])")
# Another name for the same company: "Shamrock Environmental Corporation d/b/a Aqua Clean Environmental Co., LLC"
ALIAS_GAP = re.compile(r"^[\s,;(]*(?:d/b/a|dba|doing business as|f/?k/?a|formerly(?: known as)?|a/?k/?a|n/?k/?a)[\s,:]*$", re.I)
DECREASE_RX = re.compile(r"\b(?:contract |cost |price )?decrease of \$|\bdecreas\w+ (?:the )?(?:contract|agreement|purchase order)\b|"
                         r"\bdeductive change order|\bcredit change order|[–-]\s*\(\$\s?[\d,]+(?:\.\d+)?\)|\breduc\w+ the contract (?:amount|price|sum)", re.I)
RAISE_RX = re.compile(r"\bincreas\w+\b[^$]{0,80}?\bfrom \$\s?([\d,]+(?:\.\d+)?)\s?(million|M\b)? to \$\s?([\d,]+(?:\.\d+)?)\s?(million|M\b)?", re.I)
# A contract number written before the name: "FM24-002 Bandes Construction Company",
# "No.FM24-021-Williamson Dacar Associates, Inc." (not "A-1 Florida Sod Inc.": two digits needed)
CONTRACT_NO = re.compile(r"^(?:No\.?\s*)?[A-Z]{1,5}\d{2,}(?:-\d+)+[-–\s]+")
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
    # a name never runs across a sentence end ("… PROVIDING FOR AN EFFECTIVE DATE. The Diocese of Venice, Inc.")
    n = re.split(r"(?<=\b[A-Z]{4})\.\s+(?=[A-Z])|(?<=[a-z]{5})\.\s+(?=[A-Z])", n)[-1]
    m = PERSON_OF.match(n)
    if m and not (ORG_WORDS.match(m.group(1)) or ORG_WORDS.match(m.group(2)) or _place_only(n[m.end():])):
        n = n[m.end():]
    prev = None
    while prev != n:
        prev = n
        n = LEAD_WORDS.sub("", n).strip(" ,;:–-")
        n = re.sub(r"^(?:(?:inc|llc|corp|co)\.?,?\s+(?:and\s+)?|[a-z]\s+|&\s*|[\d,.]+\s+)", "", n, flags=re.I)
        n = re.sub(r"^\d[\d.,-]*\d[.,-]*\s*(?=[A-Z])|^\d[.)]\s*(?=[A-Z])", "", n)  # "2026-53 APPROVING …", "85.002Kalos …"
        n = CONTRACT_NO.sub("", n)
        n = GOV_AND.sub("", n)
        parts = re.split(r"\s([–-]|from|with|w/|to|by|between|and/or)\s(?=[A-Z])", n, flags=re.I)
        # "Westcare Gulfcoast - Florida, Inc.": what follows the dash only says where, so it's one name
        n = " ".join(parts[-3:]) if len(parts) >= 3 and parts[-2] in "–-" and _place_only(parts[-1]) else parts[-1]
    n = re.sub(r",?\s+a\s+(?:Florida|Delaware|foreign)\s.*$", "", n).strip(" ,")
    if len(n) < 5 or len(n) > 80 or NOT_COMPANY.search(n) or not re.search(SUFFIXES + r"$", n, re.I):
        return ""
    if len(re.sub(SUFFIXES + "$", "", n, flags=re.I).strip(" ,").split()) < 1:
        return ""
    if re.fullmatch(r"[A-Z][A-Za-z]{1,3}\.", " ".join(_core(n))):  # "HASSELL CO. INT., LLC" cut to "Int., LLC"
        return ""
    return n


def key(name: str) -> str:
    """One company however it's spelled: 'Lennar Homes, LLC' and 'Lennar Homes LLC' -> 'lennar homes'."""
    k = name.lower().replace("&", " and ").replace("’", "'")
    k = re.sub(r"\bu\.?\s?s\.?\b", "us", k)
    k = re.sub(r"[.,'()]", " ", k)
    k = re.sub(r"\b(?:svcs?|service)\b", "services", k)  # "G.A. Food Svcs", "… Service", "… Services"
    k = re.sub(r"\b([a-z])\s+(?=[a-z]\b)", r"\1", k)  # initials: "g a food" (G.A.) is "ga food" (GA)
    k = re.sub(r"\b(?:inc|incorporated|llc|l l c|corp|corporation|company|co|lp|l p|llp|lllp|p a|pa|pllc|ltd|n a|the)\b", " ", k)
    return re.sub(r"\s+", " ", k).strip()


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", key(name)).strip("-")[:70] or "company"


def payees(text: str, aliases: dict[str, list[str]] | None = None) -> list[tuple[str, int, int]]:
    """[(name, start, end)] of each company named, in order, first mention only. A second name joined by
    "d/b/a" or "fka" is the same company: it extends the first name's span and is recorded in aliases."""
    out, seen = [], set()
    for m in PAYEE_RX.finditer(text):
        n = clean_name(m.group(1))
        if n and CREDENTIAL.match(" ".join(_core(n))):  # "W.E. Oliver, P.E., LLC": the person's firm, not "P.E., LLC"
            before = re.search(r"((?:[A-Z][\w.'’-]*\s){0,3}[A-Z][\w.'’-]*),\s$", text[:m.start(1) + max(m.group(1).find(n), 0)])
            n = f"{before.group(1)}, {n}" if before else ""
        if n and _place_only(n):  # "Westcare Gulfcoast - Florida, Inc.": the name began before the dash
            before = re.search(r"((?:[A-Z][\w&.'’]*\s){1,6})[–-]\s$", text[:m.start(1)])
            n = clean_name(before.group(1) + "- " + n) if before else ""
        if n and len(_core(n)) == 1 and ORG_WORDS.match(_core(n)[0]):
            n = ""  # "Steps to Recovery, Inc." cut down to one generic word: not a name we can stand behind
        if not n:
            continue
        at = m.group(1).find(n)  # where the cleaned name starts; the raw match can begin inside "$2,433,000 and"
        start = m.start(1) + max(at, 0)
        if out and ALIAS_GAP.match(text[out[-1][2]:start]):
            if aliases is not None and key(n) != key(out[-1][0]):
                aliases.setdefault(out[-1][0], []).append(n)
            out[-1] = (out[-1][0], out[-1][1], m.end())
            continue
        if key(n) not in seen:
            seen.add(key(n))
            out.append((n, start, m.end()))
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
    if len(names) == 1 and not re.search(r"\bby \$", text):
        m = RAISE_RX.search(text)  # "increasing funding from $237,500 to $475,000": the decision adds the difference
        if m:
            a, b = (float(m.group(i).replace(",", "")) * (1e6 if m.group(i + 1) else 1) for i in (1, 3))
            if b > a:
                return b - a
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
                aka: dict[str, list[str]] = {}
                names = payees(text, aka)
                if JURISDICTIONS[county].get("florida") and JURISDICTIONS[county].get("platform") == "legistar":
                    # These records' action text is often the clerk's narrative of the discussion
                    # (Brevard: "they were able to pass $117.5 billion budget" under a lobbying item
                    # was read as a payment). Only the item's own wording is used.
                    text = re.sub(r"\s+", " ", " ".join(x for x in (it["title"], it.get("motion") or "") if x))
                    aka = {}
                    names = payees(text, aka)
                if JURISDICTIONS[county].get("platform") == "civicclerk":
                    # Here the extra wording is the staff memo, which also names losing bidders, past
                    # vendors and neighbors. Use the title when it names the company; otherwise the memo
                    # only when it names exactly one company.
                    head = re.sub(r"\s+", " ", it["title"])
                    aka = {}
                    in_title = payees(head, aka)
                    if in_title:
                        text, names = (head, in_title) if money(head) else (text, payees(text, aka)[:0] or in_title)
                        if text is not head:  # company in the title, amount only in the memo
                            wanted = {key(n) for n, _, _ in in_title}
                            names = payees(text, aka)
                            if len(names) != 1 or key(names[0][0]) not in wanted:
                                continue
                    elif len(names) != 1:
                        continue
                if not names or not money(text):
                    continue
                way = direction(text)
                less = bool(DECREASE_RX.search(text))
                for i, (n, _, _) in enumerate(names):
                    amt = amount_for(text, names, i)
                    c = companies.setdefault(key(n), {"names": defaultdict(int), "rows": [], "aka": set()})
                    c["names"][n] += 1
                    c["aka"].update(aka.get(n, []))
                    c["rows"].append({"county": county, "date": d, "row": r, "amount": amt, "direction": way,
                                      "shared": len(names) > 1, "decrease": less,
                                      "counted": not CLOSEOUT_RX.search(text) and not less,
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
               + (" (a decrease to a contract: not added to the total, and not subtracted)" if x.get("decrease")
                  else " (a close-out: the contract's final total, not added to the total again)" if not x["counted"] else "")
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
<li>A contract's close-out or final payment restates its final total, so it's listed but not added again.
A decrease to a contract is listed but neither added nor subtracted.</li>
<li>When a contract is changed, the wording sometimes gives the added amount and sometimes the contract's new
total, and doesn't always say which. Where it says "from $A to $B" we count the difference; otherwise we count
the figure as written, so a company's total can include part of one contract twice. Read the decisions.</li>
<li>"Doing business as" and "formerly known as" names are joined to the company's legal name.</li>
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
            f'<li data-name="{_e(c["name"].lower())}" data-gov="{_e(" ".join(c["governments"]))}"><p class="title"><a href="companies/{slugs[k]}.html">{_e(c["name"])}</a></p>'
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
    by_gov: dict[str, dict] = {}
    for k, c in companies.items():
        for x in c["paid"]:
            g = by_gov.setdefault(x["county"], {"total": 0.0, "n": 0, "companies": defaultdict(float)})
            g["companies"][k] += 0
            if x["row"]["facts"] and x["row"]["facts"].get("passed"):
                g["n"] += 1
                if x["counted"]:
                    g["total"] += x["amount"] or 0
                    g["companies"][k] += x["amount"] or 0
    gov_rows = []
    for slug_, g in sorted(by_gov.items(), key=lambda kv: (-kv[1]["total"], _gov(kv[0]))):
        top = max(g["companies"].items(), key=lambda kv: kv[1])
        gov_rows.append(
            f'<tr><th scope="row"><a href="meetings/{slug_}.html">{_e(JURISDICTIONS[slug_]["board"])}</a></th>'
            f'<td>{_e(dollars(g["total"])) if g["total"] else "none counted"}</td><td>{g["n"]:,}</td><td>{len(g["companies"]):,}</td>'
            f'<td>{f"""<a href="companies/{slugs[top[0]]}.html">{_e(companies[top[0]]["name"])}</a> ({_e(dollars(top[1]))})""" if top[1] else "—"}</td></tr>')
    gov_options = "".join(f'<option value="{_e(g)}">{_e(JURISDICTIONS[g]["board"])}</option>'
                          for g in sorted(by_gov, key=lambda g: JURISDICTIONS[g]["board"]))
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
<h2 id="governments">By government</h2>
<p>What each board approved, counting only decisions that passed. Governments whose records we began collecting
recently, or whose agendas don't name the company and amount in the item's title, show less than they spent.</p>
<div class="scroll" role="region" aria-labelledby="cap-gov" tabindex="0"><table class="data">
<caption id="cap-gov">Amounts approved for companies and organizations, by government</caption>
<thead><tr><th scope="col">Government</th><th scope="col">Approved</th><th scope="col">Decisions</th>
<th scope="col">Companies named</th><th scope="col">Largest</th></tr></thead>
<tbody>{''.join(gov_rows)}</tbody></table></div>
<h2 id="all">Every company, by amount approved</h2>
<form class="search" role="search" onsubmit="return false"><label for="cq">Find a company</label>
<div class="row"><input type="search" id="cq" autocomplete="off" placeholder="for example: construction"></div>
<label for="cg">Paid by</label>
<div class="row"><select id="cg"><option value="">Every government</option>{gov_options}</select></div></form>
<p class="small" id="ccount" role="status"></p>
<ol class="records" id="clist">{''.join(rows)}</ol>
<p class="small">Download every decision listed here as a spreadsheet: <a href="companies.csv">companies.csv</a>.</p>
{HOW.format(flags=flag_dl, repo=site.REPO)}
<script>
(function () {{
  var q = document.getElementById('cq'), g = document.getElementById('cg'), n = document.getElementById('ccount');
  function show() {{
    var text = q.value.trim().toLowerCase(), gov = g.value, shown = 0;
    document.querySelectorAll('#clist > li').forEach(function (li) {{
      var hide = (text && li.getAttribute('data-name').indexOf(text) < 0) ||
                 (gov && (' ' + li.getAttribute('data-gov') + ' ').indexOf(' ' + gov + ' ') < 0);
      li.hidden = hide;
      if (!hide) shown++;
    }});
    n.textContent = (text || gov) ? shown + (shown === 1 ? ' company' : ' companies') + ' shown' : '';
  }}
  q.addEventListener('input', show);
  g.addEventListener('change', show);
}})();
</script>"""
    return site.page("Public money to companies", body, 0, path="companies.html",
                     description=(f"{len(companies):,} companies and organizations Tampa Bay and southeast Volusia "
                                  "governments agreed to pay, with each decision, its vote and the official record."),
                     jsonld=[{"@type": "CollectionPage", "name": "Public money to companies"}])


def _breakdown(c: dict) -> str:
    """Where a company's approved total comes from: by government (when several), and how much of it
    was added to contracts approved earlier."""
    ok = [x for x in c["paid"] if x["row"]["facts"] and x["row"]["facts"].get("passed") and x["counted"]]
    lines = []
    if len(c["governments"]) > 1:
        per: dict[str, list[float]] = defaultdict(list)
        for x in ok:
            per[x["county"]].append(x["amount"] or 0)
        lines += [f"<li>{_e(JURISDICTIONS[g]['board'])}: {_e(dollars(sum(v)))} in {len(v):,} "
                  f"{'decision' if len(v) == 1 else 'decisions'}</li>"
                  for g, v in sorted(per.items(), key=lambda kv: -sum(kv[1]))]
    added = [x for x in ok if "added" in x["flags"] and x["amount"]]
    if added and len(added) < len(ok):
        lines.append(f"<li>Of the total, {_e(dollars(sum(x['amount'] for x in added)))} in {len(added):,} "
                     f"{'decision was' if len(added) == 1 else 'decisions were'} money added to contracts "
                     "approved earlier (change orders, amendments, added spending authority).</li>")
    years: dict[str, list[float]] = defaultdict(list)
    for x in ok:
        years[x["date"][:4]].append(x["amount"] or 0)
    if len(years) > 1:
        lines.append("<li>By year: " + " · ".join(f"{y}: {_e(dollars(sum(v)))}" for y, v in sorted(years.items())) + "</li>")
    return f'<ul class="facts">{"".join(lines)}</ul>' if lines else ""


def csv_rows(companies: dict[str, dict]) -> list[list]:
    """One row per company per decision, for companies.csv."""
    from . import site
    from .people import outcome
    head = ["company", "also_known_as", "government", "board", "date", "amount_approved", "counted_in_total",
            "money_goes", "outcome", "worth_a_second_look", "names_several_companies", "official_wording", "page"]
    out = [head]
    for k in sorted(companies, key=lambda k: companies[k]["name"].lower()):
        c = companies[k]
        for x in c["rows"]:
            it, f = x["row"]["item"], x["row"]["facts"]
            passed = bool(f and f.get("passed"))
            out.append([
                c["name"], "; ".join(sorted(c.get("aka", []))), JURISDICTIONS[x["county"]]["name"],
                JURISDICTIONS[x["county"]]["board"], x["date"], "" if x["amount"] is None else f"{x['amount']:.2f}",
                "yes" if x["direction"] == "out" and passed and x["counted"] and x["amount"] else "no",
                "to the company" if x["direction"] == "out" else "not to the company (it pays, or asks for something)",
                outcome(f) if f else "On the agenda; no vote recorded",
                "; ".join(FLAGS[fl][0] for fl in x["flags"]), "yes" if x["shared"] else "no",
                re.sub(r"\s+", " ", it.get("motion") or it["title"]),
                site.absolute(f"meetings/{x['county']}/{x['date']}.html") or f"meetings/{x['county']}/{x['date']}.html"])
    return out


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
{f'<p class="small">Also written as: {_e("; ".join(spellings[1:]).rstrip("."))}.</p>' if len(spellings) > 1 else ""}
{f'<p class="small">The record also calls it (doing business as, or formerly): {_e("; ".join(sorted(c["aka"])).rstrip("."))}.</p>' if c.get("aka") else ""}
{_breakdown(c)}
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
    import csv
    with open(out / "companies.csv", "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows(csv_rows(companies))
    flagged = {x["row"]["item"]["key"] for c in companies.values() for x in c["paid"] if x["flags"]}
    return {"companies": len(companies), "approved_total": round(sum(c["approved_total"] for c in companies.values())),
            "flagged_decisions": len(flagged)}
