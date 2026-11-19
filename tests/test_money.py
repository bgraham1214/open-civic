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
        # contract numbers before the name (seen on companies.html, Nov 15, 2026)
        self.assertEqual(c("FM24-002 Bandes Construction Company"), "Bandes Construction Company")
        self.assertEqual(c("No.FM24-021-Williamson Dacar Associates, Inc."), "Williamson Dacar Associates, Inc.")
        self.assertEqual(c("A-1 Florida Sod Inc."), "A-1 Florida Sod Inc.")

    def test_one_company_many_spellings(self):
        self.assertEqual(money.key("Lennar Homes, LLC"), money.key("Lennar Homes LLC"))
        self.assertEqual(money.key("U.S. Water Services Corporation"), money.key("US Water Services Corporation"))
        self.assertEqual(money.key("Bandes Construction Co."), money.key("Bandes Construction Company"))
        # three spellings of one company on companies.html, Nov 15, 2026
        self.assertEqual({money.key(n) for n in ("G.A. Food Svcs of Pinellas County Inc.",
                                                 "G.A. Food Service of Pinellas County Inc.",
                                                 "GA Food Services of Pinellas County Inc.")}, {"ga food services of pinellas county"})
        self.assertEqual(money.key("A.J. Landscaping LLC"), money.key("AJ Landscaping, LLC"))
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


class Nov16(unittest.TestCase):
    """Wording that was misread on companies.html, Nov 16, 2026."""

    def one(self, text):
        aka = {}
        ns = money.payees(text, aka)
        return [(n, money.amount_for(text, ns, i)) for i, (n, _, _) in enumerate(ns)], aka

    def test_names_kept_whole(self):
        for text, name in [
            ("Second Amendment to Agreement for Additional Purchase Authority – Schaer Development of Central Florida "
             "Inc. – As Needed Miscellaneous Pipeline Construction – $6,500,000.00", "Schaer Development of Central Florida Inc."),
            ("Exempt Purchase – Westcare Gulfcoast - Florida, Inc. – Adult Outpatient Treatment Services - $1,086,000.00",
             "Westcare Gulfcoast - Florida, Inc."),
            ("Approve an Agreement between Hillsborough County and Enterprising Latinas, Inc., in the not-to-exceed "
             "total amount of $250,000", "Enterprising Latinas, Inc."),
            ("commercial solid waste container collection svcs to Republic Svcs of Florida LP in the amount of "
             "$1,756,676.16", "Republic Svcs of Florida LP"),
            ("Task Order No. PDE25-TO-002 - W.E. Oliver, P.E., LLC - 2025 Mobility Fee Update Study - $193,898.40",
             "W.E. Oliver, P.E., LLC"),
            ("Agreement for Sale and Purchase of Property and Budget Amendment – Square 1 Properties, LLC – Lot 6 – "
             "$155,000.00", "Square 1 Properties, LLC"),
            ("Additional Purchasing Authority - GSA Purchase - sCube, Inc. - Software Support Services - $268,800.00",
             "sCube, Inc."),
        ]:
            self.assertEqual([n for n, _ in self.one(text)[0]], [name], text)
        # a person introduced before the company is still dropped
        self.assertEqual(money.clean_name("Mark Keschl of Meridien Development, LLC"), "Meridien Development, LLC")
        # a name cut down to one generic word isn't used
        self.assertEqual(self.one("Opioid Funding Agreement – Steps to Recovery, Inc. – $437,000.00")[0], [])

    def test_whose_contract_is_used(self):
        got, _ = self.one("Piggyback of contract between Gainesville Regional Utilities and Atlantic Pipe Services, LLC. "
                          "for pipe lining in the amount of $300,000")
        self.assertEqual(got, [("Atlantic Pipe Services, LLC.", 300000)])

    def test_doing_business_as_is_one_company(self):
        got, aka = self.one("Utilization of Hillsborough County Contract With Shamrock Environmental Company d/b/a Aqua "
                            "Clean Environmental Co., LLC, for Leachate Hauling (Contract No. 25-P0200/FH; Amount: $450,000.00)")
        self.assertEqual(got, [("Shamrock Environmental Company", 450000)])
        self.assertEqual(aka, {"Shamrock Environmental Company": ["Aqua Clean Environmental Co."]})
        got, _ = self.one("Task Order No. FM25-011 - Site Improvements - CPH Consulting, LLC, fka CPH, LLC fka CPH, Inc. "
                          "- $99,992.89")
        self.assertEqual(got, [("CPH Consulting, LLC", 99992.89)])

    def test_shorthand_millions(self):
        got, _ = self.one("Approve a change order to the pavement treatment program contract w/ Hubbard Construction Co. "
                          "increasing the total contract capacity by $3.5M, from $5,071,168.40 to $8,571,168.40")
        self.assertEqual(got, [("Hubbard Construction Co.", 3500000)])
        self.assertEqual(money.money("to R.M. Halts & Associates, $3 mill, Kenyon & Partners Inc, $2.5 mill"), [3e6, 2.5e6])
        self.assertEqual(money.money("a $500 minimum and $4 Main Street"), [500, 4])

    def test_raise_from_to_counts_the_difference(self):
        got, _ = self.one("Approve first modification to agreement w/ Tampa Hillsborough Homeless Initiative Inc., "
                          "increasing funding from $237,500 to $475,000")
        self.assertEqual(got[0][1], 237500)
        got, _ = self.one("Approve first modification w/ Acme Paving Inc., increasing funding from $100,000 to $475,000")
        self.assertEqual(got[0][1], 375000)

    def test_decreases_are_not_added(self):
        rows = [row("FAC26-1040 – Change Order No. 1 (Final) to Agreement for East Pasco Senior Center Construction - "
                    "Ryman Construction of Florida, Inc. – ($52,110.59) January 12, 2026")]
        c = list(money.collect({"pasco": {"2026-02-17": rows}}).values())[0]
        self.assertEqual((c["approved_total"], c["rows"][0]["decrease"]), (0, True))
        # an amount in brackets after a place isn't a decrease
        rows = [row("Award and execute agreements with Stage Door II Inc. for the South Service Area ($7,995,635.75)")]
        c = list(money.collect({"pasco": {"2026-02-17": rows}}).values())[0]
        self.assertEqual(c["approved_total"], 7995635.75)


class NotPaid(unittest.TestCase):
    def test_transfers_and_lawsuits(self):
        for t in ["Approve a letter of agreement with Florida AHCA for participation in low-income pool (LIP) intergovernmental "
                  "transfer (IGT), for a total amount of $27,450,667 on behalf of Florida General Sciences Center Inc.",
                  "Agreement – State of Florida, Agency for Healthcare Administration – Premier Community Healthcare, Inc. – "
                  "Local Match Funding for Low Income Pool – $150,000.00",
                  "Recommendation to authorize the County Attorney to file a lawsuit on behalf of Collier County Board of County "
                  "Commissioners against On Time Utility Services, Inc., and any other responsible parties for $87,096"]:
            self.assertEqual(money.direction(t), "", t)
        self.assertEqual([n for n, _, _ in money.payees("Resolution No. 2025-97 - Approving Certain Incentives on Behalf of "
                                                        "Costco Wholesale Corporation for their Expansion")],
                         ["Costco Wholesale Corporation"])


class StaffMemos(unittest.TestCase):
    """CivicClerk agenda items carry the staff memo; it names more companies than the one being paid."""

    def setUp(self):
        from opencivic.jurisdictions import JURISDICTIONS
        JURISDICTIONS["memotown"] = {"platform": "civicclerk", "short": "Memo Town", "board": "Memo Town Council"}
        self.addCleanup(JURISDICTIONS.pop, "memotown")

    def names(self, title, memo):
        r = row(title, county="memotown")
        r["item"]["action_text"] = memo
        return sorted(c["name"] for c in money.collect({"memotown": {"2026-01-06": [r]}}).values())

    def test_title_wins_and_memo_needs_exactly_one_company(self):
        self.assertEqual(self.names("Bid Award\nConstruction of Fire Station 2",
                                    "Staff recommends award to Mulligan Constructors, Inc in the amount of $2,975,290."),
                         ["Mulligan Constructors, Inc"])
        self.assertEqual(self.names("On-Call Facility Construction Services",
                                    "Ranked firms: Adaptive Project Strategies, LLC; Boulevard Contractors Corp. Budget $500,000."), [])
        self.assertEqual(self.names("FY19-10 - Advanced Compatible Solutions, Inc. - Fire Alarm System & Monitoring",
                                    "The prior vendor, Mitratech Trakstar, Inc., was paid $40,960."), [])
        self.assertEqual(self.names("Award to Paint King USA, LLC for $12,000", "Other bidder: Acme Painting Inc. at $15,000"),
                         ["Paint King USA, LLC"])

    def test_narrative_minutes_are_not_read_for_money(self):
        from opencivic.jurisdictions import JURISDICTIONS
        JURISDICTIONS["memotown"].update(platform="legistar", florida=True)
        r = row("Discussion, Re: State Lobbying Services", county="memotown")
        r["item"]["action_text"] = ("Mr. X of Crisafulli Consulting Company said the Legislature was able to pass "
                                    "$117.5 billion budget; the County ended up with $6.87 million.")
        self.assertEqual(money.collect({"memotown": {"2026-08-04": [r]}}), {})

    def test_number_prefixes_and_sentence_ends(self):
        c = money.clean_name
        self.assertEqual(c("2026-53 APPROVING J. COLLINS ENGINEERING ASSOCIATES, LLC"), "J. COLLINS ENGINEERING ASSOCIATES, LLC")
        self.assertEqual(c("85.002Kalos Services, Inc."), "Kalos Services, Inc.")
        self.assertEqual(c("PROVIDING FOR AN EFFECTIVE DATE. The Diocese of Venice, Inc."), "Diocese of Venice, Inc.")
        self.assertEqual(c("Vogel Bros. Building Co."), "Vogel Bros. Building Co.")
        self.assertEqual(c("Int., LLC"), "")


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
        # one matter on two lines of one meeting counts once
        twice = {"pasco": {"2026-01-06": [row("Award of Bid – Sun Civil LLC – Traffic Signal – $1,000,000.00", key="a"),
                                          row("Award of Bid – Sun Civil LLC – Traffic Signal – $1,000,000.00", key="b")]}}
        for r in twice["pasco"]["2026-01-06"]:
            r["item"]["file_number"] = "15-9815"
        self.assertEqual(next(iter(money.collect(twice).values()))["approved_total"], 1_000_000)
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


class Nov17(unittest.TestCase):
    """Found by reading the top-ten lists against their decisions, Nov 17, 2026 (real wording)."""

    def test_more_decreases(self):
        for t in ["Budget Amendment and Resolution to Standard Contract EZ025-PASCO Amendment No. 002 – Acme Paving, Inc. "
                  "– Decrease in Contract Funding; CSFA No. 65.002 – $127,817.73",
                  "agreement between Collier County and Habitat for Humanity of Collier County, Inc. to decrease funding in "
                  "the amount of $125,000.00",
                  "Approve Amendment 002 to contract w/Acme Paving Inc. to decrease standard contract amt by $154,983",
                  "authorize the necessary Budget Amendment in the amount of $6,054 to reflect a decrease from the estimated funding"]:
            self.assertTrue(money.DECREASE_RX.search(t), t)
        self.assertFalse(money.DECREASE_RX.search(
            "Case Management Services to Prevent, Decrease, or Delay Premature or Inappropriate Placement"))

    def test_more_ways_to_add_money(self):
        for t in ["Authorize an increase to the purchase order with Rowland, Inc. of Pinellas Park",
                  "Approval of a $40,000.00 increase to Purchase Order No. 26-00055 with Ferguson Enterprises, LLC",
                  "Motion Approving an Increase in Contract Cost Capacity to the Consultant Services Agreement",
                  "MOTION TO APPROVE threshold increase for open-end Contract No. BLD2121366B1_1",
                  "Increased Annual Expenditure of Contract With DesignLab, Inc., for Uniforms",
                  "for an increased aggregate expenditure amount of $75,000",
                  "increase the maximum not-to-exceed amount of the Agreement for Services by $14,880,473",
                  "Moss & Associates, LLC - Increase the Guaranteed Maximum Price and the Project Budget"]:
            self.assertTrue(money.ADDED_RX.search(t), t)
        for t in ["closeout services in the amount of $153,281.10, with no increase to the previously approved Work Order",
                  "for the first year an amount of $159,875.09 and subsequent annual price increases in the amount not to exceed 2.5%"]:
            self.assertFalse(money.ADDED_RX.search(t), t)

    def test_funders_are_not_paid(self):
        rows = [row("Budget Amendment and Resolution to Standard Contract EZ025-PASCO Amendment No. 002 – Area Agency on "
                    "Aging of Pasco-Pinellas, Inc.– Increase in Contract Funding; CSFA No. 65.002 – $63,517.19", key="a"),
                row("Request for approval to expend no more than $55,000.00 in Florida Housing Finance Corporation State "
                    "Housing Initiatives Partnership (SHIP) funds for the Purchase Assistance project", key="b", county="deltona")]
        self.assertEqual(money.collect({"pasco": {"2026-10-06": rows[:1]}, "deltona": {"2025-08-04": rows[1:]}}), {})

    def test_names(self):
        one = Nov16.one
        self.assertEqual(one(self, "Approve the First Amendment to the Child Protection Team Services Agreement with Kids "
                                   "House of Seminole, Inc. for medical examination services – $70,000")[0][0][0],
                         "Kids House of Seminole, Inc.")
        self.assertEqual(one(self, "Request for approval of Resolution No. 2025-107 for Shelley’s Septic Tanks Inc located "
                                   "in Zellwood, FL. Requested change order amount is $40,000.00.")[0][0][0],
                         "Shelley’s Septic Tanks Inc")
        self.assertEqual(money.key("Goodwin Bros. Construction, Inc."), money.key("Goodwin Brothers Construction, Inc."))


class TopCompanies(unittest.TestCase):
    def by(self):
        return {
            "pasco": {"2026-01-06": [
                row("Award of Bid – Sun Civil LLC – Traffic Signal – $1,000,000.00", key="a"),
                row("Change Order No. 1 – Sun Civil, LLC – Additional Funds – $200,000.00", key="b"),
                row("Task Order No. 2-26 – Mead and Hunt, Inc. – Reservoir Services – $300,000.00", key="c"),
                row("Task Order No. 3-26 – Mead and Hunt, Inc. – Lift Station Services – $300,000.00", key="d"),
            ]},
            "hillsborough": {"2016-03-02": [row("Approve agreement with Prince Contracting LLC for road work, $9,000,000",
                                                key="h", county="hillsborough")]},
            "zephyrhills": {"2026-02-02": [row("Award to Acme Paving Inc. – $50,000", key="z", county="zephyrhills",
                                               votes=[], result="")]},
        }

    def test_ranking(self):
        cs = money.collect(self.by())
        rows = money.ranking(cs, {"pasco", "hillsborough"}, money.SINCE)
        by_amount, by_count, ties = money.top_lists(rows)
        self.assertEqual([r["name"] for r in by_amount], ["Sun Civil LLC", "Mead and Hunt, Inc."])  # 2016 not in 2025-on lists
        sun = by_amount[0]
        self.assertEqual((sun["amount"], sun["contracts"], sun["added"]), (1_200_000, 1, 1))  # a change order isn't a contract
        self.assertEqual([r["name"] for r in by_count], ["Mead and Hunt, Inc.", "Sun Civil LLC"])
        self.assertEqual(ties, 0)

    def test_pages(self):
        by = self.by()
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            site.configure("https://example.github.io/open-civic/", "2026-11-17T20:00:00Z")
            site.write_assets(out)
            res = money.write(by, out)
            top = (out / "top-companies.html").read_text()
            self.assertIn("Most money approved", top)
            self.assertIn("Most contracts", top)
            self.assertIn("All years we have", top)  # Hillsborough's record starts before 2025
            self.assertIn('value="top-companies/pasco-county.html"', top)
            self.assertNotIn("zephyrhills.html", top)  # no votes, so no list
            pc = (out / "top-companies" / "pasco-county.html").read_text()
            self.assertIn("Zephyrhills", pc)  # named as not counted, with the reason
            self.assertIn("without votes", pc)
            self.assertIn("1 contract, 1 increase", pc)
            self.assertNotIn("All years we have", pc)
            self.assertEqual(res["top_lists"], len(list((out / "top-companies").glob("*.html"))) + 1)


class AllCapitals(unittest.TestCase):
    """Titles written in capitals (Coconut Creek, Delray Beach, Doral, Taylor County…), Nov 17, 2026."""

    def names(self, t):
        return [n for n, _, _ in money.payees(money.decap(t))]

    def test_names_read(self):
        for t, want in [
            ("A RESOLUTION AUTHORIZING THE CITY MANAGER, OR DESIGNEE, TO APPROVE A CHANGE ORDER IN THE AMOUNT OF $153,875.00 "
             "FOR MILLER LEGG & ASSOCIATES, INC. TO COMPLETE POST DESIGN SERVICES", "Miller Legg & Associates, Inc."),
            ("WORK AUTHORIZATION WITH WGI, INC. IN AN AMOUNT NOT TO EXCEED $70,000", "WGI, Inc."),
            ("RECOGNIZING THAT PHOENIX CONCRETE PLUS, INC. HAS COMPLETED", "Phoenix Concrete Plus, Inc."),
            ("NEW 2025 FORD F150 WORK TRUCKS THROUGH BECK AUTO SALES, INC. FOR $90,000", "Beck Auto Sales, Inc."),
            ("AGREEMENT WITH EARTH SURFACES OF AMERICA, INC. FOR $5", "Earth Surfaces of America, Inc."),
            ("AN AGREEMENT WITH AREA AGENCY ON AGING OF PASCO-PINELLAS, INC. FOR $5", "Area Agency on Aging of Pasco-Pinellas, Inc."),
            ("CONTRACT BETWEEN TAYLOR COUNTY BOARD OF COUNTY COMMISSIONERS AND LAMPL HERBERT CONSULTANTS, INC. FOR $5",
             "Lampl Herbert Consultants, Inc."),
            ("AWARD TO H&R PAVING, INC. $5", "H&R Paving, Inc."),
            ("TO APPROVE P.L.A. ELECTRIC, INC. TO PURCHASE AND INSTALL $5", "P.L.A. Electric, Inc."),
            ("AGREEMENT WITH MAN-CON, INC. FOR $5", "Man-Con, Inc."),
            ("A CONSTRUCTION AGREEMENT BETWEEN THE CITY OF DORAL AND METRO EXPRESS, INC. FOR $5", "Metro Express, Inc."),
            ("AN AGREEMENT WITH MILLS+SCHONERING ARCHITECTS, LLC FOR DESIGN $5", "Mills+Schonering Architects, LLC"),
            ("TO AWARD AN AGREEMENT WITH LOUMINEL GENERAL CONTRACTOR, LLC., FOR FENCING REPAIR $5", "Louminel General Contractor, LLC."),
            ("AN AGREEMENT WITH ARCHITECTS DESIGN GROUP/ADG, LLC FOR DESIGN $5", "Architects Design Group/ADG, LLC"),
            ("BETWEEN THE CITY AND OUTFRONT MEDIA, LLC A DELAWARE LIMITED LIABILITY COMPANY, $5", "Outfront Media, LLC"),
        ]:
            self.assertEqual(self.names(t), [want], t)

    def test_ordinary_case_unchanged(self):
        t = "Award of Bid – Sun Civil LLC – Traffic Signal – $1,000,000.00"
        self.assertEqual(money.decap(t), t)


if __name__ == "__main__":
    unittest.main()
