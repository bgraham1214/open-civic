# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Fingerprint and log every published document (Phase 1, step 3).

Reads the adapters' listings, downloads each document, and records its SHA-256.
Two files under the data directory, both committed to git:

  manifest.jsonl  Append-only event log, one JSON line per event:
                    new       first time we saw and fetched this document
                    changed   same document (same key), different bytes
                    unlisted  dropped from the source's listing
                    relisted  back in the listing after being dropped
                  Git history of this file is the tamper-evident record.

  state.json      Latest known state per document (hash, size, last check, errors).
                  Rewritten each run; it decides what to re-check.

A document's key is stable per source: `civicclerk:<tenant>:<fileId>` or
`civicplus_archive:<host>:<ADID>`. Known documents are re-downloaded every
`--recheck-days` days, so a silent edit to a published PDF shows up as `changed`.

With --store-dir, each distinct file is also saved as <sha256>.<ext> so copies can be
kept somewhere the city doesn't control (the workflow uploads them to a GitHub release).

Usage:
  python -m opencivic.manifest update --civicclerk data/listings/civicclerk-meetings.jsonl \\
      --archive data/listings/archive-items.jsonl --data-dir data --store-dir out/files
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .fetch import FetchError, HttpFetcher
from .jurisdictions import JURISDICTIONS, group_of, jurisdiction_of

# Guard: if a source's listing shrinks below this share of what was listed before,
# assume a partial fetch and don't mark the missing documents as unlisted.
MIN_LISTING_RATIO = 0.5


@dataclass
class Doc:
    key: str
    source: str
    url: str
    title: str
    kind: str
    date: str
    body: str      # meeting name or archive module
    page: str      # human-facing page that links the document


def _skip_kinds(key: str) -> set[str]:
    return set(JURISDICTIONS.get(jurisdiction_of(key) or "", {}).get("skip_kinds", []))


def docs_from_civicclerk(path: Path) -> list[Doc]:
    """Documents in a CivicClerk meetings listing, minus the kinds its jurisdiction skips."""
    out = []
    for line in path.read_text("utf-8").splitlines():
        m = json.loads(line)
        skip = _skip_kinds(f"civicclerk:{m['tenant']}:")
        for f in m["files"]:
            if f["kind"] in skip:
                continue
            out.append(Doc(
                key=f"civicclerk:{m['tenant']}:{f['file_id']}", source="civicclerk",
                url=f["download_url"], title=f["name"], kind=f["kind"], date=m["date"],
                body=f"{m['name']} ({m['category']})", page=m["portal_url"],
            ))
    return out


ARCHIVE_KINDS = {"agenda": "Agenda", "minutes": "Minutes"}


def docs_from_archive(path: Path) -> list[Doc]:
    out = []
    for line in path.read_text("utf-8").splitlines():
        it = json.loads(line)
        host = urlsplit(it["site"]).netloc
        mod = it["module"].lower()
        kind = ("Agendas & Minutes" if "agenda" in mod and "minutes" in mod
                else next((v for k, v in ARCHIVE_KINDS.items() if k in mod), "Document"))
        out.append(Doc(
            key=f"civicplus_archive:{host}:{it['adid']}", source="civicplus_archive",
            url=it["url"], title=it["title"], kind=kind, date=it["date"],
            body=it["module"], page=it["module_url"],
        ))
    return out


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _ext(body: bytes, content_type: str) -> str:
    if body.startswith(b"%PDF-"):
        return "pdf"
    ct = content_type.split(";")[0].strip().lower()
    return {"text/html": "html", "application/msword": "doc",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx"}.get(ct, "bin")


def _due(entry: dict, now: datetime, recheck_days: float) -> bool:
    last = entry.get("last_checked")
    if not last:
        return True
    return now - datetime.fromisoformat(last.replace("Z", "+00:00")) >= timedelta(days=recheck_days)


def update(docs: list[Doc], data_dir: Path, fetcher, *, recheck_days: float = 7.0,
           max_downloads: int | None = None, store_dir: Path | None = None,
           copy_base: str | None = None, sources_ok: set[str] | None = None) -> dict:
    """Fetch what's due, append events, rewrite state. Returns a run summary."""
    data_dir.mkdir(parents=True, exist_ok=True)
    state_path = data_dir / "state.json"
    state: dict[str, dict] = json.loads(state_path.read_text("utf-8")) if state_path.exists() else {}
    events: list[dict] = []
    summary = {"listed": len(docs), "downloaded": 0, "new": 0, "changed": 0, "unchanged": 0,
               "unlisted": 0, "relisted": 0, "errors": 0, "skipped_not_due": 0, "deferred": 0}
    now_dt = datetime.now(timezone.utc)
    sources_ok = sources_ok if sources_ok is not None else {d.source for d in docs}

    def event(kind: str, doc: Doc | None, entry: dict, **extra) -> None:
        rec = {"event": kind, "key": entry["key"], "at": _now(), "source": entry["source"],
               "date": entry.get("date", ""), "kind": entry.get("kind", ""), "title": entry.get("title", ""),
               "url": entry.get("url", ""), "sha256": entry.get("sha256", ""), "bytes": entry.get("bytes", 0)}
        if entry.get("copy_url"):
            rec["copy_url"] = entry["copy_url"]
        rec.update(extra)
        events.append(rec)
        summary[kind] += 1

    seen_keys = set()
    downloads = 0
    for doc in docs:
        if doc.key in seen_keys:
            continue
        seen_keys.add(doc.key)
        entry = state.get(doc.key)
        meta = {"key": doc.key, "source": doc.source, "url": doc.url, "title": doc.title,
                "kind": doc.kind, "date": doc.date, "body": doc.body, "page": doc.page}
        if entry is None:
            entry = {**meta, "listed": True}
        else:
            if not entry.get("listed", True):
                entry.update(meta, listed=True)
                event("relisted", doc, entry)
            entry.update(meta)
        state[doc.key] = entry

        if entry.get("sha256") and not _due(entry, now_dt, recheck_days):
            summary["skipped_not_due"] += 1
            continue
        if max_downloads is not None and downloads >= max_downloads:
            summary["deferred"] += 1
            continue
        downloads += 1
        try:
            body, ctype = fetcher.download(doc.url)
        except FetchError as e:
            entry["last_error"] = f"{_now()} {e}"
            summary["errors"] += 1
            continue
        summary["downloaded"] += 1
        sha = hashlib.sha256(body).hexdigest()
        ext = _ext(body, ctype)
        retrieved = _now()
        entry.pop("last_error", None)
        entry["last_checked"] = retrieved
        if store_dir is not None:
            store_dir.mkdir(parents=True, exist_ok=True)
            target = store_dir / f"{sha}.{ext}"
            if not target.exists():
                target.write_bytes(body)
        copy_url = f"{copy_base.rstrip('/')}/{sha}.{ext}" if copy_base else ""

        old = entry.get("sha256")
        if old == sha:
            summary["unchanged"] += 1
            continue
        entry.update(sha256=sha, bytes=len(body), content_type=ctype, ext=ext,
                     last_changed=retrieved, copy_url=copy_url or entry.get("copy_url", ""))
        if old is None:
            entry["first_seen"] = retrieved
            event("new", doc, entry, retrieved_at=retrieved, content_type=ctype)
        else:
            event("changed", doc, entry, retrieved_at=retrieved, content_type=ctype, previous_sha256=old)

    # Unlisted: only for groups (one account on one platform, e.g. civicclerk:pascocofl)
    # whose listing loaded this run and looks complete. sources_ok may name groups or
    # whole sources.
    groups = sorted({group_of(k) for k, e in state.items()
                     if group_of(k) in sources_ok or e["source"] in sources_ok})
    for group in groups:
        prev = [k for k, e in state.items() if group_of(k) == group and e.get("listed", True)]
        current = {k for k in seen_keys if group_of(k) == group}
        if prev and len(current) < MIN_LISTING_RATIO * len(prev):
            print(f"warning: {group} listing shrank from {len(prev)} to {len(current)}; "
                  "not marking documents unlisted this run", file=sys.stderr)
            continue
        for k in prev:
            if k not in current:
                state[k]["listed"] = False
                state[k]["unlisted_at"] = _now()
                event("unlisted", None, state[k])

    with (data_dir / "manifest.jsonl").open("a", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n")
    state_path.write_text(json.dumps(dict(sorted(state.items())), indent=1, ensure_ascii=False) + "\n", "utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m opencivic.manifest")
    ap.add_argument("what", choices=["update"])
    ap.add_argument("--civicclerk", type=Path, nargs="*", default=[],
                    help="civicclerk meetings jsonl, one per tenant")
    ap.add_argument("--archive", type=Path, help="archivecenter items jsonl")
    ap.add_argument("--data-dir", type=Path, default=Path("data"))
    ap.add_argument("--store-dir", type=Path, help="save each distinct file as <sha256>.<ext>")
    ap.add_argument("--copy-base", help="URL prefix where stored copies will be published")
    ap.add_argument("--recheck-days", type=float, default=7.0)
    ap.add_argument("--max-downloads", type=int)
    args = ap.parse_args(argv)

    docs: list[Doc] = []
    ok: set[str] = set()
    inputs = [(p, docs_from_civicclerk, "civicclerk") for p in args.civicclerk]
    if args.archive is not None:
        inputs.append((args.archive, docs_from_archive, "civicplus_archive"))
    for path, loader, source in inputs:
        if path.exists() and path.stat().st_size > 0:
            loaded = loader(path)
            docs += loaded
            # mark the listing's groups as complete; a tenant whose file failed stays untouched
            ok |= {group_of(d.key) for d in loaded}
            if source == "civicclerk":
                ok |= {f"civicclerk:{json.loads(x)['tenant']}" for x in path.read_text("utf-8").splitlines() if x.strip()}
        else:
            print(f"warning: {path} missing or empty; {source} skipped this run", file=sys.stderr)

    summary = update(docs, args.data_dir, HttpFetcher(), recheck_days=args.recheck_days,
                     max_downloads=args.max_downloads, store_dir=args.store_dir,
                     copy_base=args.copy_base, sources_ok=ok)
    print(json.dumps(summary), file=sys.stderr)
    return 1 if summary["errors"] and not summary["downloaded"] else 0


if __name__ == "__main__":
    sys.exit(main())
