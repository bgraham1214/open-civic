# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Payments a county recorded, from the payment lists its Clerk files with the County Commission's agenda (the
user's order, Nov 18, 2026: "payment tracking for other counties and companies").

Florida law (s. 136.06(1)) has every county's disbursements recorded in the board's minutes, so many Clerks
attach a list of payments to each Commission agenda. We already collect those agendas, so the lists come
with them. Surveyed Nov 18, 2026: the agenda titles of all 111 registry governments searched for payment
lists ("disbursements", "check register", "warrant list", "bills paid", "accounts payable"). Found:

  readable here      Collier County (Disbursements Report, every two weeks)          colliercounty
                     Santa Rosa County (Check Register by Department, about monthly) santarosacounty
  not read           Polk ("Disbursements."), Pinellas ("BCC Release Checks"), Hernando (check registers),
                     Martin (warrant lists): Legistar attachments, whose server disallows all robots.
                     St. Lucie (warrant lists), South Bay (check register): scans with no text layer.
                     Flagler County: text, but the Clerk blacks out parts of lines (utility-assistance
                     recipients) and the text may remain under the boxes; left for a careful pass.
                     St. Cloud (monthly warrant list, 3 companies with decisions): not yet written.
                     Lee County: the agenda item has no attachment. Wildwood: a budget report, not payments.

Every file was read before this was written (29 Collier, 21 Santa Rosa; 135,912 and 24,945 lines):

- **Collier**: one line per invoice line: clear date, payee (cut at 35 characters), check or payment number
  (ACH29, WIR06, JPM12, BCCAC, 232032 …), amount ("(7,293.00)" is negative), G/L description (cut at 40), and
  a "Public Purpose or Invoice Description". After each payee's lines the report prints their subtotal; every
  payee's lines are checked against it (1 of ~27,000 groups disagreed: a Dec 2024 construction payment whose
  printed subtotal takes the retainage off twice; that group is left out). **The purpose column names
  residents** (rent and disaster-assistance payments to landlords name the tenant: "ESG-… JUL 25 <SURNAME>
  <Given>"), so it is never stored. The G/L description is kept only when the layout separates it from the
  purpose by two or more spaces, it is in capitals, and it recurs in the file (a long one sometimes runs into
  the purpose: "SHIP AFFORDABLE HOUSING DOWNPAYMENT REHAPROVIDE GRANT FUNDED HOMEBUYER ASSISTANCE"). Lines whose
  text says the money was paid on a person's behalf (ON_BEHALF: rent relief to a landlord, assistance, refunds,
  burials, homebuyer help) are dropped even when the payee is a business; the test reads the whole line,
  purpose included, before anything is blanked.
- **Santa Rosa**: grouped by department; a vendor's name is printed on its first line (wrapped onto a second
  line when long) and in full on its subtotal line, which is checked (every one of ~13,700 groups agreed). The
  transaction description names residents ("OVERPAYMENT", a Clerk payment described by a person's name), so
  only the department name is stored. Lines marked void ("Y", 73) are not payments and aren't stored. Four lines
  whose account code has a dot or whose amount the report cut off are unread.
- Both: **only payees whose name ends in a business suffix are stored** (payments.is_business), as for Pasco.
- No black boxes in any of the 50 files (dark_pages(): every page rendered; it finds Flagler's cross-hatched
  boxes and nothing in these). A page with a box is never read.

    python -m opencivic.agendapayments collect --clerk colliercounty --data-dir data

Downloads each list not seen before (the item listing gives its attachment id and size), through CivicClerk's
GetAttachmentFile (it downloads; residents are linked to the meeting's portal page, not to it), and rewrites
data/listings/<clerk>-payment-registers.jsonl and <clerk>-payments.jsonl, the files payments.load() reads.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .fetch import FetchError, HttpFetcher

SOURCES = {
    "colliercounty": {"tenant": "colliercofl", "parser": "collier",
                      "item": re.compile(r"\bdisbursements?\b", re.I),
                      "attachment": re.compile(r"disbursement", re.I)},
    "santarosacounty": {"tenant": "santarosacofl", "parser": "santarosa",
                        "item": re.compile(r"\bcheck registers?\b", re.I),
                        "attachment": re.compile(r"."),
                        "bytes_min": 50_000},  # the register itself, not a cover memo
}

# --- Collier ---------------------------------------------------------------------------------------------
_AMT = r"(\(?-?[\d,]*\.\d\d\)?)"
C_ROW = re.compile(r"^\s{0,8}(\d{1,2}/\d{1,2}/\d{4})\s+(\S.*?)\s+(?:\$\s{0,20})?" + _AMT + r"(?:\s{1,60}(\S.*?))?\s*$")
C_SUB = re.compile(r"^\s{20,}(?:\$\s*)?" + _AMT + r"\s*$")
# a payee cut at 35 characters can run into the payment number: "… MARKETING INACH28", "… SERVICNTACH16"
C_GLUED = re.compile(r"^(?P<pre>[A-Z.,&]{1,4}?)(?P<chk>(?:ACH|JPM|WIR|BCC)\w{0,4})$")
# Paid on a person's behalf (Nov 18, 2026, every Collier purpose under each category read): rent relief to
# landlords ("CARES RELIEF", "ESG-<case> <month> <tenant>"), assistance, refunds, burials, homebuyer help.
ON_BEHALF = re.compile(r"ASSISTANCE|REFUND|BURIAL|HOMEBUYER|DOWNPAYMENT|CARES RELIEF|\bRELIEF\b|\bESG\b")


def _amount(s: str) -> float:
    neg = "(" in s or "-" in s
    v = float(re.sub(r"[^\d.]", "", s) or 0)
    return -v if neg else v


def _mdy(s: str) -> str:
    m, d, y = s.split("/")
    return f"{y}-{int(m):02d}-{int(d):02d}"


def parse_collier(text: str) -> tuple[list[dict], dict]:
    rows: list[dict] = []
    grp: list[int] = []
    since = 0.0
    counts = {"lines": 0, "unread": 0, "groups": 0, "groups_wrong": [], "dropped_in_wrong_groups": 0}
    gl_seen: Counter = Counter()
    for pno, page in enumerate(text.split("\f"), 1):
        for s in page.split("\n"):
            m = C_ROW.match(s)
            if m:
                d, mid, a, rest = m.groups()
                toks = mid.rsplit(None, 1)
                payee, chk = (toks[0], toks[1]) if len(toks) == 2 else (mid, "")
                cm = C_GLUED.match(chk)
                if cm and len(payee) >= 28:
                    payee, chk = payee + " " + cm.group("pre"), cm.group("chk")
                parts = re.split(r"\s{2,}", rest or "")
                gl = parts[0][:40].strip() if len(parts) >= 2 else ""
                if gl and gl != gl.upper():
                    gl = ""
                counts["lines"] += 1
                rows.append({"vendor": re.sub(r"\s+", " ", payee).strip(), "check": chk, "paid": _mdy(d),
                             "amount": _amount(a), "account_desc": gl, "page": pno,
                             # judged on the whole line's text, before any category is blanked below
                             "_on_behalf": bool(ON_BEHALF.search(rest or ""))})
                gl_seen[gl] += 1
                grp.append(len(rows) - 1)
                since += _amount(a)
                continue
            if re.match(r"^\s{0,8}\d{1,2}/\d{1,2}/\d{4}\b", s):
                counts["unread"] += 1
                continue
            m = C_SUB.match(s)
            if m and grp:
                counts["groups"] += 1
                if abs(_amount(m.group(1)) - since) > 0.005:
                    counts["groups_wrong"].append(f"p{pno} {rows[grp[0]]['vendor']}: {m.group(1)} vs {since:,.2f}")
                    for i in grp:
                        rows[i]["_drop"] = True
                    counts["dropped_in_wrong_groups"] += len(grp)
                grp, since = [], 0.0
    for i in grp:  # lines after the last subtotal were never checked
        rows[i]["_drop"] = True
    for r in rows:
        if r["account_desc"] and gl_seen[r["account_desc"]] < 3:
            r["account_desc"] = ""
    counts["on_behalf"] = sum(1 for r in rows if r["_on_behalf"])
    keep = [r for r in rows if not r.pop("_drop", False) and not r.pop("_on_behalf")]
    return keep, counts


# --- Santa Rosa ------------------------------------------------------------------------------------------
_SAMT = r"(\(?-?\$[\d,]*\.\d\d\)?)"
S_ROW = re.compile(r"^\s{0,4}(?P<vendor>\S.*?)?\s{2,}(?P<fund>\d{3})\s{2,}(?P<fundname>\S.*?)\s{2,}(?P<check>V?\d{5,8})\s+"
                   r"(?:(?P<void>\S{1,6})\s+)?(?P<date>\d\d/\d\d/\d{4})\s+(?P<vno>\S+)\s+(?P<acct>[\d.]{4,12})\s{1,40}"
                   r"(?P<desc>\S.*?)?\s+" + _SAMT + r"\s*$")
S_SUB = re.compile(r"^\s{0,4}(?P<name>[A-Za-z0-9&].*?)\s{8,}" + _SAMT + r"\s*$")
S_DEPT = re.compile(r"^\s{0,4}Department:\s*(\S+)\s+(\S.*?)\s*$")
S_DTOT = re.compile(r"^\s{0,4}\d{3,6}\s{3,}\S.*?\s{8,}" + _SAMT + r"\s*$")


def parse_santarosa(text: str) -> tuple[list[dict], dict]:
    rows: list[dict] = []
    grp: list[int] = []
    since = 0.0
    dept = ""
    counts = {"lines": 0, "unread": 0, "groups": 0, "groups_wrong": [], "void": 0, "dropped_in_wrong_groups": 0}
    for pno, page in enumerate(text.split("\f"), 1):
        for s in page.split("\n"):
            m = S_DEPT.match(s)
            if m:
                dept = m.group(2)
                continue
            m = S_ROW.match(s)
            if m:
                g = m.groupdict()
                a = _amount(m.group(m.lastindex))
                counts["lines"] += 1
                rows.append({"vendor": "", "check": g["check"], "paid": _mdy(g["date"]), "amount": a,
                             "account_desc": dept.title(), "void": bool(g["void"]), "page": pno})
                grp.append(len(rows) - 1)
                since += a
                continue
            if S_DTOT.match(s) or re.match(r"^\s*Summary\s", s):
                continue
            m = S_SUB.match(s)
            if m and grp:
                counts["groups"] += 1
                name = re.sub(r"\s+", " ", m.group("name")).strip()
                if abs(_amount(m.group(2)) - since) > 0.005:
                    counts["groups_wrong"].append(f"p{pno} {name}: {m.group(2)} vs {since:,.2f}")
                    counts["dropped_in_wrong_groups"] += len(grp)
                else:
                    for i in grp:
                        rows[i]["vendor"] = name
                grp, since = [], 0.0
            elif re.search(r"\d\d/\d\d/\d{4}", s) and re.search(r"\$[\d,]*(?:\.\d\d)?\s*$", s):
                counts["unread"] += 1
    counts["void"] = sum(1 for r in rows if r["void"])
    keep = [{k: v for k, v in r.items() if k != "void"} for r in rows if r["vendor"] and not r["void"]]
    return keep, counts


PARSERS = {"collier": parse_collier, "santarosa": parse_santarosa}


# --- black boxes -------------------------------------------------------------------------------------------
def dark_pages(pdf: bytes, dpi: int = 50, min_w: float = 0.3, min_h: float = 0.08) -> set[int]:
    """Pages holding a filled dark box at least min_w x min_h inches (dark: gray < 110, since some Clerks'
    boxes are cross-hatched). Rule lines are one pixel tall and text isn't solid, so neither counts. Checked
    Nov 18, 2026: finds the boxes on Flagler's Oct 23 report (pages 2-6), none in 50 Collier/Santa Rosa files."""
    out: set[int] = set()
    need_w, need_h = int(min_w * dpi), max(2, int(min_h * dpi))
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "r.pdf"
        src.write_bytes(pdf)
        subprocess.run(["pdftoppm", "-gray", "-r", str(dpi), str(src), str(Path(tmp) / "p")], check=True, timeout=1200)
        for f in Path(tmp).glob("p-*.pgm"):
            n = int(re.search(r"(\d+)\.pgm$", f.name).group(1))
            parts = f.read_bytes().split(maxsplit=4)
            w, h, px = int(parts[1]), int(parts[2]), parts[4]
            height: dict[tuple[int, int], int] = {}
            for y in range(h):
                line = px[y * w:(y + 1) * w]
                runs, x0 = [], None
                for x, v in enumerate(line):
                    if v < 110:
                        if x0 is None:
                            x0 = x
                    elif x0 is not None:
                        if x - x0 >= need_w:
                            runs.append((x0, x))
                        x0 = None
                if x0 is not None and w - x0 >= need_w:
                    runs.append((x0, w))
                cur = {}
                for a, b in runs:
                    hgt = 1 + max([v for (c, d), v in height.items() if min(b, d) - max(a, c) >= need_w] or [0])
                    cur[(a, b)] = hgt
                    if hgt >= need_h:
                        out.add(n)
                height = cur
    return out


def pdf_text(pdf: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as fh:
        fh.write(pdf)
        fh.flush()
        return subprocess.run(["pdftotext", "-layout", fh.name, "-"], capture_output=True, text=True, check=True,
                              timeout=300).stdout


def read(clerk: str, pdf: bytes) -> tuple[list[dict], dict]:
    """Kept rows (business payees, not on a page with a black box) and counts, for one list."""
    from .payments import is_business
    rows, counts = PARSERS[SOURCES[clerk]["parser"]](pdf_text(pdf))
    boxed = dark_pages(pdf)
    counts["boxed_pages"] = sorted(boxed)
    rows = [r for r in rows if r["page"] not in boxed]
    kept = [r for r in rows if is_business(r["vendor"])]
    counts["kept"] = len(kept)
    return kept, counts


# --- collecting ---------------------------------------------------------------------------------------------
def candidates(clerk: str, data_dir: Path) -> list[dict]:
    """Payment lists attached to this government's agenda items, oldest first: [{name, id, bytes, date, item,
    portal_url}]. One list can be attached to more than one item (a re-posted agenda): kept once, by id."""
    src = SOURCES[clerk]
    path = data_dir / "listings" / f"civicclerk-{src['tenant']}-items.jsonl"
    out: dict[int, dict] = {}
    for line in path.read_text("utf-8").splitlines() if path.exists() else []:
        it = json.loads(line)
        if not src["item"].search(it.get("title") or ""):
            continue
        for a in it.get("attachments") or []:
            if src["attachment"].search(a.get("name") or "") and a.get("bytes", 0) >= src.get("bytes_min", 0) \
                    and (a.get("content_type") or "application/pdf") == "application/pdf":
                out[a["id"]] = {"name": a["name"].strip(), "id": a["id"], "bytes": a.get("bytes", 0), "date": it["date"],
                                "item": (it.get("title") or "")[:300], "portal_url": it.get("portal_url") or ""}
    return sorted(out.values(), key=lambda r: (r["date"], r["id"]))


def attachment_url(tenant: str, file_id: int) -> str:
    return f"https://{tenant}.api.civicclerk.com/v1/Meetings/GetAttachmentFile(fileId={file_id})"


def _read_jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text("utf-8").splitlines() if x.strip()] if p.exists() else []


def _write_jsonl(p: Path, rows: list[dict]) -> None:
    p.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), "utf-8")


def collect(clerk: str, data_dir: Path, fetcher=None, pdfs: dict[int, bytes] | None = None) -> dict:
    """pdfs: {attachment id: bytes} to read instead of downloading (tests, or files fetched through Explore)."""
    src = SOURCES[clerk]
    f = fetcher or HttpFetcher()
    listings = data_dir / "listings"
    reg_path, pay_path = listings / f"{clerk}-payment-registers.jsonl", listings / f"{clerk}-payments.jsonl"
    registers = {r["name"]: r for r in _read_jsonl(reg_path)}
    payments = _read_jsonl(pay_path)
    summary = {"listed": 0, "new": 0, "changed": 0, "unchanged": 0, "errors": 0, "unread_lines": 0,
               "groups_wrong": 0, "boxed_pages": 0, "kept": 0}
    for c in candidates(clerk, data_dir):
        summary["listed"] += 1
        key = f"{src['tenant']}:{c['id']}"
        old = registers.get(key)
        if old and old.get("bytes") == c["bytes"]:
            summary["unchanged"] += 1
            continue
        try:
            body = pdfs[c["id"]] if pdfs and c["id"] in pdfs else f.download(attachment_url(src["tenant"], c["id"]))[0]
        except (FetchError, KeyError) as e:
            print(f"{clerk}: {c['name']}: {e}", file=sys.stderr)
            summary["errors"] += 1
            continue
        if body[:5] != b"%PDF-":
            print(f"{clerk}: {c['name']}: not a PDF", file=sys.stderr)
            summary["errors"] += 1
            continue
        sha = hashlib.sha256(body).hexdigest()
        kept, counts = read(clerk, body)
        summary["unread_lines"] += counts["unread"]
        summary["groups_wrong"] += len(counts["groups_wrong"])
        summary["boxed_pages"] += len(counts["boxed_pages"])
        for g in counts["groups_wrong"]:
            print(f"{clerk}: {c['name']}: subtotal disagrees, group left out: {g}", file=sys.stderr)
        paid = sorted({r["paid"] for r in kept})
        registers[key] = {"name": key, "title": c["name"], "item": c["item"], "meeting_date": c["date"],
                          "url": c["portal_url"], "week": c["date"], "first_paid": paid[0] if paid else "",
                          "last_paid": paid[-1] if paid else "", "sha256": sha, "bytes": c["bytes"],
                          "pages": pdf_text(body).count("\f") or 1, "lines": counts["lines"], "unread": counts["unread"],
                          "groups_wrong": len(counts["groups_wrong"]), "boxed_pages": counts["boxed_pages"],
                          "kept": len(kept), "copy_url": "",
                          "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                          **({"replaces": old["sha256"]} if old else {})}
        payments = [x for x in payments if x["register"] != key]
        payments += [{**x, "register": key} for x in kept]  # the file's sha256 is on its register line
        summary["changed" if old else "new"] += 1
    # the same file attached again under another id (a re-posted agenda) is the same payments: keep the first
    first: dict[str, str] = {}
    for r in sorted(registers.values(), key=lambda r: (r.get("meeting_date", ""), r["name"])):
        first.setdefault(r["sha256"], r["name"])
        r["duplicate_of"] = first[r["sha256"]] if first[r["sha256"]] != r["name"] else ""
    payments = sorted((x for x in payments if not registers.get(x["register"], {}).get("duplicate_of")),
                      key=lambda x: (x["register"], x["page"], x["vendor"], x["check"]))
    summary["kept"] = len(payments)
    listings.mkdir(parents=True, exist_ok=True)
    _write_jsonl(reg_path, sorted(registers.values(), key=lambda r: r["name"]))
    _write_jsonl(pay_path, payments)
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="opencivic.agendapayments")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--clerk", choices=sorted(SOURCES), action="append")
    c.add_argument("--data-dir", type=Path, default=Path("data"))
    c.add_argument("--from-dir", type=Path, help="read <tenant>-<attachment id>.pdf files here instead of downloading")
    p = sub.add_parser("parse", help="read one saved list and print its kept rows (for checking)")
    p.add_argument("clerk", choices=sorted(SOURCES))
    p.add_argument("pdf", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "collect":
        out = {}
        for clerk in a.clerk or sorted(SOURCES):
            pdfs = None
            if a.from_dir:
                t = SOURCES[clerk]["tenant"]
                pdfs = {int(f.stem.rsplit("-", 1)[1]): f.read_bytes() for f in a.from_dir.glob(f"{t}-*.pdf")}
            out[clerk] = collect(clerk, a.data_dir, pdfs=pdfs, fetcher=HttpFetcher() if not pdfs else _NoFetch())
        print(json.dumps({"payments": out}))
        return 0
    kept, counts = read(a.clerk, a.pdf.read_bytes())
    for r in kept:
        print(json.dumps(r))
    print(json.dumps(counts), file=sys.stderr)
    return 0


class _NoFetch:
    def download(self, url):
        raise FetchError(f"not in --from-dir: {url}")


if __name__ == "__main__":
    sys.exit(main())
