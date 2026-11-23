# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""County FollowTheMoney entities from saved Legistar and Clerk records."""

import collections
import json
import tempfile
import unittest
from pathlib import Path

from opencivic import county_entities as ce
from opencivic import hillsclerk as hc

from test_region import jl, make_data

FX = Path(__file__).parent / "fixtures" / "hillsclerk" / "bocc-vote-comparison-2025-p1-2-69.txt"


class CountyEntities(unittest.TestCase):
    def test_board_of(self):
        self.assertEqual(ce.board_of("Board of County Commissioners Budget Hearing"), ce.BOCC)
        self.assertEqual(ce.board_of("BOCC Land Use"), ce.BOCC)
        self.assertEqual(ce.board_of("LDC Amendment Second Public Hearing"), ce.BOCC)
        joint = "Board of County Commissioners, School Board, and Brooksville City Council Interlocal Governmental Meeting"
        self.assertEqual(ce.board_of(joint), joint)
        self.assertEqual(ce.board_of("Planning & Zoning Commission"), "Planning & Zoning Commission")

    def test_build(self):
        with tempfile.TemporaryDirectory() as d:
            data = make_data(Path(d))
            rows, _ = hc.parse_report(FX.read_text(), "hillsclerk:bocc-votes:2025", "https://www.hillsclerk.com/r.pdf")
            (data / "listings" / "hillsclerk-bocc-votes.jsonl").write_text(jl(rows))
            counts = ce.write(data)
            ents = [json.loads(x) for x in (data / "entities" / "counties.ftm.jsonl").read_text().splitlines()]
            by = collections.defaultdict(list)
            for e in ents:
                by[e["schema"]].append(e)
            names = {e["id"]: e["properties"]["name"][0] for e in by["Person"] + by["PublicBody"]}
            self.assertIn("Hillsborough County Board of County Commissioners", names.values())
            # Legistar and Clerk records of the same commissioner are one person, one membership
            hagan = [e for e in by["Person"] if e["properties"]["name"] == ["Ken Hagan"]]
            self.assertEqual(len(hagan), 1)
            m = [e for e in by["Membership"] if e["properties"]["member"] == [hagan[0]["id"]]]
            self.assertEqual(len(m), 1)
            self.assertEqual(names[m[0]["properties"]["organization"][0]], "Hillsborough County Board of County Commissioners")
            # nobody from agenda text: every Person is someone recorded voting
            self.assertTrue(all("Recorded voting" in e["properties"]["notes"][0] for e in by["Person"]))
            self.assertEqual(len(by["Document"]), 1)  # the archived Pasco agenda
            self.assertEqual(counts["counties"]["ftm_entities"], len(ents))
            self.assertEqual(counts["volusia"]["schemata"], {"PublicBody": 2})  # Edgewater, Oak Hill; no records in this sample
            # ids are stable across runs
            self.assertEqual(ents, [json.loads(x) for x in (data / "entities" / "counties.ftm.jsonl").read_text().splitlines()])
            ce.write(data)
            self.assertEqual(ents, [json.loads(x) for x in (data / "entities" / "counties.ftm.jsonl").read_text().splitlines()])

    def test_build_skips_removed_names(self):
        # region.load returns "removed" (names per county, a dict) beside the record lists. From Nov 17 to
        # Nov 22, 2026 build() read it as records and crashed every night once any board had removed someone,
        # leaving 42 regions' entity files frozen; the step's `| tee` hid the failure.
        with tempfile.TemporaryDirectory() as d:
            data = make_data(Path(d))
            real = ce.load
            ce.load = lambda p: {**real(p), "removed": {"oakhill": {"Pat Example"}}}
            try:
                ents = ce.build(data)
            finally:
                ce.load = real
            self.assertTrue(ents)
            self.assertNotIn("Pat Example", json.dumps(ents))


if __name__ == "__main__":
    unittest.main()
