# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Oak Hill City Commission votes read from its minutes (opencivic/oakhillminutes.py, Nov 15, 2026).
The wording below is copied from the real minutes (OCR text), one sample per clerk's style."""

import gzip
import json
import tempfile
import unittest
from pathlib import Path

from opencivic import oakhillminutes as oh
from opencivic import people, region, site

M = {"taylor": "Ricky Taylor", "catigano": "Joe Catigano", "werning": "Carrie Werning",
     "hyatt": "Linda Hyatt", "drollinger": "Mark Drollinger"}
ROLL = ("A. OPENING\n4. Roll Call\nPresent Mayor Taylor, Vice Mayor Catigano, Commissioner Drollinger, Commissioner Hyatt, "
        "Commissioner\nWerning, City Attorney Michael Kelly, City Administrator Janet Shira\nB. AGENDA MODIFICATIONS\nNone\n")


def votes(d):
    return {k: v for k, v in d["votes"].items()}


class Members(unittest.TestCase):
    def test_from_the_minutes(self):
        texts = ["Mayor Ricky Taylor, Vice Mayor Joe Catigano, Commissioner Linda Hyatt, Commissioner Carrie Werning, "
                 "Commissioner Mark Drollinger. Commissioner Werning moved. Mayor Taylor's report. City Commission."] * 3
        self.assertEqual(oh.members_of(texts), M)


class RollCall(unittest.TestCase):
    def test_wordings(self):
        rc = lambda t: oh.roll_call(t, M)
        self.assertEqual(rc(ROLL), (set(M), set()))
        # Jul 13, 2026: "Absent: None" right after the last name
        p, a = rc("4. Roll Call\nPresent: Mayor Ricky Taylor, Vice Mayor Joseph Catigano,\nCommissioner Linda Hyatt, "
                  "Commissioner Carrie Werning, Commissioner Mark\nDrollinger Absent: None\nB. AGENDA MODIFICATIONS\n")
        self.assertEqual((p, a), (set(M), set()))
        # Apr 28, 2025 (all caps), Hyatt excused
        p, a = rc("Roll Call\nPresent:\nMAYOR RICKY TAYLOR\nVICE MAYOR JOE CATIGANO\nCOMMISSIONER CARRIE WERNING\n"
                  "COMMISSIONER MARK DROLLINGER\nAbsent:\nEXCUSED COMMISSIONER LINDA HYATT\nStaff Present\n"
                  "ATTORNEY MIKE KELLY\nB. AGENDA MODIFICATIONS\n")
        self.assertEqual((p, a), (set(M) - {"hyatt"}, {"hyatt"}))
        # Aug 11, 2025 budget workshop
        p, a = rc("Roll Call\nVice Mayor Catigano — Present\nCommissioner Drollinger — Absent\nCommissioner Werning — Present\n"
                  "Mayor Ricky Taylor — Present\nCommissioner Hyatt — Present\nB. AGENDA MODIFICATIONS\n")
        self.assertEqual(a, {"drollinger"})
        # Jan 12, 2026
        p, _ = rc('4. Roll Call\nCity Manager John Barkley conducted roll call. Commissioner Hyatt responded "Here." Vice\n'
                  'Mayor Catigano responded "Here." Commissioner Drollinger responded "Here." Mayor\nTaylor responded "Here." '
                  'Commissioner Werning responded "Here." All commissioners\nwere present.\nB. AGENDA MODIFICATIONS\n')
        self.assertEqual(p, set(M))
        # names nobody: the caller fills them in from the last full roll call
        self.assertEqual(rc("Roll Call\nRoll call affirmed all commissioners were present, establishing quorum.\n"
                            "B. AGENDA MODIFICATIONS\n"), (set(M), set()))


class Formats(unittest.TestCase):
    def one(self, body, roll=ROLL):
        ds, probs, _ = oh.parse([roll + body], M)
        return ds, probs

    def test_motion_second_action(self):  # Jan 13, 2025
        ds, _ = self.one("F. CITY ADMINISTRATOR\n3. Stormwater Fee Proposal - Mead & Hunt\nMayor Taylor clarified that the "
                         "Commission is voting on the study right now.\nMotion to accept Vice Mayor Catigano Second "
                         "Commissioner Hyatt Action Passed Unanimously\n")
        d = ds[0]
        self.assertEqual((d["number"], d["title"]), ("F.3.", "Stormwater Fee Proposal - Mead & Hunt"))
        self.assertEqual((d["motion"], d["mover"], d["seconder"]), ("To accept", "catigano", "hyatt"))
        self.assertEqual(set(votes(d).values()), {"Yes"})

    def test_each_members_vote_listed_after(self):  # Mar 10, 2025
        ds, _ = self.one("B. AGENDA MODIFICATIONS\nVice Mayor Catigano: Made a motion to table G2 & H1 until we hire a city "
                         "administrator.\nCommissioner Drollinger: Seconded\nAction: Passed 4-1\nMayor Taylor: Yes\nVice Mayor "
                         "Catigano: Yes\nCommissioner Hyatt: Yes\nCommissioner Werning: No\nCommissioner Drollinger: Yes\n"
                         "C. PRESENTATIONS / BRIEF ANNOUNCEMENTS\n")
        d = ds[0]
        self.assertEqual(votes(d)["werning"], "No")
        self.assertEqual(sum(v == "Yes" for v in votes(d).values()), 4)
        self.assertEqual(d["action"], "table")
        self.assertEqual(d["mover"], "catigano")

    def test_all_caps_list_before_the_outcome(self):  # Apr 28, 2025, across a page break
        roll = ("Roll Call\nPresent:\nMAYOR RICKY TAYLOR\nVICE MAYOR JOE CATIGANO\nCOMMISSIONER CARRIE WERNING\n"
                "COMMISSIONER MARK DROLLINGER\nAbsent:\nEXCUSED COMMISSIONER LINDA HYATT\nB. AGENDA MODIFICATIONS\n")
        ds, probs, _ = oh.parse([roll + "E. CONSENT AGENDA\nACTION: MOTION MADE BY COMMISSIONER WERNING FOR UP TO\n$200 FOR "
                                 "THE FLAGS.\nSECONDED- BY COMMISSIONER DROLLINGER\nMAYOR TAYLOR: YES\nVICE MAYOR CATIGANO: "
                                 "YES\nCOMMISSIONER WERNING: YES\nCOMMISSIONER DROLLINGER: YES\n",
                                 "e COMMISSIONER HYATT: ABSENT\ne MOTION PASSED 4-0\n"], M)
        self.assertEqual(probs, [])
        d = ds[0]
        self.assertEqual(d["motion"], "Up to $200 for the flags")
        self.assertEqual(votes(d)["hyatt"], "Absent")
        self.assertEqual(d["page"], 1)

    def test_parenthesized_list(self):  # Sep 8, 2025
        ds, _ = self.one("Motion to approve the tentative budget for fiscal year 2025-2026.\nMotion by: Commissioner Hyatt "
                         "Second by: Commissioner Drollinger Vote: Passed 4-1 (Hyatt-Yes, Catigano-Yes, Drollinger-Yes, "
                         "Taylor-Yes, Werning-No)\n")
        self.assertEqual(votes(ds[0])["werning"], "No")
        self.assertEqual(ds[0]["motion"], "To approve the tentative budget for fiscal year 2025-2026")

    def test_dissenters_named(self):  # May 11, 2026
        ds, _ = self.one("H. NEW BUSINESS\n1. Application for Variance: 508 Cheyenne Drive\nMotion to approve the variance "
                         "was made by Commissioner Werning and seconded by Commissioner Hyatt. The motion carried 3-2, with "
                         "Mayor Taylor and Commissioner Drollinger voting no.\n")
        d = ds[0]
        self.assertEqual({k for k, v in votes(d).items() if v == "No"}, {"taylor", "drollinger"})
        self.assertEqual((d["motion"], d["mover"], d["seconder"]), ("To approve the variance", "werning", "hyatt"))

    def test_was_made_by_and_passed(self):  # Oct 27, 2025
        ds, _ = self.one("G. NEW BUSINESS\n1. Equipment Purchase\nA motion to purchase a utility trailer from Wheel-A-Way at "
                         "$4,013.78 (including tax, tag and registration) was made by Commissioner Werning, seconded by "
                         "Commissioner Drollinger, and passed 5-0.\n")
        self.assertEqual(ds[0]["motion"], "To purchase a utility trailer from Wheel-A-Way at $4,013.78 (including tax, tag and registration)")
        self.assertEqual(ds[0]["tally"], "5-0")

    def test_quoted_motion(self):  # Jan 12, 2026
        ds, _ = self.one('Commissioner Werning immediately spoke up: "I\'d like to make a motion that we move G3 to the '
                         'beginning of the meeting." Mayor Taylor called for a second, which was received. City Manager John '
                         'Barkley conducted a roll call vote: Commissioner Werning voted "Yes," Mayor Taylor voted "Yes," '
                         'Commissioner Drollinger voted "Yes," Vice Mayor Catigano voted "Yes," and Commissioner Hyatt voted '
                         '"Yes." The motion passed unanimously.\n')
        self.assertEqual(ds[0]["motion"], "We move G3 to the beginning of the meeting")
        self.assertEqual(set(votes(ds[0]).values()), {"Yes"})

    def test_not_accept_is_a_denial(self):  # Sep 22, 2025
        ds, _ = self.one("An ordinance of the City of Oak Hill, Volusia County, Florida extending for a period of one year the\n"
                         "moratorium enacted by ordinance 2024-10; providing for an effective date.\nPublic comment followed.\n"
                         "Motion: Commissioner Carrie Werning moved to not accept Ordinance 2025-01 at this point in time.\n"
                         "Commissioner Linda Hyatt seconded the motion. The motion passed 4-1 with Vice Mayor Joe Catigano "
                         "voting no.\n")
        d = ds[0]
        self.assertEqual(d["action"], "deny")
        self.assertTrue(d["caption"].lower().endswith("providing for an effective date."))
        self.assertEqual(votes(d)["catigano"], "No")

    def test_caption_stops_at_its_last_words(self):  # Jan 13, 2025: a resident spoke right after it
        ds, _ = self.one("H. OLD BUSINESS - PUBLIC HEARING\n1. Ordinance regarding sleeping/camping on Public Property\n"
                         "AN ORDINANCE OF THE CITY OF OAK HILL, VOLUSIA COUNTY, FLORIDA CREATING SECTION 28-27\n"
                         "PROHIBITING SLEEPING ON PUBLIC PROPERTY; PROVIDING FOR AN\nEFFECTIVE DATE.\n"
                         "Jane Resident 123 River Road asked whether this covers campers.\n"
                         "Motion to approve Commissioner Hyatt Second Commissioner Werning Action Passed Unanimously\n")
        self.assertTrue(ds[0]["caption"].endswith("EFFECTIVE DATE."))
        self.assertNotIn("Resident", ds[0]["caption"])

    def test_public_comment_heading_is_never_a_title(self):  # Apr 28, 2025: "2. (a resident's name): SPOKE …"
        ds, _ = self.one("D. CITIZEN PARTICIPATION / PUBLIC INPUT\n2. JANE RESIDENT: SPOKE IN REGARD TO MEMORIAL DAY\n"
                         "Motion to accept Commissioner Werning Second Commissioner Hyatt Action Passed Unanimously\n")
        self.assertEqual(ds[0]["title"], "")

    def test_adjourn_is_not_a_decision(self):
        ds, _ = self.one("M. ADJOURNMENT\nMotion to adjourn Commissioner Werning Second Commissioner Hyatt Action Passed "
                         "Unanimously\n")
        self.assertEqual(ds, [])


class NeverGuess(unittest.TestCase):
    def test_split_vote_without_names(self):  # Feb 23, 2026: "Motion carried 4-1."
        ds, probs, _ = oh.parse([ROLL + "Motion to approve payment of Invoice No. 46 was made by Commissioner Werning. "
                                 "Motion carried 4-1.\n"], M)
        self.assertEqual(ds, [])
        self.assertIn("doesn't say who", probs[0]["problem"])

    def test_count_must_match_the_roll_call(self):
        roll = ROLL.replace("Commissioner Drollinger, ", "").replace("Present", "Present") + ""
        roll = ("4. Roll Call\nPresent: Mayor Taylor, Vice Mayor Catigano, Commissioner Hyatt, Commissioner Werning\n"
                "Absent: Commissioner Drollinger\nB. AGENDA MODIFICATIONS\n")
        ds, probs, _ = oh.parse([roll + "Motion to renew the lease was made by Commissioner Werning and seconded by "
                                 "Commissioner Hyatt. The motion carried 5-0.\n"], M)
        self.assertEqual(ds, [])
        self.assertIn("roll call shows 4 present", probs[0]["problem"])

    def test_dissent_count_must_match(self):
        ds, probs, _ = oh.parse([ROLL + "Motion to approve the site plan was made by Commissioner Werning. The motion "
                                 "carried 3-2, with Mayor Taylor voting no.\n"], M)
        self.assertEqual(ds, [])
        self.assertTrue(probs)

    def test_vote_list_must_match_the_count(self):
        ds, probs, _ = oh.parse([ROLL + "Commissioner Werning: Made a motion to approve the shed.\nCommissioner Hyatt: "
                                 "Seconded\nAction: Motion passes 5-0\nMayor Taylor: Yes\nVice Mayor Catigano: Yes\n"
                                 "Commissioner Werning: No\nCommissioner Hyatt: Yes\nCommissioner Drollinger: Yes\n"], M)
        self.assertEqual(ds, [])
        self.assertIn("doesn't match", probs[0]["problem"])

    def test_no_roll_call(self):
        ds, probs, _ = oh.parse(["Motion to accept Commissioner Werning Second Commissioner Hyatt Action Passed Unanimously\n"], M)
        self.assertEqual(ds, [])
        self.assertIn("roll call", probs[0]["problem"])


def make_data(d: Path) -> Path:
    """Two meetings' minutes, plus the July 2026 case: the city posted the Jul 13 minutes again as the
    Jul 20 budget workshop's."""
    data = d / "data"
    (data / "listings").mkdir(parents=True)
    (data / "text").mkdir()
    names = ("Mayor Ricky Taylor, Vice Mayor Joe Catigano, Commissioner Linda Hyatt, Commissioner Carrie Werning, "
             "Commissioner Mark Drollinger")
    docs = {
        "a1": ("2026-07-13", "City Commission", "07-13-2026 Commission Meeting Minutes",
               f"7-13-2026 Commission Meeting - AMENDED\nMeeting Minutes\n4. Roll Call\nPresent: {names}\nAbsent: None\n"
               "B. AGENDA MODIFICATIONS\nH. NEW BUSINESS\n4. Committee Appointments\nMotion to appoint Doug Gibson to PLDRC "
               "Seat 5 was made by Commissioner Carrie Werning and seconded by Commissioner Linda Hyatt. The motion carried "
               "3-2, with Vice Mayor Catigano and Commissioner Drollinger voting no.\n"),
        "a2": ("2026-07-20", "City Commission Budget Workshop", "07-20-2026 Commission Meeting Minutes", None),
        "a3": ("2026-06-08", "City Commission", "6-8-2026 Commission Meeting Minutes",
               f"June 8, 2026\nMinutes\n4. Roll Call\nPresent: {names}\nAbsent: None\nB. AGENDA MODIFICATIONS\n"
               "E. CONSENT AGENDA\nMotion to approve the minutes was made by Commissioner Werning and seconded by "
               "Commissioner Hyatt. The motion carried 5-0.\n"),
        "a4": ("2026-06-08", "City Commission", "06-08-2026 Commission Minutes Amended",
               f"June 8, 2026\nAmended Minutes\n4. Roll Call\nPresent: {names}\nAbsent: None\nB. AGENDA MODIFICATIONS\n"
               "E. CONSENT AGENDA\nMotion to approve the May 11 minutes as corrected was made by Commissioner Werning and "
               "seconded by Commissioner Hyatt. The motion carried 5-0.\nG. OLD BUSINESS\n1. Speed limit\nMotion to approve "
               "Resolution 2026-02 lowering the speed limit was made by Commissioner Drollinger and seconded by Commissioner "
               "Hyatt. The motion carried 5-0.\n"),
    }
    docs["a2"] = docs["a2"][:3] + (docs["a1"][3],)
    state = {}
    for i, (fid, (dt, body, title, text)) in enumerate(docs.items()):
        sha = f"{i:064x}"
        key = f"weblinks:oakhillfl:{fid}"
        state[key] = {"key": key, "source": "weblinks", "kind": "Minutes", "date": dt, "body": body, "title": title,
                      "url": f"https://cdn.example/{fid}.pdf", "copy_url": f"https://c/{sha}.pdf", "sha256": sha,
                      "listed": True, "first_seen": "2026-11-12T00:00:00Z"}
        (data / "text" / f"{sha}.json.gz").write_bytes(gzip.compress(json.dumps({"pages": [text]}).encode()))
    agenda = {"key": "weblinks:oakhillfl:ag1", "source": "weblinks", "kind": "Agenda", "date": "2026-07-20",
              "body": "City Commission Budget Workshop", "title": "7-20-2026 Budget Workshop Agenda",
              "url": "https://cdn.example/ag1.pdf", "copy_url": "https://c/ag.pdf", "sha256": "f" * 64, "listed": True}
    state[agenda["key"]] = agenda
    (data / "state.json").write_text(json.dumps(state))
    (data / "manifest.jsonl").write_text("")
    return data


class Run(unittest.TestCase):
    def test_documents_and_pages(self):
        with tempfile.TemporaryDirectory() as d:
            data = make_data(Path(d))
            r = oh.run(data)
            docs = {x["key"].rsplit(":", 1)[1]: x for x in r["docs"]}
            # misfiled: its own date says Jul 13
            self.assertFalse(docs["a2"]["used"])
            self.assertEqual(docs["a2"]["stated_date"], "2026-07-13")
            # amended minutes win
            self.assertTrue(docs["a4"]["used"])
            self.assertFalse(docs["a3"]["used"])
            self.assertEqual(r["stats"]["decisions"], 3)
            self.assertEqual({x["date"] for x in r["actions"]}, {"2026-06-08", "2026-07-13"})
            self.assertEqual(r["actions"][-1]["minutes_url"], "https://cdn.example/a1.pdf#page=1")
            oh.main(["--data-dir", str(data)])

            dd = region.load(data)
            jul20 = next(m for m in dd["meetings"] if m["county"] == "oakhill" and m["date"] == "2026-07-20")
            self.assertEqual(jul20["minutes_url"], "")  # the file isn't this meeting's minutes
            self.assertIn("minutes of July 13, 2026", jul20["comment"])

            rec = people.all_votes(data)["oakhill"]
            self.assertEqual(len(rec["items"]), 3)
            out = Path(d) / "site"
            site.configure("https://example.github.io/open-civic/", "2026-11-15T20:00:00Z")
            site.write_assets(out)
            self.assertEqual(people.write(data, out, "https://example.github.io/open-civic/")["oakhill"], 5)
            idx = (out / "commissioners" / "oakhill.html").read_text()
            self.assertIn("Ricky Taylor", idx)
            self.assertIn("Mayor", idx)
            werning = (out / "commissioners" / "oakhill" / "carrie-werning.html").read_text()
            self.assertIn("City Commissioner", werning)
            self.assertIn("Commission minutes, page 1", werning)


if __name__ == "__main__":
    unittest.main()
