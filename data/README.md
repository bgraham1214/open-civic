# Data

Written by the nightly **Collect** workflow. Don't edit by hand.

| File | What it is |
| --- | --- |
| `manifest.jsonl` | Append-only log. One line per event: `new`, `changed`, `unlisted` or `relisted`, with the document's SHA-256, size, retrieval time, source URL and `copy_url`. |
| `state.json` | Latest known state of every document. Rewritten each run. |
| `listings/` | Each night's full listing from CivicClerk and the Archive Center, plus every CivicClerk agenda item (`civicclerk-items.jsonl`). |
| `text/<sha256>.json.gz` | Text of each document version, page by page. Pages marked `"method": "ocr"` were machine-read from a scan and can contain errors. |

**Checking a document.** Download it from the city (`url`) or from our copy (`copy_url`, in the repo's "files" release) and compare its SHA-256 with the manifest: `sha256sum file.pdf`. The git history of `manifest.jsonl` shows when each line was added, so the log can't be quietly rewritten.

Known documents are re-downloaded every 7 days, so an edit to a published PDF shows up as a `changed` event with the previous hash.
