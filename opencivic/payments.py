# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Payments a county Clerk recorded, from its weekly payment registers (the user's order, Nov 17, 2026:
"payments and what was ordered should be collected").

An approval is permission to spend up to an amount. A payment register shows a check or transfer actually
sent. Pasco County's Clerk & Comptroller (the county's auditor, who pays its bills) posts one PDF a week:

  index  https://app.pascoclerk.com/appdot-public-statistical-reports-boccpr.asp
  file   https://app.pascoclerk.com/public_records/bcc-payment-registers/For%20the%20week%20through%20<date>.pdf

Checked Nov 17, 2026 (all 8 files then online, 720 pages, read before this was written):

- app.pascoclerk.com has no robots.txt (404); pascoclerk.com's rules don't cover it. The folder itself is
  403, so the index page is the only list.
- **Only the last eight weeks are online.** The week through Apr 19, 2026, found by a search engine, was
  gone (404). Anything older needs a records request; this collector keeps every week it sees from Nov 17,
  2026 on (earliest kept: the week through Sep 27, 2026).
- Text PDFs from Tyler Munis. Each file holds several reports: a "PAID INVOICES REPORT" per pay run (17145C,
  17145D, 17145E, 17145EJ, 17145JB …), then "A/P CASH DISBURSEMENTS JOURNAL" and "JOURNAL ENTRIES TO BE
  CREATED" sections. **Only the Paid Invoices reports are read**: the journals list refunds by payee (home
  builders, utility customers), and residents are never stored.
- A Paid Invoices report lists a vendor ("  4460 ORLANDO FREIGHTLINER INC"), one line per invoice line,
  "INVOICE: <number>" under each, and "VENDOR TOTALS". A vendor's lines can carry over a page break, after
  the repeated page header, without the vendor line. Every one of the 7,848 invoice lines matched LINE:

    INV DATE  [VOUCHER | PO]  CHECK NO  T  CHK DATE  GL ACCOUNT (8)  OBJECT (6)  PROJECT (5 or blank)
    ACCOUNT DESCRIPTION (cut at 25 characters by the report)  AMOUNT (negative for credits)

  A line carries a voucher or a purchase order, never both (see below for telling which).
  T is P (printed check), T (electronic transfer) or M (manual check), as the journals' totals name them.
- VENDOR TOTALS prints three figures whose labels are ambiguous; they're not stored.
- Payees include people paid for services (sports officials, instructors, reimbursements). **Only payees
  whose name ends in a business suffix (Inc, LLC, Corp, Co, P.A. …; money.SUFFIXES) are stored.** The money
  tracker only recognizes companies by that suffix, so no company page loses a match by this; 5,442 of 7,848
  lines (Nov 17). Inmate-fund, bond and child-support lines go to sheriffs, clerks and the state.

- **The Clerk blacks out some payees** (114 vendor blocks in the 8 weeks): the name is removed from the file,
  and usually the lines too. In the week through Oct 11, 2026 one vendor's 45 lines were still in the text
  under the boxes. Nothing under a box is ever stored: lines with no vendor line are skipped, each vendor's
  lines must add up to its VENDOR TOTALS figure (this caught ~700 refund lines first credited to the
  business above them), and blacked_out() renders each page and drops any line whose amount sits under a
  dark box or can't be found. Because the files themselves keep that text, **copies are not uploaded** to
  the public "files" release (the workflow passes no --store-dir) until the user decides.
- The text layout misplaces columns line to line; voucher vs PO is decided from word positions instead
  (blacked_out). All but one of 3,549 such numbers are POs.

    python -m opencivic.payments collect --data-dir data [--store-dir out/files]

Reads the index (one request), downloads each register not seen before or whose "Updated On" date changed
(about 2 MB each), with --store-dir keeps a copy named by SHA-256, and rewrites:

  data/listings/pasco-payment-registers.jsonl  one line per register: name, url, updated, sha256, bytes,
                                               pages, lines read, lines kept, copy_url, retrieved_at
  data/listings/pasco-payments.jsonl           one line per kept invoice line
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from .fetch import FetchError, HttpFetcher

CLERKS = {
    # kind "register": the Clerk's own weekly payment registers (this module).
    # kind "agenda": payment lists the Clerk files with the Commission's agendas (agendapayments.py, Nov 18, 2026).
    "pasco": {
        "kind": "register",
        "name": "Pasco County Clerk & Comptroller",
        "index": "https://app.pascoclerk.com/appdot-public-statistical-reports-boccpr.asp",
        "kept_online": "about eight weeks",
    },
    "colliercounty": {
        "kind": "agenda",
        "name": "Collier County Clerk of the Circuit Court & Comptroller",
        "lists": "the Disbursements Reports the Clerk files with the County Commission's agenda about every two weeks",
        "account": "The Clerk's account name (G/L)",
        "account_note": "Account names are as the report prints them. Payee names are cut at 35 characters by the "
                        "report, so a company whose name is longer may not be matched. Lines paid on a person's "
                        "behalf (assistance, refunds) are left out.",
    },
    "santarosacounty": {
        "kind": "agenda",
        "name": "Santa Rosa County Clerk of Courts & Comptroller",
        "lists": "the Check Registers filed with the County Commission's agenda about once a month",
        "account": "Department",
        "account_note": "Department names are as the register prints them. Voided checks are left out.",
    },
}
COPY_BASE = "https://github.com/bgraham1214/open-civic/releases/download/files"

LINE = re.compile(
    r"^(\s+)(?P<inv_date>\d\d/\d\d/\d\d)(?P<mid>(?:\s+\S+){0,2}?)\s+(?P<check>\d{4,7})\s+(?P<type>[A-Z])\s+"
    r"(?P<paid>\d\d/\d\d/\d\d)\s+(?P<gl>\w{8})\s+(?P<obj>\d{6})\s+(?P<proj>\w{5}|\s{5,6})\s{0,40}"
    r"(?P<desc>\S.{0,29}?)\s{1,60}(?P<amount>-?[\d,]*\.\d\d)\s*$")
INVOICE = re.compile(r"^\s+INVOICE:\s{0,20}(\S.*?)\s*$")
VENDOR = re.compile(r"^\s{0,8}(\d{1,7})\s{1,4}(\S.*?)\s*$")
NOT_VENDOR = re.compile(r"Page\s+\d+\s*$|PAY RUN|VENDOR|Report generated|User:|Program ID|Pasco County|INV DATE")
TYPES = {"P": "check", "T": "electronic transfer", "M": "manual check"}
BUSINESS = re.compile(r"[\s,.](?:inc|incorporated|llc|l\.l\.c|corp|corporation|company|co|lp|l\.p|llp|lllp|"
                      r"p\.\s?a|pa|pllc|pl|ltd|n\.a)\.?$", re.I)


def is_business(name: str) -> bool:
    """A payee we may store: its name ends in a business suffix. People's names don't."""
    return bool(BUSINESS.search(name.strip()))


def _date(mdy: str) -> str:
    m, d, y = mdy.split("/")
    return f"20{y}-{m}-{d}"


def _amount(s: str) -> float:
    return float(s.replace(",", ""))


def parse(text: str) -> tuple[list[dict], dict]:
    """Invoice lines of the Paid Invoices reports in a register's text (pdftotext -layout, pages split by
    form feeds). Returns (rows for every payee, counts). Callers keep only is_business payees."""
    rows: list[dict] = []
    counts = {"lines": 0, "unread": 0, "pay_runs": set(), "totals_checked": 0, "totals_wrong": []}
    since = 0.0  # this vendor's lines since its vendor line, checked against VENDOR TOTALS
    section = vendor = header = None
    vendor_no = run = ""
    for page_no, page in enumerate(text.split("\f"), 1):
        for s in page.split("\n"):
            if "PAID INVOICES REPORT" in s:
                section = "paid"
                continue
            if "A/P CASH DISBURSEMENTS" in s or "JOURNAL ENTRIES TO BE" in s:
                section, vendor = "other", None
                continue
            if section != "paid" or not s.strip():
                continue
            m = re.search(r"PAY RUN:\s*(\S+)", s)
            if m:
                if m.group(1) != run:
                    vendor, since = None, 0.0  # a new pay run starts with its own vendor line
                run = m.group(1)
                counts["pay_runs"].add(run)
                continue
            if "INV DATE" in s and "VOUCHER" in s:
                header = s
                continue
            m = LINE.match(s)
            if m:
                counts["lines"] += 1
                if not vendor:
                    counts["unread"] += 1
                    continue
                since += _amount(m.group("amount"))
                ref = " ".join(m.group("mid").split())  # voucher or PO: told by its column (place())
                rows.append({"vendor": vendor, "vendor_no": vendor_no, "invoice_date": _date(m.group("inv_date")),
                             "ref": ref, "voucher": "", "po": "", "check": m.group("check"),
                             "type": TYPES.get(m.group("type"), m.group("type")), "paid": _date(m.group("paid")),
                             "account": f'{m.group("gl")} {m.group("obj")} {m.group("proj").strip()}'.strip(),
                             "account_desc": m.group("desc").strip(), "amount": _amount(m.group("amount")),
                             "invoice": "", "pay_run": run, "page": page_no})
                continue
            m = INVOICE.match(s)
            if m:
                if rows and not rows[-1]["invoice"] and vendor and rows[-1]["vendor"] == vendor:
                    rows[-1]["invoice"] = m.group(1)
                continue
            if re.match(r"^\s+VENDOR TOTALS", s):
                # the last figure is this run's total for the vendor; a missed vendor line shows up here
                t = re.findall(r"-?[\d,]*\.\d\d", s)
                if vendor and t:
                    counts["totals_checked"] += 1
                    if abs(_amount(t[-1]) - since) > 0.005:
                        counts["totals_wrong"].append(f"p{page_no} {vendor}: {t[-1]} vs {since:,.2f}")
                vendor, since = None, 0.0
                continue
            m = VENDOR.match(s)
            if m and not NOT_VENDOR.search(s) and not re.search(r"\d\d/\d\d/\d\d", s):
                vendor_no, vendor, since = m.group(1), re.sub(r"\s+", " ", m.group(2)), 0.0
    counts["pay_runs"] = sorted(counts["pay_runs"])
    return rows, counts


def list_registers(page_html: str, base: str) -> list[dict]:
    """[{name, url, updated}] from the Clerk's index page, oldest first."""
    out = []
    rows = re.findall(r"<tr\b.*?</tr>", page_html, re.S | re.I)
    for r in rows:
        m = re.search(r'href="([^"]*bcc-payment-registers/[^"]+\.pdf)"[^>]*>(.*?)</a>', r, re.S | re.I)
        if not m:
            continue
        name = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(2))).replace("PDF file, opens in a new window", "")
        u = re.search(r"\b(\d{1,2}/\d{1,2}/\d{4})\b", re.sub(r"<[^>]+>", " ", r))
        out.append({"name": html.unescape(name).strip(), "url": urljoin(base, html.unescape(m.group(1))),
                    "updated": u.group(1) if u else ""})
    if not out:  # no table rows: plain links
        for m in re.finditer(r'href="([^"]*bcc-payment-registers/[^"]+\.pdf)"', page_html, re.I):
            u = urljoin(base, html.unescape(m.group(1)))
            out.append({"name": re.sub(r"%20", " ", u.rsplit("/", 1)[-1])[:-4], "url": u, "updated": ""})
    return sorted(out, key=lambda r: r["name"])


def week_of(name: str) -> str:
    m = re.search(r"(\d{4}-\d\d-\d\d)", name)
    return m.group(1) if m else ""


def pdf_text(pdf: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as fh:
        fh.write(pdf)
        fh.flush()
        return subprocess.run(["pdftotext", "-layout", fh.name, "-"], capture_output=True, text=True,
                              check=True, timeout=300).stdout


def _pgm(path: Path) -> tuple[int, int, bytes]:
    data = path.read_bytes()
    parts = data.split(maxsplit=4)  # P5, width, height, maxval, pixels
    assert parts[0] == b"P5", path
    return int(parts[1]), int(parts[2]), parts[4]


def blacked_out(pdf: bytes, rows: list[dict], dpi: int = 50) -> list[bool]:
    """For each row, True when the Clerk blacked it out, or it can't be found on its page to check.
    Also files each row's number under VOUCHER or PO by where it sits on the page: pdftotext's layout
    moves columns line to line (Nov 17, 2026: of 3,549 such numbers, 3,548 sit under PO, at x=255, and one
    under VOUCHER, at x=218; the layout text had put 741 nearer VOUCHER).

    The Clerk redacts some payees with black boxes drawn over the text, but the text stays in the file
    (Nov 17, 2026: one vendor's 45 lines in the week through Oct 11). The vendor's name was removed, so its
    lines have no vendor and are never read; this also catches a box over one line under a visible name.
    Each row is found by its check number and amount on the same line of its page; the amount's box on the
    rendered page must not be mostly dark."""
    if not rows:
        return []
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "r.pdf"
        src.write_bytes(pdf)
        bbox = subprocess.run(["pdftotext", "-bbox", str(src), "-"], capture_output=True, text=True,
                              check=True, timeout=600).stdout
        subprocess.run(["pdftoppm", "-gray", "-r", str(dpi), str(src), str(Path(tmp) / "p")], check=True,
                       timeout=1200)
        pages = {}
        for n, page in enumerate(re.findall(r"<page\b.*?</page>", bbox, re.S), 1):
            pages[n] = [(float(a), float(b), float(c), float(d), html.unescape(t)) for a, b, c, d, t in re.findall(
                r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>', page)]
        images = {int(re.search(r"(\d+)\.pgm$", f.name).group(1)): f for f in Path(tmp).glob("p-*.pgm")}
        cache: dict[int, tuple[int, int, bytes]] = {}
        out = []
        for r in rows:
            words = pages.get(r["page"], [])
            amt = f'{r["amount"]:,.2f}'.replace("-", "")
            amt = amt[1:] if amt.startswith("0.") else amt  # the report prints ".59", not "0.59"
            checks = [w for w in words if w[4] == r["check"]]
            hits = [w for w in words if w[4].lstrip("-") == amt and any(abs(c[1] - w[1]) < 1.5 for c in checks)]
            if not hits or r["page"] not in images:
                out.append(True)
                continue
            if r.get("ref"):
                y = hits[0][1]
                heads = [w for w in words if w[4] == "VOUCHER" and w[1] < y]
                at = [w[0] for w in words if w[4] == r["ref"] and abs(w[1] - y) < 1.5]
                if heads and at:
                    v = max(heads, key=lambda w: w[1])  # the column header nearest above the line
                    pos = [w[0] for w in words if w[4] == "PO" and abs(w[1] - v[1]) < 1.5 and w[0] > v[0]]
                    if pos:
                        r["voucher" if abs(at[0] - v[0]) < abs(at[0] - min(pos)) else "po"] = r["ref"]
            if r["page"] not in cache:
                cache[r["page"]] = _pgm(images[r["page"]])
            width, height, px = cache[r["page"]]
            k = dpi / 72
            dark = False
            for x0, y0, x1, y1, _ in hits:
                xs = range(max(0, int(x0 * k)), min(width, int(x1 * k) + 1))
                ys = range(max(0, int(y0 * k)), min(height, int(y1 * k) + 1))
                vals = [px[y * width + x] for y in ys for x in xs]
                dark = dark or (bool(vals) and sum(vals) / len(vals) < 80)
            out.append(dark)
        return out


def _read_jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text("utf-8").splitlines() if x.strip()] if p.exists() else []


def _write_jsonl(p: Path, rows: list[dict]) -> None:
    p.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), "utf-8")


def collect(clerk: str, data_dir: Path, store_dir: Path | None, fetcher=None) -> dict:
    c = CLERKS[clerk]
    f = fetcher or HttpFetcher()
    listings = data_dir / "listings"
    reg_path, pay_path = listings / f"{clerk}-payment-registers.jsonl", listings / f"{clerk}-payments.jsonl"
    registers = {r["name"]: r for r in _read_jsonl(reg_path)}
    payments = _read_jsonl(pay_path)
    summary = {"listed": 0, "new": 0, "changed": 0, "unchanged": 0, "errors": 0, "unread_lines": 0, "kept": 0}
    try:
        listed = list_registers(f.get_text(c["index"]), c["index"])
    except FetchError as e:
        print(f"{clerk}: index not read: {e}", file=sys.stderr)
        summary["errors"] += 1
        return summary
    summary["listed"] = len(listed)
    for r in listed:
        old = registers.get(r["name"])
        if old and old.get("updated") == r["updated"] and r["updated"]:
            summary["unchanged"] += 1
            continue
        try:
            body, _ = f.download(r["url"])
        except FetchError as e:
            print(f"{clerk}: {r['name']}: {e}", file=sys.stderr)
            summary["errors"] += 1
            continue
        sha = hashlib.sha256(body).hexdigest()
        if old and old.get("sha256") == sha:
            old["updated"] = r["updated"]
            summary["unchanged"] += 1
            continue
        text = pdf_text(body)
        rows, counts = parse(text)
        kept = [x for x in rows if is_business(x["vendor"])]
        hidden = blacked_out(body, kept)
        summary["blacked_out"] = summary.get("blacked_out", 0) + sum(hidden)
        kept = [x for x, h in zip(kept, hidden) if not h]
        for x in kept:
            if x["po"] or x["voucher"]:
                x.pop("ref")
        summary["unread_lines"] += counts["unread"]
        if store_dir:
            store_dir.mkdir(parents=True, exist_ok=True)
            (store_dir / f"{sha}.pdf").write_bytes(body)
        pages = text.count("\f") or 1
        registers[r["name"]] = {**r, "week": week_of(r["name"]), "sha256": sha, "bytes": len(body),
                                "pages": pages, "lines": counts["lines"], "unread": counts["unread"],
                                "kept": len(kept), "blacked_out": sum(hidden), "pay_runs": counts["pay_runs"],
                                "copy_url": f"{COPY_BASE}/{sha}.pdf" if store_dir else "",
                                "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                **({"replaces": old["sha256"]} if old else {})}
        payments = [x for x in payments if x["register"] != r["name"]]
        payments += [{**x, "register": r["name"], "sha256": sha} for x in kept]
        summary["changed" if old else "new"] += 1
    payments.sort(key=lambda x: (x["register"], x["page"], x["vendor"], x["check"], x["invoice"]))
    summary["kept"] = len(payments)
    listings.mkdir(parents=True, exist_ok=True)
    _write_jsonl(reg_path, sorted(registers.values(), key=lambda r: r["name"]))
    _write_jsonl(pay_path, payments)
    return summary


def load(data_dir: Path) -> dict[str, dict]:
    """clerk -> {"registers": {name: register}, "payments": [rows]} for every clerk with data."""
    out = {}
    for clerk in CLERKS:
        regs = _read_jsonl(data_dir / "listings" / f"{clerk}-payment-registers.jsonl")
        if regs:
            out[clerk] = {"registers": {r["name"]: r for r in regs},
                          "payments": _read_jsonl(data_dir / "listings" / f"{clerk}-payments.jsonl")}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="opencivic.payments")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--clerk", default="pasco", choices=sorted(k for k, v in CLERKS.items() if v["kind"] == "register"))
    c.add_argument("--data-dir", type=Path, default=Path("data"))
    c.add_argument("--store-dir", type=Path)
    p = sub.add_parser("parse", help="read a saved register PDF and print its kept rows (for checking)")
    p.add_argument("pdf", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "collect":
        s = collect(a.clerk, a.data_dir, a.store_dir)
        print(json.dumps({"payments": {a.clerk: s}}))
        return 0
    body = a.pdf.read_bytes()
    rows, counts = parse(pdf_text(body))
    kept = [x for x in rows if is_business(x["vendor"])]
    hidden = blacked_out(body, kept)
    for x, h in zip(kept, hidden):
        if not h:
            print(json.dumps(x))
    print(json.dumps({**counts, "rows": len(rows), "kept": len(kept) - sum(hidden), "blacked_out": sum(hidden)}),
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())


# --- On a company's page (money.company_html) ---------------------------------------------------------

SHOW = 60  # newest payments listed on a page; the rest are in payments/<clerk>.csv


def _e(s: str) -> str:
    return html.escape(str(s), quote=True)


def _money(v: float) -> str:
    return f"-${-v:,.2f}" if v < 0 else f"${v:,.2f}"


def for_company(company_key: str, data: dict, keyfn) -> dict[str, list[dict]]:
    """clerk -> this company's payments, newest first. Matched by the money tracker's name key only."""
    out = {}
    for clerk, d in data.items():
        if "_by_key" not in d:  # one pass per build, not one per company
            d["_by_key"] = {}
            for p in d["payments"]:
                d["_by_key"].setdefault(keyfn(p["vendor"]), []).append(p)
        rows = d["_by_key"].get(company_key)
        if rows:
            out[clerk] = sorted(rows, key=lambda p: (p["paid"], p["check"], p.get("invoice", "")), reverse=True)
    return out


def _gaps(registers: list[dict], days: int = 14) -> str:
    """' No list here covers payments between X and Y.' for each hole of more than `days` between one list's
    last payment and the next list's first (Santa Rosa, Nov 18, 2026: May 6 to June 10, 2025)."""
    from datetime import date
    from . import site
    rs = sorted((r for r in registers if r.get("first_paid") and r.get("last_paid")), key=lambda r: r["first_paid"])
    holes = [(a["last_paid"], b["first_paid"]) for a, b in zip(rs, rs[1:])
             if (date.fromisoformat(b["first_paid"]) - date.fromisoformat(a["last_paid"])).days > days]
    return "".join(f" No list here covers payments between {_e(site.long_date(x))} and {_e(site.long_date(y))}."
                   for x, y in holes)


def section_html(clerk: str, name: str, rows: list[dict], registers: dict[str, dict], approvals: list[dict],
                 depth: int) -> str:
    """'Payments the Clerk recorded' for one company. approvals: [{date, amount}] of this government's
    approved decisions for it, for same-amount notes."""
    from . import site
    from .jurisdictions import JURISDICTIONS
    c = CLERKS[clerk]
    agenda = c.get("kind") == "agenda"
    weeks = sorted(r["week"] for r in registers.values() if r.get("week") and not r.get("duplicate_of"))
    total = sum(p["amount"] for p in rows)
    up = "../" * depth

    def where(p: dict) -> str:
        r = registers.get(p["register"], {})
        if agenda:
            when = site.long_date(r["meeting_date"]) if r.get("meeting_date") else ""
            return (f'<a href="{_e(r["url"])}">Payment list filed with the {_e(when)} agenda</a> '
                    f'(&ldquo;{_e(r.get("title", ""))}&rdquo;, PDF page {p["page"]})') if r.get("url") else _e(when)
        wk = site.long_date(r["week"]) if r.get("week") else p["register"]
        link = (f'<a href="{_e(r["url"])}#page={p["page"]}">Clerk\'s register, week through {_e(wk)}</a> '
                f'(PDF, page {p["page"]})') if r.get("url") else _e(wk)
        if r.get("copy_url"):
            link += f'; <a href="{_e(r["copy_url"])}">our copy</a> (PDF download)'
        return link

    def same(p: dict) -> str:
        hits = [a for a in approvals if a["amount"] and abs(a["amount"] - p["amount"]) < 0.005 and a["date"] <= p["paid"]]
        return ("<br><span class=\"small\">Same amount as the approval of "
                + ", ".join(site.long_date(a["date"]) for a in hits) + " (a match the machine found)</span>") if hits else ""

    if agenda:
        head = (f'<th scope="col">Paid</th><th scope="col">Amount</th><th scope="col">Check or payment number</th>'
                f'<th scope="col">{_e(c["account"])}</th><th scope="col">Source</th>\n')
        body = "".join(
            f'<tr><td>{_e(site.long_date(p["paid"]))}</td><td class="num">{_e(_money(p["amount"]))}{same(p)}</td>'
            f'<td>{_e(p["check"] or "not shown")}</td><td>{_e(p.get("account_desc") or "not shown")}</td><td>{where(p)}</td></tr>'
            for p in rows[:SHOW])
    else:
        head = ('<th scope="col">Paid</th>\n<th scope="col">Amount</th><th scope="col">Check or transfer</th>'
                '<th scope="col">Invoice</th>\n<th scope="col">Purchase order</th><th scope="col">The Clerk\'s '
                'account name</th><th scope="col">Source</th>\n')
        body = "".join(
            f'<tr><td>{_e(site.long_date(p["paid"]))}</td><td class="num">{_e(_money(p["amount"]))}{same(p)}</td>'
            f'<td>{_e(p["type"])} {_e(p["check"])}</td><td>{_e(p["invoice"] or "not shown")}'
            f'{" (invoice dated " + _e(site.long_date(p["invoice_date"])) + ")" if p.get("invoice_date") else ""}</td>'
            f'<td>{_e(p["po"] or ("voucher " + p["voucher"] if p["voucher"] else "") or (p["ref"] + " (voucher or order)" if p.get("ref") else "") or "none listed")}</td><td>{_e(p["account_desc"])}</td><td>{where(p)}</td></tr>'
            for p in rows[:SHOW])
    gov = JURISDICTIONS[clerk]["short"] if clerk in JURISDICTIONS else clerk
    more = (f'<p class="small">The {SHOW} newest of {len(rows):,} are listed. All of them are in '
            f'<a href="{up}payments/{clerk}.csv">payments/{clerk}.csv</a> (spreadsheet).</p>') if len(rows) > SHOW else ""
    sid = f"pay-{clerk}"
    first, last = site.long_date(rows[-1]["paid"]), site.long_date(rows[0]["paid"])
    span = _e(f"paid on {last}" if first == last else f"paid from {first} to {last}")
    docs, doc = ("lists", "the Clerk's list") if agenda else ("registers", "the register")
    if agenda:
        live = [r for r in registers.values() if not r.get("duplicate_of") and r.get("lines", 1)]
        unread = [r for r in registers.values() if not r.get("duplicate_of") and not r.get("lines", 1)]
        weeks = sorted(r["week"] for r in live if r.get("week"))
        paid_from = min((r["first_paid"] for r in live if r.get("first_paid")), default="")
        paid_to = max((r["last_paid"] for r in live if r.get("last_paid")), default="")
        source = (f"These are payments actually sent, read from {_e(c['lists'])}. We have the {len(live)} lists filed "
                  f"with agendas from {_e(site.long_date(weeks[0]))} to {_e(site.long_date(weeks[-1]))}, covering "
                  f"payments made from {_e(site.long_date(paid_from))} to {_e(site.long_date(paid_to))}; a payment "
                  "outside those dates isn't here." + _gaps(live)
                  + (f" {len(unread)} newer {'list uses' if len(unread) == 1 else 'lists use'} a layout we don't "
                     "read yet." if unread else "")) if weeks and paid_from else (
                  f"These are payments actually sent, read from {_e(c['lists'])}.")
        note = c.get("account_note", "")
    else:
        have = (f"the week ending {site.long_date(weeks[0])}" if len(weeks) == 1 else
                f"{len(weeks)} weeks, ending {site.long_date(weeks[0])} through {site.long_date(weeks[-1])}")
        note = "Account names are as the register prints them, cut at 25 characters."
    if agenda:
        fair = f"""{source} The decisions above are permissions to spend up to an amount. The lists don't say which
decision a payment belongs to; a payment is shown beside a decision only when the amounts are the same, and that
match is the machine's, not the Clerk's. No payment here doesn't mean none was made. Payees the Clerk blacked out
are left out."""
    else:  # the Pasco wording of Nov 17, 2026, unchanged so its pages don't change
        fair = f"""These are payments actually sent, read from the Clerk's weekly payment registers. The decisions
above are permissions to spend up to an amount. The registers don't say which decision a payment belongs to;
a payment is shown beside a decision only when the amounts are the same, and that match is the machine's, not
the Clerk's. The Clerk keeps {_e(c["kept_online"])} of registers online; we have {_e(have)}, so an earlier payment isn't here, and no
payment here doesn't mean none was made. Payees the Clerk blacked out are left out."""
    return f"""<h2 id="{sid}">Payments {_e(gov)} County's Clerk recorded</h2>
<p class="lede">The {_e(c["name"])} recorded <mark>{_e(_money(total))}</mark> in {len(rows):,}
{"payment line" if len(rows) == 1 else "payment lines"} to {_e(name)}, {span}.</p>
<p class="fair">{fair}</p>
<p class="small">Matched to this company by name; {doc} calls it {_e("; ".join(sorted({p["vendor"] for p in rows})))}.</p>
<div class="scroll" role="region" aria-labelledby="{sid}-cap" tabindex="0"><table class="data">
<caption id="{sid}-cap">Payment lines to {_e(name)}, newest first</caption><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>
{more}<p class="small">{_e(note)}</p>"""


def write_csv(data: dict, out: Path) -> dict[str, int]:
    import csv
    counts = {}
    (out / "payments").mkdir(parents=True, exist_ok=True)
    for clerk, d in data.items():
        cols = (["paid", "vendor", "amount", "check", "account_desc", "register", "page"]
                if CLERKS[clerk].get("kind") == "agenda" else
                ["paid", "vendor", "amount", "type", "check", "invoice", "invoice_date", "po", "voucher", "account",
                 "account_desc", "pay_run", "register", "page", "sha256"])
        with open(out / "payments" / f"{clerk}.csv", "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(cols + ["register_url"])
            for p in sorted(d["payments"], key=lambda p: (p["paid"], p["vendor"], p["check"]), reverse=True):
                w.writerow([p.get(k, "") for k in cols] + [d["registers"].get(p["register"], {}).get("url", "")])
        counts[clerk] = len(d["payments"])
    return counts
