# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Offline tests for the Hillsborough Clerk's BOCC Master Voting Record adapter."""

import collections
import unittest
from datetime import date
from pathlib import Path

from opencivic import hillsclerk as hc

FIX = Path(__file__).parent / "fixtures" / "hillsclerk"


class Listing(unittest.TestCase):
    def test_years_from_since_plus_current(self):
        docs = hc.list_documents((FIX / "bocc-page-links.html").read_text(), 2025, today=date(2026, 11, 9))
        self.assertEqual([d["label"] for d in docs], ["2025", "current"])
        self.assertEqual(docs[0]["url"], "https://www.hillsclerk.com/documents/d/guest/bocc-vote-comparison-2025-pdf?download=true")
        self.assertEqual(docs[0]["key"], "hillsclerk:bocc-votes:2025")
        self.assertEqual(docs[1]["date"], "2026-12-31")

    def test_older_years(self):
        docs = hc.list_documents((FIX / "bocc-page-links.html").read_text(), 2014)
        self.assertEqual(len(docs), 13)  # 2014-2025 and current


class Report(unittest.TestCase):
    def test_2025_pages(self):
        rows, problems = hc.parse_report((FIX / "bocc-vote-comparison-2025-p1-2-69.txt").read_text(), "k", "u")
        self.assertEqual(problems, [])
        first = rows[0]
        self.assertEqual((first["rcs"], first["date"], first["time"], first["category_name"]),
                         (4692, "2025-01-07", "9:03AM", "Miscellaneous"))
        self.assertEqual(first["subject"], "Approval of changes to the agenda. Moved for approval.")
        self.assertEqual([v["name"] for v in first["votes"]],
                         ["Boles", "C. Miller", "Cameron Cepeda", "Cohen", "Hagan", "Myers", "Wostal"])
        self.assertEqual(first["votes"][2]["code"], "X")
        c1 = next(r for r in rows if r["item"] == "C-1")
        self.assertIn("Folio No. 018954-1064", c1["subject"])
        self.assertEqual(c1["category_name"], "Zoning")
        last = rows[-1]
        self.assertEqual((last["rcs"], last["date"]), (5261, "2025-12-17"))
        # page furniture never leaks into subjects
        for r in rows:
            for junk in ("Printed:", "Vote Comparison", "End of December", "Cepeda Y"):
                self.assertNotIn(junk, r["subject"])
        self.assertTrue(all(len(r["votes"]) == 7 for r in rows))

    def test_current_page(self):
        rows, problems = hc.parse_report((FIX / "bocc-vote-comparison-current-p1.txt").read_text())
        self.assertEqual(problems, [])
        self.assertEqual(rows[0]["rcs"], 5262)
        self.assertEqual(collections.Counter(v["code"] for v in rows[0]["votes"]), {"Y": 7})

    def test_blank_category_and_blank_cells(self):
        header = (" RCS # Subject / Action       Date          Time       Cat.          Boles      C. Miller   Cameron   Cohen\n"
                  "                                                                                             Cepeda\n")
        text = header + (" 4722                         02/05/2025     9:18AM                   Y            Y           Y       Y\n"
                         "           Approval of Changes. Moved for approval.\n"
                         " 4723                         02/05/2025    10:05AM     0                          Y           Y       N\n"
                         "           Item with a member not yet seated.\n")
        rows, problems = hc.parse_report(text)
        self.assertEqual(problems, [])
        self.assertEqual((rows[0]["rcs"], rows[0]["category"]), (4722, ""))
        self.assertEqual(rows[0]["votes"][2]["name"], "Cameron Cepeda")
        # a blank cell is skipped, not shifted: Boles has no vote, Cohen voted N
        self.assertEqual([(v["name"], v["code"]) for v in rows[1]["votes"]],
                         [("C. Miller", "Y"), ("Cameron Cepeda", "Y"), ("Cohen", "N")])

    def test_unplaceable_votes_are_problems_not_guesses(self):
        header = " RCS # Subject / Action       Date          Time       Cat.          Boles      Cohen\n"
        text = header + (" 4722                         02/05/2025     9:18AM     0             Y          Y\n"
                         "           Fine.\n"
                         " 4723                         02/05/2025     9:19AM     0             Y Y        Y\n"
                         "           Three codes, two columns.\n")
        rows, problems = hc.parse_report(text)
        self.assertEqual([r["rcs"] for r in rows], [4722])
        self.assertEqual(problems, ["RCS 4723: votes don't line up with the 2 member columns"])

    def test_legacy_layout(self):
        text = (
            "Hillsborough County Commissioners\nVote Comparison\n"
            "Starting Session                                                                Selected Members\n\n"
            "                                                                                 Crist. Victor        Higginbotham. Al\n"
            "RCS #: Document ID      Date        Time      Subject / Action       Beckner. Kevin          Hagan. Ken\n"
            "68         CHANGES       1/8/2014 9:19 AM 0                            Y            Y          X          Y\n"
            "Moved the changes. Approval of the Agenda. Moved approval.\n"
            "90       PRS140114TH     1/14/2014 10:16 A 9                           Y            N          Y          Y\n"
            "PRS 14-0114 - Example. Moved approval.\n"
            "Begin Date: 1/8/2014        Bills: ALL End Date: 1/23/2014 Vote Types: ALL\n")
        rows, problems = hc.parse_report(text)
        self.assertEqual(problems, [])
        self.assertEqual([v["name"] for v in rows[0]["votes"]], ["Kevin Beckner", "Victor Crist", "Ken Hagan", "Al Higginbotham"])
        self.assertEqual(rows[0]["subject"], "Moved the changes. Approval of the Agenda. Moved approval.")
        self.assertEqual((rows[1]["time"], rows[1]["date"], rows[1]["key"]), ("10:16AM", "2014-01-14", "hillsclerk:bocc-votes:rcs:2014-90"))
        self.assertEqual(rows[1]["subject"], "PRS 14-0114 - Example. Moved approval.")  # summary block not attached

    def test_two_column_passes_merge(self):
        a = " RCS # Subject / Action       Date          Time       Cat.          Cohen      Hagan\n"
        b = " RCS # Subject / Action       Date          Time       Cat.          White\n"
        text = (a + " 1829                         01/08/2020     9:16AM     0             Y          Y\n           Changes.\n"
                + b + " 1829                         01/08/2020     9:16AM     0             X\n           Changes.\n")
        rows, problems = hc.parse_report(text)
        self.assertEqual(problems, [])
        self.assertEqual([(v["name"], v["code"]) for v in rows[0]["votes"]], [("Cohen", "Y"), ("Hagan", "Y"), ("White", "X")])

    def test_misread_names_fixed(self):
        rows = [{"votes": [{"name": "Al Higginbotham", "code": "Y"}]} for _ in range(30)]
        rows.append({"votes": [{"name": "AI Higginbotham", "code": "Y"}]})
        hc._clean_names(rows)
        self.assertEqual({v["name"] for r in rows for v in r["votes"]}, {"Al Higginbotham"})

if __name__ == "__main__":
    unittest.main()
