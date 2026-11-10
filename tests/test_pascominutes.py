# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Pasco votes read from the Clerk's annotated-agenda minutes (layout copied from the real files)."""

import gzip
import json
import tempfile
import unittest
from pathlib import Path

from opencivic import pascominutes as pm

PAGE1 = """       BOARD OF COUNTY COMMISSIONERS, PASCO COUNTY, FLORIDA
                   REGULAR MEETING/REZONINGS
                               ANNOTATED AGENDA
                                  OCTOBER 20, 2026

County Commissioners             Honorable Jack Mariano, Chairman, District 5
                                 Honorable Seth Weightman, Vice-Chairman, District 2
                                 Honorable Lisa Yeager, Second Vice-Chairman,
                                 District 4
                                 Honorable Ronald E. Oakley, District 1
                                 Honorable Kathryn Starkey, District 3

Clerk & Comptroller               Honorable Nikki Alvarez-Sowles, Esq.

Roll Call

Ms. Alvarez-Sowles called the roll. All Commissioners were present.


Public Comment

Ms. Jane Resident spoke regarding a fence.

Approved to receive and file documents submitted by Ms. Jane Resident with Commissioner
Oakley absent from the vote.

Resolutions

RS1           A Resolution Celebrating Veterans Day On November 11, 2026
              File Number         CAO27-2709
              Comm. Dist.         All
              Recommendation Approve

Approved to adopt.


Consent

Approved the Consent Agenda with the exception of Agenda Item C3 which was pulled
for discussion or revision and Agenda Item C4 which had been withdrawn with
Commissioner Oakley absent from the vote.


            Development Services

C2          Budget Amendment and Resolution – Office of Economic Growth – $265,000.00
            File Number        DS27-0001
            Comm. Dist.        2
            Recommendation Approve

C3          Award of Bid No. IFB-BW-26-007 – Central Florida Contractors Inc. – $375,192.86
            File Number       TED27-0011
            Comm. Dist.       3
            Recommendation Approve

Approved Staff’s recommendation with Commissioner Weightman and Chairman Mariano
                                  BCC AA 10/20/2026
                                    Page 1 of 2
"""

PAGE2 = """voting nay.

C4          Waiver of Lien Interest
            File Number         CC27-0002
            Comm. Dist.         3
            Recommendation Approve

The item was withdrawn.

Regular

R5          Interlocal Agreement – City of Zephyrhills
            File Number        CA27-0005
            Comm. Dist.        All
            Recommendation Approve

COMMISSIONER OAKLEY MOVED approval to adopt; COMMISSIONER YEAGER SECONDED.

Chairman Mariano called on the motion; the motion carried with Commissioner Starkey
abstaining from the vote due to a conflict of interest.

R6          An Ordinance Amending Chapter 82
            File Number        CA27-0006
            Comm. Dist.        All
            Recommendation Approve

The motion to adopt died with Commissioner Yeager and Chairman Mariano voting nay and
Commissioner Starkey abstaining from the vote due to a conflict of interest.

R7          Two Motions Item
            File Number        CA27-0007
            Comm. Dist.        All
            Recommendation Approve

Approved to amend the motion.

Approved Staff’s recommendation as amended.

P8          Zoning Amendment (Continuance) – Mitras Family Extended LLC
            File Number        PDE27-7901
            Comm. Dist.        5
            Recommendation Continuance Requested

Approved to continue to the December 8, 2026 Board of County Commissioners
meeting at 1:30 p.m. in New Port Richey.

R9          Unknown Name Item
            File Number        CA27-0009
            Comm. Dist.        All
            Recommendation Approve

Approved Staff’s recommendation with Commissioner Smith voting nay.

R10         Missing Period Item
            File Number        CA27-0010
            Comm. Dist.        All
            Recommendation Approve

Approved to adopt


              Noted Items

N11         Cultural Affairs Advisory Council Meeting Minutes
            File Number          NI27-0370
            Comm. Dist.          All
            Recommendation Receive and File
                                  BCC AA 10/20/2026
                                    Page 2 of 2
"""

PAGES = [{"n": 1, "text": PAGE1, "method": "pdftotext"}, {"n": 2, "text": PAGE2, "method": "pdftotext"}]
SURNAMES = ["Mariano", "Oakley", "Starkey", "Weightman", "Yeager"]


def by_code(decisions):
    return {d["code"]: d for d in decisions}


class Parse(unittest.TestCase):
    def setUp(self):
        self.decisions, self.problems, self.info = pm.parse(PAGES)
        self.d = by_code(self.decisions)

    def test_roster(self):
        self.assertEqual(self.info["members"], ["Jack Mariano", "Seth Weightman", "Lisa Yeager", "Ronald E. Oakley",
                                                "Kathryn Starkey"])

    def test_resolution_unanimous(self):
        self.assertEqual(self.d["RS1"]["votes"], {s: "Yes" for s in SURNAMES})
        self.assertEqual(self.d["RS1"]["action"], "Adopted")

    def test_consent_item_inherits_the_consent_vote(self):
        c2 = self.d["C2"]
        self.assertEqual(c2["action"], "Approved (consent agenda)")
        self.assertEqual(c2["votes"]["Oakley"], "Absent")
        self.assertEqual(sum(v == "Yes" for v in c2["votes"].values()), 4)

    def test_pulled_item_has_its_own_vote_across_a_page_break(self):
        c3 = self.d["C3"]
        self.assertEqual(c3["votes"]["Weightman"], "No")
        self.assertEqual(c3["votes"]["Mariano"], "No")
        self.assertEqual(c3["votes"]["Oakley"], "Yes")   # the consent motion's absence doesn't carry over
        self.assertEqual(c3["page"], 1)

    def test_withdrawn_and_noted_items_have_no_vote(self):
        self.assertNotIn("C4", self.d)
        self.assertNotIn("N11", self.d)

    def test_long_form_motion(self):
        r5 = self.d["R5"]
        self.assertEqual((r5["mover"], r5["seconder"]), ("Ronald E. Oakley", "Lisa Yeager"))
        self.assertEqual(r5["votes"]["Starkey"], "Abstained (conflict of interest)")
        self.assertEqual(r5["action"], "Adopted")

    def test_failed_motion(self):
        r6 = self.d["R6"]
        self.assertEqual((r6["action"], r6["result"]), ("Failed", "Fail"))
        self.assertEqual([r6["votes"][s] for s in ("Yeager", "Mariano", "Oakley", "Weightman")], ["No", "No", "Yes", "Yes"])

    def test_continuance(self):
        self.assertEqual(self.d["P8"]["action"], "Continued")

    def test_unclear_items_are_reported_not_guessed(self):
        self.assertNotIn("R7", self.d)
        self.assertNotIn("R9", self.d)
        problems = {p["code"]: p["problem"] for p in self.problems}
        self.assertEqual(problems["R7"], "2 motions")
        self.assertEqual(problems["R9"], "unknown name Smith")

    def test_action_without_final_period(self):
        self.assertEqual(self.d["R10"]["action"], "Adopted")

    def test_public_comment_is_never_read(self):
        everything = json.dumps(self.decisions) + json.dumps(self.problems)
        self.assertNotIn("Resident", everything)

    def test_whole_meeting_absence_and_late_arrival(self):
        p1 = PAGE1.replace("All Commissioners were present.",
                           "All Commissioners were present with the exception of\nCommissioner Yeager who was absent.")
        d = by_code(pm.parse([{**PAGES[0], "text": p1}, PAGES[1]])[0])
        self.assertEqual(d["RS1"]["votes"]["Yeager"], "Absent")
        late = p1.replace("who was absent.", "who was absent.\n\nCommissioner Yeager arrived to the meeting at 10:20 a.m.")
        d = by_code(pm.parse([{**PAGES[0], "text": late}, PAGES[1]])[0])
        self.assertEqual(d["RS1"]["votes"]["Yeager"], "Yes")

    def test_misread_roster_stops_the_meeting(self):
        p1 = PAGE1.replace("                                 Honorable Kathryn Starkey, District 3\n", "")
        decisions, problems, _ = pm.parse([{**PAGES[0], "text": p1}, PAGES[1]])
        self.assertEqual(decisions, [])
        self.assertEqual(problems[0]["problem"], "roster has 4 names, not 5")

    def test_long_form_consent(self):
        p1 = PAGE1.replace(
            "Approved the Consent Agenda with the exception of Agenda Item C3 which was pulled\n"
            "for discussion or revision and Agenda Item C4 which had been withdrawn with\n"
            "Commissioner Oakley absent from the vote.",
            "COMMISSIONER OAKLEY MOVED approval of the Consent Agenda with the\nexception of Agenda items C3 and C4 "
            "which had been pulled; COMMISSIONER MARIANO\nSECONDED.\n\nChairman Mariano called on the motion; the "
            "vote was unanimous, and the motion\ncarried with Commissioner Yeager absent from the vote.")
        d = by_code(pm.parse([{**PAGES[0], "text": p1}, PAGES[1]])[0])
        self.assertEqual(d["C2"]["votes"]["Yeager"], "Absent")
        self.assertEqual(d["C2"]["votes"]["Oakley"], "Yes")


class Run(unittest.TestCase):
    def test_join_to_agenda_items_and_write_listings(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            (data / "text").mkdir()
            (data / "listings").mkdir()
            sha = "c" * 64
            with gzip.open(data / "text" / f"{sha}.json.gz", "wt") as fh:
                json.dump({"sha256": sha, "pages": PAGES}, fh)
            (data / "state.json").write_text(json.dumps({"civicclerk:pascocofl:1": {
                "key": "civicclerk:pascocofl:1", "kind": "Minutes", "date": "2026-10-20", "sha256": sha,
                "title": "AA BCC 10-20-2026", "body": "Board of County Commissioners (Board of County Commissioners)",
                "url": "https://pascocofl.api.civicclerk.com/f/1", "copy_url": "https://example.org/c.pdf"}}))
            item = {"date": "2026-10-20", "meeting": "Board of County Commissioners", "is_section": False,
                    "event_id": 9, "portal_url": "https://pascocofl.portal.civicclerk.com/event/9/agenda"}
            rows = [{**item, "key": "civicclerk:pascocofl:item:1", "outline": "1.", "item_number": "CAO27-2709", "title": "Veterans Day"},
                    {**item, "key": "civicclerk:pascocofl:item:3", "outline": "3.", "item_number": "TED27-0011", "title": "Bid"},
                    # the same file listed twice on one agenda: the item number picks the right one
                    {**item, "key": "civicclerk:pascocofl:item:98", "outline": "98.", "item_number": "TED27-0011", "title": "Bid again"}]
            (data / "listings" / "civicclerk-pascocofl-items.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
            r = pm.run(data)
            acts = {a["item_key"]: a for a in r["actions"]}
            self.assertEqual(set(acts), {"civicclerk:pascocofl:item:1", "civicclerk:pascocofl:item:3"})
            self.assertEqual(acts["civicclerk:pascocofl:item:3"]["minutes_url"], "https://pascocofl.api.civicclerk.com/f/1#page=1")
            self.assertEqual(acts["civicclerk:pascocofl:item:3"]["minutes_copy_url"], "https://example.org/c.pdf#page=1")
            nays = sorted(v["person"] for v in r["votes"] if v["item_key"].endswith(":3") and v["vote"] == "No")
            self.assertEqual(nays, ["Jack Mariano", "Seth Weightman"])
            self.assertTrue(all(v["body"] == "Board of County Commissioners" for v in r["votes"]))
            self.assertEqual(r["stats"]["decisions"], 2)



class OnTheSite(unittest.TestCase):
    def test_votes_reach_meeting_and_commissioner_pages(self):
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from test_region import jl, make_data
        from opencivic import meetings, people
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            data = make_data(d)
            lst = data / "listings"
            item = {"key": "civicclerk:pascocofl:item:5", "event_id": 9, "is_section": False, "date": "2025-03-04",
                    "meeting": "Board of County Commissioners", "category": "BOCC", "section": "Regular",
                    "outline": "5.", "item_number": "CA25-0005", "title": "Ordinance amending Chapter 82",
                    "portal_url": "https://pascocofl.portal.civicclerk.com/event/9/agenda", "attachments": []}
            noted = {**item, "key": "civicclerk:pascocofl:item:6", "outline": "6.", "item_number": "NI25-0001",
                     "title": "Library Advisory Board minutes"}
            (lst / "civicclerk-pascocofl-items.jsonl").write_text(jl([item, noted]))
            (lst / "pasco-minutes-actions.jsonl").write_text(jl([{
                "item_key": item["key"], "date": "2025-03-04", "code": "R5", "file_number": "CA25-0005",
                "action": "Continued", "result": "Pass", "mover": "", "seconder": "", "action_text": "x", "page": 7,
                "minutes_url": "https://pascocofl.api.civicclerk.com/f/1#page=7", "minutes_copy_url": "https://c/m.pdf#page=7"}]))
            (lst / "pasco-minutes-votes.jsonl").write_text(jl([
                {"key": f"{item['key']}:vote:{n}", "item_key": item["key"], "date": "2025-03-04",
                 "body": "Board of County Commissioners", "person": n, "vote": v, "source": "pasco-minutes"}
                for n, v in [("Jack Mariano", "No"), ("Seth Weightman", "Yes"), ("Lisa Yeager", "Yes"),
                             ("Ronald E. Oakley", "Absent"), ("Kathryn Starkey", "Yes")]]))
            meetings.write(data, d / "site")
            page = (d / "site" / "meetings" / "pasco" / "2025-03-04.html").read_text()
            self.assertIn("voted on <mark>1 decision</mark>", page)
            self.assertIn("Moved to a later meeting, 3 to 1", page)
            self.assertIn("Voted no: Jack Mariano", page)
            self.assertIn('href="https://pascocofl.api.civicclerk.com/f/1#page=7">Official minutes, page 7</a>', page)
            self.assertIn("Also on the agenda", page)
            self.assertIn("Library Advisory Board minutes", page)
            counts = people.write(data, d / "site", "https://example.org/")
            self.assertEqual(counts["pasco"], 5)
            self.assertIn("Votes read from the Pasco Clerk&#x27;s minutes",
                          (d / "site" / "commissioners" / "pasco" / "jack-mariano.html").read_text())
            oakley = (d / "site" / "commissioners" / "pasco" / "ronald-e-oakley.html").read_text()
            self.assertIn("The record covers <mark>1 decision</mark>", oakley)
            self.assertIn("Oakley never voted no and didn't vote once.", oakley)

if __name__ == "__main__":
    unittest.main()
