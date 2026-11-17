# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Find which Florida counties and cities publish meetings on a platform we can already read.

Two platforms have public, documented-by-use APIs that our adapters read: Granicus Legistar
(https://webapi.legistar.com/v1/{client}/) and the CivicClerk portal
(https://{tenant}.api.civicclerk.com/v1/). Neither publishes a list of its accounts, so this
tries the names a government would plausibly have ("cityofedgewater", "hernandocountyfl",
"pascocofl") and records what answers, with enough evidence (board names, a recent meeting's
place) for a person to confirm it is the Florida government and not a namesake elsewhere.

The list of governments comes from the Census Bureau's place-by-county file (incorporated
places only; census designated places have no government) or, failing that, the Florida
Department of State's city/county list.

    python -m opencivic.discover places -o out/florida-places.jsonl
    python -m opencivic.discover probe --places out/florida-places.jsonl -o out/discover.jsonl

Polite: one request at a time per platform, about two a second, no retries on a miss.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import threading
from urllib.parse import quote

from .fetch import FetchError, HttpFetcher

COUNTIES = """Alachua Baker Bay Bradford Brevard Broward Calhoun Charlotte Citrus Clay Collier Columbia DeSoto
Dixie Duval Escambia Flagler Franklin Gadsden Gilchrist Glades Gulf Hamilton Hardee Hendry Hernando Highlands
Hillsborough Holmes Indian_River Jackson Jefferson Lafayette Lake Lee Leon Levy Liberty Madison Manatee Marion
Martin Miami-Dade Monroe Nassau Okaloosa Okeechobee Orange Osceola Palm_Beach Pasco Pinellas Polk Putnam
St._Johns St._Lucie Santa_Rosa Sarasota Seminole Sumter Suwannee Taylor Union Volusia Wakulla Walton
Washington""".split()
COUNTIES = [c.replace("_", " ") for c in COUNTIES]

PLACE_SOURCES = [
    "https://www2.census.gov/geo/docs/reference/codes2020/place_by_cou/st12_fl_place_by_county2020.txt",
    "https://dos.fl.gov/library-archives/research/florida-information/government/local-resources/citycounty-list/",
]

KINDS = {"city": "city", "town": "town", "village": "village"}


def parse_census(text: str) -> list[dict]:
    """STATE|STATEFP|COUNTYFP|COUNTYNAME|PLACEFP|PLACENS|PLACENAME|TYPE|CLASSFP|FUNCSTAT"""
    lines = text.splitlines()
    head = [h.strip().upper() for h in lines[0].split("|")]
    if "PLACENAME" not in head or "COUNTYNAME" not in head:
        return []
    out: dict[str, dict] = {}
    for line in lines[1:]:
        row = dict(zip(head, [c.strip() for c in line.split("|")]))
        if "INCORPORATED" not in row.get("TYPE", "").upper():
            continue
        m = re.match(r"(.+?) (city|town|village)(?: \(.*\))?$", row["PLACENAME"])
        if not m:
            continue
        name, kind = m.group(1), m.group(2)
        county = re.sub(r" County$", "", row["COUNTYNAME"])
        p = out.setdefault(name, {"name": name, "kind": kind, "counties": []})
        if county not in p["counties"]:
            p["counties"].append(county)
    return list(out.values())


def parse_dos(page: str) -> list[dict]:
    """The Department of State's table: a name, a kind and a county per row, in some order."""
    counties = {c.lower(): c for c in COUNTIES}
    out: dict[str, dict] = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S | re.I):
        cells = [html.unescape(re.sub(r"<[^>]+>", " ", c)).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S | re.I)]
        cells = [re.sub(r"\s+", " ", c) for c in cells if c.strip()]
        kind = next((c.lower() for c in cells if c.lower() in KINDS), None)
        county = next((counties[c.lower()] for c in cells if c.lower() in counties), None)
        rest = [c for c in cells if c.lower() not in KINDS and c.lower() not in counties]
        if kind and county and len(rest) == 1:
            p = out.setdefault(rest[0], {"name": rest[0], "kind": kind, "counties": []})
            if county not in p["counties"]:
                p["counties"].append(county)
    return list(out.values())


def norm(name: str) -> list[str]:
    """Spellings of a place name as an account name: 'St. Pete Beach' -> stpetebeach, saintpetebeach."""
    base = re.sub(r"[^a-z ]", "", name.lower().replace("-", " "))
    words = base.split()
    forms = {"".join(words)}
    swaps = {"st": "saint", "saint": "st", "fort": "ft", "ft": "fort", "mount": "mt", "mt": "mount"}
    if any(w in swaps for w in words):
        forms.add("".join(swaps.get(w, w) for w in words))
    return sorted(forms)


def candidates(place: dict) -> dict[str, list[str]]:
    """Account names to try on each platform."""
    leg: list[str] = []
    cc: list[str] = []
    for n in norm(place["name"]):
        if place["kind"] == "county":
            leg += [f"{n}county", f"{n}countyfl", n, f"{n}fl", f"{n}co", f"{n}cofl", f"{n}clerk"]
            cc += [f"{n}cofl", f"{n}countyfl", f"{n}fl", f"{n}county"]
        else:
            of = f"{place['kind']}of{n}"
            leg += [n, f"{n}fl", of, f"{of}fl", f"{n}florida"]
            cc += [f"{n}fl", f"{of}fl", of]
    seen: set[str] = set()
    return {"legistar": [c for c in leg if not (c in seen or seen.add(c))],
            "civicclerk": list(dict.fromkeys(cc))}


def _err(e: Exception) -> str:
    m = re.search(r"HTTP (\d+)", str(e))
    return f"HTTP {m.group(1)}" if m else str(e)[:80]


def probe_legistar(client: str, f: HttpFetcher) -> dict | None:
    base = f"https://webapi.legistar.com/v1/{client}/"
    try:
        bodies = f.get_json(base + "bodies")
    except FetchError as e:
        code = _err(e)
        # an unknown client answers HTTP 500; anything else means the account exists but is closed
        return None if code in ("HTTP 500", "HTTP 404") else {"client": client, "closed": code}
    except ValueError:
        return None
    if not isinstance(bodies, list):
        return None
    hit = {"client": client, "bodies": sorted({(b.get("BodyName") or "").strip() for b in bodies})[:80],
           "recent": []}
    try:
        ev = f.get_json(base + "events?$top=5&$orderby=" + quote("EventDate desc"))
        hit["recent"] = [{"date": (e.get("EventDate") or "")[:10], "body": e.get("EventBodyName"),
                          "location": (e.get("EventLocation") or "")[:120]} for e in ev]
        since = f.get_json(base + "events?$top=1000&$select=EventId,EventBodyName&$filter="
                           + quote("EventDate ge datetime'2025-01-01'"))
        hit["events_since_2025"] = len(since)
        counts: dict[str, int] = {}
        for e in since:
            counts[e.get("EventBodyName") or ""] = counts.get(e.get("EventBodyName") or "", 0) + 1
        hit["bodies_since_2025"] = dict(sorted(counts.items(), key=lambda kv: -kv[1])[:25])
    except (FetchError, ValueError) as e:
        hit["events_error"] = _err(e)
    return hit


def probe_civicclerk(tenant: str, f: HttpFetcher) -> dict | None:
    base = f"https://{tenant}.api.civicclerk.com/v1/"
    try:
        page = f.get_json(base + "Events?$top=5&$orderby=" + quote("startDateTime desc"))
    except (FetchError, ValueError):
        return None
    rows = page.get("value") if isinstance(page, dict) else None
    if rows is None:
        return None
    hit = {"tenant": tenant, "recent": [
        {"date": (e.get("startDateTime") or "")[:10], "name": e.get("eventName"),
         "category": e.get("categoryName"),
         "location": " ".join(str(v) for v in (e.get("eventLocation") or {}).values() if v)[:120]
         if isinstance(e.get("eventLocation"), dict) else ""} for e in rows]}
    try:
        flt = quote("startDateTime ge 2025-01-01T00:00:00Z and startDateTime le 2026-12-31T00:00:00Z")
        counts: dict[str, int] = {}
        with_files = 0
        url = base + f"Events?$filter={flt}&$top=200"
        for _ in range(12):
            page = f.get_json(url)
            for e in page.get("value", []):
                counts[e.get("categoryName") or ""] = counts.get(e.get("categoryName") or "", 0) + 1
                with_files += bool(e.get("publishedFiles"))
            url = page.get("@odata.nextLink")
            if not url:
                break
        hit["events_2025_2026"] = sum(counts.values())
        hit["with_files"] = with_files
        hit["categories"] = dict(sorted(counts.items(), key=lambda kv: -kv[1])[:25])
    except (FetchError, ValueError) as e:
        hit["events_error"] = _err(e)
    return hit


def robots_note(url: str) -> str:
    """What a host's robots.txt says to us, in a few words."""
    f = HttpFetcher(retries=0, min_interval=0.3, check_robots=False)
    try:
        body = f.get_text(url)
    except FetchError as e:
        return _err(e)
    lines = [ln.strip() for ln in body.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    return " / ".join(lines[:8])[:300]


def run_probe(places: list[dict], out_path: str) -> int:
    lock = threading.Lock()
    hits: list[dict] = []

    def work(platform: str) -> None:
        f = HttpFetcher(retries=0, min_interval=0.4, timeout=20, check_robots=False)
        tried: set[str] = set()
        for p in places:
            for acct in candidates(p)[platform]:
                if acct in tried:
                    continue
                tried.add(acct)
                try:
                    hit = (probe_legistar if platform == "legistar" else probe_civicclerk)(acct, f)
                except Exception as e:  # one odd answer mustn't stop the survey
                    print(f"{platform}:{acct}: {e}", file=sys.stderr)
                    hit = None
                if hit:
                    if platform == "legistar":
                        hit["robots_site"] = robots_note(f"https://{acct}.legistar.com/robots.txt")
                    else:
                        hit["robots_api"] = robots_note(f"https://{acct}.api.civicclerk.com/robots.txt")
                    row = {"platform": platform, "place": p["name"], "kind": p["kind"],
                           "counties": p.get("counties", []), **hit}
                    with lock:
                        hits.append(row)
                        print(json.dumps(row)[:300], flush=True)
        print(f"{platform}: tried {len(tried)} names", file=sys.stderr)

    threads = [threading.Thread(target=work, args=(pf,)) for pf in ("legistar", "civicclerk")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    hits.sort(key=lambda r: (r["kind"] != "county", r["place"], r["platform"]))
    with open(out_path, "w", encoding="utf-8") as fh:
        for r in hits:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(places)} governments; {len(hits)} accounts answered", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m opencivic.discover")
    ap.add_argument("what", choices=["places", "probe"])
    ap.add_argument("--places")
    ap.add_argument("--only", help="comma-separated place names (for a quick check)")
    ap.add_argument("-o", "--output", required=True)
    a = ap.parse_args(argv)
    if a.what == "places":
        f = HttpFetcher(retries=1)
        places: list[dict] = []
        for url in PLACE_SOURCES:
            try:
                text = f.get_text(url)
            except FetchError as e:
                print(f"{url}: {e}", file=sys.stderr)
                continue
            with open(a.output + "." + ("census.txt" if "census" in url else "dos.html"), "w") as fh:
                fh.write(text)
            places = parse_census(text) if "census" in url else parse_dos(text)
            print(f"{url}: {len(places)} incorporated places", file=sys.stderr)
            if len(places) > 300:
                break
        rows = [{"name": c, "kind": "county", "counties": [c]} for c in COUNTIES] + sorted(
            places, key=lambda p: p["name"])
        with open(a.output, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        return 0 if places else 1
    places = [json.loads(ln) for ln in open(a.places, encoding="utf-8") if ln.strip()]
    if a.only:
        want = {n.strip().lower() for n in a.only.split(",")}
        places = [p for p in places if p["name"].lower() in want]
    return run_probe(places, a.output)


if __name__ == "__main__":
    raise SystemExit(main())
