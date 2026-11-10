# Open Civic Web (working name)

Open, public-interest tools that collect local government meeting records and keep them searchable for free. The pilot city is Temple Terrace, FL. Since Nov 2026 it also follows the Hillsborough, Pasco and Hernando county commissions, which govern Brandon, Lutz, Wesley Chapel and Spring Hill.

## What's here

`opencivic/civicclerk.py` lists every meeting on a city's new CivicClerk portal (`{tenant}.portal.civicclerk.com`) and every file published for it, using CivicClerk's public OData API. It has no dependencies beyond Python 3.11+.

```bash
# Offline, from a saved API response
python -m opencivic.civicclerk files --input tests/fixtures/templeterracefl/Events.json --format csv

# Live (needs network access to *.civicclerk.com; GitHub Actions has it)
python -m opencivic.civicclerk meetings --tenant templeterracefl -o meetings.jsonl
python -m opencivic.civicclerk files    --tenant templeterracefl --format csv -o files.csv
python -m opencivic.civicclerk check-schema --tenant templeterracefl
```

Options: `--category "City Council"`, `--with-files-only`, `--max-pages N`, `--format jsonl|csv`.

Each file record carries `file_id` (treated as a version id), its kind (Agenda, Agenda Packet, Minutes…), publish time, a download URL, and a plain-text URL that CivicClerk generates.

`opencivic/archivecenter.py` lists every document in a CivicPlus Archive Center (`{site}/Archive.aspx`), where Temple Terrace keeps minutes and agendas from before Oct 2025. The page has no API, so it reads the HTML, looking only for the standard `AMID` (module) and `ADID` (document) links.

```bash
python -m opencivic.archivecenter items --site https://www.templeterrace.gov --save-raw raw/
python -m opencivic.archivecenter items --input-dir raw/ --module minutes     # offline
```

`opencivic/manifest.py` downloads every listed document, records its SHA-256, and logs `new`, `changed`, `unlisted` and `relisted` events in `data/manifest.jsonl` (see `data/README.md`). Copies of each file version are kept in the repo's "files" release.

`opencivic/extract.py` pulls text from every document, page by page, OCR'ing scanned pages with Tesseract (marked `ocr`). `civicclerk items` lists every agenda item from CivicClerk's Meetings API.

`opencivic/build.py` builds the public site, published nightly to GitHub Pages at https://bgraham1214.github.io/open-civic/: SQLite databases with full-text search, opened in the browser through [Datasette Lite](https://lite.datasette.io), RSS feeds, and plain-language pages.

### The public site

| Page | What it is |
| --- | --- |
| `index.html` | The front door: pick your area (Temple Terrace, Brandon, Lutz, Wesley Chapel, Spring Hill) |
| `templeterrace.html` | Temple Terrace City Council records, search, and documents the city removed |
| `counties.html` | County commission records, search, recent meetings, feeds |
| `meetings/<county>.html`, `meetings/<county>/<date>.html` | What happened at each County Commission meeting, in plain language |
| `commissioners/<county>.html`, `commissioners/<county>/<name>.html` | How each commissioner voted |
| `learn/index.html`, `learn/land.html`, `learn/money.html` | Every term we explain, with sources; two short explainers |
| `data.html` | Downloads, feeds and raw files for researchers |
| `sitemap.xml`, `llms.txt` | Maps of the site for search engines and AI tools |

Every page goes through one shell, `opencivic/site.py`: skip link, header navigation, breadcrumbs, landmarks, a shared footer, a meta description, a canonical link and schema.org JSON-LD (meetings as `Event`, commissioners as `Person`, terms as `DefinedTerm`, downloads as `Dataset`). The single stylesheet (`plain.css`) uses Atkinson Hyperlegible, self-hosted. The site is checked with [axe-core](https://github.com/dequelabs/axe-core) against WCAG 2.2 AA at phone width; votes are shown by shape as well as colour and still read correctly in Windows high-contrast mode.

`opencivic/minutes.py` and `opencivic/entities.py` read attendance and every roll-call vote from the minutes, find contracts and vendors in agenda items, and write them to `data/entities/`, including a FollowTheMoney file (`templeterrace.ftm.jsonl`). All of it is machine-read and links back to its source page.

`opencivic/legistar.py` reads Granicus Legistar's public Web API (`webapi.legistar.com/v1/{client}/`): meetings, agenda items with the action, result, mover and seconder, and each member's vote. Legistar's file servers (`*.legistar1.com`) disallow robots, so it links to agenda and minutes PDFs instead of downloading them. Hearings mostly about private residents (Value Adjustment Board, Special Masters) are skipped.

```bash
python -m opencivic.legistar events --client hernandocountyfl --since 2025-01-01 -o events.jsonl
python -m opencivic.legistar items --client hernandocountyfl --events events.jsonl --items-out items.jsonl --votes-out votes.jsonl
```

`opencivic/hillsclerk.py` reads the Hillsborough Clerk's BOCC Master Voting Record PDFs (one per year, updated monthly) into roll calls: RCS number, item, date, category, subject and each commissioner's vote code.

`opencivic/pascominutes.py` reads each Pasco commissioner's vote from the Clerk's annotated-agenda minutes, because Pasco's CivicClerk portal publishes no vote data. The Clerk names only members who voted no, abstained or were absent, so everyone else present is counted as yes; consent items inherit the consent-agenda vote. Each item is joined to its CivicClerk agenda item by date and file number. Public comment is never read, and any item it can't read with confidence (several motions, an unknown name) is reported, not guessed.

`opencivic/people.py` writes a plain-language page for each Hillsborough, Pasco and Hernando county commissioner (`site/commissioners/`): one sentence on what the record shows, their no votes, when the board went the other way, decisions naming Brandon, Lutz or Spring Hill, and a glossary. It is written for residents who have never read an agenda.

`opencivic/explain.py` translates agenda wording into plain language by fixed rules (no AI): a topic, a plain headline ("Change to the future land-use map at 16410 Balm Wimauma Road"), decoded facts ("from Agricultural/Rural, up to 1 home per 5 acres, to Residential, up to 4 homes per acre"; dollar amounts; companies), and sourced definitions of the terms. `opencivic/meetings.py` uses it to write a "what happened" page for every County Commission meeting (`site/meetings/`) and two explainers (`site/learn/`). The official wording is always one tap away.

`opencivic/jurisdictions.py` says which sources belong to which government. `opencivic/region.py` builds `counties.db` and `counties.html` with per-county and per-area (Brandon, Lutz, Wesley Chapel, Spring Hill) RSS feeds.

| Area | Governed by | Source | What we collect |
| --- | --- | --- | --- |
| Temple Terrace | City Council | CivicClerk + Archive Center | Agendas, packets, minutes (archived), items, votes, contracts |
| Brandon, Lutz | Hillsborough County | Clerk's BOCC Master Voting Record + Legistar (`hillsboroughcounty`) | Every Commission roll call (subject, category, each commissioner's vote) from the Clerk's yearly reports, archived; land-use and zoning hearings from Legistar. Full regular agendas are on eagenda.hillsboroughcounty.org, whose robots.txt disallows all robots, so they are not collected. |
| Wesley Chapel | Pasco County | CivicClerk (`pascocofl`) + the Clerk's minutes | Agendas and minutes (archived), agenda items, and each commissioner's vote read from the minutes, from 2025 |
| Spring Hill | Hernando County | Legistar (`hernandocountyfl`) | Meetings, items, actions, votes, from 2025 |

## Tests

```bash
python -m unittest discover -s tests -v
```

The tests run entirely against saved responses (Temple Terrace, Hillsborough, Hernando) in `tests/fixtures/`, so they never touch the network. `check-schema` compares the live `$metadata` against the fields the adapter relies on, so a CivicClerk API change fails loudly instead of quietly producing empty data.

## Nightly collection

The **Collect** workflow runs every night at 3:17 AM Eastern (or on demand: Actions → Collect → Run workflow). It lists every CivicClerk meeting file and City Council Archive Center document, fingerprints them, commits `data/`, and uploads copies of new file versions to the "files" release. Raw pages and logs from the latest run are on the `live-samples` branch.

## Polite collection

Requests are spaced at least one second apart, retried with backoff on 429/5xx, checked against robots.txt, and sent with a User-Agent naming the project. Set `OCW_CONTACT` to a URL or email to add a contact.

## Status

Phase 1 (Temple Terrace) is complete. Phase 2 has started with three county commissions (see the table above).

## License

- **The project as a whole** is under the [GNU AGPL v3.0 or later](LICENSE). Anyone who runs a modified version as a public service must share their changes.
- **The city adapters** (`opencivic/civicclerk.py`, `opencivic/archivecenter.py`, `opencivic/legistar.py`, `opencivic/hillsclerk.py`, `opencivic/fetch.py` and their tests) are under the [Apache License 2.0](LICENSES/Apache-2.0.txt), the same license as [civic-scraper](https://github.com/biglocalnews/civic-scraper), so they can be contributed upstream.

Each source file starts with an `SPDX-License-Identifier` line saying which one applies. The documents in `data/` are public records of the City of Temple Terrace and of Hillsborough, Pasco and Hernando counties.
