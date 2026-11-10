# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Temple Terrace City Council decisions for the plain-language pages (wording copied from the real minutes)."""

import json
import tempfile
import unittest
from pathlib import Path

from opencivic import council as c

MEMBERS = ["Andy Ross", "James Chambers", "Alison Fernandez", "Erik Kravets", "Gil Schisler"]


def jl(rows):
    return "".join(json.dumps(r) + "\n" for r in rows)


class Wording(unittest.TestCase):
    def test_motion_clause(self):
        t = ("Discussion followed. motion by Council Member Kravets, seconded by Council Member Fernandez, Amend "
             "Ordinance 1586, remove modification of 12-354 (Prem Plat Review). Mayor Ross said he read the statute. "
             "Vote on the motion being: Council Members Fernandez and Kravets voting “aye,” Mayor Ross voting “nay.”")
        self.assertEqual(c.motion_clause(t), "Amend Ordinance 1586, remove modification of 12-354 (Prem Plat Review)")
        t = ("motion by Council Member Chambers, seconded by Council Member Fernandez, RESOLUTION 153-25(m), APPROVED "
             "to allow staff to have Friday, December 26, 2025, as a day off. Vote on the motion being: …")
        self.assertEqual(c.motion_clause(t), "Approved to allow staff to have Friday, December 26, 2025, as a day off")
        t = ("motion by Council Member Fernandez, seconded by Council Member Chambers. RESOLUTION 03- 26, ADOPTED and "
             "Approved the Final Site Plan SPR-25-10. Vote on the motion being: …")
        self.assertEqual(c.motion_clause(t), "Adopted and Approved the Final Site Plan SPR-25-10")
        self.assertEqual(c.motion_clause("Council Member Kravets asked a question. Vote on the motion being: …"), "")

    def test_consent_items(self):
        self.assertEqual(c.consent_items("RESOLUTION, 11A and 11C— 11E were ADOPTED by consent, as follows", "11."),
                         ["11.A.", "11.C.", "11.D.", "11.E."])
        self.assertEqual(c.consent_items("RESOLUTION, 11.A.-11.D., were ADOPTED by consent", "11."),
                         ["11.A.", "11.B.", "11.C.", "11.D."])
        self.assertEqual(c.consent_items("RESOLUTION, 11.A.-11.C., was ADOPTED by consent, as follows, noting that "
                                         "item 11.A. was pulled from the Consent Agenda for discussion.", "11."),
                         ["11.B.", "11.C."])
        self.assertEqual(c.consent_items("the Consent Agenda was approved", "11."), [])

    def test_actions(self):
        self.assertEqual(c.action_of("Postponed the selection of Vice-Mayor to the February 3, 2026 Council Meeting", "passed"), "Postponed")
        self.assertEqual(c.action_of("Approved to Reschedule item 13.A. Consideration of a Fence Waiver Request to a later meeting", "passed"), "Postponed")
        # adopting a resolution that postpones a program is still an adoption
        self.assertEqual(c.action_of("Adopted the Resolution, approving to postpone the implementation of the camera policy", "passed"), "Adopted")
        self.assertEqual(c.action_of("Amend Ordinance 1586", "failed"), "Failed")

    def test_misfiled_motion_moves_to_its_item(self):
        items = {k: {"key": k, "date": "2026-01-06", "number": n, "title": t} for k, n, t in [
            ("b", "12.B.", "Resolution Approving Final Site Plan SPR-25-10 for Culver's"),
            ("e", "12.E.", "Second Reading of Ordinance 1588 Amending the Future Land Use"),
            ("x", "14.A.", "Development Proposals for 8901 N. 56th Street")]}
        mk = lambda key, text: {"key": key, "date": "2026-01-06", "agenda_item_key": "b", "item": "12.B.",  # noqa: E731
                                "text": "motion by Council Member Fernandez, seconded by Council Member Chambers, " + text
                                        + " Vote on the motion being: …"}
        out = c.reassign([mk("1", "Approved the Final Site Plan SPR-25-10."), mk("2", "Approved Ordinance 1588 on second reading."),
                          mk("3", "Approved to direct staff to study parking.")], items)
        self.assertEqual([v["agenda_item_key"] for v in out], ["b", "e", "b"])
        self.assertEqual(out[1]["reassigned_from"], "b")
        self.assertEqual(c.identifiers("Proposals for 8901 N. 56th Street"), {"8901 n 56th st"})

    def test_caps_lock_title(self):
        self.assertEqual(c._case("rESOLUTION aPPROVING A LETTER"), "Resolution Approving a letter")


class Votes(unittest.TestCase):
    def test_council_votes(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            (data / "entities").mkdir()
            (data / "listings").mkdir()
            (data / "entities" / "officials.jsonl").write_text(jl(
                [{"name": n, "group": "elected", "roles": ["Mayor"] if n == "Andy Ross" else ["Council Member"],
                  "first_seen": "2025-11-04", "last_seen": "2026-10-20",
                  "absent_dates": ["2025-12-16"] if n == "Gil Schisler" else []} for n in MEMBERS]
                + [{"name": "Carlos Baia", "group": "City Manager", "roles": ["City Manager"]}]))
            item = {"date": "2025-12-16", "meeting": "City Council Meeting", "is_section": False,
                    "portal_url": "https://templeterracefl.portal.civicclerk.com/event/30/agenda", "section": "Consent Agenda"}
            (data / "listings" / "civicclerk-items.jsonl").write_text(jl([
                {**item, "key": "i:11A", "outline": "11.A.", "title": "Resolution Revising Article V"},
                {**item, "key": "i:11B", "outline": "11.B.", "title": "Resolution Awarding Asphalt Paving"},
                {**item, "key": "i:12C", "outline": "12.C.", "title": "Ordinance 1586 on Second Reading", "section": "Ordinances"},
                {**item, "key": "i:sec", "outline": "11.", "title": "Consent Agenda", "is_section": True},
                {**item, "key": "i:cra", "outline": "1.", "title": "CRA item", "meeting": "Community Redevelopment Agency"}]))
            (data / "state.json").write_text(json.dumps({"civicplus_archive:www.templeterrace.gov:9100": {
                "url": "https://www.templeterrace.gov/Archive.aspx?ADID=9100", "copy_url": "https://c/m.pdf", "listed": False}}))
            base = {"date": "2025-12-16", "minutes_page": 7, "minutes_link": "https://c/m.pdf#page=7",
                    "mover": "Erik Kravets", "seconder": "Alison Fernandez", "record_number": ""}
            ayes4 = ["Andy Ross", "James Chambers", "Alison Fernandez", "Erik Kravets"]
            (data / "entities" / "votes.jsonl").write_text(jl([
                {**base, "key": "civicplus_archive:www.templeterrace.gov:9100:vote:1", "item": "11.B.", "consent_section": "11.",
                 "agenda_item_key": "", "ayes": ayes4, "nays": [], "result": "passed",
                 "text": "motion by Council Member Chambers, seconded by Vice Mayor Schisler and unanimously carried, "
                         "RESOLUTION, 11.A.-11.B., were ADOPTED by consent, as follows: Vote on the motion being: …"},
                {**base, "key": "civicplus_archive:www.templeterrace.gov:9100:vote:2", "item": "12.C.", "consent_section": "",
                 "agenda_item_key": "i:12C", "ayes": ["Alison Fernandez", "Erik Kravets"],
                 "nays": ["Andy Ross", "James Chambers"], "result": "failed",
                 "text": "motion by Council Member Kravets, seconded by Council Member Fernandez, Amend Ordinance 1586, "
                         "remove modification of 12-354. Vote on the motion being: …"},
                {**base, "key": "civicplus_archive:www.templeterrace.gov:9100:vote:3", "item": "12.C.", "consent_section": "",
                 "agenda_item_key": "i:12C", "ayes": ["Andy Ross", "James Chambers", "Erik Kravets"],
                 "nays": ["Alison Fernandez"], "result": "passed",
                 "text": "motion by Council Member Chambers, seconded by Mayor Ross, Approved Ordinance 1586 on Second "
                         "Reading. Vote on the motion being: …"},
                {**base, "key": "civicplus_archive:www.templeterrace.gov:9100:vote:4", "item": "", "consent_section": "",
                 "agenda_item_key": "", "ayes": ayes4, "nays": [], "result": "passed",
                 "text": "Council discussed it at length. Vote on the motion being: …"}]))
            r = c.council_votes(data)
            items, votes = r["items"], r["votes"]
            # consent: both named items get the consent vote
            self.assertEqual(items["i:11A"]["action"], "Approved (consent agenda)")
            self.assertEqual(items["i:11B"]["agenda_key"], "i:11B")
            self.assertEqual({v["person"]: v["vote"] for v in votes["i:11A"]}["Gil Schisler"], "Absent")
            self.assertEqual(len(votes["i:11A"]), 5)          # the City Manager is never counted
            # two motions on one item: two decisions, each with its motion
            twelve = [i for i in items.values() if i.get("agenda_key") == "i:12C"]
            self.assertEqual(sorted(i["action"] for i in twelve), ["Approved", "Failed"])
            self.assertTrue(all(i["motion"] for i in twelve))
            # a motion we can't word still shows, pointing to the minutes page
            orphan = items["civicplus_archive:www.templeterrace.gov:9100:vote:4"]
            self.assertEqual(orphan["title"], "A motion made during the meeting (its wording is in the minutes, page 7)")
            # the city took its copy down: link ours only
            self.assertTrue(orphan["minutes_removed"])
            self.assertEqual(orphan["minutes_url"], "")
            self.assertEqual(orphan["minutes_copy_url"], "https://c/m.pdf#page=7")
            self.assertNotIn("i:cra", items)

            # the pages
            from opencivic import meetings, people
            out = data / "site"
            self.assertEqual(meetings.write(data, out)["templeterrace"], 1)
            page = (out / "meetings" / "templeterrace" / "2025-12-16.html").read_text()
            self.assertIn("Temple Terrace City Council meeting", page)
            self.assertIn('<p class="headline">New or changed city law (ordinance)</p><p class="subject">Amend Ordinance 1586', page)
            self.assertIn("<strong>Agenda item 12.C.</strong> Ordinance 1586 on Second Reading", page)
            self.assertIn("Failed 2 to 2", page)
            self.assertIn("our archived copy; the city has taken its own copy down", page)
            self.assertIn('href="../../council/templeterrace.html">How each council member voted', page)
            self.assertIn('href="../../templeterrace.html">Temple Terrace</a>', page)
            self.assertEqual(people.write(data, out)["templeterrace"], 5)
            ross = (out / "council" / "templeterrace" / "andy-ross.html").read_text()
            self.assertIn('<p class="role">Mayor, Temple Terrace City Council</p>', ross)
            self.assertIn("In Temple Terrace the mayor votes too", ross)
            self.assertEqual(ross.count("our archived copy; the city has taken its own copy down"), 6)
            self.assertNotIn("Decisions that mention", ross)
            idx = (out / "council" / "templeterrace.html").read_text()
            self.assertIn("On the Council now", idx)


if __name__ == "__main__":
    unittest.main()
