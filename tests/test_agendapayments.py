# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Payment lists filed with agendas (agendapayments.py). Lines are made up in each report's layout; the
names are invented."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from opencivic import agendapayments as ap
from opencivic import payments

COLLIER = """\
                                                       COLLIER COUNTY BOARD OF COUNTY COMMISSIONERS
                                                                   DISBURSEMENTS REPORT
Clear Date                     Payee            Check       Amount                        G/L Description                              Public Purpose or Invoice Description
   1/29/2026 EXAMPLE PAVING INC                 ACH29            8,440.14 ROAD MATERIALS                           MAINTAIN ROADS
   1/29/2026 EXAMPLE PAVING INC                 ACH29              100.00 ROAD MATERIALS                           MAINTAIN ROADS
   1/29/2026 EXAMPLE PAVING INC                 ACH29              (40.14) RETAINAGE HELD                          MAINTAIN ROADS
                                                        $      8,500.00
  1/29/2026 SAMPLE ADVERTISING & MARKETING INACH29             300.00 ROAD MATERIALS                           PROMOTE TOURISM
                                                        $        300.00
  1/29/2026 HOMEOWNER PERSON                    232033          1,400.00 DISASTER ASSISTANCE                      CARES RELIEF
                                                        $      1,400.00
  1/29/2026 LANDLORD HOLDINGS LLC               ACHCA           2,800.00 DISASTER ASSISTANCE                      ESG-000001 JUL 25 TENANT Pat
  1/29/2026 LANDLORD HOLDINGS LLC               ACHCA           2,800.00 ROAD MATERIALS ESG-000001 JUN 25 TENANT Pat
                                                        $      5,600.00
  1/29/2026 WRONG TOTAL CORP                    WIR06           1,000.00 ROAD MATERIALS                           BUILD
                                                        $        999.00
  1/30/2026 EXAMPLE PAVING INC                  ACH30              500.00 ROAD MATERIALS                           MAINTAIN ROADS
                                                                   500.00
\f  1/31/2026 NO SUBTOTAL AFTER LLC              ACH31               10.00 ROAD MATERIALS                           X
"""

SANTA_ROSA = """\
 Department: 0010                BOARD OF COMMISSIONERS
            Vendor Name                Fund         Fund Name               Check    Void   Check Date     Vendor    Account    Transaction Description   Transaction
 PRIVATE PERSON                       001     GENERAL REVENUE FUND       2601774            11/18/2025   15613      20200015   OVERPAYMENT                       $15.00
 PRIVATE PERSON                                                                                                                                                 $15.00
 FLORIDA ASSOCIATION OF EXAMPLES      001     GENERAL REVENUE FUND       2602014            11/25/2025   00020882   5540011     MEMBERSHIP DUES               $21,796.00
 INC
 FLORIDA ASSOCIATION OF EXAMPLES INC                                                                                                                           $21,796.00
 SAMPLE CONTRACTING LLC               001     GENERAL REVENUE FUND       V2602025            11/25/2025   13633      53400010   POND WORK                      $6,705.44
                                      001     GENERAL REVENUE FUND       2602026     Y      11/25/2025   13633      53400010   POND WORK                        $100.00
 SAMPLE CONTRACTING LLC                                                                                                                                         $6,805.44
 0010         BOARD OF COMMISSIONERS                                                                                                                         $28,616.44
 Summary                                                                                                                                                     $28,616.44
"""


class Collier(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.counts = ap.parse_collier(COLLIER)

    def test_groups_checked_against_subtotals(self):
        self.assertEqual(self.counts["groups_wrong"], ["p1 WRONG TOTAL CORP: 999.00 vs 1,000.00"])
        self.assertNotIn("WRONG TOTAL CORP", {r["vendor"] for r in self.rows})
        # a subtotal printed without "$" still closes its group; lines after the last subtotal aren't kept
        self.assertIn(("EXAMPLE PAVING INC", 500.0), {(r["vendor"], r["amount"]) for r in self.rows})
        self.assertNotIn("NO SUBTOTAL AFTER LLC", {r["vendor"] for r in self.rows})

    def test_lines(self):
        first = self.rows[0]
        self.assertEqual((first["vendor"], first["check"], first["paid"], first["amount"], first["account_desc"]),
                         ("EXAMPLE PAVING INC", "ACH29", "2026-01-29", 8440.14, "ROAD MATERIALS"))
        self.assertIn(-40.14, [r["amount"] for r in self.rows])
        glued = [r for r in self.rows if r["vendor"].startswith("SAMPLE ADVERTISING")][0]
        self.assertEqual((glued["vendor"], glued["check"]), ("SAMPLE ADVERTISING & MARKETING IN", "ACH29"))

    def test_purpose_never_stored_and_on_behalf_dropped(self):
        text = json.dumps(self.rows)
        self.assertNotIn("TENANT", text)
        self.assertNotIn("ESG", text)
        self.assertNotIn("DISASTER ASSISTANCE", text)
        # rent relief paid to a landlord is paid on the tenant's behalf: neither line is kept, even the one whose
        # category ran into the purpose (the test reads the whole line before anything is blanked)
        self.assertNotIn("LANDLORD HOLDINGS LLC", {r["vendor"] for r in self.rows})

    def test_only_businesses_kept_by_read(self):
        self.assertFalse(payments.is_business("HOMEOWNER PERSON"))
        self.assertTrue(payments.is_business("EXAMPLE PAVING INC"))


class SantaRosa(unittest.TestCase):
    def test_parse(self):
        rows, counts = ap.parse_santarosa(SANTA_ROSA)
        self.assertEqual(counts["groups_wrong"], [])
        self.assertEqual(counts["void"], 1)
        by = {(r["vendor"], r["amount"]) for r in rows}
        # the wrapped name comes whole from the subtotal line
        self.assertIn(("FLORIDA ASSOCIATION OF EXAMPLES INC", 21796.0), by)
        self.assertIn(("SAMPLE CONTRACTING LLC", 6705.44), by)
        self.assertNotIn(("SAMPLE CONTRACTING LLC", 100.0), by)  # void
        self.assertEqual({r["account_desc"] for r in rows}, {"Board Of Commissioners"})
        self.assertNotIn("OVERPAYMENT", json.dumps(rows))  # descriptions are never stored
        self.assertNotIn("POND WORK", json.dumps(rows))


def _pdf_with_box(box: bool) -> bytes:
    """A one-page PDF; with box, a filled black rectangle like a redaction."""
    content = b"BT /F1 12 Tf 72 720 Td (Payment list) Tj ET\n" + (b"0 0 0 rg 72 600 120 14 re f\n" if box else b"")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(content) + content + b"endstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)


@unittest.skipUnless(shutil.which("pdftoppm"), "needs pdftoppm (poppler-utils)")
class BlackBoxes(unittest.TestCase):
    def test_box_found_text_not(self):
        self.assertEqual(ap.dark_pages(_pdf_with_box(True)), {1})
        self.assertEqual(ap.dark_pages(_pdf_with_box(False)), set())


class Candidates(unittest.TestCase):
    def test_attachments_from_items(self):
        with tempfile.TemporaryDirectory() as d:
            lst = Path(d) / "listings"
            lst.mkdir()
            items = [
                {"date": "2026-02-24", "title": "To record ... the referenced disbursements in the amount of $1",
                 "portal_url": "https://colliercofl.portal.civicclerk.com/event/1508/files",
                 "attachments": [{"id": 16657, "name": "2.11.2026  Disbursements", "bytes": 428799,
                                  "content_type": "application/pdf"},
                                 {"id": 1, "name": "Warranty Deed", "bytes": 5, "content_type": "application/pdf"}]},
                {"date": "2026-02-24", "title": "Recommendation to accept a warranty deed",
                 "attachments": [{"id": 2, "name": "Disbursements memo", "bytes": 9}]},
            ]
            (lst / "civicclerk-colliercofl-items.jsonl").write_text("".join(json.dumps(i) + "\n" for i in items))
            c = ap.candidates("colliercounty", Path(d))
            self.assertEqual([x["id"] for x in c], [16657])
            self.assertEqual(c[0]["portal_url"], "https://colliercofl.portal.civicclerk.com/event/1508/files")


class Page(unittest.TestCase):
    def test_section_names_its_range_and_holes(self):
        regs = {"t:1": {"name": "t:1", "title": "040225 - 041525", "meeting_date": "2025-04-24", "week": "2025-04-24",
                        "first_paid": "2025-04-08", "last_paid": "2025-04-15", "url": "https://x.example/event/1/files"},
                "t:2": {"name": "t:2", "title": "060425 - 061725", "meeting_date": "2025-06-23", "week": "2025-06-23",
                        "first_paid": "2025-06-10", "last_paid": "2025-06-17", "url": "https://x.example/event/2/files"}}
        rows = [{"vendor": "SAMPLE CONTRACTING LLC", "check": "2504416", "paid": "2025-06-10", "amount": 10.0,
                 "account_desc": "Solid Waste", "page": 3, "register": "t:2"}]
        h = payments.section_html("santarosacounty", "Sample Contracting, LLC", rows, regs, [], 1)
        self.assertIn("We have the 2 lists filed with agendas from April 24, 2025 to June 23, 2025", h)
        self.assertIn("No list here covers payments between April 15, 2025 and June 10, 2025.", h)
        self.assertIn('href="https://x.example/event/2/files"', h)
        self.assertIn("PDF page 3", h)
        self.assertNotIn("Invoice", h)


if __name__ == "__main__":
    unittest.main()
