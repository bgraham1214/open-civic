"""Minutes parsing (attendance, roll-call votes) and contract/vendor extraction.

The minutes text below copies the formats seen in Temple Terrace's real minutes,
including the variants that broke earlier versions of the parser.
"""

import unittest

from opencivic import entities as en
from opencivic import minutes as mn

PAGE1 = """CITY OF TEMPLE TERRACE, FLORIDA
CITY COUNCIL MEETING MINUTES

Present were: Mayor Andy Ross, Council Members James Chambers, Alison Fernandez (entered 5:08 pm), and
Gil Schisler, City Manager Carlos Baia, City Clerk Lynda Sader, and City Attorney Ernie Mueller.
[Honorary Mayor for the Day Kamden Jaime]
Absent was: Council Member Kravets.
Also present were: Police Chief Rob Staley, Finance Director Jim Ingram.

8.   Consideration of Minutes from Previous Meetings:
       8.A. Approval of the October 21, 2025 City Council meeting minutes
Upon motion of Council Member Schisler, seconded by Council Member Fernandez, unanimously carried,
the MINUTES of October 21, 2025, City Council Meeting were APPROVED as presented.

11.   Consent Agenda:
       A. Resolution Approving the Purchase of a Sidewalk Grinder
       B. Resolution Awarding the Continuing Contract for Asphalt Paving Services
Upon motion by Council Member Chambers, seconded by Vice Mayor Schisler and unanimously carried,
RESOLUTION, 11.A.-11.B., were ADOPTED by consent, as follows:
"""

PAGE2 = """12.   Public Hearings, Ordinances, and Resolutions:
       C. Second Public Hearing and Second Reading of Ordinance 1586
4. The applicant noted three points about drainage.
Upon motion by Council Member Kravets, seconded by Council Member Fernandez, Amend
Ordinance 1586, remove modification of 12-354.
Vote on the motion being: Council Members Fernandez and Kravets voting “aye,” Mayor Ross
and Council Members Chambers and Schisler “nay.” Therefore, the motion failed.

Upon motion by Vice Mayor Schisler, seconded by Council Member Chambers, Approved
Ordinance 1586 on Second Reading.
Vote on the motion being: Mayor Ross, Council Members Chambers, Schisler and Kravets voting “aye,”
Council Member Ferandez voting, “nay.”

Upon motion by Council Member Chambers seconded by Council Member Schisler, RESOLUTION 19-26, ADOPTED
the resolution. Vote on the motion being: Mayor Ross and Council! Members Chambers, Fernandez, and
Schisler voting “aye,” no “nay.”
"""

AGENDA = {
    "8.": "Consideration of Minutes from Previous Meetings",
    "8.A.": "Approval of the October 21, 2025 City Council Meeting Minutes",
    "11.": "Consent Agenda",
    "11.A.": "Resolution Approving the Purchase of a Sidewalk Grinder",
    "11.B.": "Resolution Awarding the Continuing Contract for Asphalt Paving Services to Six Contractors",
    "12.": "Public Hearings, Ordinances, and Resolutions",
    "12.C.": "Second Public Hearing and Second Reading of Ordinance 1586 Amending Sections",
}


class Minutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.f = mn.parse_minutes([{"n": 1, "text": PAGE1}, {"n": 2, "text": PAGE2}], AGENDA)

    def test_attendance(self):
        self.assertEqual([(a.name, a.role) for a in self.f.present], [
            ("Andy Ross", "Mayor"), ("James Chambers", "Council Member"), ("Alison Fernandez", "Council Member"),
            ("Gil Schisler", "Council Member"), ("Carlos Baia", "City Manager"), ("Lynda Sader", "City Clerk"),
            ("Ernie Mueller", "City Attorney")])
        self.assertEqual([(a.name, a.role) for a in self.f.absent], [("Kravets", "Council Member")])
        self.assertNotIn("Kamden Jaime", [a.name for a in self.f.present])  # bracketed honorary guest

    def test_votes(self):
        v = self.f.votes
        self.assertEqual(len(v), 5)
        carried = [x for x in v if not x["roll_call"]]
        self.assertEqual([x["item"] for x in carried], ["8.A.", "11.B."])
        failed, passed, unanimous = [x for x in v if x["roll_call"]]
        self.assertEqual(failed["item"], "12.C.")  # "4. The applicant..." is not a heading
        self.assertEqual((failed["ayes"], failed["nays"]), (["Fernandez", "Kravets"], ["Ross", "Chambers", "Schisler"]))
        self.assertEqual(failed["result"], "failed")
        self.assertEqual(passed["nays"], ["Ferandez"])  # clerk's typo kept here; entities fixes it
        self.assertEqual(passed["mover"], "Schisler")
        self.assertEqual(unanimous["nays"], [])
        self.assertNotIn("Council", unanimous["ayes"])
        self.assertEqual(unanimous["record_number"], "Resolution 19-26")
        self.assertEqual(unanimous["page"], 2)

    def test_canonical_names(self):
        rosters = [[mn.Attendee("Ernie Mueller", "City Attorney")], [mn.Attendee("Ernest Mueller", "City Attorney")],
                   [mn.Attendee("Ernest Mueller", "City Attorney")]]
        self.assertEqual(mn.canonical_names(rosters)[("Mueller", "City Attorney")], "Ernest Mueller")


def item(title, description="", attachments=()):
    return {"key": "k", "date": "2026-01-01", "outline": "11.A.", "item_number": "", "is_section": False,
            "title": title, "description": description, "fiscal_impact": "", "portal_url": "u",
            "attachments": [{"name": a} for a in attachments]}


class Vendors(unittest.TestCase):
    def test_suffixed_and_coop(self):
        rows = en.contract_rows([item(
            "Resolution Approving the Purchase of a Sidewalk Grinder",
            "Staff recommends the purchase of a sidewalk grinder in the amount of $53,265.25 from Sherwin "
            "Industries, Inc., utilizing Sourcewell Contract 110122-SWN.")])
        self.assertEqual(rows[0]["vendors"], ["Sherwin Industries, Inc"])
        self.assertEqual(rows[0]["amount_stated"], 53265.25)
        self.assertEqual(rows[0]["cooperative_contract"], "Sourcewell Contract 110122-SWN")

    def test_list_of_contractors(self):
        rows = en.contract_rows([item(
            "Resolution Awarding the Continuing Contract for Asphalt Paving Services to Six Contractors",
            "Staff recommends that City Council authorize the City Manager to execute contracts with Ajax Paving "
            "Industries of Florida, LLC; Asphalt Paving Systems, Inc.; and Superior Asphalt, Inc. to conduct "
            "as needed asphalt paving services.")])
        self.assertEqual(rows[0]["vendors"], ["Ajax Paving Industries of Florida, LLC", "Asphalt Paving Systems, Inc",
                                              "Superior Asphalt, Inc"])

    def test_vendor_from_quote_attachment_and_junk_rejected(self):
        rows = en.contract_rows([item("Resolution Approving the Purchase of Three Police Vehicles",
                                      "approving the purchase of three vehicles ($61,966.03 each)",
                                      ["Resolution", "Bartow Ford Quote", "Vendor Quote", "Pump Quote",
                                       "Signed HydraStop Equipment Quote"])])
        self.assertEqual(rows[0]["vendors"], ["Bartow Ford"])

    def test_not_contracts(self):
        self.assertEqual(en.contract_rows([item("Resolution Approving an Addendum to the City Clerk's Employment Agreement"),
                                           item("Citizen Award of Valor Presented to a Resident"),
                                           item("8901 Proposal Summary")]), [])

    def test_vendor_key_merges_spellings(self):
        self.assertEqual(en.vendor_key("Mid-Florida Diesel"), en.vendor_key("Mid Florida Diesel, Inc."))
        self.assertEqual(en.vendor_key("Asphalt Paving System"), en.vendor_key("Asphalt Paving Systems, Inc"))


if __name__ == "__main__":
    unittest.main()
