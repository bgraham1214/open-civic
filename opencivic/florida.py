# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Collect every government in florida.json in one step, inside a time budget.

The first governments (Hillsborough, Pasco, Hernando, Edgewater) each have their own lines in the
nightly workflow. That doesn't scale to dozens, so the rest are collected here from the registry:

    python -m opencivic.florida collect --data-dir data --out out --minutes 120

Legistar governments: the meeting list for every public board (one or two requests), then agenda
items and each member's vote for the governing board's meetings (board_rx), newest first.
CivicClerk governments: the meeting list, then the agenda items of the governing board's meetings.

Budget. A government's first collection takes thousands of requests (one per roll call). Each night
every government first gets a small allowance (enough to keep recent meetings current), then the
remaining time goes to filling in older meetings, a slice per government in rotation, until the
deadline. Whatever isn't reached keeps what it had and is picked up the next night. Newest meetings
always come first, so a new government shows its latest meetings on its first night.

Polite: one request at a time to Legistar's API, about two a second. Each CivicClerk government is
its own host; four are read at a time, each no faster than two requests a second. Neither platform
sets a Crawl-delay; every request carries our User-Agent.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path

from . import civicclerk, legistar
from .fetch import FetchError, HostDown, HttpFetcher
from .jurisdictions import FLORIDA, JURISDICTIONS
from .privacy import resident_speaker, unname_item
from .region import PUBLIC_COMMENT_SECTION, narrative_line

REFRESH_DAYS = 21     # meetings this recent are re-read every night
AHEAD_DAYS = 45       # agendas are read this far ahead; later dates are calendar placeholders


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text("utf-8").splitlines() if x.strip()]


def _write(rows: list[dict], path: Path) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), "utf-8")


class Budget:
    def __init__(self, minutes: float):
        self.deadline = time.monotonic() + minutes * 60
        self.requests = 0

    def left(self) -> bool:
        return time.monotonic() < self.deadline


class LegistarGov:
    """One Legistar government's collection, resumable within a run (step() can be called again)."""

    def __init__(self, f: dict, lst: Path, fetcher, today: date):
        self.f, self.client, self.fetcher, self.today = f, f["account"], fetcher, today
        self.rx = re.compile(JURISDICTIONS[f["slug"]]["board_rx"])
        self.paths = {k: lst / f"legistar-{self.client}-{k}.jsonl" for k in ("events", "items", "votes", "officers")}
        self.items: dict[int, list[dict]] = {}
        for it in _read(self.paths["items"]):
            self.items.setdefault(it["event_id"], []).append(it)
        self.votes: dict[str, list[dict]] = {}
        for v in _read(self.paths["votes"]):
            self.votes.setdefault(v["item_key"], []).append(v)
        self.events: list[dict] = _read(self.paths["events"])
        self.todo: list[dict] | None = None
        self.stats = {"fetched": 0, "requests": 0, "errors": 0, "left": 0}
        self.failed = False

    def list_events(self) -> None:
        try:
            self.events = legistar.crawl_events(self.client, self.fetcher, self.f.get("since", "2025-01-01"))
            self.stats["requests"] += 1 + len(self.events) // legistar.PAGE
        except FetchError as e:
            print(f"{self.client}: events not updated: {e}", file=sys.stderr)
            self.stats["errors"] += 1
            self.failed = True
        try:
            rows = legistar.crawl_officers(self.client, self.fetcher, self.f.get("since", "2025-01-01"))
            self.stats["requests"] += 1
            if rows:
                _write(rows, self.paths["officers"])
        except (FetchError, KeyError, TypeError, ValueError) as e:
            print(f"{self.client}: office records not updated: {e}", file=sys.stderr)
        horizon = (self.today + timedelta(days=AHEAD_DAYS)).isoformat()
        fresh_from = (self.today - timedelta(days=REFRESH_DAYS)).isoformat()
        todo = []
        for ev in self.events:
            if not self.rx.match((ev["body"] or "").strip()) or ev["date"] > horizon:
                continue
            prev = self.items.get(ev["event_id"])
            if (prev is None or ev["date"] >= fresh_from
                    or prev and prev[0].get("event_last_modified") != ev["last_modified"]):
                todo.append(ev)
        # known-but-empty past meetings (read before, nothing there) are in self.items as [] and skipped
        self.todo = sorted(todo, key=lambda ev: ev["date"], reverse=True)

    def step(self, max_requests: int, budget: Budget) -> None:
        """Read up to max_requests' worth of meetings, newest first."""
        used = 0
        while self.todo and used < max_requests and budget.left() and not self.failed:
            ev = self.todo.pop(0)
            prev = {it["item_id"]: it for it in self.items.get(ev["event_id"], [])}
            try:
                raw_items = [r for r in self.fetcher.get_json(legistar.items_url(self.client, ev["event_id"]))
                             if legistar._clean(r.get("EventItemTitle"))]
                used += 1
                new_items = []
                for r in raw_items:
                    it = legistar.parse_item(self.client, ev, r)
                    it["item_last_modified"] = r.get("EventItemLastModifiedUtc") or ""
                    new_items.append(it)
                    if not legistar.wants_votes(r):
                        self.votes.pop(it["key"], None)
                        continue
                    old = prev.get(it["item_id"])
                    # a roll call already read is kept unless the item changed since
                    if (old and it["key"] in self.votes and it["item_last_modified"]
                            and old.get("item_last_modified") == it["item_last_modified"]):
                        continue
                    self.votes[it["key"]] = legistar.parse_votes(
                        self.client, it, self.fetcher.get_json(legistar.votes_url(self.client, it["item_id"])))
                    used += 1
                self.items[ev["event_id"]] = new_items
                self.stats["fetched"] += 1
            except HostDown as e:
                print(f"{self.client}: {e}", file=sys.stderr)
                self.failed = True
            except (FetchError, KeyError, TypeError, ValueError) as e:
                print(f"{self.client}: event {ev['event_id']}: {e}", file=sys.stderr)
                self.stats["errors"] += 1
        self.stats["requests"] += used
        budget.requests += used
        self.stats["left"] = len(self.todo or [])

    def save(self) -> None:
        if not self.events:
            return
        live = {ev["event_id"] for ev in self.events}
        # lines that aren't agenda items (notices, page breaks, the clerk's notes of who spoke at public
        # comment) are not stored: see region._load, which also leaves them out of every page
        items = [it for eid, its in self.items.items() if eid in live for it in its if not narrative_line(it)]
        for it in items:
            it.pop("minutes_note", None)  # raw rich text of the discussion; never used
            unname_item(it)  # volunteers removed from a board aren't named (privacy.py)
        keys = {it["key"] for it in items}
        votes = [v for k, vs in self.votes.items() if k in keys for v in vs]
        items.sort(key=lambda i: (i["date"], i["event_id"], i["sequence"], i["item_id"]))
        votes.sort(key=lambda v: (v["date"], v["item_key"], v["sort"], v["person"]))
        _write(self.events, self.paths["events"])
        _write(items, self.paths["items"])
        _write(votes, self.paths["votes"])
        print(f"{self.client}: {len(self.events)} events, {len(items)} items, {len(votes)} votes; "
              f"{json.dumps(self.stats)}", file=sys.stderr)


class CivicClerkGov:
    def __init__(self, f: dict, lst: Path, fetcher, today: date):
        self.f, self.tenant, self.fetcher, self.today = f, f["account"], fetcher, today
        self.rx = re.compile(JURISDICTIONS[f["slug"]]["board_rx"])
        self.paths = {k: lst / f"civicclerk-{self.tenant}-{k}.jsonl" for k in ("meetings", "items")}
        self.items: dict[int, list[dict]] = {}
        for it in _read(self.paths["items"]):
            self.items.setdefault(it["event_id"], []).append(it)
        self.seen = {m["event_id"]: [f_["file_id"] for f_ in m["files"]] for m in _read(self.paths["meetings"])}
        self.meetings: list = []
        self.todo: list | None = None
        self.stats = {"fetched": 0, "requests": 0, "errors": 0, "left": 0}
        self.failed = False

    def list_events(self) -> None:
        try:
            crawl = civicclerk.crawl_events(self.tenant, self.fetcher, since=self.f.get("since", "2025-01-01"), top=200)
        except FetchError as e:
            print(f"{self.tenant}: meetings not updated: {e}", file=sys.stderr)
            self.stats["errors"] += 1
            self.failed = True
            return
        self.stats["requests"] += crawl.pages
        self.meetings = [m for m in crawl.meetings if not m.is_deleted
                         and not (legistar.is_private_body(m.category) or legistar.is_private_body(m.name))]
        fresh_from = (self.today - timedelta(days=REFRESH_DAYS)).isoformat()
        todo = []
        for m in self.meetings:
            if not m.agenda_id or not m.files or not self.rx.match(f"{m.name} ({m.category})"):
                continue
            files = [f_.file_id for f_ in m.files]
            if m.event_id not in self.items or m.date >= fresh_from or self.seen.get(m.event_id) != files:
                todo.append(m)
        self.todo = sorted(todo, key=lambda m: m.date, reverse=True)

    def step(self, max_requests: int, budget: Budget) -> None:
        used = 0
        while self.todo and used < max_requests and budget.left() and not self.failed:
            m = self.todo.pop(0)
            try:
                raw = self.fetcher.get_json(civicclerk.meeting_url(self.tenant, m.agenda_id))
                used += 1
                self.items[m.event_id] = civicclerk.parse_agenda_items(self.tenant, m, raw)
                self.stats["fetched"] += 1
            except HostDown as e:
                print(f"{self.tenant}: {e}", file=sys.stderr)
                self.failed = True
            except (FetchError, KeyError, TypeError, ValueError) as e:
                print(f"{self.tenant}: meeting {m.event_id}: {e}", file=sys.stderr)
                self.stats["errors"] += 1
        self.stats["requests"] += used
        budget.requests += used
        self.stats["left"] = len(self.todo or [])

    def save(self) -> None:
        if not self.meetings:
            return
        live = {m.event_id for m in self.meetings}
        _write([asdict(m) for m in self.meetings], self.paths["meetings"])
        _write([unname_item(it) for eid, its in self.items.items() if eid in live for it in its
                if it.get("is_section") or not (PUBLIC_COMMENT_SECTION.match((it.get("section") or "").strip())
                                                 or resident_speaker(it))],
               self.paths["items"])
        print(f"{self.tenant}: {len(self.meetings)} meetings, "
              f"{sum(len(v) for k, v in self.items.items() if k in live)} agenda rows; {json.dumps(self.stats)}",
              file=sys.stderr)


def collect(data: Path, minutes: float, first: int, slice_: int, only: set[str] | None = None,
            fetchers: dict | None = None, today: date | None = None, workers: int = 4) -> dict:
    today = today or date.today()
    lst = data / "listings"
    lst.mkdir(parents=True, exist_ok=True)
    budget = Budget(minutes)
    shared = fetchers or {}
    govs = []
    rows = [f for f in FLORIDA if not only or f["slug"] in only]
    # rotate the starting point so a deadline doesn't always cut off the same governments
    start = today.toordinal() % len(rows) if rows else 0
    leg_fetcher = shared.get("legistar") or HttpFetcher(min_interval=0.5, retries=2)
    for f in rows[start:] + rows[:start]:
        if f["platform"] == "legistar":
            govs.append(LegistarGov(f, lst, leg_fetcher, today))
        else:  # every CivicClerk tenant is its own host, so each gets its own polite fetcher
            govs.append(CivicClerkGov(f, lst, shared.get("civicclerk") or HttpFetcher(min_interval=0.5, retries=2), today))

    def first_pass(g) -> None:
        if budget.left():
            g.list_events()
            g.step(first, budget)
            g.save()

    def backfill(group: list) -> None:
        while budget.left():
            waiting = [g for g in group if g.todo and not g.failed]
            if not waiting:
                return
            for g in waiting:
                if budget.left():
                    g.step(slice_, budget)
                    g.save()

    # Legistar is one host: one government at a time. CivicClerk tenants are separate hosts: a few at once.
    legistar_govs = [g for g in govs if isinstance(g, LegistarGov)]
    cc_govs = [g for g in govs if isinstance(g, CivicClerkGov)]

    def legistar_line() -> None:
        for g in legistar_govs:  # pass 1: every government's meeting list and newest meetings
            first_pass(g)
        backfill(legistar_govs)  # pass 2: older meetings, a slice each, until the time is up

    def cc_one(g) -> None:
        first_pass(g)
        backfill([g])

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=1 + (workers if cc_govs else 0)) as pool:
        jobs = [pool.submit(legistar_line)] + [pool.submit(cc_one, g) for g in cc_govs]
        for j in jobs:
            j.result()
    summary = {"governments": len(govs), "requests": budget.requests,
               "complete": sum(1 for g in govs if g.todo == [] and not g.failed),
               "unfinished": {g.f["slug"]: len(g.todo) for g in govs if g.todo},
               "failed": [g.f["slug"] for g in govs if g.failed],
               "not_reached": [g.f["slug"] for g in govs if g.todo is None and not g.failed]}
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m opencivic.florida")
    ap.add_argument("what", choices=["collect", "list"])
    ap.add_argument("--data-dir", type=Path, default=Path("data"))
    ap.add_argument("--minutes", type=float, default=120)
    ap.add_argument("--first", type=int, default=120, help="requests each government gets before any backfill")
    ap.add_argument("--slice", type=int, default=400, help="requests per government per backfill round")
    ap.add_argument("--only", help="comma-separated slugs")
    a = ap.parse_args(argv)
    if a.what == "list":
        for f in FLORIDA:
            print(f["slug"], f["platform"], f["account"], sep="\t")
        return 0
    only = {s.strip() for s in a.only.split(",")} if a.only else None
    print(json.dumps({"florida": collect(a.data_dir, a.minutes, a.first, a.slice, only)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
