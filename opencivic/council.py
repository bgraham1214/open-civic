# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Temple Terrace City Council decisions, in the shape the plain-language page builders use.

opencivic/minutes.py and entities.py already read every roll call from the city's minutes
(data/entities/votes.jsonl: who moved, who seconded, the ayes and nays, the page) and each
elected official's attendance (officials.jsonl). This module turns them into the same
{"items": {key: item}, "votes": {key: [vote]}} record that people.commission_votes gives
for each county, so the meeting and member pages work the same way for the city.

  - A motion on an agenda item becomes a decision on that item. An item with several motions
    (an amendment, then the final vote) gets one decision per motion, each showing its motion.
  - A consent motion names the items it covers ("11.A.-11.D. were ADOPTED by consent",
    "noting that item 11.A. was pulled"): each named item gets the consent vote. Items with
    a roll call of their own keep that one. If the range can't be read, the consent motion is
    shown as one decision.
  - A motion made during discussion, with no agenda item ("RESOLUTION 148-25(m), APPROVED to
    direct staff ..."), is shown as its own decision, headlined by the motion.
  - An elected member who isn't in the ayes or nays is "Absent" when the minutes list them
    absent that day (true of every such vote so far), otherwise "Not recorded".
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .civicclerk import viewer_links

SLUG = "templeterrace"
TENANT = "templeterracefl"
COUNCIL = re.compile(r"^(City Council( Meeting| Special( Meeting)?)?|Special Meeting|Budget Work Session|Budget Workshop)$", re.I)
VERBS = re.compile(r"\b(ADOPTED|APPROVED|AUTHORIZED|POSTPONED|DENIED|TABLED|CONTINUED|ACCEPTED|APPOINTED|"
                   r"DIRECTED|RATIFIED|PASSED|FAILED|REJECTED|SELECTED)\b")
PAGE_HEAD = re.compile(r"Mayor and City Council [A-Z][a-z]+ \d{1,2}, \d{4}\s*Page\s*\d+", re.I)


IDENT = re.compile(r"\bOrdinance\s+(?:No\.\s*)?(\d{3,5})\b|\b([A-Z]{2,5}-\d{2}-\d{2,3})\b|"
                   r"\b(\d{3,5}\s+(?:[NSEW]\.?\s+)?\w+\s+(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Boulevard|Blvd|Lane|Ln))\b",
                   re.I)


def identifiers(text: str) -> set[str]:
    """Ordinance numbers, case numbers (SPR-25-10, RZP-25-02) and street addresses in a title or motion."""
    out = set()
    for a, b, c in IDENT.findall(text or ""):
        if a:
            out.add(f"ordinance {a}")
        elif b:
            out.add(b.upper())
        elif c:
            out.add(re.sub(r"[.\s]+", " ", c.lower()).replace(" street", " st").replace(" avenue", " ave")
                    .replace(" road", " rd").replace(" drive", " dr").replace(" boulevard", " blvd").replace(" lane", " ln"))
    return out


def reassign(votes: list[dict], items: dict[str, dict]) -> list[dict]:
    """Put each motion under the agenda item it was about.

    The minutes parser files every motion under the last item heading it recognised, so when several
    items are taken up together, motions on 12.C-12.E can all land on 12.B. When an item carries more
    than one motion, a motion moves to another item of the same meeting only if they share an exact
    identifier (an ordinance number, a case number, a street address) and no other item does."""
    count: dict[str, int] = {}
    for v in votes:
        if v.get("agenda_item_key"):
            count[v["agenda_item_key"]] = count.get(v["agenda_item_key"], 0) + 1
    by_date: dict[str, list[dict]] = {}
    for i in items.values():
        by_date.setdefault(i["date"], []).append(i)
    out = []
    for v in votes:
        k = v.get("agenda_item_key")
        if k and count.get(k, 0) > 1 and k in items:
            ids = identifiers(motion_clause(v.get("text", "")))
            if ids and not (ids & identifiers(items[k]["title"])):
                hits = [i for i in by_date.get(v["date"], []) if ids & identifiers(i["title"])]
                if len(hits) == 1:
                    v = {**v, "agenda_item_key": hits[0]["key"], "item": hits[0]["number"], "reassigned_from": k}
        out.append(v)
    return out


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text("utf-8").splitlines() if x.strip()] if p.exists() else []


def motion_clause(text: str) -> str:
    """The motion itself, from the minutes passage: what follows "motion by …, seconded by …," up to
    "Vote on the motion being". '' when the passage doesn't contain one cleanly."""
    t = PAGE_HEAD.sub(" ", re.sub(r"\s+", " ", text or ""))
    found = list(re.finditer(r"motion (?:by|of) (?:Council Member|Vice[- ]Mayor|Mayor) [\w'’-]+,\s*seconded by "
                             r"(?:Council Member|Vice[- ]Mayor|Mayor) [\w'’-]+,?(?:\s*and unanimously carried,?)?\s*(.*?)"
                             r"(?=\s*Vote on the motion being|$)", t, re.I))
    if not found:
        return ""
    clause = found[-1].group(1).strip()
    clause = re.sub(r"^[.,;:\s]+", "", clause)
    clause = re.sub(r"^(?:unanimously carried,?\s*)", "", clause, flags=re.I)
    clause = re.sub(r"^(?:RESOLUTION|ORDINANCE)\s+[\w.()-]*(?:\s+\d[\w()]*)?\s*,\s*", "", clause, flags=re.I)
    # the minutes often carry on with the discussion before "Vote on the motion being"
    clause = re.split(r"(?<=[.)])\s+(?=(?:Mayor|Vice[- ]Mayor|Council Members?|City Manager|City Attorney|City Clerk|"
                      r"Mr\.|Ms\.|Mrs\.|Dr\.)\s)", clause)[0]
    clause = clause.strip().rstrip(".,;")
    return _calm(clause[:1].upper() + clause[1:]) if clause else ""


def _calm(text: str) -> str:
    """'APPROVED to Direct Staff' -> 'Approved to Direct Staff'; the minutes capitalise the action words."""
    return re.sub(r"\b(ADOPTED|APPROVED|AUTHORIZED|POSTPONED|DENIED|TABLED|CONTINUED|ACCEPTED|APPOINTED|DIRECTED|"
                  r"RATIFIED|PASSED|FAILED|REJECTED|SELECTED|AMENDED|MINUTES|RESOLUTION|ORDINANCE)\b",
                  lambda m: m.group(1).capitalize() if m.start() == 0 else m.group(1).lower(), text)


def action_of(clause: str, result: str) -> str:
    """What the vote did, from the motion's leading verb. Only a motion that itself puts something off
    ("Postponed the selection …", "Approved to reschedule item 13.A. …") counts as postponing; adopting a
    resolution that postpones a program is still an adoption."""
    if (result or "").lower().startswith("fail"):
        return "Failed"
    c = (clause or "").strip()
    first = (re.match(r"^(\w+)", c) or [None, ""])[1].lower()
    if first in ("postponed", "tabled", "continued", "deferred") or \
            re.match(r"^approved to (reschedule|postpone|continue|table|defer)\b.*\b(item|meeting)\b", c, re.I):
        return "Postponed"
    if first in ("denied", "rejected"):
        return "Denied"
    return "Adopted" if first == "adopted" else "Approved"


def consent_items(text: str, section: str) -> list[str]:
    """Outline numbers ('11.A.') a consent motion says it adopted, without any it says were pulled."""
    n = (section or "").strip(".")
    if not n:
        return []
    t = re.sub(r"\s+", " ", text or "")
    m = re.search(r"(?:RESOLUTIONS?,?\s*)?(.*?)\s*(?:were|was)\s+ADOPTED by consent", t, re.I)
    if not m:
        return []
    seg = re.sub(r"\s*[–—-]\s*", "-", m.group(1))
    letters: list[str] = []
    for a, b in re.findall(rf"\b{n}\.?\s*([A-Z])\.?(?:-(?:{n}\.?\s*)?([A-Z])\.?)?", seg):
        if b and b >= a:
            letters += [chr(c) for c in range(ord(a), ord(b) + 1)]
        else:
            letters.append(a)
    pulled = set(re.findall(rf"\bitems?\s+{n}\.?\s*([A-Z])\.?\s+(?:was|were)\s+pulled", t, re.I))
    return [f"{n}.{x}." for x in dict.fromkeys(letters) if x not in pulled]


def _case(title: str) -> str:
    """A title typed with caps lock on ('rESOLUTION aPPROVING A LETTER') is flipped back."""
    return title.swapcase() if re.match(r"^[a-z][A-Z]{3,}", title) else title


def members(data: Path) -> list[dict]:
    return [o for o in _jsonl(data / "entities" / "officials.jsonl") if o.get("group") == "elected"]


def _state(data: Path) -> dict:
    p = data / "state.json"
    return json.loads(p.read_text("utf-8")) if p.exists() else {}


def agenda_items(data: Path) -> list[dict]:
    """City Council agenda items (not section headings), shaped like the county items."""
    out = []
    # link the agenda in the portal's viewer; its /event/N/agenda route doesn't exist (see civicclerk.file_viewer_url)
    _, agenda_at = viewer_links(_jsonl(data / "listings" / "civicclerk-meetings.jsonl"))
    for i in _jsonl(data / "listings" / "civicclerk-items.jsonl"):
        if i.get("is_section") or not COUNCIL.match((i.get("meeting") or "").strip()):
            continue
        out.append({"county": SLUG, "key": i["key"], "date": i["date"], "body": "City Council",
                    "number": i.get("outline", ""), "title": _case(i.get("title") or ""), "file_number": i.get("item_number", ""),
                    "matter_type": i.get("section", ""), "action": "", "result": "", "mover": "", "seconder": "",
                    "action_text": i.get("description", ""), "matter_url": "",
                    "portal_url": agenda_at.get(i.get("event_id")) or i.get("portal_url", "").replace("/agenda", "/files")})
    return out


def council_votes(data: Path) -> dict:
    """{"items": {key: item}, "votes": {key: [{person, vote}]}} for every recorded City Council motion."""
    votes = _jsonl(data / "entities" / "votes.jsonl")
    if not votes:
        return {"items": {}, "votes": {}}
    elected = members(data)
    items = {i["key"]: i for i in agenda_items(data)}
    votes = reassign(votes, items)
    by_date_outline = {(i["date"], i["number"]): i for i in items.values()}
    state = _state(data)
    own = {v["agenda_item_key"] for v in votes if v.get("agenda_item_key")}
    per_item: dict[str, int] = {}
    for v in votes:
        if v.get("agenda_item_key"):
            per_item[v["agenda_item_key"]] = per_item.get(v["agenda_item_key"], 0) + 1

    def ballot(v: dict) -> list[dict]:
        out = [{"person": p, "vote": "Yes"} for p in v.get("ayes", [])] + [{"person": p, "vote": "No"} for p in v.get("nays", [])]
        named = set(v.get("ayes", [])) | set(v.get("nays", []))
        for o in elected:
            if o["name"] in named or not (o.get("first_seen", "") <= v["date"] <= o.get("last_seen", "9999")):
                continue
            out.append({"person": o["name"], "vote": "Absent" if v["date"] in o.get("absent_dates", []) else "Not recorded"})
        return out

    def links(v: dict) -> dict:
        doc_key = v["key"].rsplit(":vote:", 1)[0]
        doc = state.get(doc_key, {})
        page = v.get("minutes_page")
        frag = f"#page={page}" if page else ""
        listed = doc.get("listed", True)
        return {"minutes_url": (doc.get("url", "") + frag) if doc.get("url") and listed else "",
                "minutes_copy_url": v.get("minutes_link") or (doc.get("copy_url", "") + frag if doc.get("copy_url") else ""),
                "minutes_page": page, "minutes_code": v.get("item", ""), "minutes_removed": not listed}

    rec_items: dict[str, dict] = {}
    rec_votes: dict[str, list[dict]] = {}
    for v in votes:
        clause = motion_clause(v.get("text", ""))
        common = {"action": action_of(clause, v.get("result", "")),
                  "result": "Fail" if (v.get("result") or "").lower().startswith("fail") else "Pass",
                  "mover": v.get("mover", ""), "seconder": v.get("seconder", ""), "record_number": v.get("record_number", ""),
                  **links(v)}
        if v.get("consent_section") and not v.get("agenda_item_key"):
            covered = [by_date_outline.get((v["date"], o)) for o in consent_items(v.get("text", ""), v["consent_section"])]
            covered = [i for i in covered if i and i["key"] not in own]
            if covered:
                for i in covered:
                    rec_items[i["key"]] = {**i, **common, "agenda_key": i["key"], "action": "Approved (consent agenda)"}
                    rec_votes[i["key"]] = ballot(v)
                continue
            rec_items[v["key"]] = {"county": SLUG, "key": v["key"], "date": v["date"], "body": "City Council",
                                   "number": v.get("item", ""), "title": "Approved the consent agenda (routine items together)",
                                   "matter_type": "Consent Agenda", "portal_url": "", **common}
            rec_votes[v["key"]] = ballot(v)
            continue
        item = items.get(v.get("agenda_item_key") or "")
        if item:
            several = per_item.get(item["key"], 0) > 1
            key = v["key"] if several else item["key"]
            rec_items[key] = {**item, **common, "key": key, "agenda_key": item["key"],
                              **({"motion": clause} if several and clause else {})}
            rec_votes[key] = ballot(v)
            continue
        title = clause or ("A motion made during the meeting (its wording is in the minutes"
                           + (f", page {v['minutes_page']})" if v.get("minutes_page") else ")"))
        rec_items[v["key"]] = {"county": SLUG, "key": v["key"], "date": v["date"], "body": "City Council",
                               "number": v.get("item", ""), "title": title, "matter_type": "Motion during the meeting",
                               "portal_url": "", **common}
        rec_votes[v["key"]] = ballot(v)
    return {"items": rec_items, "votes": rec_votes}


def _clock(start: str) -> str:
    """CivicClerk start '2026-11-17T18:00:00Z' (local wall-clock with a stray Z) -> '6:00 PM'."""
    m = re.match(r"^\d{4}-\d{2}-\d{2}T(\d{2}):(\d{2})", start or "")
    if not m:
        return ""
    h = int(m.group(1))
    return f"{h % 12 or 12}:{m.group(2)} {'AM' if h < 12 else 'PM'}"


def meeting_info(data: Path) -> dict[tuple[str, str], dict]:
    out = {}
    for m in _jsonl(data / "listings" / "civicclerk-meetings.jsonl"):
        if not (COUNCIL.match((m.get("name") or "").strip()) or (m.get("category") == "City Council"
                                                                  and COUNCIL.match((m.get("name") or "City Council").strip()))):
            continue
        k = (SLUG, m["date"])
        rank = bool(m.get("files"))
        if k in out and out[k]["_rank"] >= rank:
            continue
        out[k] = {"county": SLUG, "date": m["date"], "time": _clock(m.get("start", "")), "location": m.get("location", ""),
                  "portal_url": m.get("portal_url", ""), "agenda_status": "", "_rank": rank}
    return out
