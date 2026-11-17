import unittest

from opencivic import money, payments

HEAD = """Pasco County, FL LIVE
PAID INVOICES REPORT
     PAY RUN: 90001C                                                                                   TO FISCAL 2026/12 10/01/2025 TO 11/30/2026

VENDOR NAME
                          INV DATE VOUCHER   PO         CHECK NO   T CHK DATE GL ACCOUNT               GL ACCOUNT DESCRIPTION
"""
FOOT = """
Report generated: 11/09/2026 11:47                                                                                                   Page        1
User:             someone
Program ID:       appdwarr
"""

# Invented vendors and numbers, in the layout of Pasco's register (Nov 17, 2026 survey).
PAGE1 = HEAD + """
 12001 EXAMPLE TRUCKS INC
                    08/21/26                   26001111      700001 P 10/15/26 10061410 564000 00000 Fleet Machinery & Equipme           206,040.00
          INVOICE: XJ1

         VENDOR TOTALS                5,206,096.30 YTD INVOICED                     5,205,766.00 YTD PAID                                206,040.00

  4142 SAMPLE GAS CO
                          09/14/26           27000252      700002 P 11/09/26 10060370 552000 00000 Operating Supplies                -125.99
             INVOICE:     9703
                          09/01/26                         700002 P 11/09/26 10060370 552000 00000 Operating Supplies                 299.99
""" + FOOT + "\f" + HEAD + """
             INVOICE:     5527
                          10/27/26           27000252      700002 T 11/09/26 10060370 552000 00000 Operating Supplies               2,217.33
             INVOICE:     9176

         VENDOR TOTALS                25,006.06 YTD INVOICED                        24,127.60 YTD PAID                                  2,391.33

      5 REFUNDS
                          10/13/26                         5999 P 10/19/26 26000020 223040 00000 Inmate Funds                             52.24
             INVOICE:     101326

         VENDOR TOTALS                    52.24 YTD INVOICED                           52.24 YTD PAID                                      52.24

                    09/13/26                         700003 P 10/05/26 10000400 541005 00000 Communications                      138.23
          INVOICE: HIDDEN

         VENDOR TOTALS                   138.23 YTD INVOICED                          138.23 YTD PAID                                    138.23

 13382 PAT EXAMPLE
                    09/28/26                         700004 P 10/05/26 10005820 534000 00000 Other Services                           40.00
          INVOICE: PR1

         VENDOR TOTALS                       440.00 YTD INVOICED                           440.00 YTD PAID                                  40.00
""" + FOOT + "\f" + """crousa             |A/P CASH DISBURSEMENTS JOURNAL
 12345 11/09/2026 PRTD     12 SOME HOME BUILDER LLC                           11/01/2026                900001
                    10/01/26                                   5993 P 10/12/26 26000020 223040 00000 Inmate Funds                     72.70
"""


class ParseTest(unittest.TestCase):
    def setUp(self):
        self.rows, self.counts = payments.parse(PAGE1)

    def test_lines_and_vendors(self):
        self.assertEqual([r["vendor"] for r in self.rows],
                         ["EXAMPLE TRUCKS INC", "SAMPLE GAS CO", "SAMPLE GAS CO", "SAMPLE GAS CO", "REFUNDS", "PAT EXAMPLE"])
        # the journal section is never read, and a block whose name the Clerk removed has no vendor
        self.assertEqual(self.counts["unread"], 1)
        self.assertEqual(self.counts["totals_wrong"], [])
        self.assertEqual(self.counts["totals_checked"], 4)  # not the block without a name

    def test_fields(self):
        r = self.rows[0]
        # which column the number is in is decided from the PDF's word positions (blacked_out), not the text
        self.assertEqual((r["ref"], r["po"], r["voucher"], r["check"], r["type"], r["paid"], r["invoice_date"]),
                         ("26001111", "", "", "700001", "check", "2026-10-15", "2026-08-21"))
        self.assertEqual((r["amount"], r["invoice"], r["account_desc"], r["page"]),
                         (206040.0, "XJ1", "Fleet Machinery & Equipme", 1))
        gas = self.rows[1:4]
        self.assertEqual([g["ref"] for g in gas], ["27000252", "", "27000252"])
        self.assertEqual(gas[0]["amount"], -125.99)
        self.assertEqual(gas[1]["invoice"], "5527")  # INVOICE: carried over the page break
        self.assertEqual((gas[2]["type"], gas[2]["page"]), ("electronic transfer", 2))

    def test_totals_catch_a_missed_vendor_line(self):
        broken = PAGE1.replace(" 12001 EXAMPLE TRUCKS INC\n", "")
        rows, counts = payments.parse(broken)
        self.assertNotIn(206040.0, [r["amount"] for r in rows])
        self.assertEqual(counts["unread"], 2)

    def test_only_businesses_kept(self):
        kept = [r["vendor"] for r in self.rows if payments.is_business(r["vendor"])]
        self.assertEqual(sorted(set(kept)), ["EXAMPLE TRUCKS INC", "SAMPLE GAS CO"])
        for name in ("PAT EXAMPLE", "REFUNDS", "JAIME P EXAMPLE PE", "UTILITIES REFUND"):
            self.assertFalse(payments.is_business(name), name)
        for name in ("WEISS EXAMPLE & BIERMAN PL", "BOOTH & EXAMPLE PA", "A C EXAMPLE OF FLORIDA INC"):
            self.assertTrue(payments.is_business(name), name)


class IndexTest(unittest.TestCase):
    def test_list(self):
        page = """<table><tr><td><a href="public_records/bcc-payment-registers/For%20the%20week%20through%202026-11-15.pdf"
        target="_blank">For the week through 2026-11-15<span class="sr-only">PDF file, opens in a new window</span></a></td>
        <td>11/16/2026</td></tr><tr><td><a href="public_records/bcc-payment-registers/For%20the%20week%20through%202026-11-08.pdf">
        For the week through 2026-11-08</a></td><td>11/9/2026</td></tr></table>"""
        got = payments.list_registers(page, "https://app.pascoclerk.com/appdot-public-statistical-reports-boccpr.asp")
        self.assertEqual([g["name"] for g in got], ["For the week through 2026-11-08", "For the week through 2026-11-15"])
        self.assertEqual(got[1]["url"], "https://app.pascoclerk.com/public_records/bcc-payment-registers/"
                                        "For%20the%20week%20through%202026-11-15.pdf")
        self.assertEqual(got[1]["updated"], "11/16/2026")
        self.assertEqual(payments.week_of(got[1]["name"]), "2026-11-15")


class PageTest(unittest.TestCase):
    def test_match_and_section(self):
        rows, _ = payments.parse(PAGE1)
        data = {"pasco": {"registers": {"W": {"name": "W", "week": "2026-10-18", "url": "https://example.gov/w.pdf"}},
                          "payments": [{**r, "register": "W"} for r in rows if payments.is_business(r["vendor"])]}}
        got = payments.for_company(money.key("Example Trucks, Inc."), data, money.key)
        self.assertEqual([p["amount"] for p in got["pasco"]], [206040.0])
        html = payments.section_html("pasco", "Example Trucks, Inc.", got["pasco"], data["pasco"]["registers"],
                                     [{"date": "2026-02-17", "amount": 206040.0}, {"date": "2026-11-01", "amount": 206040.0}], 1)
        self.assertIn("paid on October 15, 2026", html)
        self.assertIn("Same amount as the approval of February 17, 2026 (a match the machine found)", html)
        self.assertNotIn("November 1, 2026", html)  # an approval after the payment isn't a match
        self.assertIn('href="https://example.gov/w.pdf#page=1"', html)
        self.assertIn("the register calls it EXAMPLE TRUCKS INC", html)
        self.assertNotIn("PAT EXAMPLE", str(data))


if __name__ == "__main__":
    unittest.main()
