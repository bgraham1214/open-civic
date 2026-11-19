# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Volunteers removed from a board aren't named (privacy.py). The records' wording, with names replaced."""

import unittest

from opencivic.privacy import blank_names, removed_people, resident_speaker, scrub_text, unname_item, unname_removals


class Removals(unittest.TestCase):
    def test_names_dropped(self):
        for before, after in [
            ("To permanently remove the two volunteers (Jane Doe & Mary Ann Roe) from all city boards per the City "
             "Manager's recommendation",  # Oak Hill, Mar 9, 2026
             "To permanently remove the two volunteers from all city boards per the City Manager's recommendation"),
            ("to remove Jane DeRoe from the Historic Preservation Board and replace Dana Smith as the Hollywood Historical "
             "Society Representative",  # Hollywood, Jul 7, 2026: the replacement is an appointment, still named
             "to remove a member from the Historic Preservation Board and replace Dana Smith as the Hollywood Historical "
             "Society Representative"),
            ("The Board approved removing Jane Doe from the Election Canvassing Board; and appointed Mary Roe, as the alternate.",
             "The Board approved removing a member from the Election Canvassing Board; and appointed Mary Roe, as the alternate."),
            ("A Resolution Of The City Commission Of The City Of Hollywood, Florida, Removing Jane Doe From The African "
             "American Advisory Council And The Education Advisory Committee",
             "A Resolution Of The City Commission Of The City Of Hollywood, Florida, Removing a member From The African "
             "American Advisory Council And The Education Advisory Committee"),
            ("Recommendation to remove John Doe from the East of 951 Ad Hoc Advisory Committee for consecutive absences",
             "Recommendation to remove a member from the East of 951 Ad Hoc Advisory Committee for consecutive absences"),
            ("Request to Remove Planning & Zoning Board Member (John Q. Doe)", "Request to Remove Planning & Zoning Board Member"),
            ("A motion to remove the member (Jane Doe and John Roe) from the board", "A motion to remove the member from the board"),
        ]:
            self.assertEqual(unname_removals(before), after)

    def test_left_alone(self):
        for t in ["Moved the Board remove the item from the map before the Board transmitted the item.",
                  "requires the City Commission to remove the candidate from the Consent Agenda",
                  "Approve removing Commissioner Smith from the TPO board",  # an elected official
                  # Tarpon Springs, Feb 24, 2026: the commissioner who asked, in brackets
                  "Request to Remove Planning & Zoning Board Member (Commissioner Jane Doe)",
                  "remove the two volunteers from all city boards",
                  "To appoint Jane Doe, Sara Roe, Roger Poe to the Parks and Recreation Board",  # appointments
                  "Commissioner Townsend and Commissioner Lowry have requested to be removed from the Canvassing Board.",
                  "proposes removing the opioid review and recommendations committee from the TIP Advisory Board structure",
                  "Case Management Services to Prevent, Decrease, or Delay Premature Placement"]:
            self.assertEqual(unname_removals(t), t)

    def test_item(self):
        it = unname_item({"title": "VIA Hall/Museum Operations", "number": "F.3.",
                          "motion": "To remove the volunteer (Jane Doe) from all city boards"})
        self.assertEqual(it["motion"], "To remove the volunteer from all city boards")


class SearchText(unittest.TestCase):
    """Residents left out of the searchable text of minutes and memos (scrub_text), in the forms the Oak Hill,
    Pasco, Temple Terrace and Brevard records use (names and addresses replaced)."""
    KEEP = {"ricky taylor", "carrie werning", "jack mariano", "andy ross"}

    def s(self, t):
        return scrub_text(t, self.KEEP)

    def test_residents_left_out(self):
        for before, after in [
            ("Jane Roe 205 N. Brooks Cir asked the city for speed bumps.", "[name left out] [address left out] asked the city for speed bumps."),
            ("1. John Doe 130 N Putnam spoke regarding nails", "1. [name left out] [address left out] spoke regarding nails"),
            ("Mary Roe 576 N. US Hwy 1 spoke about it.", "[name left out] [address left out] spoke about it."),
            ("2. JANE ROE: SPOKE IN REGARD TO MEMORIAL DAY", "2. [name left out]: SPOKE IN REGARD TO MEMORIAL DAY"),
            ("Ms. Jane Roe expressed her appreciation", "Ms. [name left out] expressed her appreciation"),
            ("Approved to receive and file documents submitted by Ms. Jane Roe.",
             "Approved to receive and file documents submitted by [name left out]."),
            ("e Resident Jane Taylor spoke in favor", "e [name left out] spoke in favor"),  # not the Mayor
            ("D. PUBLIC COMMENTS: Jane Roe spoke about the school", "D. PUBLIC COMMENTS: [name left out] spoke about the school"),
            ("3. John Doe — Complimented city staff", "3. [name left out] — Complimented city staff"),
            ("Tony and Patty Roe requested three variances", "[name left out] requested three variances"),
            ("Citizens Comments\n\nJohn Doe (205 Randall Avenue) asked about it",
             "Citizens Comments\n\n[name left out] ([address left out]) asked about it"),
            ("Jane Roe and Mary Doe of Girl Scout Troop #1 spoke of learning", "[name left out] of Girl Scout Troop #1 spoke of learning"),
            ("Applicant, Jane Roe, stated the location", "Applicant, [name left out], stated the location"),
            ("Contact jroe@example.com or (813) 555-1234.", "Contact [email left out] or [phone left out]."),
            # surnames that are also everyday words
            ("Neil Bond 295 Indian Creek Rd spoke about the road.", "[name left out] [address left out] spoke about the road."),
            ("Bill Grant asked about the park.", "[name left out] asked about the park."),
            ("Jane Chambers stated her concerns.", "[name left out] stated her concerns."),
            ("Mary Park commented on the plan.", "[name left out] commented on the plan."),
            ("We ask you to deny it.\n\nSincerely,\n\nJane Q. Roe\n", "We ask you to deny it.\n\nSincerely,\n\n[name left out]\n"),
        ]:
            self.assertEqual(self.s(before), after)

    def test_officials_and_headings_stay(self):
        for t in ["Commissioner Werning moved to approve.", "Mayor Taylor assured the resident.", "MAYOR TAYLOR asked",
                  "CITY ADMINISTRATOR JANE SHIRA stated", "Chairman Mariano spoke regarding the letter",
                  "Senior Planner Jane Doe stated the request", "11. Consent Agenda:\nA. Resolution Approving",
                  "Miscellaneous Business - District Five - Chairman Mariano", "Economic Development - [name left out]",
                  "The Pledge of Allegiance was led", "REGULAR MEETING was called to order",
                  "GO Bond Referendum was discussed", "House Bill 803 addressed building permits",
                  "from Blue Lake Avenue to the Dr. Martin Luther King, Jr. Beltway",
                  "The Placid Lakes Homeowners Association Inc is requesting a waiver",
                  "closing on Right-of-Way for US Highway 441 - Sleepy Hollow Racetrack, which is in the City of Leesburg",
                  "Carrie Werning stated", "Mr. Taylor stated"]:
            self.assertEqual(self.s(t), t, t)
        # a memo's property address stays when asked; a speaker's address never does
        t = "Annexation of the parcel located at 8325 North Bradshaw Road. Jane Roe 12 Oak St spoke in favor."
        self.assertEqual(scrub_text(t, addresses=False),
                         "Annexation of the parcel located at 8325 North Bradshaw Road. [name left out] [address left out] spoke in favor.")
        t = "from North of Commercial Circle to North of St. Johns Bluff Road (Item 4) is planned"
        self.assertEqual(self.s(t), t)
        # staff the documents name with a title stay elsewhere in the same text
        t = "Sincerely,\n\nJohn Barkley\nCity Manager"  # the documents call him City Manager elsewhere
        self.assertEqual(scrub_text(t, self.KEEP | {"john barkley"}), t)
        t = "City Manager John Barkley presented the budget. Mr. Barkley stated it was balanced."
        self.assertEqual(self.s(t), t)


class RemovedPeople(unittest.TestCase):
    def test_found_and_blanked_everywhere(self):
        t = "Commissioner Doe moved to permanently remove the two volunteers (Jane Q Doe & Mary Roe) from all city boards"
        self.assertEqual(removed_people(t), {"jane doe", "mary roe"})
        self.assertEqual(removed_people("To appoint Jane Doe and Mary Roe to the Parks Board"), set())
        self.assertEqual(blank_names("To appoint Jane Q.  Doe, Sam Poe and MARY ROE to the Parks Board", {"jane doe", "mary roe"}),
                         "To appoint [name left out], Sam Poe and [name left out] to the Parks Board")


class ResidentSpeakers(unittest.TestCase):
    """Items about a resident who asked to speak are never stored (florida.py), as public comment isn't."""

    def test_title_and_speaker_form_share_a_name(self):
        self.assertTrue(resident_speaker({"title": "Short-Term Rental Ordinance Enforcement - Pat Example",
                                          "attachments": [{"name": "Speaker form city council 4-7-26, Example"}]}))
        self.assertTrue(resident_speaker({"title": "Request to Speak about Safety - Pat Example",
                                          "attachments": ["Request to Speak Pat Example"]}))

    def test_cards_on_ordinary_items_left_alone(self):
        self.assertFalse(resident_speaker({"title": "An Ordinance Amending the Official Zoning Atlas of the City of Venice",
                                           "attachments": ["Staff Report", "Speaker card 01.14.25"]}))
        self.assertFalse(resident_speaker({"title": "Citizens To Be Heard - Public Comment.",
                                           "attachments": ["Citizens to be Heard Speaker Cards", "Public Comment Letter"]}))
        self.assertFalse(resident_speaker({"title": "Assistant City Manager: Resiliency Presentation",
                                           "attachments": ["Memorandum", "Speaker Card 01.28.25"]}))


if __name__ == "__main__":
    unittest.main()
