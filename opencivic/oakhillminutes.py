# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Each Oak Hill City Commissioner's vote, read from the Commission's minutes.

Oak Hill posts its minutes as scanned PDFs on its website (opencivic/weblinks.py collects them and
opencivic/extract.py reads them by OCR). There is no vote data anywhere else. The minutes have been
written by several clerks since 2025, so the same thing is said in many ways (checked Nov 15, 2026
over all 53 sets of minutes from Jan 2025 to Aug 2026):

  Motion to accept Commissioner Werning Second Commissioner Hyatt Action Passed Unanimously
  Commissioner Werning: Made a motion to approve the shed. / Commissioner Hyatt: Seconded /
      Action: Motion passes 5-0 / Mayor Taylor: Yes / Vice Mayor Catigano: Yes / …
  ACTION: MOTION MADE BY COMMISSIONER WERNING … SECONDED BY COMMISSIONER DROLLINGER /
      MAYOR TAYLOR: YES / … / COMMISSIONER HYATT: ABSENT / MOTION PASSED 4-0
  Motion: Vice Mayor Catigano moved to adopt the social media policy. / Seconded by: … /
      Vote: Unanimous approval (5-0)
  Motion by: Commissioner Hyatt Second by: … Vote: Passed 4-1 (Hyatt-Yes, Catigano-Yes, …, Werning-No)
  A motion to … was made by Commissioner Werning, seconded by …, and passed 5-0.
  The motion carried 3-2, with Mayor Taylor and Commissioner Drollinger voting no.

Each stated outcome ("Passed 4-1", "carried unanimously") is one decision. Its votes come from, in
order: a list of every member's vote next to it; or the members present at the roll call, all yes,
except those named as voting no. The count must match: "4-1" needs four present yes and one named
no. Anything else (a split vote with no names, a count that doesn't match the roll call, a name we
don't know) gets no votes and is reported. Nothing is guessed.

The members are read from the minutes themselves (a title, Mayor, Vice Mayor or Commissioner,
followed by a surname that recurs across documents), so a new member after an election is found
without a code change.

The date of each set of minutes is the date it states. The city has posted one meeting's minutes
under another meeting's name (the "07-20-2026" budget workshop minutes are the Jul 13, 2026 meeting's;
checked Nov 15, 2026), so a document whose own date differs from its link is reported, not used.
When a meeting has amended minutes, only those are read.

Rules (see the project guide, Guardrails): public comment is never read for votes, a motion's wording
is left out if it names someone by Mr./Ms./Mrs. (could be a resident), and motions to adjourn aren't
decisions.

  python -m opencivic.oakhillminutes --data-dir data
    -> data/listings/oakhill-minutes-actions.jsonl   one row per decision
       data/listings/oakhill-minutes-votes.jsonl     one row per commissioner per decision
       data/listings/oakhill-minutes-docs.jsonl      each set of minutes: its own date, and whether it was read
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ACCOUNT = "oakhillfl"
SLUG = "oakhill"
SEATS = 5
BODIES = re.compile(r"^City Commission( (Special Meeting|Workshop|Budget Workshop))?$")
TITLE = r"(?:Vice[ -]Mayor|Mayor|Commissioner)"
MONTHS = "january february march april may june july august september october november december".split()

# OCR reads bullet points as a stray letter or mark at the start of a line ("e Commissioner Hyatt: Seconded")
BULLET = re.compile(r"(?m)^[ \t]*(?:[eo•°«»©*|·]|\(e\))[ \t]+(?=[A-Z])")
OUTCOME = re.compile(
    r"(?:\bAction\s*:?\s*(?:Motion\s+)?|\bVote\s*:\s*|\b(?:the\s+)?motion\s+(?:was\s+)?|,?\s+and\s+)"
    r"(?P<res>pass(?:ed|es)|carried|fail(?:ed|s)|unanimous(?:ly)?(?:\s+approval)?)"
    r"(?:[ \t]+(?P<un>unanimously))?"
    r"(?:\s*\(?\s*(?P<y>\d)\s*[-–]\s*(?P<n>\d)\s*\)?)?", re.I)
DISSENT = re.compile(r"\s*,?\s*(?:with|w/)\s+(?P<names>[^.;]{3,140}?)\s+voting\s+(?P<how>no|nay|against|yes|in favor)\b", re.I)
MOTION_START = re.compile(
    r"\bmotion\s*(?::|by\s*:)|\b(?:a\s+)?motion\s+(?:was\s+made\s+)?(?:to|by)\b|\b(?:made|make)\s+(?:a|the)\s+motion\b|"
    r"\bmotion\s+made\s+by\b|\bmoved\s+to\b", re.I)
ADJOURN = re.compile(r"^\W*(?:\w+\W+){0,8}?(?:motion|moved)\s+(?:was\s+made\s+)?to\s+adjourn", re.I)
CAPTION = re.compile(r"\b(?:AN\s+|A\s+)?(?:ORDINANCE|RESOLUTION)\s+(?:NO\.?\s*[\d.-]+\s+)?OF\s+THE\s+CITY\s+OF\s+OAK\s+HILL\b"
                     r"[^\n]*?(?:\n[^\n]*?){0,10}?EFFECTIVE\s+DATE\b\.?", re.I)  # ends at its own last words
# "to not accept Ordinance 2025-01", "to reject the bid": the motion passed, the item didn't
DENY_RX = re.compile(r"^(?:to\s+)?(?:not\s+(?:accept|approve|adopt|pass)|reject|deny)\b", re.I)
PUBLIC_INPUT = re.compile(r"citizen|public\s+(?:input|participation|comment)", re.I)
PERSONAL = re.compile(r"\b(?:Mr|Ms|Mrs|Miss)\.?\s+[A-Z]")
SECTION = re.compile(r"^\s*([A-M])\.\s*(\S.{2,})$")
ITEM = re.compile(r"^\s*(\d{1,2})\.\s*(\S.{2,})$")
HEADER_DATE = re.compile(rf"\b({'|'.join(m[:3] for m in MONTHS)})[a-z]*\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(20\d\d)\b|"
                         r"^\s*(\d{1,2})[-/](\d{1,2})[-/](20\d\d)\b", re.I | re.M)
ALL_PRESENT = re.compile(r"\ball\s+(?:the\s+)?(?:commissioners|members)\s+(?:were\s+)?present|"
                         r"\bpresence\s+of\s+all\s+commissioners|\bwith\s+all\s+commissioners\s+present", re.I)


NOT_NAMES = {"and", "the", "of", "for", "pro", "tem", "city", "commission", "commissioner", "commissioners", "mayor",
             "vice", "seat", "elect", "chair", "member", "members", "meeting", "agenda", "present", "absent",
             "second", "seconded", "action", "made", "moved", "motion", "yes", "no", "here", "responded", "voted",
             "vote", "note", "manager", "attorney", "administrator", "clerk", "staff", "also"}


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text("utf-8").splitlines() if x.strip()] if p.exists() else []


def normalize(pages: list[str]) -> tuple[str, list[int]]:
    """One text, one line per line of the minutes (spaces collapsed, blank lines and OCR bullets
    dropped), and the offset where each page starts."""
    out, starts, pos = [], [], 0
    for p in pages:
        starts.append(pos)
        p = BULLET.sub("", p or "")
        lines = [re.sub(r"[ \t]+", " ", x).strip() for x in p.splitlines()]
        chunk = "\n".join(x for x in lines if x) + "\n"
        out.append(chunk)
        pos += len(chunk)
    return "".join(out), starts


def page_of(starts: list[int], at: int) -> int:
    return max(i for i, s in enumerate(starts) if s <= at) + 1 if starts else 1


def header_date(text: str) -> str:
    """The meeting date the minutes give at the top ("January 13, 2025", "June 23rd, 2025", "7-13-2026 …")."""
    m = HEADER_DATE.search(text[:900])
    if not m:
        return ""
    try:
        if m.group(1):
            return date(int(m.group(3)), [x[:3] for x in MONTHS].index(m.group(1)[:3].lower()) + 1, int(m.group(2))).isoformat()
        return date(int(m.group(6)), int(m.group(4)), int(m.group(5))).isoformat()
    except ValueError:
        return ""


def members_of(texts: list[str]) -> dict[str, str]:
    """surname (lower case) -> the name most often written in full ("Ricky Taylor"), from every set of
    minutes. A surname is a word written alone after a title ("Mayor Taylor", "Commissioner Hyatt
    moved") in at least 3 documents; a word only ever written before another name is a first name.
    Words that follow a name in the clerks' shorthand ("Commissioner Werning Second") aren't names."""
    solo: dict[str, set[int]] = defaultdict(set)
    pairs: dict[tuple[str, str], set[int]] = defaultdict(set)
    for i, t in enumerate(texts):
        for m in re.finditer(rf"\b{TITLE}s?\s+([A-Z][A-Za-z]+(?![A-Za-z'’]))(?:\s+([A-Z][A-Za-z]+(?![A-Za-z'’])))?", t):
            words = [w.title() for w in m.groups() if w]
            if words[0].lower() in NOT_NAMES:
                continue
            if len(words) == 2 and words[1].lower() not in NOT_NAMES:
                pairs[(words[0], words[1])].add(i)
            else:
                solo[words[0]].add(i)
    surnames = {w for w, docs in solo.items() if len(docs) >= 3}
    surnames |= {b for (a, b), docs in pairs.items() if len(docs) >= 3 and a not in surnames}
    out = {}
    for s in surnames:
        full = Counter({f"{a} {b}": len(docs) for (a, b), docs in pairs.items() if b == s and a not in surnames})
        out[s.lower()] = full.most_common(1)[0][0] if full else s
    return out


def roll_call(text: str, members: dict[str, str]) -> tuple[set[str] | None, set[str]]:
    """(present, absent) surnames from the roll call; present is None when it can't be read, or when
    it only says "all commissioners were present" (the caller fills in the members)."""
    m = re.search(r"roll\s*call|\bpresent\s*:", text[:6000], re.I)
    if not m:
        return None, set()
    w = text[m.start(): m.start() + 900]
    end = re.search(r"\n\s*(?:B\.|AGENDA MODIFICATIONS|Agenda Modifications)|\bAGENDA MODIFICATIONS\b", w[10:])
    w = w[: end.start() + 10] if end else w[:600]
    if ALL_PRESENT.search(w) and not re.search(r"\babsent\b(?!\s*:?\s*none)", w, re.I):
        return set(members), set()
    present, absent = set(), set()
    absent_at = re.search(r"\b(?:absent|excused)\b(?!\s*:?\s*none)\s*:?", w, re.I)
    for s in members:
        hits = [x for x in re.finditer(rf"\b{s}\b", w, re.I)]
        if not hits:
            continue
        x = hits[0]
        after = w[x.end(): x.end() + 25]
        # "Drollinger — Absent", "Hyatt: Absent"; not the next line's "Absent:" heading
        if re.match(r"[ \t]*[:—–-][ \t]*(?:absent|excused)\b(?!\s*:)", after, re.I):
            absent.add(s)
        elif re.match(r"\s*[:—–-]?\s*(?:present|here)|\s+responded", after, re.I):
            present.add(s)
        elif absent_at and x.start() > absent_at.start() and not re.search(r"staff|also present", w[absent_at.end(): x.start()], re.I):
            absent.add(s)
        else:
            present.add(s)
    if len(present) + len(absent) != SEATS:
        return None, absent
    return present, absent


def _surnames_in(s: str, members: dict[str, str]) -> list[str]:
    return [m for m in members if re.search(rf"\b{m}\b", s, re.I)]


def _roll_lists(text: str, members: dict[str, str]) -> list[dict]:
    """Runs of three or more "Mayor Taylor: Yes" / "Hyatt-Yes" / "COMMISSIONER HYATT: ABSENT" entries."""
    names = "|".join(sorted(members, key=len, reverse=True))
    rx = re.compile(rf"(?:{TITLE}\s+(?:[A-Za-z]+\s+)?)?\b({names})\b\s*(?:[:—–-]|\s)\s*(?:voted\s*[\"\u201c]?\s*)?(yes|aye|no|nay|absent|abstain(?:ed)?)\b", re.I)
    runs, cur = [], []
    for m in rx.finditer(text):
        if cur and m.start() - cur[-1].end() > 40:
            runs.append(cur)
            cur = []
        cur.append(m)
    if cur:
        runs.append(cur)
    out = []
    for r in runs:
        if len(r) < 3:
            continue
        votes = {}
        for m in r:
            v = m.group(2).lower()
            votes[m.group(1).lower()] = "Yes" if v in ("yes", "aye") else "No" if v in ("no", "nay") else \
                "Absent" if v == "absent" else "Abstain"
        out.append({"start": r[0].start(), "end": r[-1].end(), "votes": votes, "dupes": len(r) != len(votes)})
    return out


NAME = r"[A-Z][a-z'’]+(?:\s[A-Z][a-z'’]+)?"   # "Werning", "Carrie Werning" (case-sensitive)
WHO = rf"(?:Vice[ -]Mayor|Mayor|Commissioner)\s+{NAME}"


def _plain(raw: str) -> str:
    s = re.sub(r"\s+", " ", raw).strip()
    letters = [c for c in s if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) > 0.6 * len(letters):  # an all-caps clerk
        s = s.title().replace("’S ", "’s ").replace("'S ", "'s ")
    return s


def _clause(raw: str) -> str:
    """The motion's own words, without the mover, seconder and vote bookkeeping around them:
    "Motion to add the Garden Street item to the agenda was made by Mayor Taylor and seconded by
    Commissioner Werning." -> "To add the Garden Street item to the agenda"."""
    s = _plain(raw)
    caps = s != re.sub(r"\s+", " ", raw).strip()
    # "Motion by Commissioner Werning, seconded by Mayor Taylor, to approve the consent agenda …"
    m = re.search(rf"\b[Ss]econd(?:ed)?\s+by\s*:?\s*{WHO},?\s+(to\s.+)$", s)
    if m:
        s = m.group(1)
    s = re.sub(rf"\s*(?:and\s+)?(?:it\s+was\s+|It\s+was\s+)?(?:{WHO}\s*:?\s*)?\b[Ss]econd(?:ed)?\b.*$", "", s)
    s = re.sub(rf"^(?:Action\s*:\s*)?[Mm]otion\s+[Mm]ade\s+[Bb]y\s*:?\s*{WHO}\s+(?:[Ff]or\s+(?=[Uu]p\s)|(?=[Tt]o\s|[Ff]or\s))?", "", s)
    s = re.sub(rf",?\s+(?:was\s+)?[Mm]ade\s+[Bb]y\s*:?\s*{WHO}.*$", "", s)
    s = re.sub(r"^.{0,80}?\b(?:I'll|I’ll|I'd\s+like\s+to|I’d\s+like\s+to|I)\s+make\s+a\s+motion\s+(?:that\s+we\s+|to\s+)?", "", s)
    s = re.sub(r"\s*\b(?:Action|Vote)\s*:?\s*$", "", s)
    s = re.sub(rf"^{WHO}\s*:\s*(?=[Mm]otion\b|[Mm]ade\b|[Mm]oved\b)", "", s)      # "Commissioner Werning: Motion to …"
    s = re.sub(rf"^(?:Motion\s*:\s*|Motion\s+by\s*:?\s*)?(?:{WHO}\s*:?\s*)?"
               r"(?:[Mm]ade\s+(?:a|the)\s+[Mm]otion\s*:?\s*(?:[Ff]or\s+(?=\S+\s+to\s))?|[Mm]oved\s+)", "", s)
    s = re.sub(r"^(?:[Tt]o\s+)?make\s+a\s+motion\s+(?:for|to|that)\s+", "", s)
    s = re.sub(r"^\W*(?:I'll\s+|I'd\s+like\s+to\s+|I\s+)?(?:[Mm]ake|[Mm]ade)\s+a\s+motion\s+(?:that\s+we\s+|to\s+)?", "", s)
    s = re.sub(r"^(?:A\s+)?[Mm]otion\s+(?:was\s+made\s+)?", "", s)
    s = re.sub(r"^[Mm]oved\s+(?=to\s)", "", s)
    s = re.sub(rf"^(?:Motion\s*:?\s*)?{WHO}\s+(?=to\s)", "", s)        # "Motion: Commissioner Werning to approve …"
    s = re.sub(rf"\s+{WHO}\s*$", "", s)                                  # "Motion to accept Commissioner Werning"
    s = re.split(rf"\.\s+(?={WHO}\s*:)|(?<=[.?!])[\"”]|\.\s+(?:A\s+)?[Mm]otion\b", s)[0]  # a new speaker, a closing quote, a restated motion
    s = re.sub(r"[.\s]+(?:It\s+was|and)$", "", s)
    if len(s.split()) <= 3:
        s = s[:1] + s[1:].lower()  # "To Table" -> "To table"
    s = s.strip(" .,;:-\"“”")
    if not re.search(r"[a-z]{3}", s) or re.fullmatch(r"(?:Motion|By .*)", s):
        return ""
    if caps:  # an all-caps clerk: sentence case reads better than Title Case
        s = s.lower()
    return (s[:1].upper() + s[1:])[:400]


def _people(raw: str, members: dict[str, str]) -> tuple[str, str]:
    """(mover, seconder) surnames, where the wording says so. The same member for both is a clerk's
    slip (Mar 9, 2026), so then only the mover is kept."""
    s = _plain(raw)
    names = "|".join(n.title() for n in members)
    who = rf"(?:Vice[ -]Mayor|Mayor|Commissioner)\s+(?:[A-Z][a-z]+\s+)?({names})\b"
    mover = (re.search(rf"\b({names})\b\s*:?\s*(?:[Mm]ade\s+(?:a|the)\s+[Mm]otion|[Mm]oved|:\s*[Mm]otion)\b", s)
             or re.search(rf"\b(?:[Mm]otion\s+)?(?:was\s+)?[Mm]ade\s+[Bb]y\s*:?\s*{who}", s)
             or re.search(rf"\b[Mm]otion\s*(?:by\s*)?:\s*{who}", s)
             or re.search(rf"\b[Mm]otion\s+by\s+{who}", s)
             or re.search(rf"{who}\s*,?\s*[Ss]econd", s))
    second = (re.search(rf"\b[Ss]econd(?:ed)?(?:\s*-?\s*by)?\s*:?\s*{who}", s)
              or re.search(rf"\b({names})\b\s*:?\s*[Ss]econded\b", s))
    mv = mover.group(1).lower() if mover else ""
    sc = second.group(1).lower() if second else ""
    return mv, ("" if sc == mv else sc)


def _heading(text: str, at: int) -> tuple[str, str]:
    """(number, title) of the agenda section or item the motion falls under, e.g. ("F.4.",
    "Indian Harbor Estates Septic to Sewer Pay Request - Metro Equipment Service, Inc.")."""
    before = text[:at].splitlines()
    sec, sec_title, item, item_title = "", "", "", ""
    for line in before:
        m = SECTION.match(line)
        if m and (m.group(2)[:1].isupper()) and len(m.group(2)) < 90:
            sec, sec_title, item, item_title = m.group(1), m.group(2), "", ""
            continue
        m = ITEM.match(line)
        if m and sec and len(m.group(2)) < 160 and not re.match(rf"{TITLE}\b", m.group(2)):
            item, item_title = m.group(1), m.group(2)
    def tidy(t: str) -> str:
        t = re.sub(r"\s+\d{1,2}:\d{2}(?::\d{2})?$", "", t).strip(" .:")  # a video timestamp ("Consent Agenda 53:15")
        return t.title() if t.isupper() else t
    if PUBLIC_INPUT.search(sec_title):
        return (f"{sec}." if sec else ""), ""   # public comment: never a resident's name as a title
    if item:
        return f"{sec}.{item}.", tidy(item_title)
    return (f"{sec}." if sec else ""), tidy(sec_title)


def parse(pages: list[str], members: dict[str, str], roster_hint: set[str] | None = None) -> tuple[list[dict], list[dict], dict]:
    """(decisions, problems, info) for one set of minutes."""
    text, starts = normalize(pages)
    present, absent = roll_call(text, members)
    info = {"roll_call": "read" if present is not None else "not read"}
    if present is None and roster_hint and ALL_PRESENT.search(text[:6000]):
        present, info["roll_call"] = set(roster_hint), "all present"
    if present is not None and len(present) + len(absent) != SEATS and info["roll_call"] != "all present":
        present = None
    lists = _roll_lists(text, members)
    used: set[int] = set()
    anchors = []
    for m in OUTCOME.finditer(text):
        res = m.group("res").lower()
        unanimous = bool(m.group("un")) or res.startswith("unanim") or (m.group("n") == "0" and m.group("y"))
        if not (unanimous or m.group("y")):
            continue  # "the motion passed" with no count or "unanimously": not enough to say who voted
        anchors.append(m)
    decisions, problems = [], []
    floor = 0
    for k, m in enumerate(anchors):
        res = m.group("res").lower()
        passed = not res.startswith("fail")
        y, n = (int(m.group("y")), int(m.group("n"))) if m.group("y") else (None, None)
        unanimous = bool(m.group("un")) or res.startswith("unanim") or n == 0
        # the motion: the last motion wording before the outcome, after the previous decision
        lo = max(floor, m.start() - 1500)
        starts_ = [x for x in MOTION_START.finditer(text, lo, m.start())]
        if not starts_:
            problems.append({"page": page_of(starts, m.start()), "problem": "outcome with no motion before it",
                             "text": text[max(0, m.start() - 120): m.end()]})
            continue
        st = starts_[-1].start()
        for x in reversed(starts_[:-1]):  # "Motion: Commissioner Hyatt moved to …": start at "Motion:"
            if st - x.end() < 120:
                st = x.start()
            else:
                break
        # a "Name: Made a motion" format puts the mover's name first
        line_start = text.rfind("\n", 0, st) + 1
        if re.match(rf"\s*{TITLE}\s+(?:[A-Za-z]+\s+)?[A-Za-z]+\s*:?\s*$", text[line_start:st]):
            st = line_start
        else:
            w = re.search(rf"{TITLE}\s+(?:[A-Z][a-z]+\s+)?[A-Z][a-z]+\s*:?\s*$", text[max(0, st - 60):st])
            if w and re.match(r"\s*(?:made|make)\b", text[st:], re.I):
                st = max(0, st - 60) + w.start()
        raw = text[st: m.start()]
        # a list of each member's vote, right before or right after the outcome
        near = None
        for i, r in enumerate(lists):
            if i in used:
                continue
            if 0 <= r["start"] - m.end() <= 60 or 0 <= m.start() - r["end"] <= 80 or (st <= r["start"] and r["end"] <= m.start()):
                near = i
                break
        if near is not None:
            used.add(near)
            raw = text[st: min(m.start(), lists[near]["start"]) if lists[near]["start"] > st else m.start()]
        floor = max(m.end(), lists[near]["end"] if near is not None else 0)
        if k + 1 < len(anchors) and floor > anchors[k + 1].start():
            floor = anchors[k + 1].start()
        if ADJOURN.search(raw):
            continue
        number, title = _heading(text, st)
        clause = _clause(raw)
        mover, second = _people(raw, members)
        page = page_of(starts, st)
        verb = re.match(r"(?:to\s+)?(\w+)", clause.lower()) if clause else None
        # the ordinance or resolution's own caption, when the minutes print it under the item
        cap = None
        for cap in CAPTION.finditer(text, max(lo, text.rfind("\n", 0, max(lo, st - 2500)) if lo else 0), st):
            pass
        caption = re.sub(r"\s+", " ", cap.group(0)).strip() if cap else ""
        d = {"page": page, "number": number, "title": title, "motion": clause, "passed": passed, "caption": caption,
             "tally": f"{y}-{n}" if y is not None else ("unanimous" if unanimous else ""),
             "action": "deny" if DENY_RX.search(clause) else
             verb.group(1) if verb and verb.group(1) in ("table", "postpone", "continue", "defer") else "approve", "mover": mover, "seconder": second, "sentence": re.sub(r"\s+", " ", text[st: m.end()])[:600]}
        why = ""
        votes: dict[str, str] = {}
        if near is not None:
            votes = dict(lists[near]["votes"])
            if lists[near]["dupes"]:
                why = "a member is listed twice in the vote list"
            for s in members:
                votes.setdefault(s, "Absent" if s in absent else "Not recorded")
            yes = sum(v == "Yes" for v in votes.values())
            no = sum(v == "No" for v in votes.values())
            if y is not None and (yes, no) not in ((y, n), (n, y)):
                why = f"the vote list ({yes}-{no}) doesn't match the stated count ({y}-{n})"
        else:
            dis = DISSENT.match(text, m.end())
            named = _surnames_in(dis.group("names"), members) if dis else []
            if present is None:
                why = "the roll call couldn't be read, so we can't say who was present"
            elif unanimous:
                if y is not None and y != len(present):
                    why = f"{y} voted but the roll call shows {len(present)} present"
                votes = {s: ("Yes" if s in present else "Absent") for s in members}
            elif not dis:
                why = f"a {y}-{n} vote that doesn't say who voted which way"
            elif len(named) != (n if dis.group("how").lower() in ("no", "nay", "against") else y):
                why = f"a {y}-{n} vote naming {len(named)} member(s) on the other side"
            elif y + n != len(present):
                why = f"a {y}-{n} vote but the roll call shows {len(present)} present"
            else:
                minority = "No" if dis.group("how").lower() in ("no", "nay", "against") else "Yes"
                majority = "Yes" if minority == "No" else "No"
                votes = {s: (minority if s in named else majority) if s in present else "Absent" for s in members}
        if why:
            problems.append({"page": page, "number": number, "problem": why, "text": d["sentence"][:300]})
            continue
        d["votes"] = votes
        decisions.append(d)
    info["decisions"] = len(decisions)
    return decisions, problems, info


def _docs(data: Path) -> list[dict]:
    state = json.loads((data / "state.json").read_text("utf-8")) if (data / "state.json").exists() else {}
    return sorted((v for k, v in state.items() if k.startswith(f"weblinks:{ACCOUNT}:") and v.get("kind") == "Minutes"
                   and v.get("listed", True) and v.get("sha256")), key=lambda v: (v["date"], v["key"]))


def _pages(data: Path, sha: str) -> list[str] | None:
    p = data / "text" / f"{sha}.json.gz"
    if not p.exists():
        return None
    d = json.loads(gzip.decompress(p.read_bytes()))
    return [x if isinstance(x, str) else x.get("text", "") for x in d.get("pages", [])]


def run(data: Path) -> dict:
    docs = []
    for v in _docs(data):
        pages = _pages(data, v["sha256"])
        if pages is not None:
            docs.append((v, pages))
    members = members_of(["\n".join(p) for _, p in docs])
    stats: Counter = Counter()
    problems_out, doc_rows = [], []
    # which document speaks for each meeting: its own date must match; amended minutes win
    chosen: dict[tuple[str, str], tuple[dict, list[str]]] = {}
    for v, pages in docs:
        own = header_date("\n".join(pages)[:900])
        row = {"key": v["key"], "date": v["date"], "body": v.get("body", ""), "title": v.get("title", ""), "stated_date": own}
        doc_rows.append(row)
        if own and own != v["date"]:
            row["used"] = False
            row["why"] = f"posted as the {v['date']} minutes, but the document is the minutes of {own}"
            problems_out.append({"date": v["date"], "doc": v["key"], "problem": row["why"]})
            stats["misfiled"] += 1
            continue
        if not BODIES.match(v.get("body", "")):
            row["used"] = False
            row["why"] = "not a City Commission meeting"
            continue
        k = (v["date"], v.get("body", ""))
        prev = chosen.get(k)
        if prev is None or (re.search(r"amend", v.get("title", ""), re.I) and not re.search(r"amend", prev[0].get("title", ""), re.I)):
            chosen[k] = (v, pages)
    for row in doc_rows:
        if "used" in row:
            continue
        pick = chosen.get((row["date"], row["body"]))
        row["used"] = bool(pick and pick[0]["key"] == row["key"])
        if not row["used"]:
            row["why"] = "another version of these minutes (amended) was read instead"
            stats["older version"] += 1
    actions, votes = [], []
    last_roster: set[str] | None = None
    for (d_, body), (v, pages) in sorted(chosen.items()):
        decisions, problems, info = parse(pages, members, last_roster)
        p, _ = roll_call(normalize(pages)[0], members)
        if p is not None and len(p) == SEATS:
            last_roster = p
        stats["documents"] += 1
        stats["roll call " + info["roll_call"]] += 1
        for pr in problems:
            problems_out.append({"date": d_, "doc": v["key"], **pr})
        for i, d in enumerate(decisions, 1):
            key = f"{v['key']}:motion:{i}"
            frag = f"#page={d['page']}"
            # wording that names someone as Mr./Ms. could be a resident: left out (see Guardrails)
            actions.append({
                "key": key, "date": d_, "body": body, "doc_key": v["key"], "page": d["page"], "number": d["number"],
                "title": "" if PERSONAL.search(d["title"]) else d["title"], "caption": d["caption"],
                "motion": "" if PERSONAL.search(d["motion"]) else d["motion"],
                "action": d["action"], "result": "Pass" if d["passed"] else "Fail", "tally": d["tally"],
                "mover": members.get(d["mover"], ""), "seconder": members.get(d["seconder"], ""),
                "minutes_url": (v.get("url") or "") + frag if v.get("url") else "",
                "minutes_copy_url": (v.get("copy_url") or "") + frag if v.get("copy_url") else ""})
            for j, (s, vote) in enumerate(sorted(d["votes"].items())):
                person = members.get(s, s)
                votes.append({"key": f"{key}:vote:{re.sub(r'[^a-z]+', '-', person.lower()).strip('-')}", "item_key": key,
                              "date": d_, "body": body, "person": person, "vote": vote, "sort": j + 1,
                              "source": "oakhill-minutes", "doc_key": v["key"], "page": d["page"]})
            stats["decisions"] += 1
    # each member's title, as the newest minutes that name them write it ("Mayor Taylor"); the Vice Mayor's
    # seat rotates, so pages show only Mayor or City Commissioner
    titles = []
    for s, full in sorted(members.items()):
        title = ""
        for (d_, _), (v, pages) in sorted(chosen.items(), reverse=True):
            found = Counter(re.sub(r"\s+", " ", t).title().replace("Vice-Mayor", "Vice Mayor")
                            for t in re.findall(rf"\b({TITLE})\s+(?:[A-Z][a-z]+\s+)?{s.title()}\b", "\n".join(pages)))
            if found:
                title = found.most_common(1)[0][0]
                break
        titles.append({"key": s, "date": "", "name": full, "title": title})
    stats["votes"] = len(votes)
    stats["no"] = sum(v["vote"] == "No" for v in votes)
    stats["problems"] = len(problems_out)
    stats["members"] = len(members)
    return {"actions": actions, "votes": votes, "docs": doc_rows, "members_rows": titles, "problems": problems_out,
            "members": members, "stats": dict(stats)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m opencivic.oakhillminutes", description=__doc__.split("\n")[0])
    ap.add_argument("--data-dir", type=Path, default=Path("data"))
    ap.add_argument("--problems", type=Path, help="write the votes we couldn't read here (JSON lines)")
    args = ap.parse_args(argv)
    r = run(args.data_dir)
    lst = args.data_dir / "listings"
    for name in ("actions", "votes", "docs"):
        rows = sorted(r[name], key=lambda x: (x["date"], x["key"]))
        (lst / f"oakhill-minutes-{name}.jsonl").write_text(
            "".join(json.dumps(x, sort_keys=True, ensure_ascii=False) + "\n" for x in rows), "utf-8")
    (lst / "oakhill-minutes-members.jsonl").write_text(
        "".join(json.dumps(x, sort_keys=True, ensure_ascii=False) + "\n" for x in r["members_rows"]), "utf-8")
    if args.problems:
        args.problems.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in r["problems"]), "utf-8")
    print(json.dumps({**r["stats"], "names": sorted(r["members"].values())}))
    print(json.dumps(dict(Counter(re.sub(r"\d", "N", p["problem"]) for p in r["problems"]).most_common())), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
