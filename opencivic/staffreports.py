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
READER = 2  # bump when amount() changes: stored rows from an older reader are read again (text only, one request)
PASS_THROUGH = re.compile(r"\bpass[- ]?through\b", re.I)
_AMT = r"\$\s?([\d,]+(?:\.\d{1,2})?)"
_NTE = r"not[- ]to[- ]exceed"
# What the decision is, from its title (Nov 17, 2026, all 198 Pinellas reports read).
# A title that names several vendors: one amount for all of them can't be given to the one the reader finds
# ("Agreements with Average Joe Landscape, Duval Landscape Maintenance, and Rotolo Consultants, Inc.", "ADB
# Safegate Americas, LLC and Allen Enterprises").
SEVERAL = re.compile(r"\bagreements\b|\bauthorizations\b|\bcontracts\b|"
                     r"(?:LLC|L\.?L\.?C\.?|Inc\.?|Corp\.?|Corporation|Company|Co\.|L\.?P\.?|LLLP|P\.?A\.?),?\s+(?:and|&)\s+"
                     r"[A-Z][\w&.'’-]*(?:\s+[A-Z][\w&.'’-]*){0,4},?\s+for\b")
_VENDORS = re.compile(r"\b(?:with|to)\s+(.{3,160}?)\s+for\b")
_LIST = re.compile(r",\s+[A-Z][\w&.'’-]*(?:\s+[A-Z][\w&.'’-]*)*,?\s+and\s+[A-Z]")


def several_vendors(title: str) -> bool:
    m = _VENDORS.search(title or "")
    return bool(SEVERAL.search(title or "") or (m and _LIST.search(m.group(1))))


NOT_A_PAYMENT = re.compile(r"\btermina(?:te|ted|tes|ting|tion)\b|\blitigation\b|\blawsuit\b|\brevok\w*|\brescind\w*|\brepeal\w*", re.I)
_ORD = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
        "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12}
_ORD_WORD = {v: k for k, v in _ORD.items()}
AMENDMENT = re.compile(rf"\b({'|'.join(_ORD)}|\d+(?:st|nd|rd|th))\s+amendment\b|\bamendment\s+no\.?\s*(\d+)", re.I)
CHANGE_ORDER = re.compile(r"\bchange\s+order\s+no\.?\s*(\d+)", re.I)
# The award's total: "Contract expenditure not-to-exceed: $454,860.00", "Total not to exceed amount of $522,183.40",
# "Thirty-Six (36) month agreement not-to-exceed: $2,389,975.00", "Total contract not to exceed $413,880.00",
# "EXPENDITURES: $1,653,503.00" (Coconut Creek), "COST: $100,000.00" (Deltona).
AWARD_LABEL = re.compile(
    rf"((?:[A-Za-z()\-0-9]+\s+){{0,5}}?(?:expenditures?|fees|contract|agreement|amount|award)?\s*{_NTE}(?:\s+(?:amount|expenditure))?"
    rf"(?:\s+of)?|expenditures|cost|total cost)\s*:?\s*{_AMT}(?!\s*(?:per|an?|/)\s*(?:hour|year|month|annual))", re.I)
# history and funding lines, which aren't this award's total
_NOT_TOTAL = re.compile(r"\b(?:revised|current|original|approved|to date|budget|funding|fund|grants?|fy\s?\d|remaining|"
                        r"previous|prior|combined|year\s+\d|annual)\b", re.I)


def fiscal_section(plain: str) -> str:
    """The report's Fiscal Impact section (Pinellas), or the whole text when it has none (Coconut Creek's
    "FISCAL IMPACT:", Deltona's "COST:" come first)."""
    text = re.sub(r"\s+", " ", plain or "")
    i = text.lower().find("fiscal impact")
    if i < 0:
        return text
    ends = [j for j in (text.find(m, i) for m in ("Staff Member Responsible", "Partners:", "Attachments:", "SOURCE OF FUNDS"))
            if j > i]
    return text[i:min(ends) if ends else i + 2000]


def _ordinal(title: str) -> tuple[str, int] | None:
    m = CHANGE_ORDER.search(title)
    if m:
        return "change order", int(m.group(1))
    m = AMENDMENT.search(title)
    if m:
        w = (m.group(1) or m.group(2) or "").lower()
        n = _ORD.get(w) or int(re.match(r"\d+", w).group())
        return "amendment", n
    return None


def amount(plain: str, title: str = "") -> dict | None:
    """{label, amount, added} from a staff report, or None.

    An amendment or change order gives only its own line ("Third Amendment $ 670,000.00", "Change Order No. 2
    increase: $ 475,581.27"), as money added to a contract approved earlier; never the revised total. An award
    gives its not-to-exceed total; history and funding lines are skipped, and an annual figure gives way to a
    total. Nothing for a termination, litigation or revocation, when labeled figures disagree, or when the
    report mentions pass-through funds."""
    text = re.sub(r"\s+", " ", plain or "")
    if PASS_THROUGH.search(text) or NOT_A_PAYMENT.search(title or "") or several_vendors(title):
        return None
    f = fiscal_section(text)
    kind = _ordinal(title or "")
    if kind:
        what, n = kind
        if what == "change order":
            rx = rf"\bchange\s+order\s+no\.?\s*{n}\b(?:\s+(?:increase|additional funds[\w ]*))?\s*:?\s*{_AMT}"
            label = f"Change Order No. {n}"
        else:
            names = rf"(?:{_ORD_WORD.get(n, str(n))}|{n}(?:st|nd|rd|th))"
            rx = (rf"\b{names}\s+amendment\b(?:\s+(?:increase|funds for [\w ]{{1,40}}?))?(?:\s+{_NTE})?(?:\s+amount)?"
                  rf"\s*:?\s*{_AMT}")
            label = f"{_ORD_WORD.get(n, str(n)).capitalize()} Amendment"
        found = {float(m.group(1).replace(",", "")) for m in re.finditer(rx, f, re.I)}
        found.discard(0.0)
        if len(found) == 1:
            return {"label": label, "amount": found.pop(), "added": True}
        # a renewal whose report gives only its own spend, with no history of earlier approvals ("Estimated
        # twenty-four (24) expenditure not to exceed: $190,000.00", Van Scoyoc's First Amendment)
        if found or re.search(r"\b(?:original|current|revised|previous|prior|to date|approved|initial)\b|"
                              r"\bno fiscal impact\b", f, re.I):
            return None
        got = _award(f)
        return {**got, "added": True} if got else None
    return _award(f)


def _award(f: str) -> dict | None:
    found = []
    for m in AWARD_LABEL.finditer(f):
        lab = re.sub(r"\s+", " ", m.group(1)).strip()
        a = float(m.group(2).replace(",", ""))
        if a <= 0 or _NOT_TOTAL.search(lab):
            continue
        found.append((lab, a))
    if not found or len({a for _, a in found}) > 1:
        return None
    lab, a = found[0]
    lab = re.sub(r"^(?:[\d,.]+\s+|(?:and|the|with|a|an|of|for)\s+)+", "", lab, flags=re.I)
    if lab.isupper():
        lab = lab.lower()
    return {"label": lab[:1].upper() + lab[1:], "amount": a, "added": False}


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


def fetch_one(client: str, it: dict, fetcher, have: dict | None = None) -> dict:
    base = api_base(client).rstrip("/")
    if have and have.get("found") and have.get("item_last_modified") == it.get("item_last_modified", ""):
        # the item hasn't changed; only the reader has: read the same text again
        text = fetcher.get_json(f"{base}/matters/{have['matter_id']}/texts/{have['text_id']}")
        row = {k: have[k] for k in ("key", "item_last_modified", "matter_id", "text_id", "found")}
        row["reader"] = READER
        got = amount(text.get("MatterTextPlain") or "", it.get("title") or "")
        return {**row, **got} if got else row
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
    got = amount(text.get("MatterTextPlain") or "", it.get("title") or "")
    row = {"key": it["key"], "item_last_modified": it.get("item_last_modified", ""), "matter_id": mid,
           "text_id": int(text_id), "found": True, "reader": READER}
    if got:
        row.update(got)
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
                if it["key"] not in have or have[it["key"]].get("item_last_modified") != it.get("item_last_modified", "")
                or (have[it["key"]].get("found") and have[it["key"]].get("reader", 1) < READER)]
        done = errors = 0
        for it in todo:
            if time.monotonic() > deadline:
                break
            try:
                have[it["key"]] = fetch_one(client, it, fetcher, have.get(it["key"]))
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
                out[k] = {"label": r["label"], "amount": r["amount"], "added": bool(r.get("added"))}
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
