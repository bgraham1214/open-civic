# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""The governments we collect from, and which sources belong to each.

A document or record key starts with `<source>:<account>:` (for example
`civicclerk:pascocofl:5123` or `legistar:hernandocountyfl:item:56536`). The first two
parts name a *group*: one account on one platform. Each group belongs to one jurisdiction.

Brandon and Lutz are unincorporated: their local government is the Hillsborough County
Commission. Wesley Chapel is governed by Pasco County, Spring Hill by Hernando County.
Edgewater, Oak Hill and New Smyrna Beach are cities in southeast Volusia County (added Nov 12, 2026).

Every government except Temple Terrace (council.py, templeterrace.db) is built by region.py into its
region's database and hub page (REGIONS): the Tampa Bay counties in counties.db, the Volusia cities
in volusia.db.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

JURISDICTIONS: dict[str, dict] = {
    "templeterrace": {
        "name": "City of Temple Terrace", "short": "Temple Terrace", "body": "City Council",
        "areas": [], "groups": ["civicclerk:templeterracefl", "civicplus_archive:www.templeterrace.gov"],
        "since": "2025-10-01", "govt": "city",
    },
    "hillsborough": {
        "name": "Hillsborough County", "short": "Hillsborough", "body": "Board of County Commissioners",
        "areas": ["Brandon", "Lutz"], "groups": ["legistar:hillsboroughcounty", "hillsclerk:bocc-votes"],
        "since": "2025-01-01",
        "coverage": ("Every roll-call vote of the County Commission since January 2014, from the Clerk's Master "
                     "Voting Record (updated monthly by the Clerk, so the newest meetings appear a few weeks "
                     "late; some 2016-2017 pages are scans, and 33 rows we couldn't read reliably are left "
                     "out rather than guessed), plus "
                     "land-use and zoning hearings (BOCC Land Use, Zoning Hearing Master, Land Use Hearing "
                     "Officer) from Hillsborough's Legistar. The county's regular agendas are on a site that "
                     "asks automated tools not to collect it, so full agendas are not here."),
    },
    "pasco": {
        "name": "Pasco County", "short": "Pasco", "body": "Board of County Commissioners",
        "areas": ["Wesley Chapel"], "groups": ["civicclerk:pascocofl"], "since": "2025-01-01",
        "skip_kinds": ["Agenda Packet"],
        "coverage": ("Agendas and minutes for the County Commission, Planning Commission and other boards, "
                     "from Pasco's CivicClerk portal, and each commissioner's vote on Commission decisions, read "
                     "from the Clerk's minutes (from 2025). Agenda packets are linked but not yet archived."),
    },
    "hernando": {
        "name": "Hernando County", "short": "Hernando", "body": "Board of County Commissioners",
        "areas": ["Spring Hill"], "groups": ["legistar:hernandocountyfl"], "since": "2025-01-01",
        "coverage": ("County Commission, Planning & Zoning, MPO and other public meetings from Hernando's "
                     "Legistar, with agenda items, actions and each commissioner's vote. Value Adjustment "
                     "Board and Special Master hearings (private residents' cases) are left out."),
    },
    "edgewater": {
        "name": "City of Edgewater", "short": "Edgewater", "body": "City Council", "county": "Volusia",
        "areas": [], "groups": ["legistar:cityofedgewater"], "since": "2025-01-01", "govt": "city",
        "website": "https://www.cityofedgewater.org",
        # the council's own meetings; the Executive Session is closed (attorney-client)
        "board_rx": r"^City Council( - (Special Meeting|Workshop))?$",
        "outline": "lettered",  # sub-items "a.", "b." under numbered sections, consent voted once (region._legistar_outline)
        "coverage": ("City Council meetings (regular, special and workshops) and the city's boards, from Edgewater's "
                     "Legistar, with agenda items, actions and each council member's vote, from 2025. Code "
                     "Enforcement/Special Magistrate hearings (private residents' cases) are left out. Agendas "
                     "and minutes are linked on the city's site (its file server asks automated tools not to copy them)."),
    },
    "oakhill": {
        "name": "City of Oak Hill", "short": "Oak Hill", "body": "City Commission", "county": "Volusia",
        "areas": [], "groups": ["weblinks:oakhillfl"], "since": "2025-01-01", "govt": "city",
        "website": "https://www.oakhillfl.gov",
        "listing_pages": ["https://www.oakhillfl.gov/archives/city-commission-archive",
                          "https://www.oakhillfl.gov/archives/agenda-archives-by-year/2025-archive"],
        # regular and special meetings and workshops; not Shade (closed) or Neighborhood meetings, or the TRC
        "board_rx": r"^City Commission( (Special Meeting|Workshop|Budget Workshop))?$",
        "coverage": ("City Commission agendas and minutes posted on the city's website, from 2025, archived and "
                     "searchable (the minutes are scans, read by machine), and each commissioner's vote, read "
                     "from the minutes. Votes the minutes don't state clearly are left out, not guessed."),
    },
    "newsmyrnabeach": {
        "name": "City of New Smyrna Beach", "short": "New Smyrna Beach", "body": "City Commission",
        "county": "Volusia", "areas": [], "groups": [], "govt": "city", "since": "",
        "website": "https://www.cityofnsb.com",
        "official_records": "https://cityofnsb.granicus.com/ViewPublisher.php?view_id=1",
        # Checked Nov 12, 2026: cityofnsb.granicus.com robots.txt is "User-agent: * / Disallow: /"; the
        # city's older meeting portal (newsmyrnabeachfl.iqm2.com) ends in 2020; its Agenda Center is empty.
        "blocked": ("The city publishes its City Commission agendas and minutes only on a site that asks automated "
                    "tools not to collect it, so we don't. Its own page is linked here instead."),
    },
}

COUNTIES = [k for k, j in JURISDICTIONS.items() if j.get("govt", "county") == "county"]

# --- The rest of Florida (added Nov 16, 2026) ---------------------------------------------------
# florida.json lists every county and city found on a platform our adapters read (Legistar or
# CivicClerk) by `python -m opencivic.discover`, each confirmed by a person as the Florida government
# and not a namesake. One row per government: slug, name, kind (county, city, town, village),
# county, platform, account, body (what its governing board is called) and boards (the exact
# meeting-body names that are that board's own meetings).
FLORIDA: list[dict] = json.loads((Path(__file__).parent / "florida.json").read_text("utf-8"))


def _board_rx(names: list[str], platform: str = "legistar") -> str:
    alt = "(?:" + "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)) + ")"
    # CivicClerk meetings are listed as "Meeting name (Category)"; the category says whose meeting it is
    return rf"^.*\({alt}\s*\)$" if platform == "civicclerk" else f"^{alt}$"


def _coverage(f: dict) -> str:
    the = "" if f["kind"] == "county" else "the "
    if f["platform"] == "legistar":
        return (f"{f['body']} meetings and other public boards, from {the}{f['name']}'s Legistar records, with "
                "agenda items, actions and each member's vote where the record gives one, from 2025. Hearings "
                "about private residents' own cases (code enforcement, special magistrates, value adjustment "
                "boards) are left out. Agendas and minutes are linked on the government's own site.")
    return (f"{f['body']} meetings and other public boards, from {the}{f['name']}'s CivicClerk portal: meeting "
            "dates and agenda items, from 2025, linked to the official agenda. Votes aren't on this portal; they "
            "are in the minutes, which we don't read for this government yet.")


for _f in FLORIDA:
    JURISDICTIONS[_f["slug"]] = {
        "name": _f["name"], "short": _f["short"], "body": _f["body"], "county": _f["county"], "areas": [],
        "groups": [f"{_f['platform']}:{_f['account']}"], "since": "2025-01-01",
        "govt": "county" if _f["kind"] == "county" else "city", "kind": _f["kind"],
        "board_rx": _board_rx(_f["boards"], _f["platform"]), "coverage": _coverage(_f), "florida": True,
        "platform": _f["platform"], "votes": _f["platform"] == "legistar",
    }

# Regions built by region.py: one search database, hub page and set of feeds each.
REGIONS: dict[str, dict] = {
    "counties": {"title": "County commission records", "short": "County records", "db": "counties",
                 "page": "counties.html", "members": COUNTIES,
                 "place": "Tampa Bay county records"},
    "volusia": {"title": "Southeast Volusia city records", "short": "Southeast Volusia", "db": "volusia",
                "page": "volusia.html", "members": ["edgewater", "oakhill", "newsmyrnabeach"],
                "place": "Southeast Volusia city records"},
}


def county_slug(county: str) -> str:
    return re.sub(r"[^a-z]", "", county.lower())


# One region per Florida county for the governments in florida.json: the county government (if we
# have it) first, then its cities by name.
for _f in sorted(FLORIDA, key=lambda f: (f["county"], f["kind"] != "county", f["short"])):
    _k = f"{county_slug(_f['county'])}-county"
    _r = REGIONS.setdefault(_k, {
        "title": f"{_f['county']} County: local government records", "short": f"{_f['county']} County",
        "db": _k, "page": f"{_k}.html", "members": [], "place": f"{_f['county']} County local government records",
        "county": _f["county"]})
    _r["members"].append(_f["slug"])
REGIONAL = [s for r in REGIONS.values() for s in r["members"]]


def region_of(slug: str) -> str | None:
    return next((k for k, r in REGIONS.items() if slug in r["members"]), None)


# How each government's board and members are named on the plain-language pages.
for _slug, _j in JURISDICTIONS.items():
    _j.setdefault("govt", "county")
    _hub = (REGIONS[region_of(_slug)]["short"], REGIONS[region_of(_slug)]["page"]) if region_of(_slug) else None
    if _slug == "templeterrace":
        _j.update(board="Temple Terrace City Council", board_formal="Temple Terrace City Council",
                  body_short="Council", member="council member", members="council members",
                  member_title="Council Member", people_dir="council", hub=("Temple Terrace", "templeterrace.html"))
    elif _j["govt"] == "city":
        council = "Council" in _j["body"]
        _kind = _j.get("kind", "city").capitalize()
        _j.update(board=f"{_j['short']} {_j['body']}", board_formal=f"{_j['short']} {_j['body']}",
                  body_short="Council" if council else "Commission",
                  member="council member" if council else "commissioner",
                  members="council members" if council else "commissioners",
                  member_title="Council Member" if council else f"{_kind} Commissioner",
                  people_dir="council" if council else "commissioners", hub=_hub)
    elif "Council" in _j["body"]:  # a county governed by a council (Volusia-style charters)
        _j.update(board=f"{_j['name']} Council", board_formal=f"{_j['name']} {_j['body']}",
                  body_short="Council", member="council member", members="council members",
                  member_title="County Council Member", people_dir="council", hub=_hub)
    else:
        _j.update(board=f"{_j['name']} Commission", board_formal=f"{_j['name']} Board of County Commissioners",
                  body_short="Commission", member="commissioner", members="commissioners",
                  member_title="County Commissioner", people_dir="commissioners", hub=_hub)

_BY_GROUP = {g: slug for slug, j in JURISDICTIONS.items() for g in j["groups"]}


def group_of(key: str) -> str:
    return ":".join(key.split(":")[:2])


def jurisdiction_of(key: str) -> str | None:
    return _BY_GROUP.get(group_of(key))


def civicclerk_tenants() -> dict[str, str]:
    """tenant -> jurisdiction slug"""
    return {g.split(":")[1]: slug for g, slug in _BY_GROUP.items() if g.startswith("civicclerk:")}


def weblinks_sites() -> dict[str, str]:
    """account -> jurisdiction slug, for governments that post documents as links on a web page."""
    return {g.split(":")[1]: slug for g, slug in _BY_GROUP.items() if g.startswith("weblinks:")}


def legistar_clients() -> dict[str, str]:
    return {g.split(":")[1]: slug for g, slug in _BY_GROUP.items() if g.startswith("legistar:")}
