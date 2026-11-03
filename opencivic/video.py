"""Link Temple Terrace's YouTube meeting videos to meetings (Phase 1, step 7).

Uses the YouTube Data API v3 (official, needs a free API key in YOUTUBE_API_KEY).
YouTube's web pages are bot-walled for GitHub's servers and its RSS feeds are disallowed
by robots.txt, so the API is the sanctioned route.

  1. channels.list        -> the channel's "uploads" playlist
  2. playlistItems.list   -> every upload: id, title, description, publish time
  3. videos.list          -> duration and, for live streams, the actual start time

Each video is matched to a meeting by, in order:
  * a CivicClerk link in its description (".../event/<id>")
  * the meeting date in its title ("City Council Meeting February 17, 2026"),
    or the live stream's start date, against CivicClerk meetings on that date

Writes data/listings/youtube-videos.jsonl (one row per video, with its matched meeting).
The API key is never written anywhere: errors are reported without the request URL.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from .fetch import FetchError, HttpFetcher

API = "https://www.googleapis.com/youtube/v3/"
CHANNEL_ID = "UC4z9CgD1RQNAwFPMKbTKupw"  # @cityoftempleterrace
LOCAL = ZoneInfo("America/New_York")

_MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"
_TITLE_DATE = re.compile(rf"\b({_MONTHS})\s+(\d{{1,2}}),?\s+(\d{{4}})\b", re.I)
_NUM_DATE = re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{2}|\d{4})\b")
_EVENT_LINK = re.compile(r"civicclerk\.com/event/(\d+)")


class ApiClient:
    """Calls the Data API with the key, and never lets the key reach logs or files."""

    def __init__(self, key: str, fetcher=None):
        self.key = key
        # Official API with an issued key: robots.txt governs crawlers, not keyed API calls.
        self.fetcher = fetcher or HttpFetcher(min_interval=0.2, check_robots=False)
        self.calls = 0

    def get(self, method: str, **params) -> dict:
        self.calls += 1
        url = API + method + "?" + urlencode({**params, "key": self.key})
        try:
            return self.fetcher.get_json(url)
        except FetchError as e:
            raise FetchError(str(e).replace(self.key, "***").split(" for ")[0] + f" ({method})") from None


def parse_title_date(title: str) -> str:
    m = _TITLE_DATE.search(title)
    if m:
        mo = _MONTHS.split("|").index(m.group(1).lower()) + 1
        try:
            return datetime(int(m.group(3)), mo, int(m.group(2))).date().isoformat()
        except ValueError:
            return ""
    m = _NUM_DATE.search(title)
    if m:
        y = int(m.group(3)) + (2000 if len(m.group(3)) == 2 else 0)
        try:
            return datetime(y, int(m.group(1)), int(m.group(2))).date().isoformat()
        except ValueError:
            return ""
    return ""


def _local_date(ts: str) -> str:
    if not ts:
        return ""
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(LOCAL).date().isoformat()


def _iso_duration(d: str) -> int:
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d or "")
    if not m:
        return 0
    days, h, mi, s = (int(x or 0) for x in m.groups())
    return days * 86400 + h * 3600 + mi * 60 + s


def list_videos(api: ApiClient, channel_id: str = CHANNEL_ID, max_pages: int = 40) -> list[dict]:
    ch = api.get("channels", part="contentDetails", id=channel_id)
    uploads = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    videos, token = [], None
    for _ in range(max_pages):
        params = {"part": "snippet,contentDetails", "playlistId": uploads, "maxResults": 50}
        if token:
            params["pageToken"] = token
        page = api.get("playlistItems", **params)
        for it in page.get("items", []):
            sn = it["snippet"]
            videos.append({
                "video_id": it["contentDetails"]["videoId"], "title": sn.get("title", ""),
                "description": sn.get("description", ""),
                "published_at": it["contentDetails"].get("videoPublishedAt") or sn.get("publishedAt", ""),
            })
        token = page.get("nextPageToken")
        if not token:
            break
    for i in range(0, len(videos), 50):
        batch = videos[i:i + 50]
        det = api.get("videos", part="contentDetails,liveStreamingDetails", id=",".join(v["video_id"] for v in batch))
        by_id = {d["id"]: d for d in det.get("items", [])}
        for v in batch:
            d = by_id.get(v["video_id"], {})
            v["duration_seconds"] = _iso_duration(d.get("contentDetails", {}).get("duration", ""))
            v["live_started_at"] = d.get("liveStreamingDetails", {}).get("actualStartTime", "")
    return videos


def _kind(text: str) -> str:
    t = text.lower()
    if "redevelopment" in t or re.search(r"\bcra\b", t):
        return "Community Redevelopment Agency"
    if "workshop" in t or "work session" in t:
        return "workshop"
    if "council" in t:
        return "City Council"
    return ""


def match(videos: list[dict], meetings: list[dict]) -> list[dict]:
    by_event = {m["event_id"]: m for m in meetings}
    by_date: dict[str, list[dict]] = {}
    for m in meetings:
        by_date.setdefault(m["date"], []).append(m)
    out = []
    for v in videos:
        row = {**v, "url": f"https://www.youtube.com/watch?v={v['video_id']}",
               "title_date": parse_title_date(v["title"]), "event_id": None, "meeting_date": "",
               "meeting": "", "matched_by": ""}
        ev = _EVENT_LINK.search(v["description"])
        if ev and int(ev.group(1)) in by_event:
            m = by_event[int(ev.group(1))]
            row.update(event_id=m["event_id"], meeting_date=m["date"], meeting=m["name"], matched_by="description link")
        else:
            for how, date in (("title date", row["title_date"]), ("live stream date", _local_date(v["live_started_at"]))):
                cands = by_date.get(date, []) if date else []
                kind = _kind(v["title"])
                if kind and len(cands) > 1:
                    narrowed = [m for m in cands if kind.lower() in (m["category"] + " " + m["name"]).lower()]
                    cands = narrowed or cands
                if len(cands) == 1:
                    m = cands[0]
                    row.update(event_id=m["event_id"], meeting_date=m["date"], meeting=m["name"], matched_by=how)
                    break
        out.append(row)
    out.sort(key=lambda r: r["published_at"], reverse=True)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m opencivic.video")
    ap.add_argument("--meetings", type=Path, default=Path("data/listings/civicclerk-meetings.jsonl"))
    ap.add_argument("-o", "--output", type=Path, default=Path("data/listings/youtube-videos.jsonl"))
    ap.add_argument("--channel-id", default=CHANNEL_ID)
    args = ap.parse_args(argv)
    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not key:
        print("YOUTUBE_API_KEY not set; skipping video listing", file=sys.stderr)
        return 0
    meetings = [json.loads(x) for x in args.meetings.read_text("utf-8").splitlines() if x.strip()]
    api = ApiClient(key)
    try:
        videos = list_videos(api, args.channel_id)
    except FetchError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    rows = match(videos, meetings)
    args.output.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), "utf-8")
    matched = sum(1 for r in rows if r["event_id"])
    print(f"{len(rows)} videos, {matched} matched to meetings, {api.calls} API calls", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
