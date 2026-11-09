# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""The governments we collect from, and which sources belong to each.

A document or record key starts with `<source>:<account>:` (for example
`civicclerk:pascocofl:5123` or `legistar:hernandocountyfl:item:56536`). The first two
parts name a *group*: one account on one platform. Each group belongs to one jurisdiction.

Brandon and Lutz are unincorporated: their local government is the Hillsborough County
Commission. Wesley Chapel is governed by Pasco County, Spring Hill by Hernando County.
"""

from __future__ import annotations

JURISDICTIONS: dict[str, dict] = {
    "templeterrace": {
        "name": "City of Temple Terrace", "short": "Temple Terrace", "body": "City Council",
        "areas": [], "groups": ["civicclerk:templeterracefl", "civicplus_archive:www.templeterrace.gov"],
        "since": "2025-10-01",
    },
    "hillsborough": {
        "name": "Hillsborough County", "short": "Hillsborough", "body": "Board of County Commissioners",
        "areas": ["Brandon", "Lutz"], "groups": ["legistar:hillsboroughcounty", "hillsclerk:bocc-votes"],
        "since": "2025-01-01",
        "coverage": ("Every roll-call vote of the County Commission, from the Clerk's Master Voting Record "
                     "(updated monthly by the Clerk, so the newest meetings appear a few weeks late), plus "
                     "land-use and zoning hearings (BOCC Land Use, Zoning Hearing Master, Land Use Hearing "
                     "Officer) from Hillsborough's Legistar. The county's regular agendas are on a site that "
                     "asks automated tools not to collect it, so full agendas are not here."),
    },
    "pasco": {
        "name": "Pasco County", "short": "Pasco", "body": "Board of County Commissioners",
        "areas": ["Wesley Chapel"], "groups": ["civicclerk:pascocofl"], "since": "2025-01-01",
        "skip_kinds": ["Agenda Packet"],
        "coverage": ("Agendas and minutes for the County Commission, Planning Commission and other boards, "
                     "from Pasco's CivicClerk portal. Agenda packets are linked but not yet archived."),
    },
    "hernando": {
        "name": "Hernando County", "short": "Hernando", "body": "Board of County Commissioners",
        "areas": ["Spring Hill"], "groups": ["legistar:hernandocountyfl"], "since": "2025-01-01",
        "coverage": ("County Commission, Planning & Zoning, MPO and other public meetings from Hernando's "
                     "Legistar, with agenda items, actions and each commissioner's vote. Value Adjustment "
                     "Board and Special Master hearings (private residents' cases) are left out."),
    },
}

COUNTIES = [k for k in JURISDICTIONS if k != "templeterrace"]

_BY_GROUP = {g: slug for slug, j in JURISDICTIONS.items() for g in j["groups"]}


def group_of(key: str) -> str:
    return ":".join(key.split(":")[:2])


def jurisdiction_of(key: str) -> str | None:
    return _BY_GROUP.get(group_of(key))


def civicclerk_tenants() -> dict[str, str]:
    """tenant -> jurisdiction slug"""
    return {g.split(":")[1]: slug for g, slug in _BY_GROUP.items() if g.startswith("civicclerk:")}


def legistar_clients() -> dict[str, str]:
    return {g.split(":")[1]: slug for g, slug in _BY_GROUP.items() if g.startswith("legistar:")}
