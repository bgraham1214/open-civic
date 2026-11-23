# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Notice when a government, or a payment source, goes quiet in our records.

A collector can break without an error. On Nov 18, 2026 we found 24 CivicClerk governments whose
listings had stopped months before (a `$top=200` cap), Bartow's listing ends Jun 15, 2026, Indian
Harbour Beach's council meetings carry no published files, and Santa Rosa's payment lists from May
2026 read 0 lines (a new layout). Each looked like a quiet government, not a failure. This module
reads only what is already stored in data/listings and says, for each government:

    python -m opencivic.health check --data-dir data        # one JSON line, a ::warning:: per problem
    python -m opencivic.health tracebacks out               # Python tracebacks in a run's logs

The usual gap is the median number of days between the governing board's meetings over the last
year. A government is flagged when something has been quiet for twice that gap (never less than
QUIET_FLOOR days, so a holiday break isn't an alarm):

  listing      no meeting of any board has been listed for that long, past or upcoming (a frozen listing)
  board        the governing board has no meeting for that long while other meetings keep being listed
               (often the board was renamed in the listing: St. Cloud's council moved to "General")
  items        the board keeps meeting but no agenda items have been stored for that long (the
               meetings carry no files, or the items aren't being read)
  renamed      in the last RENAME_DAYS days, more meetings named after the board ("City Council Meeting")
               were listed under a heading we don't read than under the ones we do. This catches a rename
               that happened long ago, which the gap can't: St. Cloud's council has been filed under
               "General" for most of 2026, so its few matched meetings make a long "usual gap".

A flag is a prompt to look, not a finding: a city that skips its summer meetings is flagged too.
Payment lists filed with agendas (agendapayments.py) are flagged when the newest lists read 0 lines
or no list has arrived for twice the usual gap; Pasco's weekly registers (payments.py) when no week
has arrived for that long.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path

from .jurisdictions import FLORIDA, JURISDICTIONS

QUIET_FLOOR = 28      # days; never flag a shorter silence
DEFAULT_GAP = 30      # days; used when the board met fewer than three times in the last year
RENAME_DAYS = 120     # days looked back for meetings named after the board but filed elsewhere

# Governments read by their own adapters, outside florida.json: listing files and the governing board.
# Hillsborough (the Clerk's monthly voting record, weeks late by design) and Oak Hill (links on the
# city's site) are not checked here yet.
EXTRA = {
    "templeterrace": ("civicclerk", "civicclerk-meetings.jsonl", "civicclerk-items.jsonl",
                      r"^.*\(City Council( Work Session)?\)$"),
    "pasco": ("civicclerk", "civicclerk-pascocofl-meetings.jsonl", "civicclerk-pascocofl-items.jsonl",
              r"^.*\(Board of County Commissioners\)$"),
    "hernando": ("legistar", "legistar-hernandocountyfl-events.jsonl", "legistar-hernandocountyfl-items.jsonl",
                 r"^Board of County Commissioners"),
    "edgewater": ("legistar", "legistar-cityofedgewater-events.jsonl", "legistar-cityofedgewater-items.jsonl",
                  JURISDICTIONS["edgewater"]["board_rx"]),
}

# Payment lists filed with Commission agendas (agendapayments.py) and Pasco's registers (payments.py).
PAYMENT_LISTS = {"colliercounty": "Collier County", "santarosacounty": "Santa Rosa County"}


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def usual_gap(dates: list[str], today: date) -> float:
    """Median days between distinct dates in the year before today (DEFAULT_GAP with fewer than three)."""
    start = (today - timedelta(days=365)).isoformat()
    ds = sorted({date.fromisoformat(d) for d in dates if start <= d <= today.isoformat()})
    gaps = [(b - a).days for a, b in zip(ds, ds[1:])]
    return float(statistics.median(gaps)) if len(ds) >= 3 else float(DEFAULT_GAP)


def threshold(gap: float) -> int:
    return max(QUIET_FLOOR, round(2 * gap))


def _ago(d: str | None, today: date) -> int | None:
    return (today - date.fromisoformat(d)).days if d else None


def _meetings(platform: str, rows: list[dict]) -> list[dict]:
    """Every listed meeting as {date, label, files}; files is None where the platform doesn't say."""
    if platform == "legistar":
        return [{"date": r["date"][:10], "label": (r.get("body") or "").strip(), "files": None,
                 "event_id": r.get("event_id")} for r in rows if r.get("date")]
    return [{"date": r["date"][:10], "label": f"{r.get('name', '')} ({r.get('category', '')})",
             "files": len(r.get("files") or []), "event_id": r.get("event_id")} for r in rows if r.get("date")]


def _times(n: int) -> str:
    return "once" if n == 1 else f"{n} times"


def government(slug: str, name: str, platform: str, meetings_rows: list[dict], items_rows: list[dict],
               board_rx: str, today: date, body: str = "") -> dict:
    """The health of one government's records: its usual gap, newest dates and any problems."""
    t = today.isoformat()
    rx = re.compile(board_rx)
    ms = _meetings(platform, meetings_rows)
    board = [m for m in ms if rx.match(m["label"])]
    past_board = sorted((m for m in board if m["date"] <= t), key=lambda m: m["date"])
    gap = usual_gap([m["date"] for m in past_board], today)
    limit = threshold(gap)
    newest_listed = max((m["date"] for m in ms), default=None)
    newest_board = past_board[-1]["date"] if past_board else None
    item_dates = sorted({i["date"][:10] for i in items_rows
                         if i.get("date") and not i.get("is_section") and i["date"][:10] <= t})
    rows_for = {i.get("event_id") for i in items_rows}
    newest_items = item_dates[-1] if item_dates else None
    problems: list[dict] = []
    if not ms:
        problems.append({"kind": "listing", "text": "No meetings are listed at all."})
    elif _ago(newest_listed, today) > limit:
        problems.append({"kind": "listing", "text": f"The listing ends on {newest_listed}: no meeting of any "
                         f"board, past or upcoming, after it (usually a meeting every {gap:g} days)."})
    elif not past_board or _ago(newest_board, today) > limit:
        later = [m for m in ms if m["date"] <= t and (not newest_board or m["date"] > newest_board)]
        names = []
        for m in sorted(later, key=lambda m: m["date"], reverse=True):
            if m["label"] not in names:
                names.append(m["label"])
        problems.append({"kind": "board", "text": (
            (f"No governing-board meeting since {newest_board}" if newest_board else "No governing-board meeting listed")
            + f", though {len(later)} other meeting{'' if len(later) == 1 else 's'} {'is' if len(later) == 1 else 'are'} listed after it, such as "
            + "; ".join(f'"{n}"' for n in names[:3])
            + ". The board may have been renamed in the listing.")})
    elif not newest_items or _ago(newest_items, today) > limit:
        after = [m for m in past_board if not newest_items or m["date"] > newest_items]
        no_files = [m for m in after if m["files"] == 0]
        headings = [m for m in after if m["files"] and m["event_id"] in rows_for]
        text = (f"The board met {_times(len(after))} since {newest_items}, but no agenda items were stored for "
                + ("that meeting" if len(after) == 1 else "those meetings") if newest_items else
                f"None of the board's {len(past_board)} past meetings has agenda items stored")

        def n(k: int) -> str:
            return f"{k} has" if k == 1 else f"{k} have"
        notes = []
        if no_files:
            notes.append(f"{n(len(no_files))} no published file in the listing")
        if headings:
            notes.append(f"{n(len(headings))} only the agenda's section headings stored")
        rest = len(after) - len(no_files) - len(headings)
        if rest > 0:
            notes.append(f"{n(rest)} files listed but no agenda items in the platform's format")
        problems.append({"kind": "items", "text": text + "; " + ", ".join(notes) + "."})
    if body and ms:
        since = (today - timedelta(days=RENAME_DAYS)).isoformat()
        named = re.compile(r"\b" + re.escape(body) + r"\b", re.I)
        recent = [m for m in ms if since <= m["date"] <= t]
        elsewhere = [m for m in recent if not rx.match(m["label"]) and named.search(m["label"].rsplit(" (", 1)[0])]
        matched = [m for m in recent if rx.match(m["label"])]
        if len(elsewhere) >= 2 and len(elsewhere) > len(matched):
            heads = sorted({m["label"].rsplit(" (", 1)[-1].rstrip(")") for m in elsewhere})
            problems.append({"kind": "renamed", "text": (
                f"In the last {RENAME_DAYS} days {len(elsewhere)} meetings named after the {body} were listed "
                f"under {', '.join(repr(h) for h in heads)}, which we don't read, and {len(matched)} under the "
                "headings we do. The board may be filed under a new heading.")})
    return {"slug": slug, "name": name, "link": f"meetings/{slug}.html", "platform": platform, "gap_days": gap, "quiet_after_days": limit,
            "newest_listed": newest_listed, "newest_board_meeting": newest_board, "newest_items": newest_items,
            "problems": problems}


def payment_list(slug: str, name: str, rows: list[dict], today: date) -> dict:
    """Payment lists filed with agendas: the newest ones read 0 lines, or none has arrived lately."""
    rows = sorted((r for r in rows if not r.get("duplicate_of")), key=lambda r: (r.get("meeting_date", ""), r.get("name", "")))
    dates = [r["meeting_date"] for r in rows if r.get("meeting_date")]
    gap = usual_gap(dates, today)
    limit = threshold(gap)
    newest = dates[-1] if dates else None
    newest_read = max((r["meeting_date"] for r in rows if r.get("lines")), default=None)
    unread = 0
    for r in reversed(rows):
        if r.get("lines"):
            break
        unread += 1
    problems = []
    if unread:
        problems.append({"kind": "unread", "text": f"The newest {unread} list{'' if unread == 1 else 's'}, filed since "
                         f"{rows[-unread]['meeting_date']}, read 0 payment lines (a new layout?)."})
    if not newest or _ago(newest, today) > limit:
        problems.append({"kind": "listing", "text": (f"No payment list has arrived since {newest}" if newest
                         else "No payment list has arrived") + f" (usually one every {gap:g} days)."})
    return {"slug": slug, "name": f"{name} payments", "link": f"payments/{slug}.csv", "gap_days": gap, "quiet_after_days": limit,
            "lists": len(rows), "newest_list": newest, "newest_read": newest_read, "problems": problems}


def pasco_registers(rows: list[dict], today: date) -> dict:
    weeks = sorted(r["week"] for r in rows if r.get("week"))
    gap = 7.0  # one register a week, by definition
    limit = threshold(gap)
    newest = weeks[-1] if weeks else None
    problems = []
    if not newest or _ago(newest, today) > limit:
        problems.append({"kind": "listing", "text": (f"No weekly register since the week through {newest}" if newest
                         else "No weekly register stored") + ". The Clerk keeps only the last eight weeks online."})
    return {"slug": "pasco-payments", "name": "Pasco County payments", "link": "payments/pasco.csv", "gap_days": gap, "quiet_after_days": limit,
            "lists": len(weeks), "newest_list": newest, "problems": problems}


def check(data: Path, today: date | None = None) -> dict:
    today = today or date.today()
    lst = data / "listings"
    govs = []
    for f in FLORIDA:
        if f["platform"] == "legistar":
            m, i = f"legistar-{f['account']}-events.jsonl", f"legistar-{f['account']}-items.jsonl"
        else:
            m, i = f"civicclerk-{f['account']}-meetings.jsonl", f"civicclerk-{f['account']}-items.jsonl"
        govs.append(government(f["slug"], f["name"], f["platform"], _read(lst / m), _read(lst / i),
                               JURISDICTIONS[f["slug"]]["board_rx"], today, f.get("body", "")))
    for slug, (platform, m, i, rx) in EXTRA.items():
        govs.append(government(slug, JURISDICTIONS[slug]["name"], platform, _read(lst / m), _read(lst / i), rx,
                               today, JURISDICTIONS[slug].get("body", "")))
    payments = [payment_list(s, n, _read(lst / f"{s}-payment-registers.jsonl"), today)
                for s, n in PAYMENT_LISTS.items()]
    payments.append(pasco_registers(_read(lst / "pasco-payment-registers.jsonl"), today))
    flagged = [g for g in govs + payments if g["problems"]]
    return {"checked": today.isoformat(), "governments": len(govs), "payment_sources": len(payments),
            "flagged": len(flagged), "records": govs + payments}


def tracebacks(folder: Path) -> dict[str, int]:
    """Python tracebacks per log file in a run's output folder (a green step can hide one)."""
    found = {}
    for p in sorted(folder.glob("*")):
        if p.is_file() and p.suffix in (".txt", ".log"):
            n = p.read_text("utf-8", errors="replace").count("Traceback (most recent call last)")
            if n:
                found[p.name] = n
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m opencivic.health")
    sub = ap.add_subparsers(dest="what", required=True)
    c = sub.add_parser("check")
    c.add_argument("--data-dir", type=Path, default=Path("data"))
    c.add_argument("--today", type=date.fromisoformat)
    t = sub.add_parser("tracebacks")
    t.add_argument("folder", type=Path)
    args = ap.parse_args(argv)
    if args.what == "tracebacks":
        found = tracebacks(args.folder)
        print(json.dumps({"tracebacks": sum(found.values()), "logs": found}))
        if found:
            print(f"::warning::{sum(found.values())} Python traceback(s) in this run's logs: "
                  + ", ".join(f"{k} ({v})" for k, v in found.items()))
        return 0
    result = check(args.data_dir, args.today)
    for r in result["records"]:
        for p in r["problems"]:
            print(f"::warning::{r['name']} ({p['kind']}): {p['text']}")
    print(json.dumps({"health": {"checked": result["checked"], "governments": result["governments"],
                                 "payment_sources": result["payment_sources"], "flagged": result["flagged"],
                                 "quiet": {r["slug"]: [p["kind"] for p in r["problems"]]
                                           for r in result["records"] if r["problems"]}}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
