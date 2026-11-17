import unittest

from opencivic import discover


class Names(unittest.TestCase):
    def test_spellings(self):
        self.assertEqual(discover.norm("St. Pete Beach"), ["saintpetebeach", "stpetebeach"])
        self.assertEqual(discover.norm("Miami-Dade"), ["miamidade"])
        self.assertIn("ftlauderdale", discover.norm("Fort Lauderdale"))

    def test_known_accounts_are_tried(self):
        c = discover.candidates({"name": "Edgewater", "kind": "city"})
        self.assertIn("cityofedgewater", c["legistar"])
        c = discover.candidates({"name": "Hernando", "kind": "county"})
        self.assertIn("hernandocountyfl", c["legistar"])
        c = discover.candidates({"name": "Pasco", "kind": "county"})
        self.assertIn("pascocofl", c["civicclerk"])
        c = discover.candidates({"name": "Zephyrhills", "kind": "city"})
        self.assertIn("zephyrhillsfl", c["civicclerk"])


class Places(unittest.TestCase):
    def test_census_keeps_only_governments(self):
        text = ("STATE|STATEFP|COUNTYFP|COUNTYNAME|PLACEFP|PLACENS|PLACENAME|TYPE|CLASSFP|FUNCSTAT\n"
                "FL|12|127|Volusia County|19825|02404253|Edgewater city|INCORPORATED PLACE|C1|A\n"
                "FL|12|057|Hillsborough County|08150|02402718|Brandon CDP|CENSUS DESIGNATED PLACE|U1|S\n"
                "FL|12|011|Broward County|39550|02404878|Lauderdale-by-the-Sea town|INCORPORATED PLACE|C1|A\n")
        got = discover.parse_census(text)
        self.assertEqual([(p["name"], p["kind"], p["counties"]) for p in got],
                         [("Edgewater", "city", ["Volusia"]), ("Lauderdale-by-the-Sea", "town", ["Broward"])])

    def test_state_table(self):
        page = ("<table><tr><td>Bunnell</td><td>city</td><td>Flagler</td></tr>"
                "<tr><td>Brandon</td><td>census designated place</td><td>Hillsborough</td></tr></table>")
        self.assertEqual(discover.parse_dos(page), [{"name": "Bunnell", "kind": "city", "counties": ["Flagler"]}])

    def test_all_67_counties(self):
        self.assertEqual(len(discover.COUNTIES), 67)


if __name__ == "__main__":
    unittest.main()


class Registry(unittest.TestCase):
    PLACES = [{"name": "Marion", "kind": "county", "counties": ["Marion"]},
              {"name": "Jackson", "kind": "county", "counties": ["Jackson"]},
              {"name": "Alachua", "kind": "county", "counties": ["Alachua"]},
              {"name": "Alachua", "kind": "city", "counties": ["Alachua"]},
              {"name": "Umatilla", "kind": "city", "counties": ["Lake"]},
              {"name": "Pembroke Park", "kind": "town", "counties": ["Broward"]}]

    def test_governing_board_names(self):
        g = discover.governing_boards
        self.assertEqual(g({"Board of County Commissioners": 50, "Board of County Commissioners Planning and Zoning": 18,
                            "Planning & Zoning Commission": 27, "Public Safety Coordinating Council": 6,
                            "Land Development Regulation Commission ": 43, "Value Adjustment Board": 3,
                            "Board of County Commissioners, School Board, and Brooksville City Council Interlocal "
                            "Governmental Meeting": 2}),
                         ["Board of County Commissioners", "Board of County Commissioners Planning and Zoning"])
        self.assertEqual(g({"Town Commission": 20, "Special Commission": 24, "Workshop Commission": 18,
                            "Code Enforcement Special Magistrate": 18, "Charter Review Committee": 2, "General": 11}),
                         ["Town Commission", "Special Commission", "Workshop Commission"])
        self.assertEqual(g({"City Council": 43, "Council Briefing": 29, "Youth Advisory Council": 16,
                            "Titusville Environmental Commission": 11, "Historic District Council": 13}), ["City Council"])

    def test_namesakes_and_reassigned_accounts(self):
        rows = [
            {"platform": "legistar", "place": "Jackson", "kind": "county", "client": "jacksonco",
             "bodies_since_2025": {"County Legislature": 103}},
            {"platform": "legistar", "place": "Marion", "kind": "county", "client": "marionfl",
             "bodies_since_2025": {"Board of County Commissioners": 50, "Code Enforcement Board": 23}},
            {"platform": "civicclerk", "place": "Alachua", "kind": "county", "tenant": "alachuafl", "with_files": 147,
             "categories": {"City Commission": 46, "General": 33}},
            {"platform": "civicclerk", "place": "Umatilla", "kind": "city", "tenant": "umatillafl", "with_files": 95,
             "categories": {"General": 99}},
            {"platform": "legistar", "place": "Pembroke Park", "kind": "town", "client": "pembrokepark",
             "bodies_since_2025": {"Town Commission": 30}},
        ]
        reg, notes = discover.registry(rows, self.PLACES)
        self.assertEqual([(r["slug"], r["kind"], r["body"], r["boards"]) for r in reg], [
            ("alachua", "city", "City Commission", ["City Commission"]),
            ("marioncounty", "county", "Board of County Commissioners", ["Board of County Commissioners"])])
        text = "\n".join(notes)
        self.assertIn("Jackson County, Missouri", text)
        self.assertIn("umatillafl (Umatilla): can't tell", text)
        self.assertIn("pembrokepark (Pembroke Park): not confirmed", text)
