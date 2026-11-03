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


def crawl_events(tenant: str, fetcher: Fetcher, max_pages: int | None = None) -> Crawl:
    by_id: dict[int, Meeting] = {}
    pages = 0
    nxt = None
    for page, nxt in iter_event_pages(fetcher, api_base(tenant) + "Events", max_pages):
        pages += 1
        for raw in page.get("value", []):
            mtg = parse_event(tenant, raw)
            by_id[mtg.event_id] = mtg  # later pages win if an id repeats
    meetings = sorted(by_id.values(), key=lambda m: (m.date, m.event_id))
    stopped_early = max_pages is not None and pages >= max_pages
    return Crawl(meetings, pages, nxt if stopped_early else None)


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
    ap.add_argument("what", choices=["meetings", "files", "check-schema"])
    ap.add_argument("--tenant", default="templeterracefl")
    ap.add_argument("--input", nargs="*", help="saved Events pages (offline); omit to fetch live")
    ap.add_argument("--metadata", help="saved $metadata file for check-schema (offline)")
    ap.add_argument("--category", help='keep only this category, e.g. "City Council"')
    ap.add_argument("--with-files-only", action="store_true", help="drop meetings with no published files")
    ap.add_argument("--max-pages", type=int)
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

    if args.input:
        fetcher: Fetcher = FixtureFetcher.from_files(api_base(args.tenant) + "Events", args.input)
        max_pages = min(args.max_pages or len(args.input), len(fetcher.pages))
    else:
        fetcher, max_pages = HttpFetcher(), args.max_pages

    crawl = crawl_events(args.tenant, fetcher, max_pages)
    meetings = crawl.meetings
    if args.category:
        meetings = [m for m in meetings if m.category.lower() == args.category.lower()]
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
