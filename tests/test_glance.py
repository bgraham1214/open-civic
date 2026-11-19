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
        self.assertNotIn("golf-carts", s("Cartin Tarpon Annual Christmas Golf Cart Parade"))
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

    def test_storms(self):
        self.assertIn("hurricanes", s("Recommendation Concerning Escambia County State of Local Emergency Related to "
                                      "Hurricane Isaias."))
        self.assertIn("hurricanes", s("Grant Acceptance - FEMA-Hazard Mitigation Grant Program - Lakewood Park Drainage "
                                      "Improvement Project Phase II"))
        self.assertNotIn("hurricanes", s("Approve the Port Security Grant Program (PSGP) Grant award, with the U.S. "
                                         "Department of Homeland Security (DHS), Federal Emergency Management Agency "
                                         "(FEMA), for FY2026-2027"))

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


def k(slug: str, title: str) -> str:
    return glance.kind(slug, {"title": title})[0]


class Exclusions(unittest.TestCase):
    def test_flock_fitness_is_a_gym(self):
        self.assertNotIn("license-plate-cameras", s("Approve and authorize the Chairman to execute the Second Amendment to "
                                                    "the Facilities Use Agreement between Seminole County and Flock Fitness, LLC"))
        self.assertIn("license-plate-cameras", s("Flock Camera Discussion"))

    def test_rental_manager_is_a_job_title(self):
        self.assertNotIn("short-term-rentals", s("Status Update of the City's Drop-In Day Center and establishing Dining "
                                                 "with Dignity at 90-92 South Dixie Highway. (B. Fox, Code Enforcement and "
                                                 "Vacation Rental Manager)"))

    def test_resident_speaker_never_grouped(self):
        it = {"title": "Short-Term Rental Ordinance Enforcement - Pat Example",
              "attachments": ["Speaker form city council 4-7-26, Example", "Short Term Rental Ordinance Enforcement - Pat Example"]}
        self.assertEqual(glance.subjects(it), [])
        # a speaker card on an ordinary hearing doesn't hide the hearing
        it = {"title": "An Ordinance establishing a temporary moratorium on data centers",
              "attachments": ["Staff Report", "Speaker card 01.14.25"]}
        self.assertEqual(glance.subjects(it), ["data-centers"])


class Kinds(unittest.TestCase):
    def test_talks_first(self):
        # a direction to draft a moratorium is not a moratorium (Hillsborough, Broward)
        self.assertEqual(k("data-centers", "Requested the County Attorney's Office to draft and to bring back to the "
                                           "Commission for review an ordinance which imposed a moratorium"), "talk")
        self.assertEqual(k("data-centers", "MOTION TO DIRECT County Attorney's Office to draft an Ordinance establishing a "
                                           "temporary, one-year moratorium on the development of large-scale data centers"), "talk")
        # a member's agenda item, no ordinance named (Venice, Santa Rosa)
        self.assertEqual(k("data-centers", "Data Center Moratorium (Mayor Pachota)"), "talk")
        self.assertEqual(k("data-centers", "Commissioner Smith - 12-Month Data Center Moratorium"), "talk")
        self.assertEqual(k("data-centers", "Data Center Action Plan Progress Report Moratorium (ORD 1523-26) will expire "
                                           "June 22, 2027"), "talk")
        # "zoning in progress" is a pause, not a progress report (Wellington)
        self.assertEqual(k("data-centers", "RESOLUTION NO. R2026-51 (ZONING IN PROGRESS FOR WAREHOUSING/DATA CENTERS) A "
                                           "RESOLUTION OF WELLINGTON"), "pause")
        # "Fee Schedule" isn't scheduling a hearing (Pembroke Park)
        self.assertEqual(k("data-centers", "Consideration and approval of a M-1 Text Amendment for Data Centers and "
                                           "Artificial Intelligence (AI) Facilities and Fee Schedule"), "rules")

    def test_laws_need_their_name(self):
        self.assertEqual(k("data-centers", "Ordinance No. 2026-032 Final Data Centers Moratorium"), "pause")
        self.assertEqual(k("data-centers", "Ordinance 2033 - LDC Prohibition: Data Centers"), "ban")
        self.assertEqual(k("data-centers", "Anti-Data Center Prohibitions"), "other")
        self.assertEqual(k("data-centers", "2nd Reading - Ordinance No. 2026-O-21 - Permanent Moratorium on the Acceptance "
                                           "... for Data Centers"), "ban")
        # a word 600 characters in doesn't decide (rule 23)
        self.assertEqual(k("data-centers", "Ordinance amending the Land Development Code to permit data centers " + "x " * 300
                                           + "prohibiting"), "rules")

    def test_one_project_and_positions(self):
        self.assertEqual(k("data-centers", "Resolution 2026-35. A Resolution Approving the Location of Six (6) Grounding "
                                           "Beds Associated with the DC Blox Data Center Project"), "project")
        self.assertEqual(k("data-centers", "Resolution 2026-23: Expressing Support for Florida Senate Bill 484 Regarding "
                                           "Data Centers"), "position")
        self.assertEqual(k("data-centers", "Ordinance Amending Chapter 102 ... to Make Data Centers Ineligible for Economic "
                                           "Development Ad Valorem Tax Exemptions."), "incentive")

    def test_cameras(self):
        self.assertEqual(k("license-plate-cameras", "Resolution 2026-10-592 Terminating Flock Agreement"), "end")
        self.assertEqual(k("license-plate-cameras", "Renew File No. 250025-N-AS, Flock Safety Automatic License Plate "
                                                    "Recognition Cameras and Services"), "contract")
        self.assertEqual(k("license-plate-cameras", "A RESOLUTION OF THE MAYOR AND THE CITY COUNCIL OF THE CITY OF DORAL, "
                                                    "FLORIDA, PURSUANT TO SECTION 2-322 OF THE CITY'S CODE OF ORDINANCES, "
                                                    "AUTHORIZING THE CITY MANAGER, TO UTILIZE THE GENERAL SERVICES "
                                                    "ADMINISTRATION CONTRACT"), "contract")
        self.assertEqual(k("license-plate-cameras", "License Plate Recognition System*"), "other")
        self.assertEqual(k("school-zone-speed-cameras", "SCHOOL ZONE SPEED CAMERA ANNUAL REPORT"), "report")
        self.assertEqual(k("school-zone-speed-cameras", "AN ORDINANCE OF THE CITY OF DANIA BEACH ... AGREEMENT WITH "
                                                        "THE VENDOR"), "rules")
        self.assertEqual(k("school-zone-speed-cameras", "Motion Approving an Agreement for an Automated School Zone Speed "
                                                        "Detection Camera Program - RedSpeed Florida LLC"), "contract")
        self.assertEqual(k("school-zone-speed-cameras", "MOTION TO ADOPT Resolution, the title of which is as follows: A "
                                                        "RESOLUTION OF THE BOARD OF COUNTY COMMISSIONERS OF BROWARD COUNTY, "
                                                        "FLORIDA, URGING MUNICIPALITIES ..."), "position")

    def test_vehicles_and_rentals(self):
        self.assertEqual(k("e-bikes", "A RESOLUTION OF THE MAYOR AND THE CITY COUNCIL OF THE CITY OF DORAL, FLORIDA, "
                                      "INSTRUCTING THE CITY ATTORNEY TO AMEND CITY ORDINANCES"), "talk")
        self.assertEqual(k("e-bikes", "Ordinance No. 2026-036 Final E-Bikes"), "rules")
        self.assertEqual(k("golf-carts", "Golf Cart Resolution, Englewood Beach Waterfest 2026"), "event")
        self.assertEqual(k("golf-carts", "Public Hearing Approving the Issuance of a Certificate of Public Convenience and "
                                         "Necessity for BEACHE CARTS LLC to Operate One Low-Speed Vehicle"), "property")
        self.assertEqual(k("golf-carts", "Direct to Public Hearing to Adopt an Ordinance for the Use of Golf Carts"), "rules")
        self.assertEqual(k("short-term-rentals", "Resolution 2026-20: Increase the Base Rate and the Per Bedroom Rate "
                                                 "Charged for Short Term Rentals"), "fees")
        self.assertEqual(k("short-term-rentals", "Resolution 2026-31;(Quasi-Judicial) Conditional Use Approval to allow "
                                                 "operation of a Seasonal/Short-Term Rental"), "property")
        self.assertEqual(glance.kind("hurricanes", {"title": "Hurricane debris removal"}), ("", ""))


def row(title, passed=None, action="", yes=1, no=0):
    votes = [{"vote": "Yes"}] if passed is not None or yes or no else []
    if passed is None and not (yes or no):
        votes = []
    return {"item": {"title": title, "key": title}, "votes": votes,
            "facts": {"yes": yes, "no": no, "passed": passed, "action": action} if votes else None}


class Stages(unittest.TestCase):
    def x(self, d, r):
        return {"date": d, "stage": glance._stage(r)}

    def test_item_stage_from_votes_only(self):
        self.assertEqual(glance._stage(row("t")), "agenda")
        self.assertEqual(glance._stage(row("t", True)), "passed")
        self.assertEqual(glance._stage(row("t", False, yes=2, no=3)), "failed")
        self.assertEqual(glance._stage(row("t", None, yes=2, no=2)), "tied")
        self.assertEqual(glance._stage(row("t", None, yes=0, no=0) | {"votes": [{"vote": "Absent"}],
                                                                      "facts": {"yes": 0, "no": 0, "passed": None}}), "agenda")
        # a motion to deny or to put off that passed is not "passed" (North Port, Fort Lauderdale, Pasco)
        self.assertEqual(glance._stage(row("t", True, "denied")), "denied")
        self.assertEqual(glance._stage(row("t", True, "continued for 2 weeks")), "put off")
        self.assertEqual(glance._stage(row("t", True, "TABLED")), "put off")
        self.assertEqual(glance._stage(row("t", True, "DEFERRED")), "put off")

    def test_stage_word(self):
        today = "2026-11-19"
        past, future = "2026-10-01", "2026-12-08"
        sw = glance.stage_word
        self.assertEqual(sw([self.x(past, row("t"))], today), "")
        self.assertEqual(sw([self.x(future, row("t"))], today), "coming up")
        self.assertEqual(sw([self.x(past, row("t", True)), self.x(future, row("t"))], today), "passed; more coming up")
        self.assertEqual(sw([self.x(past, row("t", True))], today), "passed")
        self.assertEqual(sw([self.x(past, row("t", False, yes=1, no=4))], today), "motion failed")
        self.assertEqual(sw([self.x(past, row("t", None, yes=2, no=2))], today), "tie vote")
        self.assertEqual(sw([self.x(past, row("t", True, "continued"))], today), "")


class Window(unittest.TestCase):
    def test_since_upcoming_and_first_time(self):
        t = "Ordinance establishing a temporary moratorium on data centers"
        bm = {"a": {"2026-12-08": [row(t)], "2024-01-01": [row("Minutes")]},        # coming up; records from 2024
              "b": {"2026-10-01": [row(t, True)], "2025-01-05": [row(t)]},          # took it up before
              "c": {"2026-09-01": [row(t)], "2026-08-30": [row("Budget")]},          # records start late
              "h": {"2014-06-01": [row(t)]}}                                          # Hillsborough-style old item
        g = glance.gather(bm)
        self.assertNotIn("h", {x["county"] for x in g["data-centers"]})
        summ = glance.summarize(g, "2026-11-19", glance.firsts(bm), glance.starts(bm))
        self.assertEqual(len(summ), 1)
        places = {p["county"]: p for p in summ[0]["places"]}
        self.assertEqual(places["a"]["stage"], "coming up")
        self.assertEqual(places["b"]["stage"], "passed")
        self.assertEqual(summ[0]["new"], ["a"])  # b had it before; c's records don't reach back a year
        t = "Resolution adopting the final millage rate"
        bm = {c: {"2026-09-15": [row(t)], "2025-01-05": [row("Budget")]} for c in "xyz"}
        summ = glance.summarize(glance.gather(bm), "2026-11-19", glance.firsts(bm), glance.starts(bm))
        self.assertEqual(summ[0]["new"], [])  # a yearly subject: a "first" would only be a hole in our records


class Pages(unittest.TestCase):
    def test_feed_reverse_and_label(self):
        from opencivic.build import _rss
        from opencivic.site import _feed_label
        import xml.etree.ElementTree as ET
        t = "Ordinance establishing a temporary moratorium on data centers"
        bm = {"pasco": {"2026-11-01": [row(t, True)]}, "hernando": {"2026-10-01": [row(t)]},
              "edgewater": {"2026-12-01": [row(t)]}}
        for c in bm:
            for rs in bm[c].values():
                for r in rs:
                    r["item"]["key"] = f"{c}:{r['item']['key']}"
        g = glance.gather(bm)
        x = ET.fromstring(glance.feed("data-centers", g["data-centers"], _rss))
        items = x.findall("./channel/item")
        self.assertEqual(len(items), 3)
        self.assertTrue(items[0].find("guid").text.endswith("|issue|data-centers"))
        self.assertIn("Kind: Pauses (moratoriums)", items[0].find("description").text)
        html_ = glance.reverse_html("pasco", glance.by_government(g)["pasco"])
        self.assertIn('href="../issues/data-centers.html#pasco"', html_)
        self.assertEqual(_feed_label("issue-data-centers.xml"), "Florida at a glance: Data centers")
        self.assertEqual(_feed_label("spotlight.xml"), "Spotlight: new restrictions and breaks for companies")
        page = glance.page_issue("data-centers", g["data-centers"], "2026-11-19", glance.starts(bm))
        self.assertIn('<section id="pasco"', page)
        self.assertIn("How it spread", page)
        self.assertIn('aria-hidden="true"', page.split("How it spread")[1])  # the chart is decorative


if __name__ == "__main__":
    unittest.main()
