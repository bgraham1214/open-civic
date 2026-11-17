# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Volunteers removed from a board aren't named (privacy.py). The records' wording, with names replaced."""

import unittest

from opencivic.privacy import unname_item, unname_removals


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


if __name__ == "__main__":
    unittest.main()
