# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""YouTube video listing and matching, against a fake Data API."""

import unittest
from urllib.parse import parse_qs, urlsplit

from opencivic import video as vd
from opencivic.fetch import FetchError

KEY = "AIzaSECRET-test-key"


class FakeApi:
    def __init__(self, fail=False):
        self.fail = fail
        self.urls = []

    def get_json(self, url):
        self.urls.append(url)
        if self.fail:
            raise FetchError(f"HTTP 403 for {url}")
        u = urlsplit(url)
        method = u.path.rsplit("/", 1)[1]
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        assert q["key"] == KEY
        if method == "channels":
            return {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UUx"}}}]}
        if method == "playlistItems":
            if "pageToken" not in q:
                return {"nextPageToken": "p2", "items": [
                    item("v1", "Temple Terrace City Council Meeting February 17, 2026", "", "2026-02-18T15:00:00Z"),
                    item("v2", "City Council Meeting", "Agenda: https://templeterracefl.portal.civicclerk.com/event/23/files",
                         "2026-03-04T15:00:00Z")]}
            return {"items": [
                item("v3", "Community Redevelopment Agency Meeting 10-20-26", "", "2026-10-21T12:00:00Z"),
                item("v4", "Live: Council", "", "2026-09-02T12:00:00Z"),
                item("v5", "Holiday parade highlights", "", "2026-12-06T12:00:00Z")]}
        if method == "videos":
            ids = q["id"].split(",")
            return {"items": [{"id": i, "contentDetails": {"duration": "PT2H3M4S"},
                               **({"liveStreamingDetails": {"actualStartTime": "2026-09-01T22:01:00Z"}} if i == "v4" else {})}
                              for i in ids]}
        raise AssertionError(method)


def item(vid, title, desc, published):
    return {"snippet": {"title": title, "description": desc, "publishedAt": published},
            "contentDetails": {"videoId": vid, "videoPublishedAt": published}}


MEETINGS = [
    {"event_id": 11, "date": "2026-02-17", "name": "City Council Meeting", "category": "City Council"},
    {"event_id": 23, "date": "2026-03-03", "name": "City Council Meeting", "category": "City Council"},
    {"event_id": 40, "date": "2026-09-01", "name": "City Council Meeting", "category": "City Council"},
    {"event_id": 50, "date": "2026-10-20", "name": "City Council Meeting", "category": "City Council"},
    {"event_id": 51, "date": "2026-10-20", "name": "CRA Meeting", "category": "Community Redevelopment Agency Meeting"},
]


class Video(unittest.TestCase):
    def test_list_and_match(self):
        api = vd.ApiClient(KEY, FakeApi())
        videos = vd.list_videos(api)
        self.assertEqual(len(videos), 5)
        self.assertEqual(videos[0]["duration_seconds"], 2 * 3600 + 3 * 60 + 4)
        rows = {r["video_id"]: r for r in vd.match(videos, MEETINGS)}
        self.assertEqual((rows["v1"]["event_id"], rows["v1"]["matched_by"]), (11, "title date"))
        self.assertEqual((rows["v2"]["event_id"], rows["v2"]["matched_by"]), (23, "description link"))
        self.assertEqual(rows["v3"]["event_id"], 51)  # two meetings that day; title says CRA
        self.assertEqual((rows["v4"]["event_id"], rows["v4"]["matched_by"]), (40, "live stream date"))  # 6:01 PM local
        self.assertIsNone(rows["v5"]["event_id"])
        self.assertEqual(rows["v1"]["url"], "https://www.youtube.com/watch?v=v1")

    def test_key_never_in_errors(self):
        api = vd.ApiClient(KEY, FakeApi(fail=True))
        with self.assertRaises(FetchError) as cm:
            vd.list_videos(api)
        self.assertNotIn(KEY, str(cm.exception))
        self.assertIn("channels", str(cm.exception))

    def test_title_dates(self):
        self.assertEqual(vd.parse_title_date("City Council Meeting February 17, 2026"), "2026-02-17")
        self.assertEqual(vd.parse_title_date("CRA 10-20-26"), "2026-10-20")
        self.assertEqual(vd.parse_title_date("Parade"), "")


if __name__ == "__main__":
    unittest.main()
