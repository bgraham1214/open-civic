# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Adapter for CivicClerk's new public portal (`{tenant}.portal.civicclerk.com`).

The portal is backed by a public OData v4 API at `https://{tenant}.api.civicclerk.com/v1/`.
This module lists every event (meeting) and the files published for it.

Verified against Temple Terrace's saved responses (tests/fixtures/templeterracefl):
  * `GET /v1/Events` returns `{"value": [...], "@odata.nextLink": ...}`, 15 events a page,
    paged by `$skiptoken=id-N`.
  * Each event carries `publishedFiles`: fileId, type ("Agenda", "Agenda Packet", ...),
    name, publishOn, and a storage path like `stream/TENANT/<uuid>.pdf`.
  * `$metadata` declares `Meetings/GetMeetingFileStream(fileId, plainText)` and
    `Events/GetEventFileStream(fileId, fileType, plainText)` for downloads.

Assumed, not yet checked live (see ASSUMPTIONS below):
  * The download URL form used in `PublishedFile.download_url`.
  * `eventDate` is the city's local wall-clock time with a misleading "Z" suffix.

Usage:
  python -m opencivic.civicclerk meetings --tenant templeterracefl            # live
  python -m opencivic.civicclerk files --tenant templeterracefl \\
      --input tests/fixtures/templeterracefl/Events.json                       # offline
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from typing import Iterator

from .fetch import Fetcher, FetchError, FixtureFetcher, HttpFetcher

ASSUMPTIONS = [
    "download_url uses Meetings/GetMeetingFileStream(fileId=N,plainText=false); "
    "the metadata declares it, but no live download has been made yet",
    "eventDate/startDateTime are local wall-clock times despite the 'Z' suffix "
    "(18:00Z would be 1 PM Eastern; council meetings are likely 6 PM local)",
    "fileId changes with each revision of a file, so it works as a version id",
]


def api_base(tenant: str) -> str:
    return f"https://{tenant}.api.civicclerk.com/v1/"


def portal_event_url(tenant: str, event_id: int) -> str:
    return f"https://{tenant}.portal.civicclerk.com/event/{event_id}/files"


def file_viewer_url(tenant: str, event_id: int, file_id: int) -> str:
    """The portal's in-browser viewer for one of a meeting's files (agenda, packet, minutes).

    Link people here, not to the API's GetMeetingFileStream, which answers Content-Disposition:
    attachment, so a phone downloads "11751.pdf" and ignores #page (checked Nov 11, 2026). The route
    is /event/:eventId/files/:itemFileType/:fileId, with itemFileType "agenda" for meeting-level files
    (the portal's MeetingFiles bundle). There is no /event/N/agenda route: it redirects to the overview.
    """
    return f"https://{tenant}.portal.civicclerk.com/event/{event_id}/files/agenda/{file_id}"


FILE_STREAM_RX = re.compile(r"^https://([a-z0-9-]+)\.api\.civicclerk\.com/v1/Meetings/"
                            r"GetMeetingFileStream\(fileId=(\d+),plainText=false\)")


def viewer_links(meetings: list[dict]) -> tuple[dict[int, str], dict[int, str]]:
    """From a meetings listing: (file id -> viewer URL, event id -> where to read its agenda).

    The agenda link is the Agenda's viewer, or the meeting's files page when there's no separate
    Agenda (a packet can run to 86 MB, too much to open on a phone unasked).
    """
    by_file, agenda = {}, {}
    for m in meetings:
        tenant, ev = m.get("tenant") or "", m["event_id"]
        for f in m.get("files") or []:
            by_file[int(f["file_id"])] = file_viewer_url(tenant, ev, int(f["file_id"]))
        a = next((f for f in m.get("files") or [] if f.get("kind") == "Agenda"), None)
        agenda[ev] = file_viewer_url(tenant, ev, int(a["file_id"])) if a else m.get("portal_url", "")
    return by_file, agenda


def viewer_for(url: str, by_file: dict[int, str]) -> str:
    """The viewer for an API file URL we know the meeting of; otherwise the URL unchanged."""
    m = FILE_STREAM_RX.match(url or "")
    return by_file.get(int(m.group(2)), url) if m else url


@dataclass
class PublishedFile:
    file_id: int          # changes per revision (assumed) -> usable as a version id
    kind: str             # "Agenda", "Agenda Packet", "Minutes", ...
    name: str
    published_at: str     # ISO timestamp from the API (publishOn)
    file_type: int        # CivicClerk's numeric type (1 agenda, 2 packet, ...)
    storage_path: str     # e.g. stream/TEMPLETERRACEFL/<uuid>.pdf
    download_url: str
    text_url: str         # same file as plain text, extracted by CivicClerk
    sort: int = 0


@dataclass
class Meeting:
    source: str
    tenant: str
    event_id: int
    name: str
    category: str
    date: str             # YYYY-MM-DD as the city shows it
    start: str            # raw API value, kept for audit
    location: str
    agenda_id: int        # key into /v1/Meetings({agenda_id}) for agenda items (step 4)
    has_agenda: bool
    publish_status: str
    agenda_note: str      # e.g. "Amended on October 31, 2025 4:23 PM"
    is_deleted: bool
    youtube_video_id: str
    external_media_url: str
    portal_url: str
    files: list[PublishedFile] = field(default_factory=list)


def _location(loc: dict | None) -> str:
    if not loc:
        return ""
    parts = [p.strip() for p in (loc.get("address1"), loc.get("address2"), loc.get("city")) if p and p.strip()]
    text = ", ".join(parts)
    for extra in (loc.get("state"), loc.get("zipCode")):
        if extra and extra.strip() and extra.strip() not in text:
            text += f" {extra.strip()}"
    return text


def parse_file(tenant: str, raw: dict) -> PublishedFile:
    base = api_base(tenant)
    fid = int(raw["fileId"])
    return PublishedFile(
        file_id=fid,
        kind=raw.get("type") or "",
        name=(raw.get("name") or "").strip(),
        published_at=raw.get("publishOn") or "",
        file_type=int(raw.get("fileType") or 0),
        storage_path=raw.get("url") or "",
        download_url=f"{base}Meetings/GetMeetingFileStream(fileId={fid},plainText=false)",
        text_url=f"{base}Meetings/GetMeetingFileStream(fileId={fid},plainText=true)",
        sort=int(raw.get("sort") or 0),
    )


def parse_event(tenant: str, raw: dict) -> Meeting:
    start = raw.get("startDateTime") or raw.get("eventDate") or ""
    m = re.match(r"\d{4}-\d{2}-\d{2}", raw.get("eventDate") or start)
    files = sorted((parse_file(tenant, f) for f in raw.get("publishedFiles") or []),
                   key=lambda f: (f.sort, f.file_id))
    return Meeting(
        source="civicclerk",
        tenant=tenant,
        event_id=int(raw["id"]),
        name=(raw.get("eventName") or "").strip(),
        category=raw.get("categoryName") or raw.get("eventCategoryName") or "",
        date=m.group(0) if m else "",
        start=start,
        location=_location(raw.get("eventLocation")),
        agenda_id=int(raw.get("agendaId") or 0),
        has_agenda=bool(raw.get("hasAgenda")),
        publish_status=str(raw.get("isPublished") or ""),
        agenda_note=raw.get("publishedAgendaTimeStamp") or "",
        is_deleted=bool(raw.get("isDeleted")),
        youtube_video_id=raw.get("youtubeVideoId") or "",
        external_media_url=raw.get("externalMediaUrl") or "",
        portal_url=portal_event_url(tenant, int(raw["id"])),
        files=files,
    )


@dataclass
class Crawl:
    meetings: list[Meeting]
    pages: int
    unfollowed_next_link: str | None  # set when we stopped early (max_pages / offline)


def iter_event_pages(fetcher: Fetcher, first_url: str, max_pages: int | None = None) -> Iterator[tuple[dict, str | None]]:
    """Yield (page, next_link) following @odata.nextLink, with a loop guard."""
    url: str | None = first_url
    seen: set[str] = set()
    count = 0
    while url:
        if url in seen:
            raise FetchError(f"pagination loop at {url}")
        seen.add(url)
        page = fetcher.get_json(url)
        count += 1
        nxt = page.get("@odata.nextLink")
        yield page, nxt
        if max_pages is not None and count >= max_pages:
            return
        url = nxt


def events_url(tenant: str, since: str | None = None) -> str:
    """First Events page; with `since` (YYYY-MM-DD), only events starting that day or later.

    The OData filter form was checked live against pascocofl on Nov 8, 2026; its
    @odata.nextLink keeps the filter and pages by $skiptoken=startDateTime-...,id-N.
    """
    if not since:
        return api_base(tenant) + "Events"
    return (api_base(tenant) + f"Events?$filter=startDateTime%20ge%20{since}T00:00:00Z"
            "&$orderby=startDateTime")


def crawl_events(tenant: str, fetcher: Fetcher, max_pages: int | None = None, since: str | None = None) -> Crawl:
    by_id: dict[int, Meeting] = {}
    pages = 0
    nxt = None
    for page, nxt in iter_event_pages(fetcher, events_url(tenant, since), max_pages):
        pages += 1
        for raw in page.get("value", []):
            mtg = parse_event(tenant, raw)
            by_id[mtg.event_id] = mtg  # later pages win if an id repeats
    meetings = sorted(by_id.values(), key=lambda m: (m.date, m.event_id))
    stopped_early = max_pages is not None and pages >= max_pages
    return Crawl(meetings, pages, nxt if stopped_early else None)


# --- agenda items (Meetings/{agendaId}) ----------------------------------------

def _clean(html_text: str | None) -> str:
    """Agenda titles and descriptions arrive as HTML fragments; reduce to plain text."""
    if not html_text:
        return ""
    t = re.sub(r"<br\s*/?>|</p>|</div>|</li>", "\n", html_text, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t).replace("\u00a0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\s*\n\s*", "\n", t).strip()


def meeting_url(tenant: str, agenda_id: int) -> str:
    return f"{api_base(tenant)}Meetings/{agenda_id}"


def parse_agenda_items(tenant: str, meeting: Meeting, raw: dict) -> list[dict]:
    """Flatten a Meetings/{agendaId} response into one record per section and item.

    Keeps names, numbers and attachment metadata only. Attachment storage URLs are
    dropped: the API returns them as signed links with write permission.
    """
    out: list[dict] = []

    def walk(nodes: list[dict], section: str, parent_outline: str, depth: int) -> None:
        for n in sorted(nodes or [], key=lambda x: x.get("sortOrder") or 0):
            if n.get("isDeleted"):
                continue
            outline = (n.get("agendaObjectItemOutlineNumber") or "").strip()
            full = f"{parent_outline}{outline}" if depth else outline
            is_section = bool(n.get("isSection"))
            title = _clean(n.get("agendaObjectItemName"))
            here_section = title if is_section and depth == 0 else section
            out.append({
                "key": f"civicclerk:{tenant}:item:{n['id']}",
                "item_id": n["id"],
                "event_id": meeting.event_id,
                "agenda_id": meeting.agenda_id,
                "date": meeting.date,
                "meeting": meeting.name,
                "category": meeting.category,
                "is_section": is_section,
                "section": here_section,
                "outline": full,
                "level": depth,
                "item_number": n.get("agendaObjectItemNumber") or "",
                "title": title,
                "description": _clean(n.get("agendaObjectItemDescription")),
                "fiscal_impact": _clean(n.get("fiscalImpactSummary")),
                "resolution_number": n.get("resolutionFormattedNumber") or "",
                "ordinance_number": n.get("ordinanceFormattedNumber") or "",
                "attachments": [
                    {"id": a["id"], "name": (a.get("fileName") or "").strip(),
                     "content_type": a.get("contentType") or "", "bytes": a.get("fileSize") or 0}
                    for a in (n.get("attachmentsList") or []) if a.get("isPublished", True)
                ],
                "portal_url": meeting.portal_url,  # the portal has no /event/N/agenda route; see file_viewer_url
            })
            walk(n.get("childItems") or [], here_section, full, depth + 1)

    walk(raw.get("items") or [], "", "", 0)
    return out


def crawl_items(tenant: str, meetings: list[Meeting], fetcher: Fetcher) -> tuple[list[dict], list[str]]:
    items: list[dict] = []
    errors: list[str] = []
    for m in meetings:
        if not m.agenda_id or not m.files:
            continue
        try:
            raw = fetcher.get_json(meeting_url(tenant, m.agenda_id))
        except FetchError as e:
            errors.append(str(e))
            continue
        items += parse_agenda_items(tenant, m, raw)
    return items, errors


# --- schema drift guard -------------------------------------------------------

REQUIRED_EVENT_PROPS = {"id", "eventName", "eventDate", "categoryName", "agendaId", "publishedFiles", "isDeleted"}
REQUIRED_FILE_PROPS = {"fileId", "type", "name", "publishOn", "url", "fileType"}
REQUIRED_FUNCTIONS = {"GetMeetingFileStream", "GetEventFileStream"}


def schema_problems(metadata_xml: str) -> list[str]:
    """Return a list of differences between $metadata and what this adapter relies on."""
    problems = []

    def props(type_name: str) -> set[str]:
        m = re.search(rf'<(?:EntityType|ComplexType) Name="{type_name}"[^>]*>(.*?)</(?:EntityType|ComplexType)>',
                      metadata_xml, re.S)
        return set(re.findall(r'<(?:Navigation)?Property Name="(\w+)"', m.group(1))) if m else set()

    if '<EntitySet Name="Events"' not in metadata_xml:
        problems.append("Events entity set missing")
    for missing in sorted(REQUIRED_EVENT_PROPS - props("EventModel")):
        problems.append(f"EventModel.{missing} missing")
    for missing in sorted(REQUIRED_FILE_PROPS - props("PublishFileModel")):
        problems.append(f"PublishFileModel.{missing} missing")
    funcs = set(re.findall(r'<Function Name="(\w+)"', metadata_xml))
    for missing in sorted(REQUIRED_FUNCTIONS - funcs):
        problems.append(f"function {missing} missing")
    return problems


# --- output -------------------------------------------------------------------

FILE_COLUMNS = ["event_id", "date", "meeting", "category", "kind", "name", "file_id",
                "published_at", "download_url", "text_url", "storage_path", "portal_url"]


def file_rows(meetings: list[Meeting]) -> Iterator[dict]:
    for m in meetings:
        for f in m.files:
            yield {
                "event_id": m.event_id, "date": m.date, "meeting": m.name, "category": m.category,
                "kind": f.kind, "name": f.name, "file_id": f.file_id, "published_at": f.published_at,
                "download_url": f.download_url, "text_url": f.text_url,
                "storage_path": f.storage_path, "portal_url": m.portal_url,
            }


def write_output(rows: list[dict], fmt: str, out) -> None:
    if fmt == "jsonl":
        for r in rows:
            out.write(json.dumps(r, ensure_ascii=False) + "\n")
    else:
        flat = [{k: (json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in r.items()} for r in rows]
        if not flat:
            return
        w = csv.DictWriter(out, fieldnames=list(flat[0]))
        w.writeheader()
        w.writerows(flat)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m opencivic.civicclerk", description=__doc__.split("\n\n")[0])
    ap.add_argument("what", choices=["meetings", "files", "items", "check-schema"])
    ap.add_argument("--tenant", default="templeterracefl")
    ap.add_argument("--input", nargs="*", help="saved Events pages (offline); omit to fetch live")
    ap.add_argument("--metadata", help="saved $metadata file for check-schema (offline)")
    ap.add_argument("--meetings", help="for items: meetings jsonl from a previous run (skips the Events crawl)")
    ap.add_argument("--meetings-dir", help="for items, offline: saved Meetings responses named meeting-<agendaId>.json")
    ap.add_argument("--category", help='keep only this category, e.g. "City Council"')
    ap.add_argument("--with-files-only", action="store_true", help="drop meetings with no published files")
    ap.add_argument("--exclude-private", action="store_true",
                    help="drop boards whose hearings mostly concern private residents (Value Adjustment Board, "
                         "Special Magistrates, code enforcement); see legistar.PRIVATE_BODIES")
    ap.add_argument("--max-pages", type=int)
    ap.add_argument("--since", help="only events from this date (YYYY-MM-DD), filtered by the API")
    ap.add_argument("--format", choices=["jsonl", "csv"], default="jsonl")
    ap.add_argument("-o", "--output", help="write here instead of stdout")
    args = ap.parse_args(argv)

    if args.what == "check-schema":
        if args.metadata:
            with open(args.metadata, encoding="utf-8") as fh:
                xml = fh.read()
        else:
            xml = HttpFetcher().get_bytes(api_base(args.tenant) + "$metadata").decode("utf-8")
        problems = schema_problems(xml)
        for p in problems:
            print(f"SCHEMA: {p}", file=sys.stderr)
        print("schema ok" if not problems else f"{len(problems)} schema problem(s)", file=sys.stderr)
        return 1 if problems else 0

    if args.what == "items":
        if args.meetings:
            with open(args.meetings, encoding="utf-8") as fh:
                meetings = [Meeting(**{**r, "files": [PublishedFile(**f) for f in r["files"]]})
                            for r in map(json.loads, fh)]
        else:
            meetings = crawl_events(args.tenant, HttpFetcher(), args.max_pages, args.since).meetings
        if args.meetings_dir:
            from pathlib import Path
            d = Path(args.meetings_dir)
            ifetch: Fetcher = FixtureFetcher({meeting_url(args.tenant, int(p.stem.split("-")[1])): p
                                              for p in d.glob("meeting-*.json")})
        else:
            ifetch = HttpFetcher()
        if args.category:
            meetings = [m for m in meetings if m.category.lower() == args.category.lower()]
        items, errors = crawl_items(args.tenant, meetings, ifetch)
        out = open(args.output, "w", encoding="utf-8", newline="") if args.output else sys.stdout
        try:
            write_output(items, args.format, out)
        finally:
            if args.output:
                out.close()
        for e in errors:
            print(f"error: {e}", file=sys.stderr)
        n_items = sum(1 for i in items if not i["is_section"])
        print(f"{len({i['agenda_id'] for i in items})} agendas, {n_items} items, {len(errors)} errors", file=sys.stderr)
        return 1 if errors and not items else 0

    if args.input:
        fetcher: Fetcher = FixtureFetcher.from_files(api_base(args.tenant) + "Events", args.input)
        max_pages = min(args.max_pages or len(args.input), len(fetcher.pages))
    else:
        fetcher, max_pages = HttpFetcher(), args.max_pages

    crawl = crawl_events(args.tenant, fetcher, max_pages, None if args.input else args.since)
    meetings = crawl.meetings
    if args.category:
        meetings = [m for m in meetings if m.category.lower() == args.category.lower()]
    if args.exclude_private:
        from .legistar import is_private_body
        meetings = [m for m in meetings if not (is_private_body(m.category) or is_private_body(m.name))]
    if args.with_files_only:
        meetings = [m for m in meetings if m.files]

    rows = list(file_rows(meetings)) if args.what == "files" else [asdict(m) for m in meetings]
    out = open(args.output, "w", encoding="utf-8", newline="") if args.output else sys.stdout
    try:
        write_output(rows, args.format, out)
    finally:
        if args.output:
            out.close()

    nfiles = sum(len(m.files) for m in meetings)
    print(f"{len(meetings)} meetings, {nfiles} files, {crawl.pages} page(s)", file=sys.stderr)
    if crawl.unfollowed_next_link:
        print(f"note: more pages exist, not followed: {crawl.unfollowed_next_link}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
