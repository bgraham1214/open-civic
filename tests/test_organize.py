import re
import unittest

from opencivic import organize
from opencivic.spotlight import topic


def item(name, t, kind="restriction", d="2026-11-01", month="2026-11"):
    return organize.Item(f"<p>{name}</p>", {"topic": (t, t), "month": (month, month)}, {"kind": kind}, d)


class Render(unittest.TestCase):
    def test_grouped_by_first_grouping_largest_first(self):
        html_ = organize.render("x", [item("a", "Animals"), item("b", "Traffic"), item("c", "Traffic"),
                                      item("d", "Other")],
                                [organize.Grouping("topic", "Topic"), organize.Grouping("month", "Month", "desc")],
                                [organize.Filter("kind", "Show", [("", "Everything"), ("restriction", "Restrictions")])])
        groups = re.findall(r'data-group="([^"]+)"', html_)
        self.assertEqual(groups, ["Traffic", "Animals", "Other"])  # "Other" always last
        self.assertIn("4 items in 3 groups", html_)
        self.assertIn('<form class="org-bar"', html_)
        self.assertIn(" hidden ", html_)  # the dropdowns appear only with the script
        self.assertIn('data-f-kind="restriction"', html_)
        self.assertNotIn("data-s-topic", html_)  # sort value written only when it differs from the label

    def test_script_knows_every_filter_form(self):
        for form in ("min:", "after:", "span:"):
            self.assertIn(f"'{form}'", organize.JS)


class Topics(unittest.TestCase):
    def t(self, title):
        return topic({"title": title})

    def test_place_names_are_not_beaches_or_parks(self):
        self.assertNotEqual(self.t("AN ORDINANCE OF THE CITY COMMISSION OF THE CITY OF DANIA BEACH, FLORIDA, AMENDING CHAPTER 28"), "public")
        self.assertNotEqual(self.t("An Ordinance Of The Town Council Of The Town Of Palm Beach, Palm Beach County, Florida"), "public")
        self.assertEqual(self.t("Ordinance prohibiting camping on public property"), "public")

    def test_real_wordings(self):
        self.assertEqual(self.t("Prohibit Smoking, Vaping at County Parks, Public Beaches"), "substances")
        self.assertEqual(self.t("46th Avenue Parking Prohibition"), "traffic")
        self.assertEqual(self.t("Lien Reduction - 102 N. 19th Street - Kirat LLC"), "liens")
        self.assertEqual(self.t("Ordinance No. 2026-032 Final Data Centers Moratorium"), "tech")
        self.assertEqual(self.t("Request approval of waiver of fees for the Friends of Istokpoga Lake Association, Inc."), "events")
        self.assertEqual(self.t("Burn Ban Resolution"), "emergency")
        self.assertEqual(self.t("Adopt Ordinance 1711 on first reading - Regulating temporary signs"), "signs")
        self.assertEqual(self.t("authorize the Chair to sign a Charitable Organization Impact Fee Deferral"), "money")
        self.assertEqual(self.t("Approve a purchase order for Rectangular Rapid-Flashing Beacon (RRFB) systems"), "traffic")
        self.assertEqual(self.t("Consideration of Request by Fisher Link Development, LLC, to Forgive Fines Ordered by Special Master"), "liens")


class Headlines(unittest.TestCase):
    def test_boilerplate_dropped_in_compact_form(self):
        from opencivic.people import plain
        it = {"title": "AN ORDINANCE OF THE CITY COMMISSION OF THE CITY OF OPA-LOCKA, FLORIDA, AMENDING CHAPTER 13, "
                       "ARTICLE VIII, ENTITLED STREET AND MOBILE VENDORS " + "X " * 100, "county": "opalocka"}
        h = re.search(r'<p class="headline">([^<]+)</p>', plain(it, 0, None, compact='<p class="meta">m</p>')).group(1)
        self.assertTrue(h.startswith("Ordinance: AMENDING CHAPTER 13"), h)
        self.assertLessEqual(len(h), 151)
        self.assertIn("Details and official wording", plain(it, 0, None, compact=""))
        self.assertNotIn("Details and official wording", plain(it, 0, None))  # meeting pages unchanged


class MembersCache(unittest.TestCase):
    def test_a_reused_address_is_not_a_hit(self):
        from opencivic import region
        a = [{"county": "x", "person": "Jane Roe"}]
        b = [{"county": "x", "person": "John Doe"}]
        region._MEMBERS[id(b)] = (a, region._members_of(a))  # what a freed list's address left behind
        self.assertEqual(region._members_of(b), {"x": {"john doe"}})


if __name__ == "__main__":
    unittest.main()
