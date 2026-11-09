# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Who's who: officials, attendance, roll-call votes, contracts and vendors.

Reads data/state.json, data/text/ and data/listings/civicclerk-items.jsonl and writes:

  data/entities/officials.jsonl    elected officials and charter officers, with attendance
  data/entities/votes.jsonl        one row per motion: mover, seconder, ayes, nays, result
  data/entities/contracts.jsonl    agenda items that approve a purchase or contract, with
                                   vendor names and amounts found in the item text
  data/entities/templeterrace.ftm.jsonl
                                   the same as FollowTheMoney entities (PublicBody, Person,
                                   Membership, Employment, Organization/Company, Contract,
                                   ContractAward, Event, Document)

All of it is machine-read. Vendor names and amounts come from agenda wording and can be
wrong or incomplete; every record links to the agenda item or minutes page it came from.
Nothing here implies wrongdoing by anyone (see the Guardrails in the project guide).
"""

from __future__ import annotations

import argparse
import difflib
import gzip
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from .jurisdictions import COUNTIES, jurisdiction_of

from . import minutes as mn

CITY = "City of Temple Terrace"
COUNCIL = "Temple Terrace City Council"
JURISDICTION = "us"

_CONTRACT_TITLE = re.compile(
    r"\b(contract|agreement|purchase|renewal|piggyback|expenditure|change order|award(?:ing)? the|bid|lease|"
    r"rfp|rfq|services with|addendum)\b", re.I)
_NOT_CONTRACT = re.compile(r"employment agreement|employee of the|award of valor|life saving award|"
                           r"planning and design award|proclamation|recogni|proposal summary|^report on", re.I)
_MONEY = re.compile(r"\$\s?([0-9][0-9,]*(?:\.[0-9]{2})?)")
_SUFFIX = (r"(?:,?\s+(?:LLC|L\.L\.C\.|Inc\.?|Incorporated|Corp\.?|Corporation|Company|Co\.|LLP|LP|P\.A\.|PLLC|Ltd\.?))")
_NAME = r"[A-Z0-9][\w&.'’-]*(?:\s+(?:of|and|&|the|de|[A-Z0-9][\w&.'’-]*))*"
# "from X", "with X", "to X": a capitalised name, ideally ending in a company suffix.
_VENDOR_SUFFIXED = re.compile(r"\b(?:from|with|to|by)\s+(" + _NAME + _SUFFIX + r")")
_VENDOR_PLAIN = re.compile(r"\b(?:from|with)\s+(" + _NAME + r")(?=\s+(?:for|to|utilizing|under|in the amount|"
                           r"per|through|via|at|on)\b|[,.;]|$)")
_COOP = re.compile(r"\b((?:Sourcewell|GSA|NASPO|OMNIA|Florida Sheriffs Association|FSA|State of Florida|"
                   r"National Cooperative|HGACBuy|TIPS)[^.;,]{0,40}?(?:Contract|Bid)\s*(?:No\.?|#)?\s*[\w-]+)", re.I)
_RFP = re.compile(r"\b((?:RFP|RFQ|ITB|IFB|Bid)\s*(?:No\.?|#)?\s*[0-9][\w-]*)", re.I)
# Words that start a capitalised phrase but are not vendors.
_NOT_VENDOR = re.compile(r"^(?:the |a |an )?(?:city|council|staff|fiscal|fy|resolution|ordinance|option|"
                         r"initial|one|two|three|four|five|six|additional|federal|state|county|section|"
                         r"phase|amendment|exhibit|attachment|general|funds?|budget)\b", re.I)


def _id(*parts: str) -> str:
    return "tt-" + hashlib.sha1("|".join(parts).lower().encode()).hexdigest()[:20]


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text("utf-8").splitlines() if x.strip()] if path.exists() else []


_JUNK_WORDS = re.compile(r"\b(account|numbers?|signed|executed|addendum|cost|summary|avenue|road|street|drive|"
                         r"rehabilitation|pond|item|quote|contract|pricing|proposal|equipment)\b", re.I)
_COOP_NAMES = re.compile(r"^(sourcewell|gsa|naspo|omnia|fsa|tips|hgacbuy|florida sheriffs association)\b", re.I)


def _clean_vendor(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip(" ,.;:")
    name = re.split(r"\s+-\s*|\s+(?:Concerning|Regarding|For|To|Including)\b", name)[0]
    name = re.sub(r"^(?:the)\s+", "", name, flags=re.I)
    return name.strip(" ,.;:-")


def _plausible_vendor(name: str) -> bool:
    if _COOP_NAMES.match(name) or name.lower().startswith("temple terrace") or _NOT_VENDOR.match(name):
        return False
    if re.search(_SUFFIX + r"$", name):
        return True
    if _JUNK_WORDS.search(name):
        return False
    words = name.split()
    # Single words are too ambiguous unless they are an agency acronym like FDOT.
    return len(words) >= 2 or bool(re.fullmatch(r"[A-Z]{4,}", name))


def vendor_key(name: str) -> str:
    n = name.lower()
    n = re.sub(r"[,.\-]", " ", n)
    n = re.sub(r"\b(llc|l l c|inc|incorporated|corp|corporation|company|co|llp|lp|p a|pllc|ltd)\b", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return re.sub(r"(?<=\w)s$", "", n)  # "systems" and "system" are the same vendor


def find_vendors(item: dict) -> list[str]:
    text = f"{item['title']}. {item['description']}"
    found: list[str] = []
    # Lists like "with A, LLC; B, Inc.; and C, Inc. to conduct"
    lm = re.search(r"\bwith\s+(.+?;.+?)\s+to\s+", item["description"])
    if lm:
        for part in re.split(r";\s*(?:and\s+)?", lm.group(1)):
            found.append(part)
    found += [m.group(1) for m in _VENDOR_SUFFIXED.finditer(text)]
    if not found:
        found += [m.group(1) for m in _VENDOR_PLAIN.finditer(text)]
    # Quotes attached to the item are usually named after the vendor: "Bartow Ford Quote".
    for a in item.get("attachments", []):
        qm = re.match(r"(.+?)\s+(?:Quote|Proposal|Buyer'?s Order|Invoice)\b", a["name"], re.I)
        if qm and not re.match(r"vendor|sidewalk|quote", qm.group(1), re.I):
            found.append(qm.group(1))
    out, seen = [], set()
    for f in found:
        f = _clean_vendor(f)
        k = vendor_key(f)
        if len(k) < 3 or not _plausible_vendor(f) or k in seen or k in ("temple terrace", CITY.lower()):
            continue
        seen.add(k)
        out.append(f)
    return out


def contract_rows(items: list[dict]) -> list[dict]:
    rows = []
    for i in items:
        if i["is_section"] or not _CONTRACT_TITLE.search(i["title"]) or _NOT_CONTRACT.search(i["title"]):
            continue
        text = f"{i['title']} {i['description']} {i['fiscal_impact']}"
        amounts = [float(a.replace(",", "")) for a in _MONEY.findall(text)]
        coop = _COOP.search(text)
        rfp = _RFP.search(text) or next((_RFP.search(a["name"]) for a in i["attachments"] if _RFP.search(a["name"])), None)
        rows.append({
            "key": i["key"], "date": i["date"], "outline": i["outline"], "item_number": i["item_number"],
            "title": i["title"], "description": i["description"],
            "vendors": find_vendors(i),
            "amount_stated": amounts[0] if amounts else None,
            "amounts_in_text": amounts,
            "cooperative_contract": coop.group(1).strip() if coop else "",
            "solicitation": rfp.group(1).strip() if rfp else "",
            "agenda_link": i["portal_url"],
            "machine_extracted": True,
        })
    return rows


def _match(name: str, known: list[str]) -> str:
    if name in known:
        return name
    close = difflib.get_close_matches(name, known, n=1, cutoff=0.75)
    return close[0] if close else ""


def build(data: Path) -> dict:
    # Temple Terrace only: the minutes parser and the officials model are this city's.
    state = {k: e for k, e in json.loads((data / "state.json").read_text("utf-8")).items()
             if jurisdiction_of(k) not in COUNTIES}
    items = _jsonl(data / "listings" / "civicclerk-items.jsonl")
    outlines_by_date: dict[str, dict[str, dict]] = defaultdict(dict)
    for i in items:
        if not i["is_section"]:
            outlines_by_date[i["date"]][i["outline"]] = i

    # --- minutes: attendance and votes ---
    minutes_docs = sorted((e for e in state.values() if e.get("kind") == "Minutes" and e.get("sha256")),
                          key=lambda e: e["date"])
    parsed = []
    for e in minutes_docs:
        p = data / "text" / f"{e['sha256']}.json.gz"
        if not p.exists():
            continue
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            t = json.load(fh)
        agenda = {i["outline"]: i["title"] for i in items if i["date"] == e["date"]}
        parsed.append((e, t, mn.parse_minutes(t["pages"], agenda or None)))

    canon = mn.canonical_names([f.present for _, _, f in parsed])
    officials: dict[str, dict] = {}

    def official(name: str, role: str) -> dict | None:
        group = "elected" if role in mn.ELECTED else role
        full = canon.get((name.split()[-1], group)) or (name if len(name.split()) > 1 else None)
        if not full:  # surname only and never seen in full: match on surname within the group
            full = next((v for (s, g), v in canon.items() if s == name.split()[-1] and g == group), None)
        if not full:
            return None
        o = officials.setdefault(full, {"name": full, "roles": Counter(), "group": group,
                                        "present": [], "absent": [], "id": _id("person", full)})
        o["roles"][role] += 1
        return o

    elected_surnames: list[str] = []
    for e, t, f in parsed:
        for a in f.present:
            o = official(a.name, a.role)
            if o:
                o["present"].append(e["date"])
        for a in f.absent:
            o = official(a.name, a.role)
            if o:
                o["absent"].append(e["date"])
    for o in officials.values():
        if o["group"] == "elected":
            elected_surnames.append(o["name"].split()[-1])
    by_surname = {o["name"].split()[-1]: o["name"] for o in officials.values() if o["group"] == "elected"}

    votes = []
    for e, t, f in parsed:
        valid = outlines_by_date.get(e["date"], {})
        for n, v in enumerate(f.votes):
            item = valid.get(v["item"])
            sections = {i["outline"]: i for i in items if i["is_section"] and i["date"] == e["date"]}
            sec = sections.get(v["item"])
            consent = v["item"] if sec and "consent" in sec["title"].lower() else ""
            sect_no = v["item"].split(".")[0] + "." if v["item"] else ""
            sect = sections.get(sect_no)
            if not consent and sect and "consent" in sect["title"].lower() and re.search(r"\bconsent\b", v["text"], re.I):
                consent, item = sect_no, None

            def names(lst):
                out = []
                for s in lst:
                    m = _match(s, elected_surnames)
                    if m:
                        out.append(by_surname[m])
                return out

            ayes, nays = names(v["ayes"]), names(v["nays"])
            if not v.get("roll_call", True):  # "unanimously carried": everyone present voted aye
                ayes = sorted(o["name"] for o in officials.values()
                              if o["group"] == "elected" and e["date"] in o["present"])
            mover = names([v["mover"].split()[-1]] if v["mover"] else [])
            second = names([v["seconder"].split()[-1]] if v["seconder"] else [])
            votes.append({
                "key": f"{e['key']}:vote:{n + 1}", "date": e["date"],
                "item": v["item"] if (item or consent) else "",
                "item_title": item["title"] if item else ("Consent Agenda" if consent else ""),
                "consent_section": consent,
                "agenda_item_key": item["key"] if item else "",
                "mover": mover[0] if mover else "", "seconder": second[0] if second else "",
                "ayes": ayes, "nays": nays, "tally": f"{len(ayes)}-{len(nays)}",
                "result": "passed" if len(ayes) > len(nays) else "failed",
                "unanimous": not nays, "roll_call": v.get("roll_call", True), "record_number": v["record_number"], "action": v["action"],
                "minutes_page": v["page"], "page_method": next((p["method"] for p in t["pages"] if p["n"] == v["page"]), ""),
                "minutes_link": f"{e.get('copy_url') or e['url']}#page={v['page']}",
                "text": v["text"], "machine_extracted": True,
            })

    contracts = contract_rows(items)
    vote_by_item = {v["agenda_item_key"]: v for v in votes if v["agenda_item_key"]}
    # Item ranges cited in the motion text: "RESOLUTION, 11.A.-11.D., were ADOPTED by consent".
    for v in votes:
        for m in re.finditer(r"\b(\d{1,2})\.?([A-Z])\b\.?(?:\s*[-–—]\s*(?:\1\.?)?([A-Z])\b)?", v["text"]):
            if not re.search(r"\bconsent\b", v["text"], re.I):
                break
            sec, a, z = m.group(1), m.group(2), m.group(3) or m.group(2)
            for i in items:
                o = i["outline"]
                if (i["date"] == v["date"] and not i["is_section"] and re.fullmatch(rf"{sec}\.([A-Z])\.", o)
                        and a <= o.split(".")[1] <= z and i["key"] not in vote_by_item):
                    vote_by_item[i["key"]] = v
    # Consent agenda: one vote approves every item under the section ("11." -> "11.A.", "11.B." ...).
    for v in votes:
        if v["consent_section"]:
            for i in items:
                if (i["date"] == v["date"] and not i["is_section"] and i["outline"].startswith(v["consent_section"])
                        and i["key"] not in vote_by_item):
                    vote_by_item[i["key"]] = v
    for c in contracts:
        v = vote_by_item.get(c["key"])
        c["vote"] = f"{v['result']} {v['tally']}" if v else ""
        c["vote_key"] = v["key"] if v else ""

    return {"officials": officials, "votes": votes, "contracts": contracts, "parsed": parsed, "state": state}


def ftm_entities(b: dict) -> list[dict]:
    ents: list[dict] = []

    def add(schema: str, eid: str, **props) -> str:
        ents.append({"id": eid, "schema": schema,
                     "properties": {k: (v if isinstance(v, list) else [v]) for k, v in props.items() if v not in (None, "", [])}})
        return eid

    city = add("PublicBody", _id("org", CITY), name=CITY, jurisdiction=JURISDICTION, country="us",
               website="https://www.templeterrace.gov")
    council = add("PublicBody", _id("org", COUNCIL), name=COUNCIL, jurisdiction=JURISDICTION, country="us",
                  parent=city)
    for o in b["officials"].values():
        role = o["roles"].most_common(1)[0][0]
        pid = add("Person", o["id"], name=o["name"], position=sorted(o["roles"]), country="us")
        if o["group"] == "elected":
            add("Membership", _id("membership", o["name"], COUNCIL), member=pid, organization=council,
                role=sorted(o["roles"]), summary="Listed in City Council minutes as present or absent")
        else:
            add("Employment", _id("employment", o["name"], CITY), employee=pid, employer=city, role=role)

    for e, t, f in b["parsed"]:
        add("Event", _id("meeting", e["date"]), name=f"{COUNCIL} meeting {e['date']}", date=e["date"],
            organizer=council, involved=sorted({o["id"] for o in b["officials"].values()
                                                if e["date"] in o["present"]}),
            sourceUrl=e["url"])

    for e in b["state"].values():
        if not e.get("sha256"):
            continue
        add("Document", _id("doc", e["key"], e["sha256"]), title=e["title"], date=e["date"],
            sourceUrl=e["url"], publisher=CITY, mimeType="application/pdf", fileSize=str(e.get("bytes", "")),
            retrievedAt=(e.get("last_checked") or "")[:10], notes=f"sha256:{e['sha256']}; our copy: {e.get('copy_url', '')}")

    vendors: dict[str, str] = {}
    for c in b["contracts"]:
        cid = add("Contract", _id("contract", c["key"]), title=c["title"], authority=city,
                  contractDate=c["date"], amount=f"{c['amount_stated']:.2f}" if c["amount_stated"] else None,
                  currency="USD" if c["amount_stated"] else None, description=c["description"][:2000],
                  procedureNumber=c["solicitation"] or c["cooperative_contract"] or None,
                  sourceUrl=c["agenda_link"],
                  notes="Machine-extracted from a City Council agenda item; vendor and amount may be incomplete.")
        for v in c["vendors"]:
            k = vendor_key(v)
            if k not in vendors:
                schema = "Company" if re.search(_SUFFIX + r"$", v) else "Organization"
                vendors[k] = add(schema, _id("vendor", k), name=v, notes="Name as written in a City Council agenda item")
            add("ContractAward", _id("award", c["key"], k), contract=cid, supplier=vendors[k],
                amount=f"{c['amount_stated']:.2f}" if c["amount_stated"] and len(c["vendors"]) == 1 else None,
                currency="USD" if c["amount_stated"] and len(c["vendors"]) == 1 else None,
                date=c["date"], sourceUrl=c["agenda_link"])
    return ents


def write(data: Path) -> dict:
    b = build(data)
    out = data / "entities"
    out.mkdir(parents=True, exist_ok=True)

    def dump(name: str, rows: list[dict]) -> None:
        (out / name).write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), "utf-8")

    officials = [{"name": o["name"], "roles": sorted(o["roles"]), "group": o["group"],
                  "meetings_present": len(o["present"]), "meetings_absent": len(o["absent"]),
                  "absent_dates": o["absent"], "first_seen": min(o["present"] + o["absent"]),
                  "last_seen": max(o["present"] + o["absent"]), "id": o["id"]}
                 for o in sorted(b["officials"].values(), key=lambda o: (o["group"] != "elected", o["name"]))]
    dump("officials.jsonl", officials)
    dump("votes.jsonl", b["votes"])
    dump("contracts.jsonl", b["contracts"])
    ents = ftm_entities(b)
    dump("templeterrace.ftm.jsonl", sorted(ents, key=lambda x: (x["schema"], x["id"])))
    return {"officials": len(officials), "votes": len(b["votes"]),
            "split_votes": sum(1 for v in b["votes"] if v["nays"]),
            "votes_linked_to_items": sum(1 for v in b["votes"] if v["agenda_item_key"]),
            "contracts": len(b["contracts"]),
            "contracts_with_vendor": sum(1 for c in b["contracts"] if c["vendors"]),
            "ftm_entities": len(ents), "schemata": dict(Counter(e["schema"] for e in ents))}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m opencivic.entities")
    ap.add_argument("--data-dir", type=Path, default=Path("data"))
    args = ap.parse_args(argv)
    print(json.dumps(write(args.data_dir)), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
