# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Read attendance and roll-call votes out of Temple Terrace City Council minutes.

The clerk's minutes follow a steady house style, which this module relies on:

  Present were: Mayor Andy Ross, Council Members James Chambers, ..., City Manager
  Carlos Baia, City Clerk Lynda Sader, and City Attorney Ernest Mueller.
  Absent was: None.

  7.A. <item title>
  Upon motion by Council Member Fernandez, seconded by Council Member Schisler,
  RESOLUTION 101-26(m), ADOPTED AND APPROVED ... Vote on the motion being: Mayor Ross
  and Council Members Chambers, Fernandez, Kravets and Schisler voting "aye," no "nay."

Everything here is machine-read from the minutes (some pages via OCR). Each record
keeps the minutes page it came from so a person can check it.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

# Officials we track: elected members and charter officers. Staff in "Also present"
# and anyone in brackets (e.g. an honorary "Mayor for the Day", often a child) are skipped.
ROLES = [
    ("Vice-Mayor", "Vice Mayor"), ("Vice Mayor", "Vice Mayor"), ("Mayor", "Mayor"),
    ("Council Members", "Council Member"), ("Council Member", "Council Member"),
    ("Assistant City Manager", "Assistant City Manager"), ("City Manager", "City Manager"),
    ("Deputy City Clerk", "Deputy City Clerk"), ("City Clerk", "City Clerk"),
    ("Deputy City Attorney", "Deputy City Attorney"), ("City Attorney", "City Attorney"),
]
ELECTED = {"Mayor", "Vice Mayor", "Council Member"}
_ROLE_RX = re.compile(r"\b(" + "|".join(re.escape(r) for r, _ in ROLES) + r")\b")
_ROLE_MAP = dict(ROLES)
_QUOTE = "[\"“”'‘’]?"


def _norm(text: str) -> str:
    text = text.replace(" ", " ")
    return re.sub(r"[ \t]+", " ", text)


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _split_names(chunk: str) -> list[str]:
    parts = re.split(r",\s*(?:and\s+)?|\s+and\s+", chunk)
    return [p.strip(" .;:") for p in parts if p.strip(" .;:")]


@dataclass
class Attendee:
    name: str
    role: str


def parse_roster(chunk: str) -> list[Attendee]:
    """'Mayor Andy Ross, Council Members A, B and C, City Manager D' -> attendees."""
    chunk = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", chunk)
    out: list[Attendee] = []
    pieces = _ROLE_RX.split(chunk)
    # pieces: [before, role1, names1, role2, names2, ...]
    for i in range(1, len(pieces) - 1, 2):
        role = _ROLE_MAP[pieces[i]]
        for name in _split_names(pieces[i + 1]):
            name = re.sub(r"^(?:and|the)\s+", "", name, flags=re.I).strip()
            if name.lower() in ("none", "") or not re.match(r"^[A-Z][\w.'-]+", name):
                continue
            out.append(Attendee(name, role))
    return out


@dataclass
class MinutesFacts:
    present: list[Attendee] = field(default_factory=list)
    absent: list[Attendee] = field(default_factory=list)
    votes: list[dict] = field(default_factory=list)


_PRESENT = re.compile(r"Present (?:were|was)\s*:?\s*(.*?)(?:\.\s*)?Absent (?:were|was)\s*:?\s*(.*?)(?:\.\s*)?Also present", re.S | re.I)
_HEADING = re.compile(r"(?m)^\s*(\d{1,2}\.(?:[A-Z]\.(?:\d+\.)?)?)\s+([A-Z].{2,})$")
# Some minutes write sub-items as an indented "A." under "12. Public Hearings ...".
_SUBHEAD = re.compile(r"(?m)^\s*([A-Z])\.\s+([A-Z].{2,})$")


def _headings(text: str) -> list[tuple[int, str, str]]:
    found = [(h.start(), h.group(1), _flat(h.group(2)), "full") for h in _HEADING.finditer(text)]
    found += [(h.start(), h.group(1), _flat(h.group(2)), "letter") for h in _SUBHEAD.finditer(text)]
    out, section = [], ""
    for pos, outline, title, kind in sorted(found):
        if kind == "full":
            section = outline.split(".")[0] + "."
            out.append((pos, outline, title))
        elif section:
            out.append((pos, f"{section}{outline}.", title))
    return out
_VOTE = re.compile(r"Vote on the motion being\s*:?\s*(?P<vote>.{0,400}?\bnay\b\.?" + _QUOTE + r"\.?)", re.S | re.I)
_OFFICIAL = r"(?:Vice[- ]Mayor|Mayor|Council\s*Member|Councilmember)\s+[A-Z][\w’'-]+"
_MOVER = re.compile(r"motion\W{0,3}(?:made\s+)?(?:by|of)\s+(?P<mover>" + _OFFICIAL + ")", re.I)
_SECOND = re.compile(r"seconded\s+by\s+(?P<seconder>" + _OFFICIAL + ")", re.I)
_CARRIED = re.compile(r"motion\W{0,3}(?:made\s+)?(?:by|of)\s+(?P<mover>" + _OFFICIAL + r"),?\s*seconded\s+by\s+(?P<seconder>"
                      + _OFFICIAL + r")\W{0,3}(?:and\s+)?unanimously\s+carried", re.I)
_NUMBER = re.compile(r"\b(RESOLUTION|ORDINANCE)\s+(?:NO\.\s*)?([0-9][\w\-()]*)", re.I)
_ACTION = re.compile(r"\b((?:ADOPTED|APPROVED|DENIED|PASSED|FAILED|TABLED|CONTINUED|AUTHORIZED|ACCEPTED|RATIFIED|DEFERRED)"
                     r"(?:\s+(?:AND|ON|AS)\s+[A-Z]+){0,4})\b")


_NOT_NAMES = {"and", "no", "none", "council", "member", "members", "mayor", "vice", "the"}


def _surnames(chunk: str) -> list[str]:
    chunk = re.sub(r"\b(?:Vice[- ]Mayor|Mayor|Council\s*Members?|Councilmembers?|Members?)\b", ",", chunk)
    out = []
    for n in _split_names(chunk):
        word = n.split()[-1].strip("”“\"'’‘.,;:!") if n.split() else ""
        if re.fullmatch(r"[A-Z][A-Za-z’'-]+", word) and word.lower() not in _NOT_NAMES:
            out.append(word)
    return out


def parse_vote(vote: str) -> dict:
    v = _flat(vote)
    m = re.match(r"(?P<ayes>.*?)\s*voting\s*" + _QUOTE + r"aye" + _QUOTE + r"[,.]?\s*(?P<rest>.*)", v, re.I)
    if not m:
        return {"ayes": [], "nays": [], "parsed": False}
    rest = m.group("rest").lstrip("”“\"'’‘ ,.")
    if re.match(r"no\s*" + _QUOTE + r"nay", rest, re.I):
        nays = []
    else:
        nm = re.match(r"(?:and\s+)?(?P<nays>.*?)\s*(?:voting)?\s*,?\s*" + _QUOTE + r"nay", rest, re.I)
        nays = _surnames(nm.group("nays")) if nm else []
    return {"ayes": _surnames(m.group("ayes")), "nays": nays, "parsed": True}


def _who(text: str) -> str:
    text = _flat(text)
    text = re.sub(r"^(?:Vice[- ]Mayor|Mayor|Council Member|Councilmember)\s+", "", text, flags=re.I)
    return text.split()[-1] if text else ""


def _similar(a: str, b: str) -> bool:
    import difflib
    na = re.sub(r"[^a-z0-9 ]", "", a.lower())[:40]
    nb = re.sub(r"[^a-z0-9 ]", "", b.lower())[:40]
    return bool(na and nb) and difflib.SequenceMatcher(None, na, nb).ratio() >= 0.5


def parse_minutes(pages: list[dict], agenda: dict[str, str] | None = None) -> MinutesFacts:
    """pages: [{"n": 1, "text": ...}, ...] as produced by opencivic.extract.

    agenda: optional {outline: title} for this meeting. When given, a line only counts as
    an item heading if its number is on the agenda and its words resemble the item title,
    so numbered lists inside the discussion aren't mistaken for agenda items.
    """
    facts = MinutesFacts()
    head = _flat(" ".join(_norm(p["text"]) for p in pages[:2]))
    m = _PRESENT.search(head)
    if m:
        facts.present = parse_roster(m.group(1))
        facts.absent = parse_roster(m.group(2))

    # One string with page offsets, so each motion can cite its page.
    text, offsets = "", []
    for p in pages:
        offsets.append((len(text), p["n"]))
        text += _norm(p["text"]) + "\n"

    def page_at(pos: int) -> int:
        n = offsets[0][1]
        for start, num in offsets:
            if start <= pos:
                n = num
        return n

    headings = _headings(text)
    if agenda is not None:
        headings = [h for h in headings if h[1] in agenda and _similar(h[2], agenda[h[1]])]
    prev_end = 0
    for vm in _VOTE.finditer(text):
        # The motion is the last "motion by ..." between the previous vote and this one.
        window = text[prev_end:vm.start()]
        movers = list(_MOVER.finditer(window))
        mstart = prev_end + movers[-1].start() if movers else max(prev_end, vm.start() - 1500)
        seconds = list(_SECOND.finditer(text, mstart, vm.start()))
        body = _flat(text[mstart:vm.start()])
        item = next(((o, t) for hs, o, t in reversed(headings) if hs < vm.start()), ("", ""))
        vote = parse_vote(vm.group("vote"))
        num = _NUMBER.search(body)
        act = _ACTION.search(body)
        facts.votes.append({
            "item": item[0], "item_title": item[1][:300], "page": page_at(vm.start()),
            "mover": _who(movers[-1].group("mover")) if movers else "",
            "seconder": _who(seconds[0].group("seconder")) if seconds else "",
            "ayes": vote["ayes"], "nays": vote["nays"], "vote_parsed": vote["parsed"], "roll_call": True,
            "record_number": f"{num.group(1).title()} {_flat(num.group(2))}" if num else "",
            "action": act.group(1) if act else "",
            "result": ("passed" if len(vote["ayes"]) > len(vote["nays"]) else "failed") if vote["parsed"] else "",
            "text": (body[-1200:] + " " + _flat(vm.group(0)))[-1500:],
        })
        prev_end = vm.end()

    # Early minutes record some motions as "... seconded by Y and unanimously carried, ..." with
    # no roll call. Keep them, flagged, unless a roll call follows within the same motion.
    roll_calls = [vm.start() for vm in _VOTE.finditer(text)]
    for cm in _CARRIED.finditer(text):
        nxt = next((r for r in roll_calls if r > cm.start()), None)
        nxt_motion = next((m.start() for m in _MOVER.finditer(text, cm.end())), len(text))
        if nxt is not None and nxt < nxt_motion:
            continue  # this motion has a roll call, already captured above
        item = next(((o, t) for hs, o, t in reversed(headings) if hs < cm.start()), ("", ""))
        body = _flat(text[cm.start():min(nxt_motion, cm.start() + 1500)])
        num = _NUMBER.search(body)
        act = _ACTION.search(body)
        facts.votes.append({
            "item": item[0], "item_title": item[1][:300], "page": page_at(cm.start()),
            "mover": _who(cm.group("mover")), "seconder": _who(cm.group("seconder")),
            "ayes": [], "nays": [], "vote_parsed": True, "roll_call": False,
            "record_number": f"{num.group(1).title()} {_flat(num.group(2))}" if num else "",
            "action": act.group(1) if act else "", "result": "passed", "text": body,
        })
    facts.votes.sort(key=lambda v: v["page"])
    return facts


def canonical_names(all_present: list[list[Attendee]]) -> dict[tuple[str, str], str]:
    """Map (surname, role group) to the most common full name, so 'Ernie Mueller'
    and 'Ernest Mueller' (both City Attorney) become one person."""
    counts: dict[tuple[str, str], Counter] = {}
    for roster in all_present:
        for a in roster:
            group = "elected" if a.role in ELECTED else a.role
            counts.setdefault((a.name.split()[-1], group), Counter())[a.name] += 1
    return {k: c.most_common(1)[0][0] for k, c in counts.items()}
