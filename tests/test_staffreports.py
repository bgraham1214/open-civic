# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Amounts read from staff reports' labeled fields (staffreports.py), with real wording from Pinellas, Coconut
Creek and Deltona (staff names replaced)."""

import unittest

from opencivic import money
from opencivic.people import decision_facts
from opencivic.staffreports import amount


class Fields(unittest.TestCase):
    def test_labeled_amounts(self):
        for text, want in [
            ("Fiscal Impact: Contract expenditure not to exceed: $1,664,740.00 This request is budgeted",
             ("Contract expenditure not to exceed", 1664740.0)),
            ("Fiscal Impact: Total contract not to exceed: $1,356,439.00 Staff Member Responsible: Jane Doe",
             ("Total contract not to exceed", 1356439.0)),
            ("Fiscal Impact: Total estimated expenditure not to exceed: $9,000,000.00 Annual estimated expenditure not "
             "to exceed: $1,800,000.00 Funding for this is derived from", ("Total estimated expenditure not to exceed", 9000000.0)),
            ("FISCAL IMPACT: REVENUES: $0 EXPENDITURES: $1,653,503.00 BUDGETED? Yes", ("Expenditures", 1653503.0)),
            ("LOCATION: Citywide COST: $100,000.00 SOURCE OF FUNDS: Enterprise Fund", ("Cost", 100000.0)),
            ("Fiscal Impact: Contract expenditure not-to-exceed: $454,860.00. Funding for this agreement is available "
             "under the FY26-FY31 Capital Improvement Plan, funded by the STAR Center Fund in the amount of $527,250.00.",
             ("Contract expenditure not-to-exceed", 454860.0)),
            ("Fiscal Impact: Total not to exceed amount of $522,183.40 This request is budgeted for in the FY26 Budget",
             ("Total not to exceed amount of", 522183.4)),
            ("Fiscal Impact: Thirty-Six (36) month agreement not-to-exceed: $2,389,975.00 Funding is derived from",
             ("Thirty-Six (36) month agreement not-to-exceed", 2389975.0)),
        ]:
            got = amount(text)
            self.assertEqual((got["label"], got["amount"]), want)

    def test_no_amount(self):
        for text in [
            # Horne LLP: most of the total is grants passed through to homeowners
            "Rehabilitation and Reconstruction Pass through Grant Funds: not to exceed $478,875,000.00 … Fiscal Impact: "
            "Total estimated fees not to exceed: $ 565,656,023.17",
            "LOCATION: Citywide COST: N/A SOURCE OF FUNDS: N/A",
            "Billing rate of $200.00 per hour.",
            "COST: $100,000.00 … COST: $250,000.00",  # two figures that disagree
        ]:
            self.assertIsNone(amount(text), text)


class Amendments(unittest.TestCase):
    """Pinellas, Nov 17, 2026: an amendment's report tabulates the contract's history."""

    def test_own_line_only(self):
        for title, text, want in [
            ("Third Amendment with Coastal Waste & Recycling of Central Florida, LLC for Lealman residential waste",
             "Fiscal Impact: Original Award $ 6,500,000.00 First Amendment $ 8,000,000.00 Second Amendment No Fiscal "
             "Impact Third Amendment $ 670,000.00 Revised Total Contract Amount $ 15,170,000.00", 670000.0),
            ("Third Amendment with Tyler Technologies Inc for Odyssey maintenance",
             "Fiscal Impact: Current approved expenditure: $4,665,558.00 Third Amendment increase: $1,800,000.00 Revised "
             "total expenditure not to exceed: $6,465,558.92", 1800000.0),
            ("Change Order No. 2 to the agreement with Cathcart Construction Company Florida, LLC",
             "Fiscal Impact: Original Agreement Amount: $11,221,188.65 Change Order No. 1 increase: $ 1,500,000.00 Change "
             "Order No. 2 increase: $ 475,581.27 Revised Agreement Amount: $13,196,769.92", 475581.27),
            ("First Amendment to the contract with Van Scoyoc Associates, Inc. for Federal Government Relations Services.",
             "Fiscal Impact: Estimated twenty-four (24) expenditure not to exceed: $190,000.00 Estimated annual "
             "expenditure not to exceed: $95,000.00 Funding is derived from the General Fund", 190000.0),
        ]:
            got = amount(text, title)
            self.assertEqual((got["amount"], got["added"]), (want, True), title)

    def test_nothing(self):
        for title, text in [
            ("Second Amendment Term Extension with Unite USA, Inc. d/b/a Unite US",
             "Fiscal Impact: Contract not-to-exceed amount: $9,158,372.76 The Initial Estimated Five (5) Year Expenditure "
             "Not-to-Exceed: $9,158,372.76. This amendment has no fiscal impact."),
            ("Termination for convenience of agreement with New Era Electric, Inc.",
             "Fiscal Impact: Termination for convenience has no fiscal impact. Original award amount: $2,633,824.00"),
            ("Agreements with Average Joe Landscape, Duval Landscape Maintenance, and Rotolo Consultants, Inc. for mowing",
             "Fiscal Impact: Total expenditure not-to-exceed amount: $2,200,000.00"),
            ("Purchase authorization with ADB Safegate Americas, LLC and Allen Enterprises for runway lighting",
             "Fiscal Impact: Not to exceed amount: $800,000.00"),
        ]:
            self.assertIsNone(amount(text, title), title)
        # "Terminal" isn't a termination
        self.assertIsNotNone(amount("Fiscal Impact: Total contract not to exceed: $1,600,000.00",
                                    "Award of bid to Caladesi Construction and Development, Inc. for the Terminal Mitigation"))


class InTheTracker(unittest.TestCase):
    def test_staff_amount_counted_and_labeled(self):
        item = {"key": "legistar:pinellas:item:1", "county": "pinellascounty", "date": "2025-09-23",
                "title": "Ranking of firms and agreement with LucyRx Health Solutions, Inc. for pharmacy benefit services.",
                "number": "1", "body": "Board of County Commissioners", "result": "Pass", "consent": False,
                "staff_amount": 9000000.0, "staff_label": "Total estimated expenditure not to exceed"}
        votes = [{"person": p, "vote": "Yes"} for p in "ABCDEFG"]
        row = {"item": item, "votes": votes, "facts": decision_facts(item, votes),
               "x": {"topic": "money", "headline": "", "facts": [], "terms": [], "subject": ""}}
        c = next(iter(money.collect({"pinellascounty": {"2025-09-23": [row]}}).values()))
        self.assertEqual((c["approved_total"], c["rows"][0]["staff_label"]), (9000000.0, "Total estimated expenditure not to exceed"))
        self.assertIn("from the staff report", money.decision_html(c["rows"][0], 1))
        # without it, nothing is counted
        item2 = {k: v for k, v in item.items() if not k.startswith("staff")}
        row2 = {**row, "item": item2}
        self.assertEqual(money.collect({"pinellascounty": {"2025-09-23": [row2]}}), {})


if __name__ == "__main__":
    unittest.main()
