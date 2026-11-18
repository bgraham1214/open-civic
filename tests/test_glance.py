# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Florida at a glance (glance.py): each rule against real agenda wordings read on Nov 18, 2026."""

import unittest

from opencivic import glance


def s(title: str) -> list[str]:
    return glance.subjects({"title": title})


class Subjects(unittest.TestCase):
    def test_data_centers(self):
        for t in ["Ordinance suspending acceptance of development applications for data centers within the "
                  "unincorporated areas of Lake County.",
                  "Ordinance 2033 - LDC Prohibition: Data Centers",
                  "Consideration and approval of a M-1 Text Amendment for Data Centers and Artificial Intelligence (AI) "
                  "Facilities and Fee Schedule",
                  "Data Center Presentation and Resolution No. 26-51 - Intent to Adopt a Moratorium for Any-Sized Data "
                  "Center on Private Property"]:
            self.assertIn("data-centers", s(t), t)
        # a government's own server room
        for t in ["Inverness Government Center Data Center AC Replacement",
                  "Approve Single Source/Piggyback Renewal for Disaster Recovery Data Center"]:
            self.assertNotIn("data-centers", s(t), t)

    def test_cameras(self):
        self.assertIn("license-plate-cameras", s("Resolution 2026-10-592 Terminating Flock Agreement"))
        self.assertIn("license-plate-cameras", s("Overview of Automated License Plate Recognition Deployment"))
        self.assertIn("school-zone-speed-cameras", s("SCHOOL ZONE SPEED CAMERA ANNUAL REPORT"))
        self.assertIn("school-zone-speed-cameras", s("Annual Report regarding School Zone Speed Detection Systems."))

    def test_vehicles(self):
        self.assertIn("golf-carts", s("Resolution Authorizing Operation of Golf Carts Between Sunset and Sunrise on "
                                      "Designated County Roads Within High Point Community"))
        self.assertNotIn("golf-carts", s("APPROVAL OF RESOLUTION NO. 173-26 APPROVING AN AGREEMENT WITH TEXTRON E-Z-GO "
                                         "LLC., FOR GOLF CART LEASES AND RELATED EQUIPMENT"))
        self.assertIn("e-bikes", s("Ordinance No. 2026-036 Final E-Bikes"))
        self.assertIn("e-bikes", s("Council Communication - E-Bike Injury Study"))

    def test_ceremony_and_never(self):
        for t in ["Hunger and Homelessness Awareness Month (Mulicka)",
                  "National Youth Homelessness Outreach, Prevention, and Education (HOPE) Month (B)",
                  "World Homeless Day (B)",
                  "DELEGATION: Pat Example RE: Homelessness",  # a resident speaking: never grouped
                  "MOTION TO APPOINT Pat Example to the Homeless Continuum of Care Board",
                  "Reappoint Pat Example to the Affordable Housing Advisory Committee (AHAC)",
                  "Release of Lien related to a Workforce Housing Impact Fee Waiver for Pat Example (No fiscal impact).",
                  "Minutes for Approval: July 21, 2026, Regular/ Proposed Millage Meeting",
                  "Reminder of Upcoming Meetings: September 23, 2026, Final Public hearing for the FY 2027 Budget and "
                  "Final Millage"]:
            self.assertEqual(s(t), [], t)

    def test_money_subjects(self):
        self.assertIn("property-tax-rates", s("Resolution 2026-172 to adopt the Fiscal Year 2026-27 millage rate for "
                                              "the City of Ocala at the current rate of 6.6177"))
        self.assertIn("impact-fees", s("2nd Reading - Ordinance No. 2026-O-17: Amending and Modifying the schedule of "
                                       "impact fees relating to Chapter 21"))
        self.assertNotIn("impact-fees", s("Impact Fee West District Fund - Impact Fees West District - $45,500"))
        self.assertIn("utility-rates", s("Resolution No. 2026-36 Sanitation Rate Increase"))
        self.assertNotIn("utility-rates", s("Ordinance No. 2026-49 Mobility Fee Rate Adjustment Project # CCA26-00010"))

    def test_resilience_needs_water(self):
        self.assertIn("flooding-resilience", s("Adoption of the Coastal Resiliency Plan with the 2026 update to the "
                                               "Vulnerability Assessment."))
        self.assertIn("flooding-resilience", s("Resilient Florida Program Award 26SRP18"))
        self.assertNotIn("flooding-resilience", s("Resolution Establishing an Energy Resilience and Affordability "
                                                  "Policy; Rescinding the City's Net Zero Policy"))

    def test_legislature(self):
        self.assertIn("legislative-priorities", s("2027 State Legislative Priorities"))
        self.assertIn("legislative-priorities", s("Proposed Legislative Appropriation Requests for 2027-2028 State "
                                                  "Legislative Session"))
        self.assertNotIn("legislative-priorities", s("Accept State Legislative Line Item Appropriation for Provost "
                                                     "Park Improvements."))

    def test_annexation_not_a_building(self):
        self.assertIn("annexation", s("First Reading of Ordinance 26-1642 - Voluntary Annexation of One (1) Parcel"))
        self.assertNotIn("annexation", s("RFQ #2026-13 CMAR - Police Dept. Substation & Public Works Annex South"))


class Summary(unittest.TestCase):
    def test_three_places_in_window_and_stage(self):
        def row(title, passed=None):
            votes = [{"vote": "Yes"}] if passed is not None else []
            return {"item": {"title": title, "key": title}, "votes": votes,
                    "facts": {"yes": 1, "no": 0, "passed": passed, "action": ""} if votes else None}
        t = "Ordinance establishing a temporary moratorium on data centers"
        bm = {"a": {"2026-11-01": [row(t, True), row(t, True)]},  # listed twice in one meeting: once
              "b": {"2026-10-01": [row(t)]},
              "c": {"2025-01-01": [row(t)]},                       # outside the window
              "d": {"2026-09-01": [row(t)]}}
        g = glance.gather(bm)
        self.assertEqual(len(g["data-centers"]), 4)
        summ = glance.summarize(g, "2026-11-18")
        self.assertEqual([p["county"] for p in summ[0]["places"]], ["a", "b", "d"])
        self.assertTrue(summ[0]["places"][0]["passed"])
        self.assertFalse(summ[0]["places"][1]["passed"])
        bm.pop("d")
        self.assertEqual(glance.summarize(glance.gather(bm), "2026-11-18"), [])  # 2 places: not shown


if __name__ == "__main__":
    unittest.main()
