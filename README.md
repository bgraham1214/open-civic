# Open Civic Web (working name)

Open, public-interest tools that collect local government meeting records and keep them searchable for free. The pilot city is Temple Terrace, FL.

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

`opencivic/build.py` builds the public site: a SQLite database with full-text search over every page and agenda item, opened in the browser through [Datasette Lite](https://lite.datasette.io), plus RSS feeds. It is published nightly to GitHub Pages at https://bgraham1214.github.io/open-civic/.

`opencivic/minutes.py` and `opencivic/entities.py` read attendance and every roll-call vote from the minutes, find contracts and vendors in agenda items, and write them to `data/entities/`, including a FollowTheMoney file (`templeterrace.ftm.jsonl`). All of it is machine-read and links back to its source page.

## Tests

```bash
python -m unittest discover -s tests -v
```

The tests run entirely against Temple Terrace's saved responses in `tests/fixtures/`, so they never touch the network. `check-schema` compares the live `$metadata` against the fields the adapter relies on, so a CivicClerk API change fails loudly instead of quietly producing empty data.

## Nightly collection

The **Collect** workflow runs every night at 3:17 AM Eastern (or on demand: Actions → Collect → Run workflow). It lists every CivicClerk meeting file and City Council Archive Center document, fingerprints them, commits `data/`, and uploads copies of new file versions to the "files" release. Raw pages and logs from the latest run are on the `live-samples` branch.

## Polite collection

Requests are spaced at least one second apart, retried with backoff on 429/5xx, checked against robots.txt, and sent with a User-Agent naming the project. Set `OCW_CONTACT` to a URL or email to add a contact.

## Status

Phase 1, steps 1 to 5 are built: adapters, fingerprint manifest, text extraction with OCR, agenda items, and the public search site. Next: mapping records to FollowTheMoney entities, and linking meeting videos.
