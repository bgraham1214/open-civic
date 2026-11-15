# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Southeast Volusia (added Nov 12, 2026): Oak Hill's linked documents, Edgewater's Legistar council
records, and New Smyrna Beach, whose records site asks automated tools not to collect it."""

import json
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from opencivic import build, legistar as lg, manifest, meetings, people, region, site, weblinks
from opencivic.fetch import FixtureFetcher
from opencivic.jurisdictions import JURISDICTIONS, REGIONS

FIX = Path(__file__).parent / "fixtures"
LG = FIX / "legistar"
SITE = "https://example.github.io/open-civic/"
OAK = ["https://www.oakhillfl.gov/archives/city-commission-archive",
       "https://www.oakhillfl.gov/archives/agenda-archives-by-year/2025-archive"]


def jl(rows):
    return "".join(json.dumps(r) + "\n" for r in rows)


def oak_docs():
    f = FixtureFetcher({OAK[0]: FIX / "weblinks" / "oakhill-city-commission-archive.html",
                        OAK[1]: FIX / "weblinks" / "oakhill-2025-archive.html"})
    return weblinks.crawl("oakhillfl", f, OAK, "2025-01-01")


def edgewater(lst: Path) -> None:
    ev = lg.parse_event("cityofedgewater", json.loads((LG / "cityofedgewater-event-2640.json").read_text()))
    raw = json.loads((LG / "cityofedgewater-event-2640-items.json").read_text())
    pages = {lg.items_url("cityofedgewater", 2640): LG / "cityofedgewater-event-2640-items.json"}
    for r in raw:
        if lg.wants_votes(r):
            v = LG / f"cityofedgewater-item-{r['EventItemId']}-votes.json"
            pages[lg.votes_url("cityofedgewater", r["EventItemId"])] = v if v.exists() else LG / "empty-votes.json"
    items, votes, _ = lg.crawl_items("cityofedgewater", [ev], FixtureFetcher(pages), today=date(2026, 11, 12))
    officers = [lg.parse_officer("cityofedgewater", r) for r in json.loads((LG / "cityofedgewater-officerecords.json").read_text())]
    (lst / "legistar-cityofedgewater-events.jsonl").write_text(jl([ev]))
    (lst / "legistar-cityofedgewater-items.jsonl").write_text(jl(items))
    (lst / "legistar-cityofedgewater-votes.jsonl").write_text(jl(votes))
    (lst / "legistar-cityofedgewater-officers.jsonl").write_text(jl(officers))


def make_data(d: Path) -> Path:
    data = d / "data"
    (data / "listings").mkdir(parents=True)
    (data / "text").mkdir()
    edgewater(data / "listings")
    state = {}
    for i, x in enumerate(oak_docs()):
        state[x["key"]] = {**x, "source": "weblinks", "sha256": f"{i:064x}", "bytes": 10,
                           "copy_url": f"https://c/{i:064x}.pdf", "first_seen": "2026-11-12T00:00:00Z", "listed": True}
    (data / "state.json").write_text(json.dumps(state))
    (data / "manifest.jsonl").write_text("")
    return data


class OakHill(unittest.TestCase):
    def test_listing(self):
        docs = oak_docs()
        self.assertEqual(len(docs), 124)
        self.assertEqual({d["kind"] for d in docs}, {"Agenda", "Minutes"})
        self.assertEqual(min(d["date"] for d in docs), "2025-01-08")
        self.assertTrue(all(d["key"].startswith("weblinks:oakhillfl:") for d in docs))
        by_title = {(d["date"], d["title"]): d for d in docs}
        self.assertEqual(by_title[("2026-05-11", "5-11-2026 Commission Meeting Minutes")]["key"],
                         "weblinks:oakhillfl:6a57948b1fc6ac2f5f859b05")
        # "2-23-26": two-digit year
        self.assertIn(("2026-02-23", "2-23-26 Special Commission Meeting Minutes"), by_title)
        # Technical Review Committee is another board, not the Commission
        self.assertEqual(by_title[("2025-01-08", "01-08-2025 TRC Agenda")]["body"], "Technical Review Committee")
        # the link text says "Commission Meeting Minutes", the file name says budget workshop
        self.assertEqual(by_title[("2026-07-20", "07-20-2026 Commission Meeting Minutes")]["body"],
                         "City Commission Budget Workshop")
        # the city charter (no date) and the agenda packet folder (OneDrive) aren't documents of a meeting
        self.assertFalse(any("Charter" in d["title"] or "Packs" in d["title"] for d in docs))

    def test_manifest_reads_the_listing(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "l.jsonl"
            p.write_text(jl(oak_docs()))
            docs = manifest.docs_from_links(p)
            self.assertEqual(len(docs), 124)
            self.assertEqual({x.source for x in docs}, {"weblinks"})

    def test_meetings_from_documents(self):
        state = {x["key"]: {**x, "listed": True} for x in oak_docs()}
        ms = {(m["date"], m["body"]): m for m in region.weblinks_meetings(state)}
        nov10 = ms[("2025-11-10", "City Commission")]
        self.assertIn("Amended", nov10["agenda_url"])  # an amended agenda wins
        self.assertTrue(nov10["minutes_url"])
        self.assertEqual(ms[("2026-04-27", "City Commission Shade Meeting")]["minutes_url"], "")


class Edgewater(unittest.TestCase):
    def test_outline_and_consent(self):
        with tempfile.TemporaryDirectory() as d:
            data = make_data(Path(d))
            dd = region.load(data)
            items = {i["item_id"]: i for i in dd["items"] if i["county"] == "edgewater"}
            # section headings and notices with no action are left out; the consent line stays
            self.assertNotIn(52957, items)  # 6. CITIZEN COMMENTS
            self.assertNotIn(52977, items)  # "Pursuant to Chapter 286, F.S. …"
            self.assertTrue(items[52959]["consent_section"])
            # consent items take the consent agenda's single vote, and get full numbers
            fence = items[52964]
            self.assertEqual(fence["number"], "8.e.")
            self.assertTrue(fence["consent"])
            self.assertEqual(fence["result"], "Pass")
            votes = [v for v in dd["votes"] if v["item_key"] == fence["key"]]
            self.assertEqual(sorted((v["person"], v["vote"]) for v in votes),
                             [("Charlotte Gillis", "Yes"), ("Debbie Dolbow", "Yes"), ("Diezel DePew", "Absent"),
                              ("Eric Rainbird", "Yes"), ("Mike Thomas", "Yes")])
            self.assertEqual(items[52956]["number"], "9.c.")  # Legistar's sequence puts it under 9. Public Hearings

    def _outline(self, rows):
        """rows: (number, title, action_text or None); items with action_text carry a 2-person roll call."""
        out = {"items": [], "votes": []}
        for seq, (n, title, motion) in enumerate(rows):
            key = f"legistar:cityofedgewater:item:{seq}"
            out["items"].append({"county": "edgewater", "event_id": 1, "sequence": seq, "item_id": seq, "key": key,
                                 "number": n, "title": title, "action": "approve" if motion else "",
                                 "result": "Pass" if motion else "", "action_text": motion or ""})
            if motion:
                out["votes"] += [{"county": "edgewater", "item_key": key, "person": p, "vote": "Yes",
                                  "key": f"legistar:cityofedgewater:vote:{seq}:{k}"} for k, p in enumerate(("A", "B"))]
        region._legistar_outline("edgewater", out)
        items = {i["number"]: i for i in out["items"]}
        voted = {}
        for v in out["votes"]:
            voted.setdefault(v["item_key"], []).append(v)
        return items, {n: len(voted.get(i["key"], [])) for n, i in items.items()}

    def test_consent_vote_filed_on_an_item(self):
        # Sep 14, 2026: no action on the section line; 8b pulled and voted alone; 8d carries the consent vote
        items, votes = self._outline([
            ("8.", "CONSENT AGENDA", None),
            ("a.", "Authorization to Dispose of Surplus Asset Item", None),
            ("b.", "Approval of Mitigation Credit Agreements", "A motion was made by Councilwoman Dolbow, second by "
             "Councilman Thomas, to approve Consent Agenda Item 8b. The MOTION was APPROVED by the following vote:"),
            ("c.", "Lines of Coverage Insurance for FY 2027", None),
            ("d.", "Lift Station #21 and Lift Station #27 Rehabilitation", "A motion was made by Councilwoman Dolbow, "
             "second by Councilwoman Gillis, to approve the Consent Agenda excluding Item 8b. The MOTION was APPROVED by the following vote:"),
            ("9.", "PUBLIC HEARINGS, ORDINANCES AND RESOLUTIONS", None),
            ("a.", "Resolution No. 2026-R-29", None),
        ])
        self.assertNotIn("8.", items)  # no action: dropped
        self.assertEqual(votes, {"8.a.": 2, "8.b.": 2, "8.c.": 2, "8.d.": 2, "9.a.": 0})
        self.assertEqual(items["8.a."]["consent_of"], items["8.d."]["key"])
        self.assertNotIn("consent_of", items["8.b."])  # its own vote
        self.assertFalse(items["8.d."].get("consent_section"))  # 8d is a decision of its own, not a section line

    def test_items_left_out_of_the_consent_vote(self):
        # Sep 22, 2025: 8e was pulled and has no recorded vote, so it doesn't take the consent vote
        items, votes = self._outline([
            ("8.", "CONSENT AGENDA", "A motion was made by Councilwoman Gillis, second by Councilwoman Dolbow, to approve the "
             "Consent Agenda with the exception of items 8d & 8e. The MOTION was APPROVED by the following vote:"),
            ("a.", "Approve the agreement with Ryan Knight, Esq.", None),
            ("d.", "Accept the Donation of a Used Custom Concession Trailer", "A motion was made by Councilwoman Dolbow, "
             "second by Councilwoman Gillis, to approve Consent No. AR-2025-0365. The MOTION was APPROVED by the following vote:"),
            ("e.", "AR-2025-0384: Request for the acceptance of a donation", None),
        ])
        self.assertEqual(votes, {"8.": 2, "8.a.": 2, "8.d.": 2, "8.e.": 0})
        self.assertFalse(items["8.e."].get("consent"))
        self.assertTrue(items["8."]["consent_section"])

    def test_consent_exclusion_wording(self):
        ex = region.consent_exclusions
        self.assertEqual(ex("to approve the Consent Agenda excluding (d) and (e). The MOTION was APPROVED"), {"d", "e"})
        self.assertEqual(ex("to approve the Consent Agenda minus A and B. The MOTION was APPROVED"), {"a", "b"})
        # Aug 4, 2025, under section 8.: the letters still count, whatever number comes first
        self.assertEqual(ex("to approve the Consent Agenda excluding items 7d and 7g. The MOTION was APPROVED"), {"d", "g"})
        self.assertEqual(ex("to approve the Consent Agenda excluding Item 8b. The MOTION was APPROVED"), {"b"})
        self.assertEqual(ex("to approve the Consent Agenda. The MOTION was APPROVED by the following vote: except"), set())
        rx = region.CONSENT_MOTION_RX
        self.assertTrue(rx.search("to approve the CONSENT AGENDA. The MOTION"))
        self.assertTrue(rx.search("to approve all items listed within the Consent Agenda."))
        self.assertFalse(rx.search("to approve Consent Agenda Item 8b."))
        self.assertFalse(rx.search("to approve Consent Agenda A."))

    def test_council_pages_and_hub(self):
        with tempfile.TemporaryDirectory() as d:
            data = make_data(Path(d))
            out = Path(d) / "site"
            site.configure(SITE, "2026-11-12T20:00:00Z")
            site.write_assets(out)
            counts = people.write(data, out, SITE)
            self.assertEqual(counts["edgewater"], 5)
            council = (out / "council" / "edgewater.html").read_text()
            self.assertIn("Edgewater City Council", council)
            self.assertIn("Mayor", council)  # Diezel DePew, from the office records
            depew = (out / "council" / "edgewater" / "diezel-depew.html").read_text()
            self.assertIn('"jobTitle":"Mayor"', depew)
            self.assertIn("volusia.db", depew)  # search link opens the Volusia database
            gillis = (out / "council" / "edgewater" / "charlotte-gillis.html").read_text()
            self.assertIn("Council Member", gillis)
            self.assertNotIn("Temple Terrace", gillis)
            # the consent line itself isn't a separate decision: 5 votes, 8 consent items + 6 others
            rec = people.all_votes(data)["edgewater"]
            self.assertFalse(any(i.get("consent_section") for i in rec["items"].values()))

            m = meetings.write(data, out)
            self.assertEqual(m["edgewater"], 1)
            page = (out / "meetings" / "edgewater" / "2026-11-09.html").read_text()
            self.assertIn("Edgewater City Council", page)
            self.assertIn("Also on the agenda", page)  # presentations and reports with no vote
            self.assertNotIn("CITIZEN COMMENTS", page)
            idx = (out / "meetings" / "edgewater.html").read_text()
            self.assertIn("feeds/edgewater.xml", idx)
            self.assertIn("The City Council makes Edgewater", idx)

            res = region.write(data, out, SITE, "2026-11-12T20:00:00Z", build._rss)
            self.assertEqual(set(res), set(REGIONS))
            v = res["volusia"]["by_county"]
            self.assertEqual(v["oakhill"]["documents"], 124)
            self.assertEqual(v["edgewater"]["votes"], 45)  # 4 roll calls x 5, plus the consent roll call on its line and 5 items
            self.assertEqual(v["newsmyrnabeach"]["meetings"] + v["newsmyrnabeach"]["documents"], 0)  # not collected
            con = sqlite3.connect(out / "volusia.db")
            self.assertEqual(con.execute("SELECT count(*) FROM meetings WHERE county='oakhill'").fetchone()[0],
                             len(region.weblinks_meetings(json.loads((data / "state.json").read_text()))))
            self.assertEqual(con.execute("SELECT count(*) FROM agenda_items WHERE county='hillsborough'").fetchone()[0], 0)
            hub = (out / "volusia.html").read_text()
            self.assertIn("Southeast Volusia city records", hub)
            self.assertIn("cityofnsb.granicus.com", hub)  # New Smyrna Beach: official link, not collected
            self.assertIn("asks automated tools not to collect it", hub)
            self.assertNotIn("asking the city", hub)  # not claimed until someone actually asks
            self.assertIn("1 meeting ·", hub)
            self.assertIn("council/edgewater.html", hub)
            self.assertTrue((out / "feeds" / "oakhill.xml").exists())
            self.assertFalse((out / "feeds" / "newsmyrnabeach.xml").exists())
            # counties.db keeps only the counties
            cc = sqlite3.connect(out / "counties.db")
            self.assertEqual(cc.execute("SELECT count(*) FROM agenda_items WHERE county='edgewater'").fetchone()[0], 0)

            common = site.write_common(out, today="2026-11-12", tt={}, latest={"oakhill": "2026-11-09"})
            home = (out / "index.html").read_text()
            for area in ("New Smyrna Beach", "Edgewater", "Oak Hill"):
                self.assertIn(f"<h3>{area}</h3>", home)
            self.assertIn("volusia.html#oakhill", home)
            self.assertIn("Latest meeting on record: Monday, November 9, 2026", home)
            self.assertIn("In Volusia County.", home)
            self.assertGreater(common["pages"], 0)
            self.assertIn("volusia.db", (out / "data.html").read_text())
            self.assertIn("volusia.html", (out / "llms.txt").read_text())


class EdgewaterWording(unittest.TestCase):
    """Edgewater's Legistar records actions as verbs ("table", "deny"), and its moratoriums gave the
    decoder and the spotlight trouble on the first live run (Nov 12, 2026)."""

    def test_verb_actions(self):
        from opencivic import spotlight
        facts = {"yes": 3, "no": 0, "passed": True, "action": "table"}
        self.assertEqual(people.outcome(facts), "Moved to a later meeting, 3 to 0")
        self.assertEqual(people.outcome({**facts, "action": "deny"}), "Denied, 3 to 0")
        self.assertEqual(people.outcome({**facts, "action": "tabled"}), "Moved to a later meeting, 3 to 0")  # counties
        tag = {"kind": "restriction", "reason": "moratorium", "stage": "act"}
        self.assertEqual(spotlight.label(tag, facts), "Proposed restriction (put off)")

    def test_moratorium_headlines(self):
        from opencivic.explain import explain
        h = lambda t: explain(t)["headline"]
        self.assertEqual(h("2nd Reading - Ordinance 2024-O-62: Request for approval for a City wide Moratorium regarding "
                           "annexations, rezoning’s, comprehensive plan amendments, site plans, preliminary plats, and final plats"),
                         "Pause on new approvals or permits (a moratorium)")  # was "Change to the future land-use map"
        self.assertEqual(h("2nd Reading - Ordinance No. 2026-O-21 - Permanent Moratorium on the Acceptance, Processing, "
                           "Review, Approval, and Issuance of Development Orders … for Data Centers"),
                         "Permanent stop on new approvals or permits (called a moratorium)")
        self.assertEqual(h("2nd Reading - Ordinance No. 2025-O-06: Request to amend the Florida Shores Drainage Basin "
                           "Building Permit Moratorium."), "Change to a moratorium")
        # Hernando's boilerplate "Unless Extended or Terminated" is not an extension
        self.assertEqual(h("Second Public Hearing to Consider Ordinance Amending Hernando County Code to Impose Moratorium "
                           "on Processing Applications for Development Orders and Development Permits for Data Centers for "
                           "Period Up to 365 Days, Unless Extended or Terminated: Enacting a Temporary Moratorium on Data Centers"),
                         "Pause on new approvals or permits (a moratorium)")
        self.assertEqual(h("Hold a second public hearing and consider adoption of an ordinance providing for an extension of "
                           "the moratorium on the acceptance and processing of new applications for rezonings"),
                         "Moratorium extended")

    def test_amending_a_moratorium_is_not_a_new_restriction(self):
        from opencivic.spotlight import spot
        self.assertEqual(spot("2nd Reading - Ordinance No. 2025-O-06: Request to amend the Florida Shores Drainage Basin "
                              "Building Permit Moratorium.", "", "approve"), [])
        self.assertEqual(spot("2nd Reading - Ordinance 2024-O-63: Request for approval for a Building Permit Moratorium "
                              "within the Florida Shores Drainage Basin", "", "approve")[0]["reason"], "moratorium")
        from opencivic.spotlight import detail
        perm = spot("2nd Reading - Ordinance No. 2026-O-21 - Permanent Moratorium on the Acceptance, Processing, Review, "
                    "Approval, and Issuance of Development Orders … for Data Centers", "", "approve")[0]
        self.assertEqual(detail(perm), "The official wording describes a permanent moratorium.")


class Vocabulary(unittest.TestCase):
    def test_city_words(self):
        e, o = JURISDICTIONS["edgewater"], JURISDICTIONS["oakhill"]
        self.assertEqual((e["board"], e["member"], e["people_dir"], e["hub"][1]),
                         ("Edgewater City Council", "council member", "council", "volusia.html"))
        self.assertEqual((o["board"], o["member"], o["member_title"]),
                         ("Oak Hill City Commission", "commissioner", "City Commissioner"))
        self.assertEqual(people.cityify("the county's Commission", council=False), "the city's Commission")
        self.assertEqual(people.cityify("the Commission voted"), "the Council voted")


if __name__ == "__main__":
    unittest.main()
