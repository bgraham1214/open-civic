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

## Tests

```bash
python -m unittest discover -s tests -v
```

The tests run entirely against Temple Terrace's saved responses in `tests/fixtures/`, so they never touch the network. `check-schema` compares the live `$metadata` against the fields the adapter relies on, so a CivicClerk API change fails loudly instead of quietly producing empty data.

## Live check on GitHub

Open **Actions → Collect → Run workflow**. It runs the tests, then collects live from Temple Terrace: every CivicClerk meeting and file, every Archive Center document, and a test download from each source. Results and the raw Archive Center HTML are attached to the run as `templeterrace-live`.

## Polite collection

Requests are spaced at least one second apart, retried with backoff on 429/5xx, checked against robots.txt, and sent with a User-Agent naming the project. Set `OCW_CONTACT` to a URL or email to add a contact.

## Status

Phase 1, steps 1 and 2 (CivicClerk and Archive Center adapters) are written and tested offline. The Archive Center tests use synthetic HTML until the first live run saves real pages. Still unverified live: both download URL forms, and whether CivicClerk's `eventDate` (`…T18:00:00Z`) is local time with a stray `Z`.
