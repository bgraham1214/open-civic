# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Public money to companies (money.py), with real agenda wording from Pasco, Hernando and Hillsborough."""

import tempfile
import unittest
from pathlib import Path

from opencivic import money, site
from opencivic.people import decision_facts


def row(title, county="pasco", votes=None, consent=False, result="Pass", key="k1"):
    item = {"key": key, "county": county, "date": "2026-01-06", "title": title, "number": "C1",
            "body": "Board of County Commissioners", "result": result, "consent": consent}
    votes = votes if votes is not None else [{"person": p, "vote": "Yes"} for p in "ABCDE"]
    return {"item": item, "votes": votes, "facts": decision_facts(item, votes),
            "x": {"topic": "money", "headline": "", "facts": [], "terms": [], "subject": ""}}


class Names(unittest.TestCase):
    def test_clean(self):
        c = money.clean_name
        self.assertEqual(c("Sole Source Purchase AK Associates, Inc."), "AK Associates, Inc.")
        self.assertEqual(c("Franchise Agreement With Coastal Waste & Recycling, Inc."), "Coastal Waste & Recycling, Inc.")
        self.assertEqual(c("Mark Keschl of Meridien Development, LLC"), "Meridien Development, LLC")
        self.assertEqual(c("As Needed Ford Motor Company"), "Ford Motor Company")
        self.assertEqual(c("Hills. Co."), "")

    def test_one_company_many_spellings(self):
        self.assertEqual(money.key("Lennar Homes, LLC"), money.key("Lennar Homes LLC"))
        self.assertEqual(money.key("U.S. Water Services Corporation"), money.key("US Water Services Corporation"))
        self.assertEqual(money.key("Bandes Construction Co."), money.key("Bandes Construction Company"))
        names = [n for n, _, _ in money.payees("Award to Area Agency on Aging of Pasco-Pinellas, Inc. – $10.00")]
        self.assertEqual(names, ["Area Agency on Aging of Pasco-Pinellas, Inc."])


class Amounts(unittest.TestCase):
    def amounts(self, text):
        ns = money.payees(text)
        return {n: money.amount_for(text, ns, i) for i, (n, _, _) in enumerate(ns)}

    def test_each_company_its_own_figure(self):
        t = ("Award and execute two year agreements with Cardinal Landscaping Services of Tampa, Inc. in the amount of "
             "$2,433,000 and Marks Excavating Inc in the amount of $1,430,455")
        a = self.amounts(t)
        self.assertEqual(a["Cardinal Landscaping Services of Tampa, Inc."], 2433000)
        self.assertEqual(a["Marks Excavating Inc"], 1430455)

    def test_joint_total_is_nobodys(self):
        t = ("Joint Funding Agreement between Pasco County, EPG Hillcrest Holdings, LLC, Lennar Homes, LLC, Palmetto Ridge "
             "Cattle Co, LLC – State Road 52/Old Pasco Road Utilities Corridor – $40,722,000.00")
        self.assertTrue(all(v is None for v in self.amounts(t).values()))

    def test_each(self):
        t = ("Award & execute agrmnts w/ the lowest, responsive, & responsible bidders, Ajax Paving Ind. of FL LLC & "
             "Pepper Contracting Svcs Inc., in amt of $4 million each for miscellaneous stormwater const. work")
        self.assertEqual(set(self.amounts(t).values()), {4_000_000})


class Direction(unittest.TestCase):
    def test_who_pays(self):
        d = money.direction
        self.assertEqual(d("Award of Bid No. IFB-KM-25-028 – Comanco Environmental Corporation – $1,450,897.00"), "out")
        self.assertEqual(d("Approve real estate purchase agrmnt for Hunters Lake Tampa LLC to purchase 17.6 acres of "
                           "County-owned property along Bruce B. Downs Blvd for $2,020,000"), "in")
        self.assertEqual(d("Agreement for Sale and Purchase – Supplemental Easement – Duke Energy Florida, LLC – Revenue "
                           "to County $47,200.00"), "in")
        self.assertEqual(d("N89 RELEASE OF MAINTENANCE GUARANTEE #6213013911 IN THE AMT OF $210,658.49 – LEN-ANGELINE LLC"), "in")


class Flags(unittest.TestCase):
    def flags(self, title, **kw):
        r = row(title, **kw)
        return money.flags_for(r["item"], r["votes"], r["facts"], money.money(title)[0], title)

    def test_flags(self):
        self.assertEqual(self.flags("Exempt Purchase – Hach Company – Hach Service Renewal – $185,210.74"), ["no-bid"])
        self.assertEqual(self.flags("Exempt Purchase – Duke Energy Corporation – Electric Service – $24,158,160.00"), [])
        self.assertIn("added", self.flags("Approve the Fourth Modification to the Progressive Design-Build agreement with "
                                          "Garney Companies, Inc., increasing the existing contract amount by $138,575,562.44"))
        self.assertIn("added", self.flags("Change Order No. 1 – Vogel Bros. Building Co. – Additional Funds – $4,200,000.00"))
        split = [{"person": p, "vote": "Yes"} for p in "ABCD"] + [{"person": "E", "vote": "No"}]
        self.assertIn("split", self.flags("Award to Sun Civil LLC – $1,057,285.03", votes=split))
        self.assertIn("consent", self.flags("Award to Sun Civil LLC – $1,057,285.03", consent=True))
        self.assertNotIn("consent", self.flags("Award to Sun Civil LLC – $957,285.03", consent=True))
        conflict = [{"person": p, "vote": "Yes"} for p in "ABCD"] + [{"person": "E", "vote": "Abstained (conflict of interest)"}]
        self.assertIn("conflict", self.flags("Award to Sun Civil LLC – $57,285.03", votes=conflict))


class Pages(unittest.TestCase):
    def test_pages_and_totals(self):
        by = {"pasco": {"2026-01-06": [
            row("Award of Bid – Sun Civil LLC – Traffic Signal – $1,000,000.00", key="a"),
            row("Change Order No. 1 – Sun Civil, LLC – Additional Funds – $200,000.00", key="b"),
            row("Final Close-Out of Contract With Sun Civil LLC (Amount: $1,150,000.00)", key="c"),
            row("Award of Bid – Sun Civil LLC – Sidewalks – $5,000.00", key="d", result="Fail",
                votes=[{"person": p, "vote": "No"} for p in "ABCDE"]),
            row("Rezoning request by Pulte Home Company, LLC – fee $5,000", key="e"),
        ]}}
        cs = money.collect(by)
        self.assertEqual(len(cs), 1)  # the rezoning applicant isn't paid
        c = next(iter(cs.values()))
        self.assertEqual(c["approved_total"], 1_200_000)  # close-out not added again; the failed award not counted
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            site.configure("https://example.github.io/open-civic/", "2026-11-12T20:00:00Z")
            site.write_assets(out)
            res = money.write(by, out)
            self.assertEqual(res["companies"], 1)
            idx = (out / "companies.html").read_text()
            self.assertIn("none of these means", idx)
            self.assertIn("companies/sun-civil.html", idx)
            page = (out / "companies" / "sun-civil.html").read_text()
            self.assertIn("$1.2 million", page)
            self.assertIn("not added to the total again", page)
            self.assertIn("Money added to an existing contract", page)


if __name__ == "__main__":
    unittest.main()
