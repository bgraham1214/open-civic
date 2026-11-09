# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Turn clerk shorthand into plain language, by rule (no AI, nothing invented).

For one agenda item it returns a topic, a plain headline, plain facts decoded from the
wording (land-use changes, acreage, homes, dollar amounts, who gets paid), and the terms a
reader may need explained. The official wording is never replaced, only translated beside it.
If no rule fits, the headline is the official wording with the motion trimmed off.

Every definition below comes from an official or primary source, listed in TERMS.
"""

from __future__ import annotations

import re

TOPICS = {  # order = order on meeting pages
    "land": "Building and land use",
    "money": "Money",
    "law": "Local laws",
    "people": "Appointments and staff",
    "other": "Other decisions",
    "routine": "Routine business",
}

# Plain definitions with sources. Used in "what this means" notes and on the explainer pages.
TERMS = {
    "prs": ("Small change to an approved development",
            "The project already has a custom zoning plan (a “planned development”). The owner asks to make a "
            "minor change to it, in person before the Commission.",
            "https://hcfl.gov/businesses/zoning/zoning-applications-requiring-a-hearing/apply-for-minor-modification-personal-appearance-to-pd"),
    "mm": ("Big change to an approved development",
           "The project already has a custom zoning plan (a “planned development”). The owner asks for a major "
           "change. A hearing officer holds a public hearing first, then the Commission decides.",
           "https://hcfl.gov/businesses/zoning/zoning-applications-requiring-a-hearing/apply-for-a-major-modification-to-planned-development"),
    "rz-pd": ("Rezoning with a custom plan",
              "The owner asks to rezone land as a “planned development”: a custom set of rules for that one "
              "project, usually with a site plan showing what goes where.",
              "https://hcfl.gov/events/zoning-hearing-master-zhm-hearing/2026/09/28/blta28af46f4da2b139"),
    "rz-std": ("Rezoning to a standard zone",
               "The owner asks to move land into one of the county's standard zones, such as single-family homes "
               "or general commercial, with the rules that come with that zone.",
               "https://hcfl.gov/events/zoning-hearing-master-zhm-hearing/2026/09/28/blta28af46f4da2b139"),
    "rezoning": ("Rezoning",
                 "A request to change the rules for what can be built on a piece of land.",
                 ""),
    "cpa-map": ("Change to the future land-use map",
                "The county's long-range plan has a map saying how each area may be used in the future and how "
                "many homes per acre are allowed at most. This changes that map for one area. A rezoning "
                "usually comes after.",
                "https://archive.planhillsborough.org/wp-content/uploads/2019/03/FLU-Reference-Guide.pdf"),
    "cpa-text": ("Change to the wording of the long-range plan",
                 "This changes the written policies of the county's long-range land plan, which apply across "
                 "many properties rather than one.",
                 "https://archive.planhillsborough.org/wp-content/uploads/2019/03/FLU-Reference-Guide.pdf"),
    "usa": ("Urban Service Area",
            "The boundary where the county plans to provide city-style services like water and sewer. The county "
            "aims to put 80% of new growth inside it. Moving the line lets land outside it ask for more homes or "
            "businesses.",
            "https://planhillsborough.org/?p=10759"),
    "vacate": ("Giving up a public right-of-way or easement",
               "A request for the county to give up a public road, alley or utility strip it no longer needs, "
               "usually to the neighboring owners.",
               ""),
    "ldc": ("Change to the development rules",
            "The Land Development Code is the county's rulebook for building: lot sizes, setbacks, parking, "
            "signs and so on. This changes the rulebook itself, for everyone it applies to.",
            "https://library.municode.com/fl/hillsborough_county/codes/land_development_code"),
    "cdd": ("Community Development District",
            "A special district a developer can set up under Florida law (Chapter 190) to borrow money for a new "
            "community's roads, water and amenities. Homeowners there repay it through an extra yearly charge "
            "on their property tax bill.",
            "https://www.miamidade.gov/pa/library/community-developmen-districts-faq.pdf"),
    "millage": ("Property tax rate (millage)",
                "Florida property tax rates are set in “mills.” One mill is $1 of tax for every $1,000 of a "
                "property's taxable value. A home with $200,000 of taxable value pays $200 per mill.",
                "https://www.floridarevenue.com/property/Documents/homeowner_guide_millage.pdf"),
    "consent": ("Consent agenda",
                "A group of routine items approved together in one vote, to save time. Any commissioner can pull "
                "an item out to discuss it separately.",
                ""),
    "ordinance": ("Ordinance",
                  "A local law. Once adopted it applies to everyone in the county area it covers.",
                  ""),
    "contract": ("Contract or purchase",
                 "The county agrees to pay a company or group for goods or work. ITB (invitation to bid) and RFP "
                 "(request for proposals) are the ways the county asks companies to compete for the job.",
                 ""),
    "grant": ("Grant",
              "Money given for a specific purpose, either to the county (often from the state or federal "
              "government) or from the county to a local group.",
              ""),
    "budget": ("Budget change",
               "Moves money within the county budget or adds money that came in after the budget was set.",
               ""),
}

# Hillsborough future land-use labels. The number in the label is the maximum density.
# Source: Plan Hillsborough FLU reference guide (e.g. RES-4 = up to 4 homes per gross acre).
FLU_NAMES = {
    "RES": "Residential", "A/R": "Agricultural/Rural", "AR": "Agricultural/Rural", "A": "Agricultural",
    "AE": "Agricultural Estate", "RP": "Residential Planned", "NMU": "Neighborhood Mixed Use",
    "SMU": "Suburban Mixed Use", "CMU": "Community Mixed Use", "UMU": "Urban Mixed Use",
    "RMU": "Regional Mixed Use", "OC": "Office Commercial", "LI": "Light Industrial", "HI": "Heavy Industrial",
    "P/QP": "Public/Quasi-Public", "N": "Natural Preservation", "WVR": "Wimauma Village Residential",
}
# Hillsborough zoning districts (Land Development Code 2.01.02.B.1).
ZONE_NAMES = {
    "AM": "agricultural mining", "A": "agriculture", "AR": "agricultural rural", "AS": "agricultural single-family",
    "ASC": "agricultural single-family", "AI": "agricultural industrial", "RSC": "single-family homes",
    "RDC": "duplexes", "RMC": "apartments or other multi-family homes", "MH": "mobile homes",
    "BPO": "professional offices", "OR": "offices and homes", "CN": "neighborhood shops",
    "CG": "general commercial", "CI": "intensive commercial", "M": "manufacturing", "PD": "planned development",
}

MONEY_RX = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?(?:\s?(million|billion))?", re.I)
ACRES_RX = re.compile(r"(?:±|\+/-|approximately|about)?\s*(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(?:±\s*)?(?:\+/-\s*)?acres?\b", re.I)
HOMES_RX = re.compile(r"(up to )?(\d{1,3}(?:,\d{3})*|\d+)\s+(?:single[- ]family\s+|multi[- ]family\s+|residential\s+|townhome\s+|townhouse\s+|dwelling\s+)+(?:dwelling\s+)?(?:units|homes|lots)\b", re.I)
SQFT_RX = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+)\s*(?:square feet|sq\.?\s?ft\.?|sf)\s+(?:of\s+)?([a-z/ -]{3,40}?)(?:\s+uses?)?(?=[,.;)]|\s+(?:and|on|in|at|with)\b)", re.I)
FLU_CHANGE_RX = re.compile(r"from\s+(.{3,80}?)\s*\(([A-Z/]{1,4})\s?-\s?([\d./]+(?:\(\d\))?)\)\s+to\s+(.{3,80}?)\s*\(([A-Z/]{1,4})\s?-\s?([\d./]+(?:\(\d\))?)\)", re.I)
COMPANY_RX = re.compile(r"((?:(?:[A-Z][\w&.'-]*|&|of|and|for|the)\s){0,9}?[A-Z][\w&.'-]*,?\s(?:Inc|LLC|L\.L\.C|Corp|Corporation|Company|Co|LP|LLP|LLLP|P\.?A|PLLC|Ltd)\.?)(?=\W|$)")
# The Clerk ends each subject with the motion ("... Boyette Rd. Moved approval."). Split only where a
# sentence starts with it; "Chair Hagan sought a motion for ..." is one sentence and stays whole.
MOTION_RX = re.compile(r"(?<=[.;:!?)])\s+((?:Moved|So [Mm]oved|Made (?:a|the) motion|Motion(?:ed)?)\b.*)$")
SITE_RX = re.compile(r"(\b(?:N|S|E|W|NE|NW|SE|SW|North|South|East|West)\.?\s+(?:side|corner)\b.*|\b\d[\d,]*\s*(?:ft|feet)\b.*|\b\d+\s+[A-Z][\w.]*\s.*)")


def money(text: str) -> list[float]:
    out = []
    for m in MONEY_RX.finditer(text or ""):
        v = float(m.group(1).replace(",", "")) + (float("0." + m.group(2)) if m.group(2) else 0)
        if m.group(3):
            v *= 1e6 if m.group(3).lower() == "million" else 1e9
        if v >= 1:
            out.append(v)
    return out


def dollars(v: float) -> str:
    if v >= 1e9:
        return f"${v / 1e9:.1f} billion".replace(".0 ", " ")
    if v >= 1e6:
        return f"${v / 1e6:.1f} million".replace(".0 ", " ")
    return f"${v:,.0f}"


def density(code_num: str) -> str:
    """'4' -> 'up to 4 homes per acre'; '1/5' -> 'up to 1 home per 5 acres'. Label rule per Plan Hillsborough."""
    n = re.sub(r"\(\d\)$", "", code_num)
    if "/" in n:
        a, b = n.split("/", 1)
        return f"up to {a} home{'s' if a != '1' else ''} per {b} acres"
    try:
        x = float(n)
    except ValueError:
        return ""
    if x <= 0:
        return ""
    s = f"{x:g}"
    return f"up to {s} home{'s' if s != '1' else ''} per acre"


def strip_motion(text: str) -> tuple[str, str]:
    m = MOTION_RX.search(text or "")
    if m and m.start() > 15:
        return text[:m.start()].strip(), m.group(1).strip()
    if re.match(r"^(Moved|So moved|Made (?:a|the) motion|Motion(?:ed)?)\b", text or ""):
        return "", text.strip()   # the whole entry is the motion ("Motioned to ask for ...")
    return (text or "").strip(), ""


def _place(text: str) -> str:
    """'PRS 25-0077; River Springs LLC; 13420 Boyette Rd.' -> '13420 Boyette Rd'."""
    parts = [p.strip(" .") for p in re.split(r";| – | - (?=[A-Z0-9])", text) if p.strip(" .")]
    for p in parts[1:]:
        if re.search(r"\d+\s+\w+.*\b(Rd|Road|St|Street|Ave|Avenue|Hwy|Highway|Blvd|Boulevard|Dr|Drive|Ln|Lane|Pkwy|Way|Ct|Pl|Trl|Cir)\b", p, re.I) \
                or re.search(r"\b(corner|side|of|between|intersection)\b.*\b(Rd|Road|St|Ave|Hwy|Blvd|Dr|Ln|Pkwy)\b", p, re.I):
            p = re.sub(r"^(?:Location|Located at|Located on)\s*:?\s*", "", p, flags=re.I)
            if COMPANY_RX.search(p):
                m = SITE_RX.search(COMPANY_RX.sub("", p))
                p = m.group(1) if m else p
            return re.sub(r"\s+", " ", p).strip(" ,.")[:90]
    m = re.search(r"(?:located (?:at|on)|Location:)\s*([^.;]{4,80})", text, re.I)
    return m.group(1).strip() if m else ""


def _companies(text: str) -> list[str]:
    seen = []
    for m in COMPANY_RX.finditer(text):
        c = re.split(r"\s(?:from|with|to|by|between)\s", m.group(1).strip(" ,"), flags=re.I)[-1]
        c = re.sub(r"^(?:(?:to|with|and|from|by|the|for|of|&)\s+)+", "", c, flags=re.I)
        if c and c not in seen and len(c) < 70:
            seen.append(c)
    return seen


def explain(title: str, category: str = "", county: str = "") -> dict:
    """Plain-language reading of one agenda item. Keys: topic, headline, facts, terms, motion."""
    what, motion = strip_motion(re.sub(r"\s+", " ", title or ""))
    low = what.lower()
    facts: list[str] = []
    terms: list[str] = []
    topic, headline = "other", ""
    place = _place(what)
    at = f" at {place}" if place else ""

    # --- routine
    if re.match(r"^(oral vote\s*-\s*\w+\s*-\s*)?(approval of )?(the )?(changes( to the agenda)?|consent( agenda)?|agenda|minutes)\b", low) \
            or re.match(r"^(approve|approval of) (the )?(changes|consent)", low):
        topic = "routine"
        if "consent" in low:
            headline, terms = "Approved the routine items together (consent agenda)", ["consent"]
        elif "minute" in low:
            headline = "Approved the minutes of an earlier meeting"
        else:
            headline = "Approved changes to the day's agenda"
    # --- building and land use
    elif re.search(r"\bprs\s*\d", low):
        topic, headline, terms = "land", f"Small change to an approved development{at}", ["prs"]
    elif re.search(r"\bmm\s*\d|major modification", low):
        topic, headline, terms = "land", f"Big change to an approved development{at}", ["mm"]
    elif re.search(r"\brz-pd\b", low):
        topic, headline, terms = "land", f"Rezoning with a custom plan{at}", ["rz-pd"]
    elif re.search(r"\bpd\s*\d{2}-\d{3,}|planned development", low) and re.search(r"zoning|rezon|request", low):
        topic, headline, terms = "land", f"Zoning decision on a planned development{at}", ["rz-pd"]
    elif re.search(r"\brz-std\b", low):
        topic, headline, terms = "land", f"Rezoning to a standard zone{at}", ["rz-std"]
    elif re.search(r"hc/cpa|comprehensive plan|future land use|land use plan amendment", low):
        topic = "land"
        if re.search(r"text amendment", low):
            headline, terms = "Change to the wording of the county's long-range land plan", ["cpa-text"]
        else:
            headline, terms = f"Change to the future land-use map{at}", ["cpa-map"]
        if "urban service area" in low:
            terms.append("usa")
            headline = "Change to the Urban Service Area (where the county plans water and sewer)"
    elif re.search(r"urban service area", low):
        topic, headline, terms = "land", "Urban Service Area (where the county plans water and sewer)", ["usa"]
    elif re.search(r"\brezon|rezoning petition|zoning petition|\brz\b", low):
        topic, headline, terms = "land", f"Rezoning request{at}", ["rezoning"]
    elif re.search(r"vacat(e|ing) petition|petition to vacate|\bv\d{2}-", low):
        topic, headline, terms = "land", "County gives up a public right-of-way or easement", ["vacate"]
    elif re.search(r"\bldc\b|land development code", low):
        topic, headline, terms = "land", "Change to the county's development rules", ["ldc"]
    elif re.search(r"community development district|\bcdd\b", low):
        topic, headline, terms = "land", "Community Development District (special taxing district for a new community)", ["cdd"]
    # --- money
    elif re.search(r"millage|tax rate|\btrim\b", low):
        topic, headline, terms = "money", "Property tax rates (millage)", ["millage"]
    elif re.search(r"budget (amendment|resolution|transfer)|amend\w* the [\w ]{0,30}budget|\ballocat\w+|transfer\w* [\w ]{0,40}(funds|moneys)|recogniz\w+ (additional )?revenue", low) \
            and not re.search(r"no adjustment to the budget", low):
        topic, headline, terms = "money", "Budget or funding decision", ["budget"]
    elif re.search(r"\bgrant\b", low):
        topic, headline, terms = "money", "Grant", ["grant"]
    elif re.search(r"\b(award|contract|agreement|task order|purchase|bid|itb|rfp|rsq|sole source|change order|lease)\b", low) and money(what):
        topic, headline, terms = "money", "Contract or purchase", ["contract"]
    # --- laws
    elif re.search(r"(adopt|enact|amend|repeal|consider|hearing)\w*\b[^.]{0,80}\bordinance|draft ordinance|ordinance (amending|creating|repealing|establishing)", low):
        topic, headline, terms = "law", "New or changed county law (ordinance)", ["ordinance"]
    # --- people
    elif re.search(r"\b(appoint|reappoint|appointments?|nominat)", low):
        topic, headline = "people", "Appointments to boards and committees"
    elif re.search(r"employment agreement|contract extension with county administrator|(hire|select|appoint)\w* [\w ]{0,30}county (administrator|attorney)", low):
        topic, headline = "people", "County leadership contract or staffing"
    elif money(what):
        topic, headline = "money", "Involves money"

    # --- facts decoded from the wording
    for m in FLU_CHANGE_RX.finditer(what):
        a, b = density(m.group(3)), density(m.group(6))
        name_a = FLU_NAMES.get(m.group(2).upper(), m.group(1).strip())
        name_b = FLU_NAMES.get(m.group(5).upper(), m.group(4).strip())
        if a and b:
            facts.append(f"Land-use change: from {name_a} ({a}) to {name_b} ({b})")
        break
    m = ACRES_RX.search(what)
    if m and topic == "land":
        facts.append(f"Size: about {m.group(1)} acres")
    m = HOMES_RX.search(what)
    if m and topic == "land":
        facts.append(f"Homes: {'up to ' if m.group(1) else ''}{m.group(2)}")
    for m in SQFT_RX.finditer(what):
        facts.append(f"Building space: {m.group(1)} square feet of {m.group(2).strip()}")
        break
    m = re.search(r"\brezone to ([A-Z]{1,4})-?(\d+(?:\.\d+)?)?\b", what)
    if m and m.group(1) in ZONE_NAMES:
        facts.append(f"Zone requested: {m.group(1)}{'-' + m.group(2) if m.group(2) else ''} ({ZONE_NAMES[m.group(1)]})")
    amounts = money(what)
    if amounts:
        top = max(amounts)
        if topic == "money":
            headline = f"{headline}: {dollars(top)}" + (" (largest amount named)" if len(set(amounts)) > 1 else "")
        else:
            facts.append(f"Money: {dollars(top)}" + (" (largest of several amounts)" if len(set(amounts)) > 1 else ""))
    if topic == "money":
        cos = _companies(what)
        if cos:
            facts.append("Company or group named: " + "; ".join(cos[:3]))

    first = re.split(r"(?<=[a-z0-9)])\.\s+(?=[A-Z])", what or motion, maxsplit=1)[0].rstrip(".")
    short = first if len(first) <= 320 else first[:320].rsplit(" ", 1)[0] + "…"
    if not headline:
        headline = short
    # The specific item, so look-alike headlines ("Community Development District") can be told apart.
    subject = "" if short == headline else short
    return {"topic": topic, "headline": headline, "subject": subject, "facts": facts, "terms": terms,
            "motion": motion, "official": what}
