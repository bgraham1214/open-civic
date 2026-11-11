# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""The plain-language decoder, on real agenda wording from Hillsborough, Pasco and Hernando."""

import unittest

from opencivic.explain import TERMS, density, dollars, explain, money


def ex(text):
    return explain(text)


class Explain(unittest.TestCase):
    def test_land_use_map_change(self):
        e = ex("HC/CPA 25-07 Comprehensive Plan Map Amendment - Proposed change on ± 470.9 acres from "
               "Agricultural/Rural-1/5 (A/R-1/5) to Residential-4 (RES- 4) - Location: 16410 Balm Wimauma Road. Moved approval.")
        self.assertEqual(e["topic"], "land")
        self.assertEqual(e["headline"], "Change to the future land-use map at 16410 Balm Wimauma Road")
        self.assertIn("Land-use change: from Agricultural/Rural (up to 1 home per 5 acres) to Residential "
                      "(up to 4 homes per acre)", e["facts"])
        self.assertIn("Size: about 470.9 acres", e["facts"])
        self.assertEqual(e["motion"], "Moved approval.")

    def test_zoning_codes(self):
        self.assertEqual(ex("PRS 25-0077; River Springs LLC; 13420 Boyette Rd. Moved approval.")["headline"],
                         "Small change to an approved development at 13420 Boyette Rd")
        self.assertEqual(ex("MM 26-0063 - ASHLEY GLOBAL RETAIL, LLC, W. side of Broadway Center Blvd & Williams Rd. "
                            "Intersection. Moved approval.")["headline"],
                         "Big change to an approved development at W. side of Broadway Center Blvd & Williams Rd. Intersection")
        e = ex("Related Item- PD 23-0472, Existing Zoning: Residential Single Family Conventional 6, Request - Planned "
               "Development to allow for 52 single family units. So moved.")
        self.assertEqual((e["topic"], e["facts"]), ("land", ["Homes: 52"]))
        self.assertEqual(ex("Rezoning Petition Submitted by Lisa L. Tabbert as Trustee, for Property Located on "
                            "Pineda Avenue (H2546)")["topic"], "land")

    def test_money(self):
        e = ex("Award & execute the agreement for Bid ITB-C-0029-0-2014/DV, traffic pavement marking term contract to "
               "AKCA Inc. in the amount of $1,118,176 for Public Works. Moved approval.")
        self.assertEqual(e["headline"], "Contract or purchase: $1.1 million")
        self.assertNotIn("Money: $1.1 million", e["facts"])  # already in the headline
        self.assertIn("Company or group named: AKCA Inc.", e["facts"])
        e = ex("Task Order No. TED26-0028 – WSP USA Inc. – Design and Post Design Services for Zimmerman Road "
               "Sidewalk – $184,975.67")
        self.assertEqual(e["headline"], "Contract or purchase: $184,976")   # not rounded to look exact
        e = ex("Approve a Resolution allocating up to $450,000 in funding to United Food Bank & Services of Plant "
               "City, Inc. (United Food Bank) for demolition. Moved approval.")
        self.assertIn("Company or group named: United Food Bank & Services of Plant City, Inc.", e["facts"])
        self.assertEqual(ex("Setting the TRIM Millage Rates. Moved the Board set the proposed millages")["terms"], ["millage"])

    def test_no_false_labels(self):
        # mentions a budget, a law or the attorney, but isn't a budget change, a law or staffing
        self.assertEqual(ex("Accept the PRC Foster Program, Report #2024-10, performed by the County Internal "
                            "Auditor's Office. No adjustment to the budget is anticipated at this time.")["topic"], "other")
        self.assertEqual(ex("Request administration and the County Attorney's Office look at the ordinance and "
                            "make any revisions")["topic"], "other")
        self.assertEqual(ex("Direct Development Services, the County Attorney's Office, and the Fire Marshal to "
                            "coordinate with the Sheriff. Moved.")["topic"], "other")
        self.assertEqual(ex("Hold a public hearing to consider a draft ordinance to revise Chapter 130")["topic"], "law")

    def test_fallback_is_the_official_first_sentence(self):
        e = ex("Board Discussion and Flagging Process. Made the motion to accept the flag list only as presented.")
        self.assertEqual((e["topic"], e["headline"]), ("other", "Board Discussion and Flagging Process"))
        self.assertTrue(e["motion"].startswith("Made the motion"))

    def test_reported_on_phone_nov_9(self):
        # "motion" mid-sentence is not where the motion starts
        e = ex("Chair Hagan sought a motion for each person to be given two minutes. Moved to approve.")
        self.assertEqual(e["headline"], "Chair Hagan sought a motion for each person to be given two minutes")
        self.assertEqual(e["motion"], "Moved to approve.")
        # the company, not the lead-in
        e = ex("Award of Sole Source Purchase From Brehmer Mfg, Inc., for Truck Tire Derimmer Unit for Fleet "
               "Management Department (Contract No. 26-SS01397; Amount: $54,103.00)")
        self.assertIn("Company or group named: Brehmer Mfg, Inc.", e["facts"])
        self.assertIn("Amount: $54,103.00)", e["subject"])          # not cut off
        e = ex("Main Services Agreement With EMS Technology Solutions, LLC, d/b/a Operative IQ for Narcotics "
               "Inventory and Asset Management System for Hernando County Fire Rescue (Amount: $50,640)")
        self.assertIn("Company or group named: EMS Technology Solutions, LLC", e["facts"])

    def test_routine(self):
        self.assertEqual(ex("Approval of changes to the agenda. Moved for approval.")["topic"], "routine")
        self.assertEqual(ex("Approval of Consent Agenda. So moved.")["terms"], ["consent"])

    def test_helpers(self):
        self.assertEqual(density("4"), "up to 4 homes per acre")
        self.assertEqual(density("1/5"), "up to 1 home per 5 acres")
        self.assertEqual(density("4(3)"), "up to 4 homes per acre")
        self.assertEqual(money("costs $1,500 and $2.5 million"), [1500.0, 2500000.0])
        self.assertEqual(dollars(2_500_000), "$2.5 million")
        self.assertEqual(dollars(3_000_000), "$3 million")

    def test_every_term_has_plain_text(self):
        for k, (name, text, src) in TERMS.items():
            self.assertTrue(name and len(text) > 40, k)
            self.assertTrue(src == "" or src.startswith("https://"), k)


    def test_pasco_minutes_approval_is_not_a_rezoning(self):
        x = explain("Board of County Commissioners Regular Meeting/Rezoning August 6, 2024 – 10 A.M",
                    "Constitutional Officers - Clerk - Minutes Approval")
        self.assertEqual(x["topic"], "routine")
        self.assertEqual(x["headline"], "Approved the minutes of the meeting of August 6, 2024")
        self.assertEqual(x["terms"], [])
        y = explain("Board of County Commissioners Emergency Special Meeting September 24, 2024 – 3 P.M.")
        self.assertEqual(y["headline"], "Approved the minutes of the meeting of September 24, 2024")
        z = explain("Zoning Amendment (Consent) - SFG Industrial Lutz, LLC - Change in Zoning from A-R to MPUD")
        self.assertNotEqual(z["topic"], "routine")

    def test_abbreviations_dont_end_the_headline(self):
        x = explain("Task Order No. FM25-008 – Williamson Design Associates. Second sentence here.")
        self.assertIn("FM25-008", x["headline"] + x["subject"])
        self.assertNotIn("Second sentence", x["headline"] + x["subject"])

    def test_plan_wording_change_is_not_a_map_change(self):
        x = explain("Second Public Hearing and Second Reading of Ordinance 1585 Amending the Capital Improvements "
                    "Section of the City's Comprehensive Plan")
        self.assertEqual(x["terms"], ["cpa-text"])
        y = explain("Ordinance amending the Future Land Use of a parcel from Residential-9 to Residential-18 (CPA-20-02), "
                    "an amendment to the Comprehensive Plan")
        self.assertEqual(y["terms"], ["cpa-map"])

    def test_city_minutes_approval_is_routine(self):
        x = explain("Approval of April 21, 2026 City Council Meeting Minutes")
        self.assertEqual((x["topic"], x["headline"]), ("routine", "Approved the minutes of an earlier meeting"))

    def test_kratom(self):
        # Hillsborough Clerk's voting record, Jun 17, 2026, item F-5 (RCS 5536)
        x = explain("Moved with a slight amendment to the proposed language that says prohibits the sale of kratom "
                    "and wanted to be intentional and specific that the motion prohibits the sale of kratom 7OH, that "
                    "was provided as backup, moved for approval of Item F-5 as...")
        self.assertEqual((x["topic"], x["headline"], x["terms"]), ("law", "Kratom products (7-OH)", ["7-oh"]))
        self.assertIn("kratom 7OH", x["subject"])
        y = explain("Conduct a public hearing to enact an ordinance amending Section 36-507 relating to synthetic "
                    "drugs, adding 7-hydroxymitragynine. Moved approval.")
        self.assertEqual((y["headline"], y["terms"]), ("County law on kratom products (7-OH)", ["7-oh", "ordinance"]))
        # Ordinance 14-19 (Jun 18, 2014) names no kratom compound
        z = explain("Conduct a public hearing to enact an ordinance amending Section 36-507 of Hillsborough County "
                    "Code of Ordinances and Laws, Chapter 36, Article VII, relating to the possession, sale, or "
                    "manufacture of synthetic drugs in the County. Moved approval. (Ordinance 14-19)")
        self.assertEqual((z["headline"], z["terms"]), ("County law on synthetic drugs", ["ordinance"]))
        self.assertIn("fda.gov", TERMS["7-oh"][2])

    def test_incentives_are_not_contracts(self):
        x = explain("Economic Incentive Agreement – H. Lee Moffitt Cancer Center and Research Institute, Inc. – $21,000,000.00")
        self.assertEqual((x["headline"], x["terms"]), ("Incentive or tax break for a business: $21 million", ["incentive"]))
        self.assertEqual(explain("Grant Agreement With the State Department of Environmental Protection for Septic "
                                 "Upgrade Incentive Program")["terms"], ["grant"])


if __name__ == "__main__":
    unittest.main()
