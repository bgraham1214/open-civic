# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Spotlight tags: decisions residents asked to see first, found by fixed rules (no AI).

Two kinds, chosen by the project owner (Nov 10, 2026):

  restriction  "You can't do it now, but you could yesterday": a new ban, prohibition, moratorium,
               crime, or limit on sales or use, and new or changed fines or penalties. Whether the
               rule is a good idea doesn't matter; the 7-OH ban is tagged like anything else.
  business     Money, land or a break for a company: tax breaks, incentive payments, fees or fines
               forgiven, public land sold or leased, and purchases of $100,000 or more made without
               competitive bidding.

The tags say what a decision does, never whether it was right. They prefer missing a case to tagging
the wrong one, so each rule has exclusions found in the real wording (see tests/test_spotlight.py):
land-use "restriction agreements", zoning conditions, the Fine Arts Council, misdemeanor probation
contracts, state-bill advocacy, reports and presentations, procedural motions, and rules the board
sets for itself. Fee waivers and land deals count only when the other party is a company, so a
resident's own request is never spotlighted.

spot(text, motion, action) -> [{"kind", "reason", "stage"}]; label(tag, facts) gives the words shown.
"""

from __future__ import annotations

import re

from .explain import COMPANY_RX, money, strip_motion

KINDS = {
    "restriction": ("New bans, fines or penalties",
                    "Decisions that make something illegal or limited that wasn't before: bans, prohibitions, "
                    "moratoriums, new crimes, limits on sales or use, and new or changed fines."),
    "business": ("Money, land or breaks for companies",
                 "Tax breaks, incentive payments, fees or fines forgiven, public land sold or leased to a "
                 "company, and purchases of $100,000 or more made without competitive bidding."),
}
NO_BID_FLOOR = 100_000

# --- what never counts --------------------------------------------------------------------------
INFO_RX = re.compile(r"^\W*(?:oral vote[.,]?\s*)?(?:receive|accept)\w*\b[^.]{0,80}\b(?:report|presentation|update|audit|"
                     r"briefing|strateg)|\b(?:update|status) (?:regarding|on)\b|^\W*discussion\b", re.I)
PROCEDURAL_RX = re.compile(r"^\W*(?:oral vote[.,]?\s*)?(?:so )?(?:moved|motion(?:ed)?|made a motion)\b\W*(?:to |that |the board )?"
                           r"(?:waive the (?:time certain )?rules|the previous question|defer|continue|table|reconsider|"
                           r"(?:a )?substitute motion to (?:defer|continue|table)|accept (?:the )?written materials|"
                           r"(?:an |the )?amend(?:ment|ed)?\b|change (?:the )?language|strike|add (?:the )?word)", re.I)
# A vote on one amendment to a proposal, not on the proposal ("Amendment made by Commissioner X").
AMEND_RX = re.compile(r"\bamendment made by\b|\bmoved (?:an|the) amendment\b|\bamended the motion\b|\bmoved to amend\b", re.I)
ADVOCACY_RX = re.compile(r"\b(?:letter (?:of support|to)|support(?:ing)? (?:the )?(?:passage|bill|legislation|proposal|"
                         r"additional|offshore)|oppos\w+ (?:any )?(?:bill|legislation)|house bill|senate bill|"
                         r"legislative (?:delegation|program|priorit)|senator|state of florida|on the ballot|"
                         r"opposition to (?:proposed )?(?:state )?legislation|(?:proposed )?state legislation)", re.I)

# --- restrictions ---------------------------------------------------------------------------------
RESTRICT_RX = re.compile(
    r"\bprohibit\w*|\bban(?:s|ning|ned)?\b|\bmoratori(?:um|a)\b|\bunlawful\b|\bcurfew\b|"
    r"\bmake it a misdemeanor\b|\bcriminal (?:offense|penalt)|"
    r"\brestrict\w*\b(?: \w+){0,3} (?:sales?|use|delivery|hours|access|density|parking)\b|"
    r"\b(?:restrictions?|limits?) on (?:the )?(?:retail )?(?:sales?|use)\b|"
    r"\bsynthetic drugs?\b|\bkratom\b|\b7-?oh\b|hydroxymitragynine", re.I)
PENALTY_RX = re.compile(r"\b(?:uniform )?fine schedule|\bcivil penalt(?:y|ies)\b|\bfines? (?:to be imposed|for violations?)|"
                        r"\bestablish\w* (?:the )?(?:non-criminal )?fines?\b|\bpenalt(?:y|ies) (?:for|on)\b", re.I)
# The closing clauses of a formal ordinance caption ("... PROVIDING FOR PENALTIES; PROVIDING FOR SEVERABILITY ...")
# appear on ordinances about anything, so they don't make one a penalty ordinance.
BOILERPLATE_RX = re.compile(r"\bproviding (?:for )?(?:a |the )?penalt(?:y|ies)[^;.]*", re.I)
NOT_RESTRICT_RX = re.compile(
    r"land use restriction|deed restriction|restrictive covenant|covenants and restrictions|fine arts|"
    r"misdemeanor probation|fines (?:&|and) fees justice|penalty rider|performance (?:bond|guarantee)|"
    r"waiver of (?:the )?(?:civil )?penalt|forgiv\w+|"
    r"\b(?:rz|prs|mm)[- ]?(?:pd|std)?\s*\d{2}-\d{3,}|\bpd \d{2}-\d{3,}|rezone (?:from|to)\b|"   # zoning conditions
    r"with (?:the )?(?:\w+ )?restrictions|restrict\w* use ag\w*|alternative standards?|use of (?:the )?funds|"
    r"board polic\w+|prohibiting commissioners|commissioners? (?:shall|from)|public officers?|letterhead|"
    r"county applications|lame duck|county roadway|in county road|"
    r"\bamend\w* (?:the|an?|its) [^.;:]{0,80}\bmoratori|"   # changing an existing moratorium may loosen it
    # Seen when the rest of Florida was added (Nov 16, 2026):
    r"\bext(?:\.|en\w+)[^.]{0,60}\bstate of (?:local )?emergency|declaration of (?:a )?state of (?:local )?emergency|"
    r"(?-i:\bBanning [A-Z])|"                              # "Banning Ranch" is a place
    r"code (?:enforcement|compliance) (?:case|lien|fine)|reduction of (?:a |the )?lien|lien reduction|"  # one owner's case
    r"special event|street closures?|"                     # a one-day parking or street closure
    r"exception to (?:the )?[\w ]{0,40}moratori|offenders of|"
    r"from the list of prohibited|permitted or prohibited|"
    r"\b(?:re)?hiring of\b|adopting and enacting a new code|"   # a personnel matter; a recodification
    r"\bvariance\b",                                            # one applicant's relief from the code
    re.I)
UNDO_RX = re.compile(r"\b(?:repeal\w*|remov\w*|eliminat\w*|strik\w*|lift\w*|rescind\w*|end(?:s|ing)?|expir\w*|"
                     r"terminat\w*)\b(?: \w+){0,4} (?:the )?(?:moratori\w+|ban|prohibit\w*|restrictions?)", re.I)
EXTEND_RX = re.compile(r"\bextend\w*\b(?: \w+){0,3} (?:the )?(?:current )?moratori|\bextension of the moratori", re.I)

# The board asked for a rule, or set it up for a later hearing, rather than adopting it.
WORKS_RX = re.compile(r"\b(?:direct\w*|request\w*|ask\w*)\b[^.]{0,80}\b(?:draft|prepare|research|bring back|explore|"
                      r"evaluate|look into|work with|consult)\b|\bto draft\b|\bdraft (?:an |a )?(?:proposed )?"
                      r"(?:ordinance|amendments?|policy)|\b(?:first|1st) (?:public )?(?:hearing|reading)|\btransmi(?:t|ttal)\b|"
                      r"\b(?:advertise|schedule\w*|set)\b[^.]{0,40}\b(?:public hearings?|PH)\b|\bzoning in progress\b(?![^.]*moratorium)|"
                      r"\bcould do\b|\bpossible\b|\bintro(?:duction)?\b(?! of public)", re.I)
ADOPT_RX = re.compile(r"\b(?:adopt\w*|enact\w*|ordinance|resolution|declar\w+|second (?:public )?hearing|final "
                      r"(?:public )?hearing|public hearing)\b", re.I)

FINAL_RX = re.compile(r"\b(?:second|2nd|final) (?:public )?hearing|\b(?:hold|conduct)\w* (?:a )?public hearing (?:&|and) adopt", re.I)

# --- breaks for companies ---------------------------------------------------------------------------
TAX_RX = re.compile(r"ad valorem tax exemption|\btax abatement|qualified target industry|\bQTI\b|tax refund program", re.I)
NOT_TAX_RX = re.compile(r"refunding (?:revenue )?bonds|refunding revenue|research to any other|school|"
                        r"\brevocation\b|\brevok\w+|\brescind\w*", re.I)  # a break taken back isn't a break given
INCENTIVE_RX = re.compile(r"\b(?:economic|business|investment|job creation|jobs|redevelopment|film)\b[^.;–]{0,30}\bincentives?\b|"
                          r"\bincentives? (?:agreement|package|grant)|cooperative economic development agreement|"
                          r"economic development (?:agreement|grant)|(?:mobility|impact) fee buy-?down", re.I)
NOT_INCENTIVE_RX = re.compile(r"septic|housing incentive|apartment incentive|inclusionary|regional incentive|"
                              r"code compliance|surety bond|escrow agreement|performance guarantee|weatherization|terminat|"
                              r"\brevocation\b|\brevok\w+|\brescind\w*|county incentive grant program|\bCIGP\b", re.I)
FORGIVE_RX = re.compile(r"\bforgiv\w+ (?:\w+ ){0,2}(?:fines?|liens?|penalt\w+)|\bwaiv\w* (?:the |all )?(?:\w+ ){0,2}"
                        r"(?:fees?|fines?|penalt\w+|liens?)\b|\blien (?:reduction|release|forgiveness)|\bfine reduction|"
                        r"\bimpact fee (?:waiver|deferral|credit|reduction)|\bwaiver of (?:the )?(?:civil )?penalt", re.I)
# Only where the county is plainly the seller or landlord: surplus sales and leases at a county airport.
# ("Contract for sale and purchase of real property" is often the county buying, e.g. conservation land.)
LAND_RX = re.compile(r"\bsurplus (?:real )?(?:property|land)|\bsale of (?:county|county-owned)\b|"
                     r"\b(?:aviation ground|corporate hangar|hangar) lease|\bground lease\b[^.]{0,120}\bairport|"
                     r"\btransferring hangar", re.I)
NOT_LAND_RX = re.compile(r"tangible|vehicle|equipment|fixed asset|trailer|mineral rights|\bvan\b|\bdonat\w+|"
                         r"not-for-profit|nonprofit|non-profit|habitat for humanity|community services|food bank|chapel|"
                         r"church|ministr|housing authority|housing services|community development corporation|school|acquir|association|\bseller\b", re.I)
NO_BID_RX = re.compile(r"\bsole[- ]source|\bsingle[- ]source|\bexempt\w* from (?:the )?competitive|"
                       r"\bwithout competitive (?:bid|solicit)|\bno-bid\b|\bemergency purchase", re.I)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _has_company(text: str) -> bool:
    return bool(COMPANY_RX.search(text))


def spot(text: str, motion: str = "", action: str = "") -> list[dict]:
    """Tags for one decision. `text` is the item wording (for the Hillsborough Clerk's record, item and
    motion together), `motion` a separate motion when there is one, `action` the recorded action."""
    text, motion = _norm(text), _norm(motion)
    item, own_motion = strip_motion(text)
    motion = motion or own_motion
    full = f"{text} {motion}" if motion and motion not in text else text
    if (motion and PROCEDURAL_RX.search(motion)) or (not item and PROCEDURAL_RX.search(text)):
        return []
    if AMEND_RX.search(full) or INFO_RX.search(item or motion) or ADVOCACY_RX.search(full):
        return []
    tags: list[dict] = []

    if RESTRICT_RX.search(full) and not NOT_RESTRICT_RX.search(full) and not UNDO_RX.search(full):
        reason = ("moratorium" if re.search(r"moratori", full, re.I) else
                  "new crime" if re.search(r"misdemeanor|criminal", full, re.I) else
                  "limit on sales or use" if re.search(r"restrict", full, re.I) else "ban")
        tag = {"kind": "restriction", "reason": reason, "stage": _stage(full, motion, action)}
        if reason == "moratorium" and re.search(r"\bpermanent moratori", full, re.I):
            tag["permanent"] = True  # Edgewater's data-center moratorium (2026-O-21) has no end date
        tags.append(tag)
    elif PENALTY_RX.search(BOILERPLATE_RX.sub(" ", full)) and not NOT_RESTRICT_RX.search(full):
        tags.append({"kind": "restriction", "reason": "fines", "stage": _stage(full, motion, action)})

    company = _has_company(full)
    if TAX_RX.search(full) and not NOT_TAX_RX.search(full) and (company or re.search(r"\bprospect\b", full, re.I)):
        tags.append({"kind": "business", "reason": "tax break", "stage": _stage(full, motion, action, law=False)})
    elif INCENTIVE_RX.search(full) and not NOT_INCENTIVE_RX.search(full) and (company or re.search(r"\bprospect\b|\bproject \w+", full, re.I)):
        tags.append({"kind": "business", "reason": "incentive", "stage": _stage(full, motion, action, law=False)})
    elif FORGIVE_RX.search(full) and company and not re.search(r"waive the (?:time certain )?rules", full, re.I):
        tags.append({"kind": "business", "reason": "forgiven", "stage": _stage(full, motion, action, law=False)})
    elif LAND_RX.search(full) and company and not NOT_LAND_RX.search(full):
        tags.append({"kind": "business", "reason": "land", "stage": _stage(full, motion, action, law=False)})
    elif NO_BID_RX.search(full) and company and max(money(full) or [0]) >= NO_BID_FLOOR:
        tags.append({"kind": "business", "reason": "no bid", "stage": "act"})
    return tags


def _stage(full: str, motion: str, action: str, law: bool = True) -> str:
    """'works' when the board asked for the rule or scheduled it; 'extend' for an extended moratorium;
    else 'act' (adopted or approved, if the vote passed)."""
    if law and EXTEND_RX.search(full):
        return "extend"
    item = strip_motion(full)[0] or full
    if (motion and WORKS_RX.search(motion)) or (WORKS_RX.search(item) and not FINAL_RX.search(item)):
        return "works"
    if law and not ADOPT_RX.search(full) and not re.search(r"adopt|approv|enact", action or "", re.I):
        return "works"
    return "act"


REASONS = {
    "restriction": {"ban": "a ban or prohibition", "moratorium": "a temporary moratorium", "new crime": "a new crime",
                    "limit on sales or use": "a limit on sales or use", "fines": "fines or penalties"},
    "business": {"tax break": "Tax break for a company", "incentive": "Incentive payment to a company",
                 "forgiven": "Fees or fines forgiven for a company", "land": "Public land sold or leased to a company",
                 "no bid": "No-bid purchase from a company"},
}


def label(tag: dict, facts: dict | None) -> str:
    """The words on the tag, given the vote. No vote yet: what's proposed. Failed or put off: said so."""
    kind, reason, stage = tag["kind"], tag["reason"], tag["stage"]
    passed = bool(facts and facts.get("passed"))
    act = ((facts or {}).get("action") or "").lower()
    later = act.startswith(("continu", "postpon", "tabl", "defer"))  # "tabled" or Edgewater's "table"
    denied = act.startswith(("denied", "deny"))
    if kind == "restriction":
        if not facts:
            return "On the agenda: " + ("fines or penalties" if reason == "fines" else "a new restriction")
        if not passed or denied:
            return "Proposed restriction (didn't pass)"
        if later:
            return "Proposed restriction (put off)"
        if stage == "extend":
            return "Restriction extended"
        if stage == "works":
            return "Restriction in the works"
        return "Fines or penalties set or changed" if reason == "fines" else "New restriction"
    what = REASONS[kind][reason]
    if not facts:
        return f"On the agenda: {what[0].lower()}{what[1:]}"
    if not passed or denied:
        return f"{what} (didn't pass)"
    if later:
        return f"{what} (put off)"
    if stage == "works":
        return f"{what} (in the works)"
    return what


def detail(tag: dict) -> str:
    """One plain sentence under the tag: what the rule saw."""
    if tag["kind"] == "restriction":
        if tag.get("permanent"):
            return "The official wording describes a permanent moratorium."
        return f"The official wording describes {REASONS['restriction'][tag['reason']]}."
    return {"tax break": "The official wording describes a property-tax exemption or tax refund for a business.",
            "incentive": "The official wording describes an incentive agreement or payment to a named company or corporation.",
            "forgiven": "The official wording describes fees, fines or liens waived or reduced for a named company.",
            "land": "The official wording describes public land sold or leased to a named company.",
            "no bid": f"The official wording describes a purchase of ${NO_BID_FLOOR:,} or more made without competitive "
                      "bidding (sole source or emergency)."}[tag["reason"]]


def for_item(item: dict) -> list[dict]:
    """Tags for a decision record as the page builders hold it."""
    if item.get("motion"):
        return spot(item.get("title") or "", item["motion"], item.get("action") or "")
    return spot(item.get("title") or "", "", item.get("action") or "")


# --- Topics: what a tagged decision is about, for grouping the page (Nov 19, 2026) ---------------------------
# Read from the first 600 characters (titles often name their subject only in the chapter they amend: "AMENDING
# CHAPTER 6 ANIMALS"); first match wins, specific before general. Every tagged item was read for these rules.
TOPIC_HEAD = 600
TOPICS: list[tuple[str, str, re.Pattern]] = [
    ("events", "Events and fees waived for groups",
     re.compile(r"\bspecial events?\b|\bfacility use fees?\b|\bwaiv\w* (?:of )?(?:the )?(?:facility |rental )?fees\b|"
                r"\bback-to-school\b|\bfestival\b", re.I)),
    ("liens", "Code enforcement, liens and fines",
     re.compile(r"\bliens?\b|\bcode enforcement\b|\bforgive fines\b|\bspecial (?:master|magistrate)\b", re.I)),
    ("tech", "Data centers, cameras and technology",
     re.compile(r"\bdata cent\w+|\bartificial intelligence\b|\bA\.?I\.? facilit|\bsoftware\b|\bcameras?\b|\blicense plate|"
                r"\btechnology\b|\bnetwork\w*\b|\brecords management\b|\bcomputers?\b|\bcyber\w*|\bdrones?\b|\bSCADA\b|"
                r"\bsupervisory control\b|\bsubscriptions?\b", re.I)),
    ("substances", "Alcohol, smoking, vaping, hemp and kratom",
     re.compile(r"\balcohol\w*|\bliquor\b|\bbeer\b|\bwine\b|\bsmok\w+|\bvap(?:e|es|ing)\b|\btobacco\b|\bkratom\b|\bkava\b|"
                r"\bhemp\b|\bmarijuana\b|\bcannabis\b|\bdispensar\w+|\bTHC\b|\b7-OH\b|\bnitrous\b|\bsmoke shops?\b", re.I)),
    ("animals", "Animals",
     re.compile(r"\banimals?\b|\bdogs?\b|\bcats?\b|\bpets?\b|\bpet stores?\b|\broosters?\b|\bchickens?\b|\bcoops\b|"
                r"\bwildlife\b|\bbirds?\b|\bfowl\b|\brabbits?\b|\bhorses?\b|\bbees?\b|\bfeeding\b", re.I)),
    ("emergency", "Burn bans, fireworks and emergencies",
     re.compile(r"\bburn bans?\b|\bopen burning\b|\bfireworks?\b|\bstate of (?:local )?emergency\b|\bhurricane\b|\bdebris\b", re.I)),
    ("airports", "Airports",
     re.compile(r"\bairports?\b|\baviation\b|\bhangars?\b|\bairfield\b", re.I)),
    ("traffic", "Traffic, parking and vehicles",
     re.compile(r"\bparking\b|\btraffic\b|(?<!mobile )\bvehicles?\b|\btow(?:ing|ed)?\b|\bimmobiliz\w+|\bgolf carts?\b|\bmicromobility\b|"
                r"\be-?bikes?\b|\bscooters?\b|\btrucks?\b|\bspeed\b|\broads?\b|\bright[- ]of[- ]way\b|\bbus(?:es)?\b|\btransit\b|\bbeacons?\b|\bcrosswalks?\b|\btraffic signals?\b|\bpedestrians?\b", re.I)),
    ("government", "Elections, ethics and meetings",
     re.compile(r"\belections?\b|\bethics\b|\bconflict of interest\b|\blobby\w*|\bdecorum\b|\bcharter\b|"
                r"\bnonpublic forum|\bballot\b", re.I)),
    ("nuisance", "Noise and nuisances",
     re.compile(r"\bnoise\b|\bnuisances?\b|\bloiter\w*|\burinat\w+|\bdefecat\w+|\bgraffiti\b|\blighting\b|\bodors?\b|"
                r"\blitter\w*|\bsunday construction\b", re.I)),
    ("safety", "Police, fire and public safety",
     re.compile(r"\bpolice\b|\bfire (?:department|rescue)\b|\bsheriff\b|\bemergency medical\b|\bEMS\b|\bpublic safety\b|"
                r"\bjail\b|\bweapons?\b|\bfirearms?\b|\blightning\b|\bcurfew\b|\bmisdemeanor\b|\bthreats?\b|\blifeguards?\b|"
                r"\bmedical examiner\b|\bhelicopters?\b", re.I)),
    ("public", "Beaches, parks and public spaces",
     re.compile(r"\bbeach(?:es)?\b(?! county)|\bparks?\b|\bwaterways?\b|\bdocks?\b|\bmarinas?\b|\bboat\w*|\bcamping\b|"
                r"\bsleeping\b|\bhomeless\w*|\bpanhandl\w+|\bprotests?\b|\bdemonstrations?\b|\btrespass\w*|\bpublic property\b|\bplaza\b|"
                r"\bcity properties\b", re.I)),
    ("signs", "Signs",
     re.compile(r"\b(?:temporary |permanent |political |portable )?signs\b|\bsignage\b|\bbillboards?\b", re.I)),
    ("housing", "Housing and rentals",
     re.compile(r"\bshort[- ]term rentals?\b|\bvacation rentals?\b|\brentals?\b|\bhousing\b|\bapartments?\b|\bdwellings?\b|"
                r"\bduplex\w*|\bmobile homes?\b|\blandlords?\b|\blive local\b|\bresidential\b", re.I)),
    ("water", "Utilities, water, trash and environment",
     re.compile(r"\b(?:storm|waste)?water\b|\bsewer\b|\birrigation\b|\bpumps?\b|\bbiosolids?\b|\bfertiliz\w+|\blandfill\b|"
                r"\bsolid waste\b|\btipping\b|\brecycl\w+|\bplastics?\b|\bballoons?\b|\bseptic\b|\bwetlands?\b|"
                r"\benvironment\w*|\bchemical\w*|\btrees?\b|\bland application\b|\butilit(?:y|ies)\b|\breclaimed\b|\bpotable\b|"
                r"\blakes?\b|\baerators?\b", re.I)),
    ("money", "Tax breaks and incentives",
     re.compile(r"\bad valorem\b|\btax exemptions?\b|\bincentives?\b|\bqualified target\b|\beconomic development\b|"
                r"\bjob creation\b|\bimpact fees?\b|\babatements?\b", re.I)),
    ("business", "Businesses and sales",
     re.compile(r"\bvendors?\b|\bpeddl\w+|\bsolicit\w+|\bretail\b|\bbusiness\w*|\bstores?\b|\bshops?\b|\bpawn\w*|\bmassage\b|"
                r"\btattoo\w*|\bfood trucks?\b|\bdiscriminat\w+", re.I)),
    ("zoning", "Building, zoning and development",
     re.compile(r"\bzoning\b|\bland development\b|\bLDC\b|\bdevelopment orders?\b|\brezon\w*|\bland[- ]use\b|"
                r"\bcomprehensive plan\b|\bannexations?\b|\bsetbacks?\b|\bbuilding permits?\b|\bconstruction\b|"
                r"\bsubdivision\w*|\bhistoric\b|\bsite plans?\b|\bdevelopment\b|\bCPA\b|\bpermits?\b|\bapplications\b|\bapps\.", re.I)),
    ("land", "Public land sold or leased",
     re.compile(r"\bsurplus (?:real )?property\b|\bsale and purchase of\b|\bauction\w*|\bground lease\b|\bleases?\b", re.I)),
    ("equipment", "Buildings, equipment and supplies",
     re.compile(r"\bHVAC\b|\belevators?\b|\bbuilding (?:control|solutions)\b|\bcourthouse\b|\bwindows?\b|\bequipment\b|"
                r"\bparts\b|\bactuators?\b|\bsupplies\b|\bcables?\b|\bwire\b|\bmaintenance\b|\brepairs?\b|\bproducts\b|"
                r"\bpurchase orders?\b|\bservices\b", re.I)),
    ("fines", "Code enforcement, liens and fines",
     re.compile(r"\bfine schedule\b|\bpenalt\w+|\bcode violations?\b|\bfines?\b", re.I)),
]
TOPIC_LABELS = {k: label for k, label, _ in TOPICS} | {"fines": "Code enforcement, liens and fines", "other": "Other"}


# Place names aren't subjects: "Town of Palm Beach", "CITY OF DANIA BEACH", "Pinellas Park", "Palm Beach County"
# read as beaches and parks until removed (Nov 19, 2026).
_PLACE = re.compile(r"\b(?:(?:[A-Z][a-z]+|St\.)(?:[ -](?:[A-Z][a-z]+|By|by|The|the))*|[A-Z][A-Z.'-]+(?: [A-Z][A-Z.'-]+)*) "
                    r"(?:Beach(?: Shores| County)?|BEACH(?: SHORES| COUNTY)?|Park|PARK|Gardens|GARDENS)\b")


def topic(item: dict) -> str:
    """What a tagged decision is about: one TOPICS key, or "other"."""
    t = re.sub(r"\s+", " ", (item.get("title") or "") + " " + (item.get("motion") or ""))[:TOPIC_HEAD]
    t = _PLACE.sub(" ", t)
    for k, _, rx in TOPICS:
        if rx.search(t):
            return "liens" if k == "fines" else k
    return "other"


# --- On pages -----------------------------------------------------------------------------------

def _e(s: str) -> str:
    import html
    return html.escape(s or "", quote=True)


def badges(item: dict, facts: dict | None, depth: int) -> str:
    """The tags above a decision's headline, linking to how they're made."""
    tags = for_item(item)
    if not tags:
        return ""
    up = "../" * depth
    return ('<p class="spot">' + " ".join(
        f'<a class="tag {t["kind"]}" href="{up}spotlight.html#how" title="{_e(detail(t))}">{_e(label(t, facts))}</a>'
        for t in tags) + "</p>")


def entries(by_meeting: dict[str, dict[str, list[dict]]]) -> list[dict]:
    """Every tagged decision or agenda item, newest first: {county, date, kind, label, row}."""
    out = []
    seen: dict[tuple, bool] = {}
    for county, by_date in by_meeting.items():
        for d, rows in by_date.items():
            voted = any(r["votes"] for r in rows)
            for r in rows:
                facts = r["facts"] if r["votes"] else None
                for t in for_item(r["item"]):
                    # some records list one ordinance several times in a meeting (each reading or roll call);
                    # the spotlight lists it once per meeting, a voted row first
                    same = (county, d, t["kind"], _norm(r["item"].get("title") or "")[:200])
                    if same in seen and not (r["votes"] and not seen[same]):
                        continue
                    if same in seen:
                        out[:] = [x for x in out if x.get("_same") != same]
                    seen[same] = bool(r["votes"])
                    out.append({"_same": same, "county": county, "date": d, "kind": t["kind"], "tag": t,
                                "label": label(t, facts), "row": r, "voted": bool(r["votes"]), "meeting_voted": voted})
    out.sort(key=lambda x: (x["date"], x["county"]), reverse=True)
    return out


HOW = """<h2 id="how">How the tags work</h2>
<p>The tags come from fixed rules that read the official wording of each decision. No AI is involved, and the
official wording is always one tap away, under "Details and official wording".</p>
<h3>New bans, fines or penalties</h3>
<p>The test: <strong>you can't do it now, but you could yesterday.</strong> A decision is tagged when its
wording describes a ban or prohibition, a moratorium, temporary or permanent (for example on building permits), a new crime,
a limit on sales or use, or new or changed fines. Rules the board sets only for itself, such as its own ethics
or letterhead policies, aren't tagged.</p>
<ul class="links"><li><strong>New restriction</strong>: adopted at this vote.</li>
<li><strong>Restriction in the works</strong>: the board asked for one to be drafted, or set it up for a later
hearing. It isn't law yet.</li>
<li><strong>Restriction extended</strong>: an existing moratorium was made longer.</li>
<li><strong>On the agenda</strong>: proposed, with no recorded vote yet.</li></ul>
<h3>Money, land or breaks for companies</h3>
<p>A decision is tagged when its wording describes a property-tax exemption or tax refund for a business, an
incentive agreement or payment to a named company or corporation, fees or fines forgiven for a named company, public land sold
or leased to a company, or a purchase of $100,000 or more from a company without competitive bidding (sole source
or emergency). Ordinary bids and contracts aren't tagged. Requests from private residents and gifts to nonprofits
aren't tagged either.</p>
<h3>What the tags don't say</h3>
<p>They say what a decision does, not whether it was right. A ban you support is tagged the same way as one you
don't, and many breaks for companies come with promised jobs or services. The rules can miss a decision or,
rarely, tag the wrong one. <a href="https://github.com/bgraham1214/open-civic/issues">Report a mistake</a>.</p>"""


# What each tag reason is called as a group ("Kind of decision" in the dropdown)
REASON_GROUPS = {
    "ban": "Bans and prohibitions", "moratorium": "Moratoriums", "new crime": "New crimes",
    "limit on sales or use": "Limits on sales or use", "fines": "Fines and penalties",
    "tax break": "Tax breaks", "incentive": "Incentive payments", "forgiven": "Fees or fines forgiven",
    "land": "Public land sold or leased", "no bid": "No-bid purchases ($100,000 or more)",
}


def _stage_key(x: dict) -> str:
    """For the "Where it stands" dropdown, from the tag's words (which come from the vote, never the wording)."""
    if not x["voted"]:
        return "agenda"
    lab = x["label"].lower()
    if "didn't pass" in lab or "put off" in lab:
        return "no"
    if "in the works" in lab:
        return "works"
    return "passed"


def _county(g: str) -> str:
    from .jurisdictions import JURISDICTIONS
    j = JURISDICTIONS[g]
    c = j.get("county") or ("Hillsborough" if g == "templeterrace" else j["short"])
    return f"{c} County"


def page_html(items: list[dict], today: str) -> str:
    from .jurisdictions import JURISDICTIONS
    from .people import long_date, outcome, plain, record_link
    from .site import absolute, page
    from . import organize
    from datetime import date, timedelta
    year_ago = (date.fromisoformat(today) - timedelta(days=365)).isoformat()
    d90 = (date.fromisoformat(today) - timedelta(days=90)).isoformat()

    def card(x: dict) -> str:
        r, j = x["row"], JURISDICTIONS[x["county"]]
        if x["voted"]:
            how = outcome(r["facts"])
        else:
            how = "On an upcoming agenda" if x["date"] > today else "On the agenda; no vote recorded"
        meta = (f'<p class="meta"><a href="meetings/{x["county"]}/{x["date"]}.html">{_e(j["board"])}</a> · '
                f'{_e(long_date(x["date"]))} · {_e(how)}</p>')
        return plain(r["item"], 0, r["facts"] if x["voted"] else None, compact=meta, after=record_link(r["item"]))

    org_items = []
    for x in items:
        j = JURISDICTIONS[x["county"]]
        tk = topic(x["row"]["item"])
        y, m = int(x["date"][:4]), int(x["date"][5:7])
        org_items.append(organize.Item(
            card(x),
            {"topic": (TOPIC_LABELS[tk], TOPIC_LABELS[tk]),
             "county": (_county(x["county"]), _county(x["county"])),
             "government": (j["name"], j["short"]),
             "month": (f"{date(y, m, 1):%B %Y}", x["date"][:7]),
             "reason": (REASON_GROUPS[x["tag"]["reason"]], REASON_GROUPS[x["tag"]["reason"]])},
            {"kind": x["kind"], "stage": _stage_key(x)}, x["date"]))
    listing = organize.render(
        "spot", org_items,
        [organize.Grouping("topic", "Topic"), organize.Grouping("county", "County", "asc"),
         organize.Grouping("month", "Month", "desc"), organize.Grouping("government", "City or county government", "asc"),
         organize.Grouping("reason", "Kind of decision")],
        [organize.Filter("kind", "Show", [("", "Everything"), ("restriction", KINDS["restriction"][0]),
                                          ("business", KINDS["business"][0])]),
         organize.Filter("when", "When", [("", "Any time"), (f"after:{today}", "Coming up"),
                                          (f"span:{d90}:{today}", "Last 90 days"),
                                          (f"span:{year_ago}:{today}", "Last 12 months"),
                                          (f"span:2025-01-01:{today}", "Since Jan. 2025")]),
         organize.Filter("stage", "Where it stands", [("", "Any"), ("passed", "Passed"), ("works", "In the works"),
                                                      ("agenda", "On the agenda"), ("no", "Didn't pass or put off")])],
        level=2, noun=("decision", "decisions"), label="Arrange the Spotlight")
    coming = sorted((x for x in items if x["date"] > today), key=lambda x: x["date"])
    soon = ""
    if coming:
        soon = (f'<section class="soon" aria-labelledby="soon-h"><h2 id="soon-h">Coming up '
                f'<span class="topic-count">({len(coming)})</span></h2><p class="small">On upcoming agendas. Meetings are '
                'open to the public, and agendas can change up to the day.</p>'
                f'<ol class="cards">{"".join("<li>" + card(x) + "</li>" for x in coming[:5])}</ol>'
                + (f'<p class="small">{len(coming) - 5} more: choose "Coming up" under When, below.</p>' if len(coming) > 5 else "")
                + "</section>")
    recent = [x for x in items if year_ago <= x["date"] <= today]
    n_r = sum(1 for x in recent if x["kind"] == "restriction")
    n_b = sum(1 for x in recent if x["kind"] == "business")
    body = f"""<h1>Spotlight</h1>
<p class="role">New restrictions, and money, land or breaks for companies</p>
<p class="lede">In the last 12 months, the local governments we follow made <mark>{n_r} {"decision" if n_r == 1 else "decisions"}
that restrict something</mark> and <mark>{n_b} that give a company money, land or special terms</mark>.</p>
<p class="fair">Tagged by fixed rules from the official wording, for every Florida city and county government we
follow (<a href="florida.html">see which</a>). Tags say what a decision does, never whether it was right.
<a href="#how">How the tags work</a> · <a href="feeds/spotlight.xml">Get updates (RSS feed)</a></p>
{soon}
<h2 id="all">Every tagged decision</h2>
<p class="small">Grouped by topic. Open a group to see its decisions, newest first; use the choices to group them by
county, month, government or kind of decision instead, or to narrow them down. Topics are found by fixed rules
too, and can misfile an item.</p>
{listing}
{HOW}
<script src="organize.js" defer></script>"""
    desc = (f"New bans, moratoriums, fines and penalties, and tax breaks, incentives, land deals and no-bid purchases "
            f"for companies, from the Florida city and county governments we follow.")
    return page("Spotlight: new restrictions and breaks for companies in Florida local government", body, 0,
                path="spotlight.html", description=desc, here="Spotlight",
                feeds=[("Spotlight: new restrictions and breaks for companies", "feeds/spotlight.xml")],
                jsonld=[{"@type": "CollectionPage", "name": "Spotlight", "description": desc,
                         "url": absolute("spotlight.html") or None}])


def write(by_meeting: dict, out, today: str, rss=None) -> dict:
    """spotlight.html and feeds/spotlight.xml. rss: build._rss (title, link, desc, entries) -> xml."""
    from email.utils import format_datetime
    from datetime import datetime, timezone
    from .jurisdictions import JURISDICTIONS
    from .site import absolute
    items = entries(by_meeting)
    (out / "spotlight.html").write_text(page_html(items, today), "utf-8")
    if rss:
        from .explain import explain
        feed = []
        for x in items[:100]:
            it = x["row"]["item"]
            ex = explain(it.get("motion") or it["title"], it.get("matter_type") or "")
            head = ex["subject"] or ex["headline"]
            head = head if len(head) <= 110 else head[:110].rsplit(" ", 1)[0] + "…"
            words = re.sub(r"\s+", " ", it.get("title") or "")[:600]
            j = JURISDICTIONS[x["county"]]
            link = absolute(f"meetings/{x['county']}/{x['date']}.html")
            y, m, d = (int(v) for v in x["date"].split("-"))
            feed.append({"title": f"{x['label']}. {JURISDICTIONS[x['county']]['short']}: {head}", "link": link, "guid": f"{it['key']}|{x['kind']}|{x['label']}",
                         "pub": format_datetime(datetime(y, m, d, 12, tzinfo=timezone.utc)),
                         "desc": f"{j['board']}, {x['date']}. {words}"})
        (out / "feeds").mkdir(exist_ok=True)
        (out / "feeds" / "spotlight.xml").write_text(rss("Spotlight: new restrictions and breaks for companies",
                                                         absolute("spotlight.html"),
                                                         "Decisions tagged by fixed rules; see spotlight.html#how.", feed), "utf-8")
    return {"tagged": len(items), "restriction": sum(x["kind"] == "restriction" for x in items),
            "business": sum(x["kind"] == "business" for x in items)}
