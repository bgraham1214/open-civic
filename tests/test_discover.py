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
