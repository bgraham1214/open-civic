# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Adapter for Granicus Legistar, read through its public Web API.

    https://webapi.legistar.com/v1/{client}/

Verified Nov 8, 2026 against Hillsborough County (client hillsboroughcounty) and Hernando
County (hernandocountyfl), saved in tests/fixtures/legistar:
  * `events?$filter=EventDate ge datetime'2025-01-01'` lists meetings: body, date, time,
    location, agenda/minutes status, links to the agenda and minutes PDFs, and the
    meeting's page on {client}.legistar.com.
  * `events/{id}/eventitems?AgendaNote=1&MinutesNote=1&Attachments=1` lists every agenda
    item: number, title, file number, action, action text, result (Pass/Fail), mover,
    seconder, and attachment names.
  * `eventitems/{id}/votes` lists each member's vote on an item.
  * webapi.legistar.com has no robots.txt. The PDF and attachment servers
    ({client}.legistar1.com) disallow all robots, so this adapter never downloads files
    from them; it records their links for people to follow.

Bodies whose meetings are mostly about private residents (property-tax appeals, code
enforcement) are skipped by default; see PRIVATE_BODIES.

Usage:
  python -m opencivic.legistar events --client hernandocountyfl --since 2025-01-01 -o events.jsonl
  python -m opencivic.legistar items --client hernandocountyfl --events events.jsonl \\
      --items-out items.jsonl --votes-out votes.jsonl [--previous-items ... --previous-votes ...]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from .fetch import Fetcher, FetchError, HttpFetcher

# Guardrail (public roles only): these hearings mostly concern private residents.
PRIVATE_BODIES = ("Value Adjustment Board", "Special Master", "Special Magistrate", "Code Enforcement",
                  "Code Compliance", "I Messed Up")

PAGE = 1000          # Legistar's maximum $top
RECENT_DAYS = 60     # always refresh items for meetings this recent


def api_base(client: str) -> str:
    return f"https://webapi.legistar.com/v1/{client}/"


def _date(s: str | None) -> str:
    m = re.match(r"\d{4}-\d{2}-\d{2}", s or "")
    return m.group(0) if m else ""


def _clean(s: str | None) -> str:
    return re.sub(r"[ \t]+", " ", re.sub(r"\s*\r?\n\s*", "\n", (s or "").replace("\t", " "))).strip()


def is_private_body(name: str) -> bool:
    return any(p.lower() in (name or "").lower() for p in PRIVATE_BODIES)


def parse_event(client: str, raw: dict) -> dict:
    return {
        "source": "legistar", "client": client, "event_id": int(raw["EventId"]),
        "key": f"legistar:{client}:event:{raw['EventId']}",
        "body": (raw.get("EventBodyName") or "").strip(), "date": _date(raw.get("EventDate")),
        "time": raw.get("EventTime") or "", "location": (raw.get("EventLocation") or "").strip(),
        "comment": (raw.get("EventComment") or "").strip(),
        "agenda_status": raw.get("EventAgendaStatusName") or "",
        "minutes_status": raw.get("EventMinutesStatusName") or "",
        "agenda_url": raw.get("EventAgendaFile") or "", "minutes_url": raw.get("EventMinutesFile") or "",
        "agenda_published": raw.get("EventAgendaLastPublishedUTC") or "",
        "minutes_published": raw.get("EventMinutesLastPublishedUTC") or "",
        "portal_url": raw.get("EventInSiteURL") or "",
        "last_modified": raw.get("EventLastModifiedUtc") or "",
    }


def events_url(client: str, since: str, skip: int = 0) -> str:
    flt = quote(f"EventDate ge datetime'{since}'")
    return f"{api_base(client)}events?$filter={flt}&$orderby=EventDate,EventId&$top={PAGE}&$skip={skip}"


def crawl_events(client: str, fetcher: Fetcher, since: str, include_private: bool = False) -> list[dict]:
    out: list[dict] = []
    skip = 0
    while True:
        page = fetcher.get_json(events_url(client, since, skip))
        if not isinstance(page, list):
            raise FetchError(f"unexpected events response for {client}: {str(page)[:200]}")
        out += [parse_event(client, r) for r in page]
        if len(page) < PAGE:
            break
        skip += PAGE
    if not include_private:
        out = [e for e in out if not is_private_body(e["body"])]
    return sorted({e["event_id"]: e for e in out}.values(), key=lambda e: (e["date"], e["event_id"]))


def items_url(client: str, event_id: int) -> str:
    return f"{api_base(client)}events/{event_id}/eventitems?AgendaNote=1&MinutesNote=1&Attachments=1"


def votes_url(client: str, item_id: int) -> str:
    return f"{api_base(client)}eventitems/{item_id}/votes"


def matter_url(client: str, raw: dict) -> str:
    """No per-item link. Checked Nov 9, 2026: LegislationDetail.aspx?ID={MatterId}&GUID={MatterGuid}
    answers "Invalid parameters!" on both hernandocountyfl and hillsboroughcounty (the website's
    ids differ from the API's). The meeting page (EventInSiteURL) works; pages link to that."""
    return ""


def wants_votes(raw: dict) -> bool:
    """An action was taken with a recorded result, or a roll call was flagged."""
    return raw.get("EventItemPassedFlag") is not None or str(raw.get("EventItemRollCallFlag")) == "1"


def parse_item(client: str, event: dict, raw: dict) -> dict:
    return {
        "source": "legistar", "client": client, "key": f"legistar:{client}:item:{raw['EventItemId']}",
        "item_id": int(raw["EventItemId"]), "event_id": event["event_id"],
        "event_last_modified": event["last_modified"],
        "date": event["date"], "body": event["body"], "sequence": int(raw.get("EventItemAgendaSequence") or 0),
        "number": (raw.get("EventItemAgendaNumber") or "").strip(),
        "title": _clean(raw.get("EventItemTitle")),
        "file_number": raw.get("EventItemMatterFile") or "", "matter_type": raw.get("EventItemMatterType") or "",
        "matter_status": raw.get("EventItemMatterStatus") or "",
        "action": raw.get("EventItemActionName") or "", "action_text": _clean(raw.get("EventItemActionText")),
        "result": raw.get("EventItemPassedFlagName") or "", "tally": raw.get("EventItemTally") or "",
        "mover": raw.get("EventItemMover") or "", "seconder": raw.get("EventItemSeconder") or "",
        "consent": str(raw.get("EventItemConsent")) == "1",
        "agenda_note": _clean(raw.get("EventItemAgendaNote")), "minutes_note": _clean(raw.get("EventItemMinutesNote")),
        # names only: the attachment server disallows robots, and people can follow matter_url
        "attachments": [a.get("MatterAttachmentName") or "" for a in raw.get("EventItemMatterAttachments") or []],
        "matter_url": matter_url(client, raw), "portal_url": event["portal_url"],
    }


def parse_votes(client: str, item: dict, raw: list[dict]) -> list[dict]:
    return [{
        # One roll call can cover several items (e.g. a consent agenda), and Legistar then returns
        # the same VoteId under each item, so the key includes the item.
        "source": "legistar", "client": client, "key": f"legistar:{client}:vote:{item['item_id']}:{v['VoteId']}",
        "item_key": item["key"], "event_id": item["event_id"], "date": item["date"], "body": item["body"],
        "person": (v.get("VotePersonName") or "").strip(), "vote": v.get("VoteValueName") or "",
        "sort": v.get("VoteSort") or 0,
    } for v in raw]


def _recent(d: str, today: date, days: int = RECENT_DAYS) -> bool:
    try:
        return datetime.strptime(d, "%Y-%m-%d").date() >= today - timedelta(days=days)
    except ValueError:
        return True


def crawl_items(client: str, events: list[dict], fetcher: Fetcher, *, previous_items: list[dict] = (),
                previous_votes: list[dict] = (), max_requests: int | None = None,
                today: date | None = None) -> tuple[list[dict], list[dict], dict]:
    """Agenda items and votes for each event.

    An event's items are reused from the previous run when the event's LastModified is
    unchanged and the meeting is more than RECENT_DAYS old; otherwise they are fetched.
    With max_requests, events beyond the budget keep their previous items (if any) and are
    picked up on a later run.
    """
    today = today or date.today()
    prev_by_event: dict[int, list[dict]] = {}
    for it in previous_items:
        prev_by_event.setdefault(it["event_id"], []).append(it)
    prev_votes: dict[str, list[dict]] = {}
    for v in previous_votes:
        prev_votes.setdefault(v["item_key"], []).append(v)

    items: list[dict] = []
    votes: list[dict] = []
    stats = {"events": len(events), "fetched": 0, "reused": 0, "deferred": 0, "requests": 0, "errors": 0}

    def budget_left() -> bool:
        return max_requests is None or stats["requests"] < max_requests

    for ev in events:
        prev = prev_by_event.get(ev["event_id"])
        fresh_enough = prev and prev[0].get("event_last_modified") == ev["last_modified"] and not _recent(ev["date"], today)
        if fresh_enough:
            items += prev
            for it in prev:
                votes += prev_votes.get(it["key"], [])
            stats["reused"] += 1
            continue
        if not budget_left():
            stats["deferred"] += 1
            if prev:
                items += prev
                for it in prev:
                    votes += prev_votes.get(it["key"], [])
            continue
        try:
            stats["requests"] += 1
            raw_items = fetcher.get_json(items_url(client, ev["event_id"]))
            ev_items = [parse_item(client, ev, r) for r in raw_items if _clean(r.get("EventItemTitle"))]
            ev_votes: list[dict] = []
            for r, it in zip([r for r in raw_items if _clean(r.get("EventItemTitle"))], ev_items):
                if not wants_votes(r):
                    continue
                if not budget_left():
                    ev_votes += prev_votes.get(it["key"], [])
                    continue
                stats["requests"] += 1
                ev_votes += parse_votes(client, it, fetcher.get_json(votes_url(client, it["item_id"])))
        except FetchError as e:
            print(f"error: {e}", file=sys.stderr)
            stats["errors"] += 1
            if prev:  # keep what we had rather than dropping the meeting
                items += prev
                for it in prev:
                    votes += prev_votes.get(it["key"], [])
            continue
        items += ev_items
        votes += ev_votes
        stats["fetched"] += 1
    items.sort(key=lambda i: (i["date"], i["event_id"], i["sequence"], i["item_id"]))
    votes.sort(key=lambda v: (v["date"], v["item_key"], v["sort"], v["person"]))
    return items, votes, stats


def _read_jsonl(path: str | None) -> list[dict]:
    if not path or not Path(path).exists():
        return []
    return [json.loads(x) for x in Path(path).read_text("utf-8").splitlines() if x.strip()]


def _write_jsonl(rows: list[dict], path: str) -> None:
    Path(path).write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), "utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m opencivic.legistar")
    ap.add_argument("what", choices=["events", "items"])
    ap.add_argument("--client", required=True, help="Legistar client name, e.g. hernandocountyfl")
    ap.add_argument("--since", default="2025-01-01")
    ap.add_argument("--include-private-bodies", action="store_true",
                    help=f"also list {', '.join(PRIVATE_BODIES)} (off by default: public roles only)")
    ap.add_argument("--events", help="for items: events jsonl from `events`")
    ap.add_argument("--previous-items", help="items jsonl from the last run (reused when unchanged)")
    ap.add_argument("--previous-votes", help="votes jsonl from the last run")
    ap.add_argument("--max-requests", type=int, help="cap API requests this run; the rest wait")
    ap.add_argument("-o", "--output", help="events: write here")
    ap.add_argument("--items-out")
    ap.add_argument("--votes-out")
    args = ap.parse_args(argv)
    fetcher = HttpFetcher(min_interval=1.0)
    try:
        if args.what == "events":
            events = crawl_events(args.client, fetcher, args.since, args.include_private_bodies)
            _write_jsonl(events, args.output or "/dev/stdout")
            print(f"{args.client}: {len(events)} events since {args.since}", file=sys.stderr)
            return 0
        events = _read_jsonl(args.events)
        if not events:
            print("error: no events", file=sys.stderr)
            return 1
        items, votes, stats = crawl_items(args.client, events, fetcher,
                                          previous_items=_read_jsonl(args.previous_items),
                                          previous_votes=_read_jsonl(args.previous_votes),
                                          max_requests=args.max_requests)
    except FetchError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    _write_jsonl(items, args.items_out or "/dev/stdout")
    if args.votes_out:
        _write_jsonl(votes, args.votes_out)
    print(f"{args.client}: {len(items)} items, {len(votes)} votes; {json.dumps(stats)}", file=sys.stderr)
    return 1 if stats["errors"] and not stats["fetched"] and not stats["reused"] else 0


if __name__ == "__main__":
    sys.exit(main())
