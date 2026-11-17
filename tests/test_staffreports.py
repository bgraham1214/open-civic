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
        ]:
            self.assertEqual(amount(text), want)

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
