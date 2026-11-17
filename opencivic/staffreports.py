# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""The amount a staff report gives for a contract whose agenda title names the company but not the amount.

Pinellas titles read "Ranking of firms and agreement with LucyRx Health Solutions, Inc. for pharmacy benefit
services …", with no figure, so the money tracker couldn't count them. Legistar's API also serves each item's
own text (the "matter text": the staff report). Surveyed Nov 17, 2026 (two reports from each of 23
governments): the layouts differ from government to government, many reports name losing bidders or past
vendors, and some totals aren't the company's (Pinellas's CDBG-DR agreement with Horne LLP: $565.7 million, of
which $478.9 million is rebuilding grants passed through to homeowners). Free-text amounts would be wrong too
often. Three governments state the amount in a labeled field, and only those fields are read:

  pinellas      "Contract expenditure not to exceed: $1,664,740.00", "Total contract not to exceed: $1,360,000.00"
  coconutcreek  "FISCAL IMPACT: REVENUES: $0 EXPENDITURES: $1,653,503.00"
  deltona       "COST: $100,000.00"

Only approved items whose title names exactly one company and no amount, and reads as money going out, are
looked up. A report that mentions pass-through funds gives no amount. Nothing else from the report is stored
(it names residents and other vendors): one row per item, with the label, the amount and where it came from.

    python -m opencivic.staffreports collect --data-dir data --minutes 20

Three requests per item (find the matter by its file number, its versions, the newest text), one at a time,
no faster than two a second, newest items first, inside the time budget; an item is read again only when
Legistar says it changed. Output: data/listings/legistar-<client>-staffreports.jsonl.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

from .fetch import FetchError, HostDown, HttpFetcher
from .legistar import api_base

CLIENTS = {"pinellas", "coconutcreek", "deltona"}
LABEL = re.compile(
    r"\b((?:(?:total|annual|contract)\s+)?(?:estimated\s+)?(?:contract\s+)?(?:expenditures?|fees|contract|amount)\s+"
    r"not\s+to\s+exceed|expenditures|cost)\s*:\s*"
    r"\$\s?([\d,]+(?:\.\d{1,2})?)(?!\s*(?:per|an?|/)\s*(?:hour|year|month|annual))", re.I)
PASS_THROUGH = re.compile(r"\bpass[- ]?through\b", re.I)


def amount(plain: str) -> tuple[str, float] | None:
    """(label, amount) from a staff report's labeled field, or None. When a report gives several labeled
    amounts that differ, none is used."""
    text = re.sub(r"\s+", " ", plain or "")
    if PASS_THROUGH.search(text):
        return None
    found = [(re.sub(r"\s+", " ", m.group(1)), float(m.group(2).replace(",", ""))) for m in LABEL.finditer(text)]
    found = [(l, a) for l, a in found if a > 0]
    # "Total estimated expenditure not to exceed: $9,000,000.00 Annual estimated expenditure not to exceed:
    # $1,800,000.00": the total is the contract's
    if any(not l.lower().startswith("annual") for l, _ in found):
        found = [(l, a) for l, a in found if not l.lower().startswith("annual")]
    if not found or len({a for _, a in found}) > 1:
        return None
    label, a = found[0]
    return label[:1].upper() + label[1:].lower(), a


def candidates(lst: Path, client: str) -> list[dict]:
    """Approved items whose title names exactly one company, no amount, and money going out."""
    from . import money
    from .explain import money as amounts
    path = lst / f"legistar-{client}-items.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text("utf-8").splitlines():
        it = json.loads(line)
        if (it.get("result") or "").lower() not in ("pass", "passed") or not it.get("file_number"):
            continue
        t = money.decap(it["title"])
        if amounts(f"{t} {it.get('motion') or ''}") or len(money.payees(t)) != 1 or money.direction(t) != "out":
            continue
        out.append(it)
    return sorted(out, key=lambda it: it["date"], reverse=True)


def _read(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    return {r["key"]: r for r in (json.loads(x) for x in path.read_text("utf-8").splitlines() if x.strip())}


def fetch_one(client: str, it: dict, fetcher) -> dict:
    base = api_base(client).rstrip("/")
    mid = it.get("matter_id")
    if not mid:
        rows = fetcher.get_json(f"{base}/matters?$filter={quote('MatterFile eq ' + repr(it['file_number']).replace(chr(34), chr(39)), safe='')}")
        rows = [r for r in rows if (r.get("MatterFile") or "").strip() == it["file_number"].strip()]
        if len(rows) != 1:
            return {"key": it["key"], "item_last_modified": it.get("item_last_modified", ""), "found": False}
        mid = rows[0]["MatterId"]
    versions = fetcher.get_json(f"{base}/matters/{mid}/versions")
    if not versions:
        return {"key": it["key"], "item_last_modified": it.get("item_last_modified", ""), "matter_id": mid, "found": False}
    text_id = max(versions, key=lambda v: int(v.get("Value") or 0))["Key"]
    text = fetcher.get_json(f"{base}/matters/{mid}/texts/{text_id}")
    got = amount(text.get("MatterTextPlain") or "")
    row = {"key": it["key"], "item_last_modified": it.get("item_last_modified", ""), "matter_id": mid,
           "text_id": int(text_id), "found": True}
    if got:
        row.update(label=got[0], amount=got[1])
    return row


def collect(data: Path, minutes: float, fetcher=None) -> dict:
    lst = data / "listings"
    deadline = time.monotonic() + minutes * 60
    fetcher = fetcher or HttpFetcher(min_interval=0.5, retries=2)
    summary = {}
    for client in sorted(CLIENTS):
        path = lst / f"legistar-{client}-staffreports.jsonl"
        have = _read(path)
        todo = [it for it in candidates(lst, client)
                if it["key"] not in have or have[it["key"]].get("item_last_modified") != it.get("item_last_modified", "")]
        done = errors = 0
        for it in todo:
            if time.monotonic() > deadline:
                break
            try:
                have[it["key"]] = fetch_one(client, it, fetcher)
                done += 1
            except HostDown as e:
                print(f"{client}: {e}", file=sys.stderr)
                break
            except (FetchError, KeyError, TypeError, ValueError) as e:
                print(f"{client}: {it['key']}: {e}", file=sys.stderr)
                errors += 1
        path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for _, r in sorted(have.items())), "utf-8")
        summary[client] = {"candidates": len(candidates(lst, client)), "read": done, "errors": errors,
                           "left": len(todo) - done - errors,
                           "with_amount": sum(1 for r in have.values() if r.get("amount"))}
    return summary


def amounts_by_key(lst: Path) -> dict[str, dict]:
    """{item key: {label, amount}} for every stored report that gave one."""
    out = {}
    for client in CLIENTS:
        for k, r in _read(lst / f"legistar-{client}-staffreports.jsonl").items():
            if r.get("amount"):
                out[k] = {"label": r["label"], "amount": r["amount"]}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m opencivic.staffreports")
    ap.add_argument("what", choices=["collect"])
    ap.add_argument("--data-dir", type=Path, default=Path("data"))
    ap.add_argument("--minutes", type=float, default=20)
    a = ap.parse_args(argv)
    print(json.dumps({"staffreports": collect(a.data_dir, a.minutes)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
