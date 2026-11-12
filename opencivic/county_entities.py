# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""County records as FollowTheMoney entities: data/entities/counties.ftm.jsonl.

  PublicBody  each county, and each board that meets (parent: the county)
  Person      each member recorded as voting (Legistar, or the Hillsborough Clerk's record)
  Membership  person -> board, with how many roll calls and the first and last seen
  Event       each meeting, organised by its board, involving the members who voted
  Document    each archived county document (Pasco agendas and minutes, Clerk vote reports)

Only people acting in public roles appear: board members recorded in roll calls. Nobody
is added from agenda text (applicants, speakers, petitioners).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from .jurisdictions import JURISDICTIONS, REGIONS
from .region import load

WEBSITES = {"hillsborough": "https://hcfl.gov", "pasco": "https://www.pascocountyfl.net",
            "hernando": "https://www.hernandocounty.us"}
BOCC = "Board of County Commissioners"


def _id(*parts: str) -> str:
    return "oc-" + hashlib.sha1("|".join(parts).lower().encode()).hexdigest()[:20]


def board_of(body: str) -> str:
    """The board behind a meeting's body name.

    Commission meeting types (budget hearings, workshops, land-use days, LDC hearings)
    belong to the County Commission. Joint meetings ("... and Brooksville City Council
    Interlocal ...") stay separate so other boards' members aren't counted as commissioners.
    """
    b = re.sub(r"\s*\(.*\)$", "", (body or "").strip())
    if re.search(r",| and |interlocal", b, re.I):
        return b
    if re.match(rf"^({BOCC}|BOCC\b|LDC Amendment|Land Development Code Amendment)", b, re.I):
        return BOCC
    return b or BOCC


def _pasco_bodies(data: Path) -> dict[str, str]:
    """Pasco meeting key -> CivicClerk category (the board)."""
    out = {}
    p = data / "listings" / "civicclerk-pascocofl-meetings.jsonl"
    if p.exists():
        for line in p.read_text("utf-8").splitlines():
            m = json.loads(line)
            cat = (m.get("category") or "").strip()
            out[f"civicclerk:pascocofl:event:{m['event_id']}"] = "" if cat.lower() == "general" else cat
    return out


def build(data: Path, members: list[str] | None = None) -> list[dict]:
    """FollowTheMoney entities for one region's governments (default: the counties)."""
    members = members or REGIONS["counties"]["members"]
    members = [m for m in members if not JURISDICTIONS[m].get("blocked")]
    d = {k: [x for x in v if x.get("county") in members] for k, v in load(data).items()}
    pasco = _pasco_bodies(data)
    ents: dict[str, dict] = {}

    def add(schema: str, eid: str, **props) -> str:
        ents[eid] = {"id": eid, "schema": schema, "properties": {
            k: sorted(set(v)) if isinstance(v, list) else [v] for k, v in props.items() if v not in (None, "", [])}}
        return eid

    counties = {s: add("PublicBody", _id("county", s), name=JURISDICTIONS[s]["name"], jurisdiction="us",
                       country="us", website=WEBSITES.get(s) or JURISDICTIONS[s].get("website")) for s in members}
    boards: dict[tuple[str, str], str] = {}

    def board(county: str, name: str) -> str:
        if not name:
            return counties[county]
        k = (county, name)
        if k not in boards:
            boards[k] = add("PublicBody", _id("board", county, name), name=f"{JURISDICTIONS[county]['name']} {name}",
                            jurisdiction="us", country="us", parent=counties[county])
        return boards[k]

    # people and memberships, from roll calls
    item_meeting: dict[str, str] = {}
    for i in d["items"]:
        item_meeting[i["key"]] = i["date"]
    seen: dict[tuple[str, str, str], list[str]] = defaultdict(list)   # (county, board, person) -> dates
    present: dict[tuple[str, str], set[str]] = defaultdict(set)        # (county, date) -> person ids
    people: dict[tuple[str, str], str] = {}
    for v in d["votes"]:
        name = re.sub(r"\s+", " ", v["person"]).strip()
        if not name:
            continue
        c = v["county"]
        if (c, name) not in people:
            people[(c, name)] = add("Person", _id("person", c, name), name=name, country="us",
                                    notes=f"Recorded voting in {JURISDICTIONS[c]['name']} public meetings")
        brd = board_of(v["body"])
        seen[(c, brd, name)].append(v["date"])
        if v["vote"] not in ("X", "Absent", "Excused"):
            present[(c, v["date"], brd)].add(people[(c, name)])
    for (c, brd, name), dates in seen.items():
        add("Membership", _id("membership", c, brd, name), member=people[(c, name)], organization=board(c, brd),
            summary=(f"Recorded in {len(dates)} roll calls of the {brd}, {min(dates)} to {max(dates)}. "
                     "Dates are when votes were seen, not term dates."))

    # meetings
    for m in d["meetings"]:
        c = m["county"]
        brd = pasco.get(m["key"], "") if m["key"].startswith("civicclerk:") else board_of(m["body"])
        org = board(c, brd)
        add("Event", _id("meeting", m["key"]), name=f"{JURISDICTIONS[c]['name']} {brd or 'meeting'} {m['date']}",
            date=m["date"], organizer=org, location=m.get("location") or None,
            involved=sorted(present.get((c, m["date"], brd), set())),
            sourceUrl=m.get("portal_url") or None)

    # documents we archive
    for e in d["docs"]:
        add("Document", _id("doc", e["key"], e["sha256"]), title=e["title"], date=e["date"], sourceUrl=e["url"],
            publisher=JURISDICTIONS[e["county"]]["name"], mimeType="application/pdf",
            fileSize=str(e.get("bytes", "")) or None, retrievedAt=(e.get("last_checked") or "")[:10] or None,
            notes=f"sha256:{e['sha256']}; our copy: {e.get('copy_url', '')}")
    return sorted(ents.values(), key=lambda x: (x["schema"], x["id"]))


def write(data: Path) -> dict:
    """One file per region: data/entities/<db>.ftm.jsonl (counties, volusia)."""
    out = data / "entities"
    out.mkdir(parents=True, exist_ok=True)
    result = {}
    for region, r in REGIONS.items():
        ents = build(data, r["members"])
        (out / f"{r['db']}.ftm.jsonl").write_text(
            "".join(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n" for e in ents), "utf-8")
        counts: dict[str, int] = defaultdict(int)
        for e in ents:
            counts[e["schema"]] += 1
        result[region] = {"ftm_entities": len(ents), "schemata": dict(counts)}
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m opencivic.county_entities")
    ap.add_argument("--data-dir", type=Path, default=Path("data"))
    args = ap.parse_args(argv)
    print(json.dumps(write(args.data_dir)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
