# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Hillsborough County Clerk: the Board of County Commissioners' Master Voting Record.

The clerk publishes one PDF per year ("Vote Comparison", rendered by Microsoft Reporting
Services) plus one for the current year, linked from

    https://www.hillsclerk.com/en/Records-and-Reports/BOCC

Each roll call is a row: RCS number, agenda item, date, time, category, then one vote
code per commissioner in the header's column order, followed by the subject and motion
on the next lines. Checked Nov 9, 2026: every 2025 and 2026 row has exactly one code
per commissioner column (545 and 408 rows). hillsclerk.com's robots.txt allows all.

The clerk defines the categories (below). It does not define the vote codes; Y and N are
yes and no, and X and A are kept exactly as printed.

Usage:
  python -m opencivic.hillsclerk list --since 2025 -o listing.jsonl
  python -m opencivic.hillsclerk votes --listing listing.jsonl -o votes.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

from .fetch import Fetcher, FetchError, HttpFetcher

PAGE = "https://www.hillsclerk.com/en/Records-and-Reports/BOCC"
BODY = "Board of County Commissioners"

# From the clerk's page (Master Voting Record, "Actions Categories").
CATEGORIES = {
    "0": "Miscellaneous", "1": "Alcoholic Beverage", "2": "Environmental Protection Commission",
    "3": "Land Excavation", "4": "Mining Operation", "5": "Ordinances",
    "6": "Comprehensive Plan Amendments", "7": "Taxation", "8": "Transportation", "9": "Zoning",
}
# Members whose full names appear in neither the 2014-2017 reports nor Legistar. Public record:
# elected Nov 2018 and left Nov 2022 (Smith, Overman); elected Nov 2022 (Owen). Sources:
# ballotpedia.org/Municipal_elections_in_Hillsborough_County,_Florida_(2018);
# archive.planhillsborough.org/tpo-welcomes-new-board-members-and-officers (Jan 2023)
EXTRA_FULL_NAMES = ["Mariella Smith", "Kimberly Overman", "Michael Owen"]
CODES = {"Y": "Yes", "N": "No"}  # X and A are undefined by the clerk; kept as printed

LINK_RX = re.compile(r'href="(/documents/d/guest/bocc[-_]vote[^"]*)"', re.I)
# One row per roll call. Two layouts:
#   2018 on (Reporting Services):  "4692      C-1   01/07/2025   9:03AM   0   Y  Y  X  Y ..."
#   2014-2017 (Acrobat):           "68  CHANGES  1/8/2014 9:19 AM 0   Y  Y  X ..."
# The category may be blank or carry a stray dot ("9."); old times can be cut short ("10:16 A");
# vote cells are blank where a member wasn't on the board yet or anymore.
ROW_RX = re.compile(r"^\s*(\d{1,6})\s+(?:(\S.*?)\s+)?(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}:\d\d\s?(?:[AP]M?)?)"
                    r"(?:\s+(\d)\.?)?(?:\s+((?:[A-Za-z]\s+)*[A-Za-z]))?\s*$")  # 2016 has some lowercase codes
HEADER_RX = re.compile(r"RCS\s*#.*(Cat\.|Subject\s*\S?\s*Action)")  # scans misread "/" as "I" or "!"
LEGACY_NAME_RX = re.compile(r"([A-Z][\w'-]+(?: [A-Z][\w'-]+)?)\. ([A-Z][\w'-]+)")
# 2014-2017 reports end with the search settings used to print them
SUMMARY_RX = re.compile(r"Begin Date:|End Date:|Vote Types:|Sort Order:|Bills: ALL|Subjects: ALL")
VOID_RX = re.compile(r"\bVOID\b.*\btest", re.I)  # clerk test entries, e.g. "RCS #4228 - VOID – Test run"
SKIP_RX = re.compile(r"^\s*(Hillsborough County Commissioners|Vote Comparison|Item #|Printed:.*|End of \w+|"
                     r"St\w{3,6} Session.*|Selected Members.*|\d{1,3})\s*$")  # scans misread "Starting" ("Stalling")


def list_documents(html: str, since: int, today: date | None = None) -> list[dict]:
    """The yearly reports from `since` on, plus the current-year report."""
    today = today or date.today()
    out = {}
    for href in LINK_RX.findall(html):
        m = re.search(r"(20\d\d)", href)
        year = int(m.group(1)) if m else None
        if year is not None and year < since:
            continue
        label = str(year) if year else "current"
        out[label] = {
            "key": f"hillsclerk:bocc-votes:{label}", "source": "hillsclerk", "label": label,
            "url": urljoin(PAGE, href), "page": PAGE, "body": BODY, "kind": "Vote record",
            "title": f"BOCC Master Voting Record, {year}" if year else "BOCC Master Voting Record, current year",
            # a fixed date, so the nightly listing doesn't change every day
            "date": f"{year or today.year}-12-31",
        }
    return sorted(out.values(), key=lambda d: d["label"])


def _is_name_line(line: str) -> bool:
    """The staggered member names above a 2014-2017 header ("Crist. Victor   Hagan. Ken"): deeply
    indented. Subject text ("...the Agenda. Moved approval.") is not."""
    return len(line) - len(line.lstrip()) > 40 and bool(LEGACY_NAME_RX.search(line))


def _columns(header: str, continuation: str | None) -> list[tuple[float, str]]:
    """(center x, name) per member column of a 2018-on header, with any second line joined."""
    start = header.index("Cat.") + len("Cat.")
    cols = [(m.start() + start, m.group(0)) for m in re.finditer(r"\S+(?: \S+)*", header[start:])]
    names = [n for _, n in cols]
    if continuation:
        for m in re.finditer(r"\S+", continuation):
            i = max((k for k, (pos, _) in enumerate(cols) if pos <= m.start() + 2), default=0)
            names[i] = f"{names[i]} {m.group(0)}"
    return [(pos + len(cols[k][1]) / 2, names[k]) for k, (pos, _) in enumerate(cols)]


def _legacy_columns(lines: list[str]) -> list[tuple[float, str]]:
    """(center x, "First Last") from a 2014-2017 header, whose names are staggered over two lines."""
    out = []
    for line in lines:
        for m in LEGACY_NAME_RX.finditer(line):
            out.append((m.start() + (m.end() - m.start()) / 2, f"{m.group(2)} {m.group(1)}"))
    return sorted(out)


def _place(rows: list[dict], cols: list[tuple[float, str]], problems: list[str]) -> None:
    """Give each code in each row its column, by position under the page's header.

    Rows sit a few characters off the header, by a page-wide amount; that shift is found
    first (the one that puts codes closest to column centres), then each code goes to the
    nearest shifted centre. A code that isn't clearly nearer one column, or two codes
    landing in one column, makes the row a problem rather than a guess.
    """
    if not rows:
        return
    if not cols:
        for r in rows:
            problems.append(f"RCS {r['rcs']}: no header on its page")
            r["votes"] = None
        return
    centers = [c for c, _ in cols]
    xs = [x for r in rows for x, _ in r["_codes"]]

    def cost(shift: float) -> float:
        return sum(min(abs(x - c - shift) for c in centers) for x in xs)

    shift = min((s / 2 for s in range(-40, 41)), key=cost)
    gaps = [b - a for a, b in zip(centers, centers[1:])] or [20]
    tol = min(gaps) / 2
    for r in rows:
        votes, used, bad = [], set(), False
        for x, code in r["_codes"]:
            d = sorted((abs(x - c - shift), j) for j, c in enumerate(centers))
            if d[0][0] > tol or (len(d) > 1 and d[1][0] - d[0][0] < 1.0) or d[0][1] in used:
                bad = True
                break
            used.add(d[0][1])
            votes.append({"name": cols[d[0][1]][1], "code": code})
        known = {"Y", "N", "X", "A"}
        if not bad and any(v["code"] not in known for v in votes):
            # the Clerk's reports use Y, N, X and A; anything else is a misread scan ("V" for "Y")
            problems.append(f"RCS {r['rcs']}: unreadable vote code {sorted({v['code'] for v in votes} - known)}")
            r["votes"] = None
            continue
        if bad or not votes:
            problems.append(f"RCS {r['rcs']}: votes don't line up with the {len(cols)} member columns")
            r["votes"] = None
        else:
            r["votes"] = sorted(votes, key=lambda v: [n for _, n in cols].index(v["name"]))


def parse_report(text: str, doc_key: str = "", doc_url: str = "") -> tuple[list[dict], list[str]]:
    """Roll calls, and problems (rows that couldn't be read with confidence; never guessed)."""
    rows: list[dict] = []
    problems: list[str] = []
    # pdftotext ends each page with a form feed, which splitlines() treats as a line break: note the
    # PDF page each line is printed on, so links can open the report at the roll call (#page=N)
    pages, n = [], 1
    for ln in text.splitlines(keepends=True):
        pages.append(n)
        n += ln.endswith("\f")
    lines = [ln.replace("\f", "") for ln in text.splitlines()]
    cols: list[tuple[float, str]] = []
    page: list[dict] = []
    cur: dict | None = None
    layout = "modern"
    i = 0
    while i < len(lines):
        line = lines[i]
        if HEADER_RX.search(line):
            _place(page, cols, problems)
            page = []
            layout = "modern" if "Cat." in line else "legacy"
            if "Cat." in line:
                nxt = lines[i + 1] if i + 1 < len(lines) else ""
                cont = nxt if nxt.strip() and not ROW_RX.match(nxt) and len(nxt) - len(nxt.lstrip()) > 40 else None
                cols = _columns(line, cont)
                i += 2 if cont else 1
            else:
                prev = next((lines[k] for k in range(i - 1, max(i - 4, -1), -1) if LEGACY_NAME_RX.search(lines[k])), "")
                cols = _legacy_columns([prev, line])
                i += 1
            # keep `cur`: a roll call split across pages continues its subject on the next page
            continue
        m = ROW_RX.match(line)
        if m and m.group(6):
            mo, dd, yyyy = m.group(3).split("/")
            t = m.group(4).replace(" ", "")
            t = t + "M" if t.endswith(("A", "P")) else t
            codes = [(m.start(6) + k.start(), k.group(0).upper()) for k in re.finditer(r"[A-Za-z]", m.group(6))]
            cur = {
                "key": f"hillsclerk:bocc-votes:rcs:{yyyy}-{m.group(1)}", "rcs": int(m.group(1)),
                "item": (m.group(2) or "").strip(), "date": f"{yyyy}-{int(mo):02d}-{int(dd):02d}", "time": t,
                "category": m.group(5) or "", "category_name": CATEGORIES.get(m.group(5) or "", ""),
                "subject": "", "votes": [], "_codes": codes, "doc_key": doc_key, "doc_url": doc_url, "page": pages[i],
                "layout": layout,  # "legacy" (2014-2017) prints full names; "modern" prints surnames
            }
            rows.append(cur)
            page.append(cur)
        elif m or re.match(r"^\s*\d{1,6}\s+.*\d{1,2}/\d{1,2}/\d{4}", line):
            problems.append(f"unparsed row: {line.strip()[:120]}")
            cur = None
        elif SUMMARY_RX.search(line):
            cur = None
        elif cur is not None and line.strip() and not SKIP_RX.match(line) and not _is_name_line(line):
            # the carried-over part repeats the roll call's number: "4863      Oral Vote - EPC - ..."
            cont = re.match(rf"^\s*{cur['rcs']}\s+(\S.*)$", line)
            text_ = cont.group(1) if cont else line.strip()
            cur["subject"] = f"{cur['subject']} {text_}".strip()
        i += 1
    _place(page, cols, problems)
    for r in rows:
        r.pop("_codes", None)
    good: dict[str, dict] = {}
    for r in rows:
        if not r["votes"]:
            continue
        prev = good.get(r["key"])
        if prev is None:
            good[r["key"]] = r
            continue
        # Years with more members than fit on a page (2020: White; 2022: White, Wostal) print
        # every roll call again with the remaining columns. Merge; a member can't differ.
        have = {v["name"]: v["code"] for v in prev["votes"]}
        clash = [v["name"] for v in r["votes"] if v["name"] in have and have[v["name"]] != v["code"]]
        if clash:
            problems.append(f"RCS {r['rcs']} ({r['date']}): passes disagree for {', '.join(clash)}; kept the first")
        prev["votes"] += [v for v in r["votes"] if v["name"] not in have]
        prev["subject"] = prev["subject"] or r["subject"]
    out = [r for r in good.values() if not VOID_RX.search(r["subject"])]
    _clean_names(out)
    return out, problems


def _clean_names(rows: list[dict]) -> None:
    """Fix names misread in scanned pages ("Victor Grist", "At Higginbotham") by matching them
    to a name printed at least ten times as often in the same report."""
    import difflib
    counts: dict[str, int] = {}
    for r in rows:
        for v in r["votes"]:
            counts[v["name"]] = counts.get(v["name"], 0) + 1
    fix = {}
    for n, k in counts.items():
        better = [m for m, km in counts.items() if km >= 10 * k and difflib.SequenceMatcher(None, n, m).ratio() >= 0.8]
        if better:
            fix[n] = max(better, key=lambda m: counts[m])
    for r in rows:
        for v in r["votes"]:
            v["name"] = fix.get(v["name"], v["name"])


def pdf_text(pdf: Path) -> str:
    if not shutil.which("pdftotext"):
        raise RuntimeError("pdftotext (poppler-utils) is required")
    return subprocess.run(["pdftotext", "-layout", str(pdf), "-"], check=True, capture_output=True,
                          text=True).stdout


def collect_votes(listing: list[dict], fetcher: Fetcher) -> tuple[list[dict], list[str]]:
    rows: dict[str, dict] = {}
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        for doc in listing:
            try:
                body, _ = fetcher.download(doc["url"])
            except FetchError as e:
                problems.append(f"{doc['label']}: {e}")
                continue
            pdf = Path(tmp) / f"{doc['label']}.pdf"
            pdf.write_bytes(body)
            got, probs = parse_report(pdf_text(pdf), doc["key"], doc["url"])
            problems += [f"{doc['label']}: {p}" for p in probs]
            for r in got:  # a year can appear in both its own report and the current one
                rows.setdefault(r["key"], r)
    out = sorted(rows.values(), key=lambda r: (r["date"], r["rcs"]))
    _clean_names(out)  # across years too: 2016's scan reads "Al" as "AI" throughout
    return out, problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m opencivic.hillsclerk")
    ap.add_argument("what", choices=["list", "votes"])
    ap.add_argument("--since", type=int, default=2025)
    ap.add_argument("--listing", help="votes: listing jsonl from `list`")
    ap.add_argument("-o", "--output", required=True)
    args = ap.parse_args(argv)
    fetcher = HttpFetcher(min_interval=1.0)
    try:
        if args.what == "list":
            docs = list_documents(fetcher.get_text(PAGE), args.since)
            if not docs:
                print("error: no vote reports linked from the clerk's page", file=sys.stderr)
                return 1
            Path(args.output).write_text("".join(json.dumps(d) + "\n" for d in docs), "utf-8")
            print(f"{len(docs)} reports: {', '.join(d['label'] for d in docs)}", file=sys.stderr)
            return 0
        listing = [json.loads(x) for x in Path(args.listing).read_text("utf-8").splitlines() if x.strip()]
        rows, problems = collect_votes(listing, fetcher)
    except FetchError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for p in problems:
        print(f"warning: {p}", file=sys.stderr)
    if not rows:
        print("error: no roll calls parsed", file=sys.stderr)
        return 1
    Path(args.output).write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), "utf-8")
    print(f"{len(rows)} roll calls, {rows[0]['date']} to {rows[-1]['date']}, {len(problems)} problems", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
