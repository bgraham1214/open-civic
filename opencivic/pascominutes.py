# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Each Pasco County commissioner's vote, read from the Clerk's annotated-agenda minutes.

Pasco's CivicClerk portal publishes agendas and minutes but no vote data. The Clerk's minutes
("annotated agenda", files titled "BCC ... AA") follow a steady house style:

  C17         Award of Bid No. IFB-BW-26-007 – Central Florida Contractors Inc. – …
              File Number       TED27-0011
              Comm. Dist.       3
              Recommendation Approve

  Approved Staff's recommendation with Commissioner Oakley absent from the vote.

Commissioners are named only when they didn't vote with the majority or didn't vote:
"… with Commissioner Weightman and Chairman Mariano voting nay", "… absent from the vote",
"… abstaining from the vote due to a conflict of interest". Everyone else present voted yes.
Consent items carry no line of their own: one motion approves the consent agenda "with the
exception of Agenda Items C16 and C18 …", and the same for the Public Hearing Consent Agenda.

Each item is joined to its CivicClerk agenda item by meeting date and File Number.

Rules (see the project guide, Guardrails): public comment is never read, and votes to "receive
and file documents submitted by Mr./Ms. …" are skipped because they name residents. An item
whose wording we can't read with confidence (several motions, an unknown name, a dissent we
can't attribute) gets no votes and is reported instead. Nothing is guessed.

  python -m opencivic.pascominutes --data-dir data
    -> data/listings/pasco-minutes-actions.jsonl   one row per decided item
       data/listings/pasco-minutes-votes.jsonl     one row per commissioner per decided item
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

TENANT = "pascocofl"
SEATS = 5           # Pasco's Commission has five districts; a roster of any other size was misread
BOCC = "Board of County Commissioners"

FOOTER = re.compile(r"^\s*(?:BCC\b.*\d{1,2}/\d{1,2}/\d{4}.*|.*\bAA\b.*\d{1,2}/\d{1,2}/\d{4}\s*|Page \d+ of \d+)\s*$", re.I)
ITEM = re.compile(r"^\s{0,3}([A-Z]{1,3}\d{1,3}[a-z]?)\s{2,}(\S.*)$")
FILE_NO = re.compile(r"^\s*File\s+Number\s+(\S+)", re.I)
RECOMMEND = re.compile(r"^\s*Recommendation\b", re.I)
TITLE = r"(?:Second\s+Vice-Chair(?:man|woman)?|Vice-Chair(?:man|woman)?|Chair(?:man|woman)?|Commissioner)"
TITLED = re.compile(rf"{TITLE}\s+([A-Z][A-Za-z'’\-]+)")
STATUS = re.compile(r"(voting\s+(?:nay|no)|absent\s+from\s+the\s+vote|abstain(?:ing|ed)\s+from\s+the\s+vote[^.;,]*|"
                    r"recus(?:ing|ed)\s+(?:himself|herself|themselves)?[^.;,]*)", re.I)
DECISION = re.compile(r"^(Approved|Adopted|Denied|Accepted|Authorized|Ratified|Appointed|Reappointed|Confirmed|"
                      r"Directed|Selected|Awarded|Continued|Tabled|Deferred|The\s+motion|"
                      rf"{TITLE}\s+\S+\s+called\s+on\s+the\s+motion|The\s+item\s+was\s+approved)", re.I)
NO_VOTE = re.compile(r"^(The\s+item\s+(?:\w+\s+)?was\s+(withdrawn|for\s+information|information\s+only|pulled|removed|noted|tabled)|"
                     r"No\s+action\s+(?:was\s+)?required|No\s+action\s+was|There\s+was\s+none|Agenda\s+items?\s+\S+.*were\s+noted|The\s+item\s+was\s+not\s+heard)",
                     re.I)
PERSONAL = re.compile(r"\b(?:Mr|Ms|Mrs|Dr)\.\s+[A-Z]")
RESIDENT_DOCS = re.compile(r"receive\s+and\s+file\s+(?:the\s+)?documents?\s+submitted\s+by", re.I)
DOUBT = re.compile(r"\b(nay|dissent|opposed|absent|abstain|recus|conflict\s+of\s+interest|failed|died|\d\s*-\s*\d\s+vote)\b", re.I)


# --- Reading one set of minutes -------------------------------------------------------------

def lines_of(pages: list[dict]) -> list[str]:
    """All lines, page footers removed, and a paragraph broken by a page break joined up again."""
    out: list[str] = []
    for p in pages:
        ls = [ln.rstrip() for ln in (p.get("text") or "").splitlines() if not FOOTER.match(ln)]
        while ls and not ls[-1].strip():
            ls.pop()
        while ls and not ls[0].strip():
            ls.pop(0)
        if out and ls:
            prev = out[-1].strip()
            if prev and not re.search(r"[.:;]$", prev) and not ITEM.match(ls[0]) and ls[0][:1] not in (" ", "\t") \
                    and ls[0][:1].islower():
                out.extend(ls)          # a sentence that runs on to the next page
                continue
            out.append("")
        out.extend(ls)
    return out


def page_index(pages: list[dict]) -> list[int]:
    """Line number -> page number, matching lines_of()."""
    idx: list[int] = []
    for p in pages:
        ls = [ln for ln in (p.get("text") or "").splitlines() if not FOOTER.match(ln)]
        while ls and not ls[-1].strip():
            ls.pop()
        while ls and not ls[0].strip():
            ls.pop(0)
        if idx and ls:
            idx.append(p["n"])
        idx.extend([p["n"]] * len(ls))
    return idx


def roster(lines: list[str]) -> list[str]:
    """Full names from the 'County Commissioners' list on the first page."""
    names = []
    for ln in lines[:80]:
        m = re.search(r"\bHonorable\s+(.+?),\s*(?:(?:Second\s+)?Vice[- ]?\s*Chair\w*|Chair\w*|District)", ln)
        if m:
            names.append(re.sub(r"\s+", " ", m.group(1)).strip())
        elif names and re.match(r"^\s*(Clerk|County Administrator|County Attorney)", ln):
            break
    return names


def surname(full: str) -> str:
    parts = [p for p in full.replace(",", " ").split() if p.rstrip(".").lower() not in ("jr", "sr", "ii", "iii", "esq")]
    return parts[-1]


def paragraphs(lines: list[str]) -> list[tuple[int, str, bool]]:
    """(first line number, text, starts at the left margin) for each blank-line-separated paragraph."""
    out, cur, start = [], [], 0
    for i, ln in enumerate(lines + [""]):
        if ln.strip():
            if not cur:
                start = i
            cur.append(ln)
        elif cur:
            out.append((start, re.sub(r"\s+", " ", " ".join(x.strip() for x in cur)).strip(), cur[0][:1] not in (" ", "\t")))
            cur = []
    return out


def is_heading(p: str) -> bool:
    """A left-margin heading ('Consent', 'Noted Items', 'Public Hearings at 1:30 p.m.'), not a Clerk's sentence.
    Some action lines lack their final period, so length and the first word decide, not punctuation."""
    if re.search(r"[.)”\"]$", p) and not re.match(r"^Public Hearings at", p):
        return False
    return len(p.split()) <= 6 and not DECISION.match(p) and not NO_VOTE.match(p)


def roll_call_absent(text: str, names: dict[str, str]) -> tuple[set[str], bool]:
    """Members absent for the whole meeting, and whether the roll call was clear enough to use."""
    m = re.search(r"Roll Call\s+(.*?)(?:\nPublic Comment|\nConsent|\nResolutions|\nRegular|$)", text, re.S)
    if not m:
        return set(), False
    rc = re.sub(r"\s+", " ", m.group(1))
    absent = set()
    for clause in re.findall(rf"exception of ((?:{TITLE}\s+\S+?(?:,\s*|\s+and\s+)?)+)\s+who\s+(?:was|were)\s+absent", rc):
        absent |= {s for s in TITLED.findall(clause)}
    for s in re.findall(rf"{TITLE}\s+([A-Z][A-Za-z'’\-]+)\s+(?:was|is)\s+absent", rc):
        absent.add(s)
    late = set(re.findall(rf"{TITLE}\s+([A-Z][A-Za-z'’\-]+)\s+arrived", rc))
    unknown = (absent | late) - set(names)
    clear = bool(re.search(r"All Commissioners were present|called the roll", rc)) or bool(absent)
    # Someone who arrived after the roll call was there for the business; the Clerk marks any vote
    # they missed as "absent from the vote" item by item.
    return absent - late, clear and not unknown


def modifiers(sentence: str, names: dict[str, str]) -> tuple[dict[str, str], str]:
    """{surname: 'No' | 'Absent' | 'Abstained…'} named in a decision, and a problem if any."""
    found: dict[str, str] = {}
    pos = 0
    statuses = list(STATUS.finditer(sentence))
    if not statuses:
        if DOUBT.search(re.sub(r"absent\s+from\s+the\s+meeting", "", sentence)):
            return {}, "dissent or absence we can't attribute"
        return {}, ""
    w = sentence.rfind(" with ", 0, statuses[0].start())
    pos = w + 6 if w >= 0 else 0
    for st in statuses:
        seg = sentence[pos:st.start()]
        who = TITLED.findall(seg)
        if not who:
            return {}, f"no name before “{st.group(1)[:30]}”"
        phrase = st.group(1).lower()
        val = ("No" if phrase.startswith("voting") else "Absent" if phrase.startswith("absent") else
               "Abstained (conflict of interest)" if "conflict" in phrase else "Abstained")
        for s in who:
            if s not in names:
                return {}, f"unknown name {s}"
            found[s] = val
        pos = st.end()
    rest = sentence[pos:]
    if DOUBT.search(rest):
        return {}, "dissent or absence we can't attribute"
    return found, ""


MOVED = re.compile(rf"^({TITLE})\s+(\S+)\s+MOVED\s+(.*?);\s*(?:{TITLE})\s+(\S+)\s+SECONDED", re.I)
CALLED = re.compile(rf"^{TITLE}\s+\S+\s+called\s+on\s+the\s+motion", re.I)
STARTS = (r"Approved|Adopted|Denied|Accepted|Authorized|Ratified|Appointed|Reappointed|Confirmed|Directed|Selected|"
          r"Awarded|Continued|Tabled|Deferred|The\s+motion|The\s+item\s+was|The\s+vote|Discussion\s+was|"
          rf"(?:{TITLE})\s+\S+\s+(?:called|MOVED)|COMMISSIONER\s+\S+\s+MOVED|Mr\.|Ms\.|Mrs\.|Dr\.")


def sentences(par: str) -> list[str]:
    """Split a paragraph only where a new Clerk's sentence starts (so 'Mr. Smith' or 'p.m. on' never splits)."""
    return [x.strip() for x in re.split(rf"(?<=[.;])\s+(?=(?:{STARTS})\b)", par) if x.strip()]


def outcome(sentence: str, motion: str = "") -> tuple[str, str]:
    """(action, result) from a decision sentence and, in the long form, the motion it voted on."""
    s = sentence.lower()
    m = motion.lower()
    if re.search(r"\b(died|failed|did not pass|motion was defeated)\b", s):
        return "Failed", "Fail"
    what = m or s
    if what.startswith("denied") or re.match(r"(approval\s+)?(of\s+)?(to\s+)?den(y|ial)", what):
        return "Denied", "Pass"
    if re.match(r"(approved\s+|approval\s+)?(to\s+)?continu", what) or what.startswith("continued"):
        return "Continued", "Pass"
    if re.match(r"(approved\s+|approval\s+)?(to\s+)?(table|defer)", what) or re.match(r"tabled|deferred", what):
        return "Postponed", "Pass"
    if "consent agenda" in what:
        return "Approved (consent agenda)", "Pass"
    if re.match(r"adopted|(approved\s+|approval\s+)?(to\s+)?adopt", what):
        return "Adopted", "Pass"
    return "Approved", "Pass"


def _codes(text: str) -> list[str]:
    return re.findall(r"\b([A-Z]{1,3}\d{1,3}[a-z]?)\b", text)


def units(sents: list[str]) -> list[dict]:
    """Decisions in an item: {sentence (the vote), motion, mover, seconder}. Long form pairs MOVED with 'called on the motion'."""
    out, pending = [], None
    for x in sents:
        if RESIDENT_DOCS.search(x):
            pending = None
            continue
        mv = MOVED.match(x)
        if mv:
            pending = {"motion": mv.group(3).strip(), "mover": mv.group(2), "seconder": mv.group(4)}
            continue
        if CALLED.match(x) or (pending and re.match(r"The\s+(motion|vote)\b", x, re.I)):
            out.append({"sentence": x, **(pending or {"motion": "", "mover": "", "seconder": ""})})
            pending = None
            continue
        if DECISION.match(x):
            out.append({"sentence": x, "motion": "", "mover": "", "seconder": ""})
    return out


def consent_motions(paras: list[tuple[int, str, bool]]) -> dict[str, dict]:
    """'regular' and 'hearing' consent motions: the sentence carrying the vote, and the codes excepted."""
    out = {}
    sents = [x for _, p, _ in paras for x in sentences(p)]
    for i, x in enumerate(sents):
        m = re.search(r"(?:MOVED\s+approval\s+of\s+|^Approved\s+(?:of\s+|to\s+adopt\s+|to\s+approve\s+)?)the\s+(Public\s+Hearing\s+)?Consent\s+Agenda\b(.*)", x, re.I)
        if not m:
            continue
        kind = "hearing" if m.group(1) else "regular"
        rest = m.group(2)
        cut = re.search(r"exception", rest, re.I)
        excepted = _codes(rest[cut.start():]) if cut else []
        if MOVED.match(x):
            vote = next((y for y in sents[i + 1:i + 3] if CALLED.match(y)), None)
            if not vote:
                continue
        else:
            # who dissented is named after the exception list: drop the list before reading names
            vote = re.sub(r"with the exception of .*?(?=\bwith\s+(?:" + TITLE + r")|$)", "", x, flags=re.I)
        out[kind] = {"sentence": x, "vote": vote, "excepted": excepted}
    return out


def parse(pages: list[dict]) -> tuple[list[dict], list[dict], dict]:
    """-> (decisions, problems, info). A decision: {code, file_number, page, sentence, action, result, votes{surname: vote}}."""
    lines = lines_of(pages)
    pidx = page_index(pages)
    full = roster(lines)
    names = {surname(n): n for n in full}
    info = {"members": full}
    if len(names) != SEATS:
        return [], [{"code": "", "problem": f"roster has {len(names)} names, not {SEATS}"}], info
    text = "\n".join(lines)
    absent_all, clear = roll_call_absent(text, names)
    if not clear:
        return [], [{"code": "", "problem": "roll call unclear"}], info
    info["absent_all"] = sorted(absent_all)
    consent = consent_motions(paragraphs(lines))

    problems: list[dict] = []
    heads = [i for i, ln in enumerate(lines) if ITEM.match(ln)]
    decisions = []
    for a, b in zip(heads, heads[1:] + [len(lines)]):
        code = ITEM.match(lines[a]).group(1)
        block = lines[a:b]
        fno = next((FILE_NO.match(x).group(1) for x in block if FILE_NO.match(x)), "")
        r = next((k for k, x in enumerate(block) if RECOMMEND.match(x)), None)
        if not fno or r is None:
            continue
        acts = []
        for _, p, left in paragraphs(block[r + 1:]):
            if not left or is_heading(p):
                break           # a section heading: the next part of the agenda starts here
            acts.extend(sentences(p))
        page = pidx[a] if a < len(pidx) else None
        base = {"code": code, "file_number": fno, "page": page}
        prefix = re.match(r"[A-Z]+", code).group(0)
        found = units(acts)
        vote_src = None
        if not found:
            if any(NO_VOTE.match(x) for x in acts) or prefix in ("N", "W"):
                continue
            kind = "regular" if prefix in ("C", "AC") else None
            if kind and kind in consent and code in consent[kind]["excepted"]:
                continue        # pulled or withdrawn from the consent agenda, with no vote of its own recorded
            if kind and kind in consent:
                found = [{"sentence": consent[kind]["sentence"], "motion": "", "mover": "", "seconder": ""}]
                vote_src = consent[kind]["vote"]
            else:
                problems.append({**base, "problem": "no decision found"})
                continue
        if len(found) > 1:
            problems.append({**base, "problem": f"{len(found)} motions"})
            continue
        u = found[0]
        if re.search(r"approved\s+as\s+part\s+of\s+the\s+(public\s+hearing\s+)?consent\s+agenda", u["sentence"], re.I):
            kind = "hearing" if re.search(r"hearing", u["sentence"], re.I) else "regular"
            if kind not in consent:
                problems.append({**base, "problem": "consent motion not found"})
                continue
            vote_src = consent[kind]["vote"]
            u = {**u, "sentence": consent[kind]["sentence"]}
        mods, why = modifiers(vote_src or u["sentence"], names)
        if why:
            problems.append({**base, "problem": why})
            continue
        action, result = outcome(u["sentence"], u["motion"])
        votes = {}
        for sn in names:
            votes[sn] = "Absent" if sn in absent_all and sn not in mods else mods.get(sn, "Yes")
        yes = sum(v == "Yes" for v in votes.values())
        no = sum(v == "No" for v in votes.values())
        if result == "Pass" and yes <= no or result == "Fail" and yes > no:
            problems.append({**base, "problem": f"outcome {result} doesn't match {yes} yes / {no} no"})
            continue
        mover = names.get(u["mover"].title(), "") if u["mover"] else ""
        seconder = names.get(u["seconder"].title(), "") if u["seconder"] else ""
        decisions.append({**base, "sentence": (u["motion"] + "; " if u["motion"] else "") + u["sentence"],
                          "action": action, "result": result, "votes": votes, "mover": mover, "seconder": seconder})
    return decisions, problems, info


# --- All Pasco minutes ----------------------------------------------------------------------

def _jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text("utf-8").splitlines() if x.strip()] if p.exists() else []


def minutes_docs(data: Path) -> list[dict]:
    state = json.loads((data / "state.json").read_text("utf-8"))
    return sorted((e for k, e in state.items() if k.startswith(f"civicclerk:{TENANT}:") and e.get("kind") == "Minutes"
                   and e.get("sha256") and BOCC.lower() in (e.get("body") or "").lower()
                   and "workshop" not in (e.get("body") or "").lower()),
                  key=lambda e: (e["date"], e["key"]))


def run(data: Path) -> dict:
    items = [i for i in _jsonl(data / "listings" / f"civicclerk-{TENANT}-items.jsonl") if not i.get("is_section")]
    by_date_file: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for i in items:
        if BOCC.lower() in (i.get("meeting") or "").lower() and i.get("item_number"):
            by_date_file[(i["date"], i["item_number"].strip())].append(i)
    parsed = []
    stats = Counter()
    problems_out = []
    for doc in minutes_docs(data):
        tp = data / "text" / f"{doc['sha256']}.json.gz"
        if not tp.exists():
            stats["no_text"] += 1
            continue
        pages = json.load(gzip.open(tp, "rt", encoding="utf-8"))["pages"]
        decisions, problems, info = parse(pages)
        stats["documents"] += 1
        for p in problems:
            problems_out.append({"date": doc["date"], "doc": doc["key"], **p})
        parsed.append((doc, decisions, info))
    # one spelling per member, the most common across all minutes
    spelling: dict[str, Counter] = defaultdict(Counter)
    for _, _, info in parsed:
        for n in info["members"]:
            spelling[surname(n)][n] += 1
    full = {s: c.most_common(1)[0][0] for s, c in spelling.items()}

    actions, votes, seen = [], [], set()
    for doc, decisions, info in parsed:
        for d in decisions:
            match = by_date_file.get((doc["date"], d["file_number"]), [])
            if len(match) > 1:   # the same file listed twice on one agenda: the item number breaks the tie
                n = re.sub(r"\D", "", d["code"])
                match = [i for i in match if (i.get("outline") or "").rstrip(".") == n]
            if len(match) != 1:
                stats["unmatched" if not match else "ambiguous"] += 1
                problems_out.append({"date": doc["date"], "doc": doc["key"], "code": d["code"], "file_number": d["file_number"],
                                     "problem": "no agenda item with this file number" if not match else "several agenda items"})
                continue
            it = match[0]
            if it["key"] in seen:            # a revised set of minutes for the same meeting: keep the first (newest listed)
                stats["duplicate"] += 1
                continue
            seen.add(it["key"])
            frag = f"#page={d['page']}" if d["page"] else ""
            actions.append({
                "item_key": it["key"], "date": doc["date"], "code": d["code"], "file_number": d["file_number"],
                "action": d["action"], "result": d["result"], "mover": d.get("mover", ""), "seconder": d.get("seconder", ""),
                # the Clerk's sentence, unless it names someone by Mr./Ms. (could be a resident)
                "action_text": "" if PERSONAL.search(d["sentence"]) else d["sentence"],
                "doc_key": doc["key"], "page": d["page"],
                "minutes_url": (doc.get("url") or "") + frag if doc.get("url") else "",
                "minutes_copy_url": (doc.get("copy_url") or "") + frag if doc.get("copy_url") else ""})
            for i, (s, v) in enumerate(sorted(d["votes"].items())):
                person = full.get(s, s)
                votes.append({"key": f"{it['key']}:vote:{re.sub(r'[^a-z]+', '-', person.lower()).strip('-')}",
                              "item_key": it["key"], "date": doc["date"], "body": BOCC, "event_id": it.get("event_id"),
                              "person": person, "vote": v, "sort": i + 1, "source": "pasco-minutes",
                              "doc_key": doc["key"], "page": d["page"]})
            stats["decisions"] += 1
    stats["votes"] = len(votes)
    stats["problems"] = len(problems_out)
    return {"actions": actions, "votes": votes, "problems": problems_out, "stats": dict(stats)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m opencivic.pascominutes", description=__doc__.split("\n")[0])
    ap.add_argument("--data-dir", type=Path, default=Path("data"))
    ap.add_argument("--problems", type=Path, help="write the items we couldn't read here (JSON lines)")
    args = ap.parse_args(argv)
    r = run(args.data_dir)
    lst = args.data_dir / "listings"
    for name in ("actions", "votes"):
        rows = sorted(r[name], key=lambda x: (x["date"], x.get("key") or x["item_key"]))
        (lst / f"pasco-minutes-{name}.jsonl").write_text(
            "".join(json.dumps(x, sort_keys=True, ensure_ascii=False) + "\n" for x in rows), "utf-8")
    if args.problems:
        args.problems.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in r["problems"]), "utf-8")
    print(json.dumps(r["stats"]))
    reasons = Counter(p["problem"].split(" ")[0] if p["problem"].startswith("unknown") else p["problem"] for p in r["problems"])
    print(json.dumps(dict(reasons.most_common())), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
