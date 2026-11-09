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
CODES = {"Y": "Yes", "N": "No"}  # X and A are undefined by the clerk; kept as printed

LINK_RX = re.compile(r'href="(/documents/d/guest/bocc[-_]vote[^"]*)"', re.I)
# category is blank on some rows (e.g. RCS 4722, 5288)
ROW_RX = re.compile(r"^\s*(\d{3,6})\s+(?:(\S+)\s+)?(\d\d/\d\d/\d{4})\s+(\d{1,2}:\d\d\s?[AP]M)\s+(?:(\d)\s+)?((?:[A-Z]\s+)*[A-Z])\s*$")
HEADER_RX = re.compile(r"RCS\s*#.*Cat\.")
SKIP_RX = re.compile(r"^\s*(Hillsborough County Commissioners|Vote Comparison|Item #|Printed:.*|End of \w+|\d{1,3})\s*$")


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


def _columns(header: str, continuation: str | None) -> list[str]:
    """Commissioner names from the header row, joined with any second line beneath them."""
    start = header.index("Cat.") + len("Cat.")
    cols = [(m.start() + start, m.group(0)) for m in re.finditer(r"\S+(?: \S+)*", header[start:])]
    names = [n for _, n in cols]
    if continuation:
        for m in re.finditer(r"\S+", continuation):
            # attach each word to the column it sits under (nearest column start to its left)
            i = max((k for k, (pos, _) in enumerate(cols) if pos <= m.start() + 2), default=0)
            names[i] = f"{names[i]} {m.group(0)}"
    return names


def parse_report(text: str, doc_key: str = "", doc_url: str = "") -> tuple[list[dict], list[str]]:
    """Rows and problems (lines that look like rows but don't match the columns)."""
    rows: list[dict] = []
    problems: list[str] = []
    lines = text.splitlines()
    names: list[str] = []
    cur: dict | None = None
    i = 0
    while i < len(lines):
        line = lines[i].replace("\f", "")
        if HEADER_RX.search(line):
            nxt = lines[i + 1].replace("\f", "") if i + 1 < len(lines) else ""
            cont = nxt if nxt.strip() and not ROW_RX.match(nxt) and len(nxt) - len(nxt.lstrip()) > 40 else None
            names = _columns(line, cont)
            i += 2 if cont else 1
            continue
        m = ROW_RX.match(line)
        if m:
            codes = m.group(6).split()
            if len(codes) != len(names):
                problems.append(f"RCS {m.group(1)}: {len(codes)} codes for {len(names)} columns")
                cur = None
            else:
                mm, dd, yyyy = m.group(3).split("/")
                cur = {
                    "key": f"hillsclerk:bocc-votes:rcs:{m.group(1)}", "rcs": int(m.group(1)),
                    "item": m.group(2) or "", "date": f"{yyyy}-{mm}-{dd}", "time": m.group(4).replace(" ", ""),
                    "category": m.group(5) or "", "category_name": CATEGORIES.get(m.group(5) or "", ""),
                    "subject": "", "votes": [{"name": n, "code": c} for n, c in zip(names, codes)],
                    "doc_key": doc_key, "doc_url": doc_url,
                }
                rows.append(cur)
        elif re.match(r"^\s*\d{3,6}\s+.*\d\d/\d\d/\d{4}", line):
            problems.append(f"unparsed row: {line.strip()[:120]}")
            cur = None
        elif cur is not None and line.strip() and not SKIP_RX.match(line):
            cur["subject"] = f"{cur['subject']} {line.strip()}".strip()
        i += 1
    return rows, problems


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
    return sorted(rows.values(), key=lambda r: r["rcs"]), problems


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
