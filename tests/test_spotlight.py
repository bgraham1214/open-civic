# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Spotlight tags, on real wording from the three counties' records."""

import unittest

from opencivic.spotlight import label, spot

PASSED = {"yes": 7, "no": 0, "passed": True, "action": ""}
FAILED = {"yes": 2, "no": 5, "passed": False, "action": ""}


def one(text, motion="", action=""):
    tags = spot(text, motion, action)
    return tags[0] if len(tags) == 1 else tags


class Restrictions(unittest.TestCase):
    def test_kratom_motion_is_in_the_works(self):
        t = one("Moved with a slight amendment to the proposed language that says prohibits the sale of kratom and "
                "wanted to be intentional and specific that the motion prohibits the sale of kratom 7OH, that was "
                "provided as backup, moved for approval of Item F-5 as...")
        self.assertEqual((t["kind"], t["stage"]), ("restriction", "works"))
        self.assertEqual(label(t, PASSED), "Restriction in the works")

    def test_adopted_ordinances(self):
        for text in ("Second Public Hearing to Consider Ordinance Amending Hernando County Code to Impose Moratorium on "
                     "Processing Applications for Development Orders and Development Permits for Data Centers",
                     "Resolution Prohibiting Trucks From Traveling Upon Designated Roads (Resort Avenue, Redstart Avenue "
                     "and Ricebird Avenue) in Royal Highlands Subdivision",
                     "Conduct a public hearing to enact an ordinance amending Section 36-507 of Hillsborough County Code "
                     "of Ordinances and Laws, Chapter 36, Article VII, relating to the possession, sale, or manufacture "
                     "of synthetic drugs in the County. Moved approval. (Ordinance 14-19)"):
            t = one(text)
            self.assertEqual(label(t, PASSED), "New restriction", text)
        self.assertEqual(label(one("Proposed Ordinance Amending Civil Penalties for Certain Parking Violations"), PASSED),
                         "Fines or penalties set or changed")

    def test_drafts_and_scheduling(self):
        t = one("County Atty's Ofc to draft & advertise ord. & set public hearing for 9/7/2017 at 10 a.m. to consider "
                "imposing 180-moratorium on applications & issuance of permits for utility poles/wireless support "
                "structures... Moved to approve Item A-3.")
        self.assertEqual(label(t, PASSED), "Restriction in the works")
        t = one("Direct staff advertise/schedule PH to consider enactment of ordinance amending Co. Code of Ord & Laws, "
                "Ch.30, Art. II, Human Rights Ord 00-37, to prohibit discrimination...Moved Board direct Co. Atty "
                "advertise PH set for 10/1/15, next mtg to have the ordinance.")
        self.assertEqual(t["stage"], "works")
        t = one("Hold a second public hearing and consider adoption of an Ordinance providing for an extension of the "
                "moratorium on the acceptance and processing of new applications for rezonings")
        self.assertEqual(label(t, PASSED), "Restriction extended")

    def test_outcome_and_agenda(self):
        t = one("An Ordinance by the Pasco County Board of County Commissioners Establishing a Temporary Moratorium on "
                "the Submission and Acceptance of Applications for Building Permits, Site Plans, Development Orders")
        self.assertEqual(label(t, None), "On the agenda: a new restriction")
        self.assertEqual(label(t, FAILED), "Proposed restriction (didn't pass)")
        self.assertEqual(label(t, {**PASSED, "action": "continued"}), "Proposed restriction (put off)")

    def test_not_restrictions(self):
        for text in (
            "Appointment of Belinda Pratt to Fine Arts Council Until December 31, 2030",
            "Approve SHIP funding agmt & associated land use restriction agmt w/ Housing Authority of the city of Tampa",
            "Approve agrmnt between County & Tampa JCC/ Federation Inc. ($100,000) for window replacemnt & related "
            "repairs; a preservation/restricted use agrmnt between County/JCC Fed req'ing repayment of grant funds",
            "Approve agreement with Hillsborough County Sheriff's Office to implement misdemeanor probation svcs in the County.",
            "RZ-STD 24-1210; Arthur Jewell; 13309 E 92 Hwy. Moved for approval in light of all of the restrictions that were offered.",
            "Update Regarding Status of Declaration of Temporary Burn Ban Due to Drought Conditions",
            "Request Submitted by Jovite C. Palardis for Waiver of Civil Penalty and Administrative and Investigative Costs",
            "Moved to draft a letter of support on behalf of the Board in favor of placing a proposal on the ballot to ban "
            "the sale or transfer of assault weapons in the state of Florida. FAILED",
            "Public hearing to consider amending Chapter 2, Article VIII, Section 2-766, Hillsborough County Code, that "
            "adopts the constitutional amendment prohibiting commissioners...Moved approval. Ordinance 25-8",
            "Oral Vote. Adopt a new Board Policy to establish a prohibition on the use of phosphogypsum in roadway construction",
            "PRS 17-1362-NWH/NW, Bay Area Developers LLC, Minor Modification to a PD to Remove Restriction Limiting Use of "
            "Building in Commercial Outparcel to One Use. Moved approval.",
            "Conduct public hearing to amend The Animal Ordinance to enact certain restrictions on retail sales of dogs & "
            "cats. Amendment made by Commissioner Crist at 5/3/2017 Board meeting.",
            "Receive a presentation from Hillsborough County Sheriff's Office... Moved to waive the rules & proceed to Item B-13.",
        ):
            self.assertEqual(spot(text), [], text)


class BusinessBreaks(unittest.TestCase):
    def test_tags(self):
        cases = {
            "Approve an Economic Development ad valorem tax exemption agreement w/ Tampa Tank & Welding Inc., in the "
            "form in background material. Moved approval.": "Tax break for a company",
            "Economic Incentive Agreement – VantagePoint AI, LLC, March Street, LLC, & 2319 Oak Myrtle Lane, LLC – Job "
            "Creation and Economic Incentives - $331,047.00": "Incentive payment to a company",
            "Consideration of Request by Submitted by Fisher Link Development, LLC, to Forgive Fines Ordered by Special "
            "Master for Code Violations Against Parcel Located at 12495 Bell Hollow Court": "Fees or fines forgiven for a company",
            "Agreement for Sale and Purchase of Surplus Real Property – Ponchatoula Properties LLC – Scamp Drive, Hudson "
            "– Revenue – $11,648.00": "Public land sold or leased to a company",
            "Award a five-year sole source contract to Barney's Pump, Inc. in the amount of $7,660,499.98 for various "
            "pumps. Moved approval.": "No-bid purchase from a company",
        }
        for text, want in cases.items():
            self.assertEqual(label(one(text), PASSED), want, text)
        self.assertEqual(label(one("Economic Incentive Agreement – H. Lee Moffitt Cancer Center and Research Institute, "
                                   "Inc. – $21,000,000.00"), None), "On the agenda: incentive payment to a company")

    def test_not_breaks(self):
        for text in (
            # the county buying land, not selling it
            "Approve a Contract For Sale and Purchase of Real Property in the amount of $12,290,000 (average of two "
            "appraised values) with CTP Buffalo Investments, LP (\"Seller\") to acquire approximately 8.4 acres",
            # residents and nonprofits
            "Declaration of County Owned Property Located on Treiman Boulevard as Surplus Property and Consideration of "
            "Purchase Offer Submitted by Kimberly Prom (Key #832923)",
            "Request to Waive Fee for Special Warning Sign – Westfield Drive – $250.00",
            "Declaration of County Owned Property Located on Century Drive as Surplus Property and Consideration of "
            "Donation to Habitat for Humanity of Pinellas County, Inc.",
            # public programs, reports, bonds, small purchases
            "Grant Agreement With the State Department of Environmental Protection for Septic Upgrade Incentive Program",
            "Accept the qualified target industry tax refund program audit, Report IA-18-05, performed by the County "
            "Internal Auditor's Office. Moved acceptance.",
            "Adopt Resolution authorizing the issuance of the Community Investment Tax Refunding Revenue Bonds",
            "Incentives Agreement Termination Agreement With Delamere Industries, Inc., for Jobs Creation Grant Award",
            "Emergency Purchase – CenturyLink of Florida, Inc. – Network Voice and Data Carrier Services - $27,630.00",
            "So moved to waive the rules to hear Items B-1, B-2, and B-3 early.",
        ):
            self.assertEqual(spot(text), [], text)


if __name__ == "__main__":
    unittest.main()
