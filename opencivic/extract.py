# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Extract text from every fingerprinted document, page by page (Phase 1, step 4).

For each document version in data/state.json without text yet, writes
data/text/<sha256>.json.gz:

  {"sha256": ..., "pages": [{"n": 1, "text": "...", "method": "pdftotext" | "ocr"}], ...}

Pages with a text layer use pdftotext. Pages without one (scanned minutes) are OCR'd
with Tesseract and marked "ocr": machine-read text, which can contain errors and must
be labelled as such wherever it is shown.

Keyed by SHA-256, so each distinct file is processed once. OCR is capped per run
(--max-ocr-pages); documents over the remaining budget wait for the next run.

Needs poppler-utils (pdftotext, pdfinfo, pdftoppm) and tesseract-ocr.

Usage:
  python -m opencivic.extract --data-dir data --files-dir out/files
"""

from __future__ import annotations

import argparse
import gzip
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .fetch import USER_AGENT

MIN_CHARS = 40  # a page with less text than this is treated as having no text layer
# Short documents first, so agendas and minutes are searchable before big packets.
KIND_ORDER = {"Agenda": 0, "Minutes": 1, "Agendas & Minutes": 2, "Agenda Packet": 3}


def _run(args: list[str], timeout: int = 300) -> str:
    return subprocess.run(args, capture_output=True, text=True, check=True, timeout=timeout).stdout


def page_count(pdf: Path) -> int:
    for line in _run(["pdfinfo", str(pdf)]).splitlines():
        if line.startswith("Pages:"):
            return int(line.split()[1])
    raise ValueError(f"no page count for {pdf}")


def text_layer(pdf: Path, n: int) -> str:
    return _run(["pdftotext", "-f", str(n), "-l", str(n), "-layout", str(pdf), "-"])


def ocr_page(pdf: Path, n: int) -> str:
    with tempfile.TemporaryDirectory() as d:
        base = Path(d) / "p"
        _run(["pdftoppm", "-r", "300", "-gray", "-f", str(n), "-l", str(n), "-png", str(pdf), str(base)])
        img = next(Path(d).glob("p*.png"))
        return _run(["tesseract", str(img), "stdout", "--psm", "1"], timeout=600)


def tool_versions() -> dict:
    out = {}
    for name, args in (("pdftotext", ["pdftotext", "-v"]), ("tesseract", ["tesseract", "--version"])):
        try:
            p = subprocess.run(args, capture_output=True, text=True, timeout=30)
            out[name] = (p.stdout or p.stderr).splitlines()[0].strip()
        except (OSError, IndexError, subprocess.SubprocessError):
            out[name] = "unavailable"
    return out


def extract(pdf: Path, ocr_budget: int, ocr_available: bool) -> tuple[list[dict] | None, int]:
    """Return (pages, ocr_pages_used), or (None, 0) if the OCR budget can't cover it."""
    n_pages = page_count(pdf)
    layers = [text_layer(pdf, n) for n in range(1, n_pages + 1)]
    need_ocr = [i for i, t in enumerate(layers) if len(t.strip()) < MIN_CHARS]
    if need_ocr and ocr_available and len(need_ocr) > ocr_budget:
        return None, 0
    pages = []
    for i, t in enumerate(layers):
        if i in need_ocr and ocr_available:
            pages.append({"n": i + 1, "text": ocr_page(pdf, i + 1), "method": "ocr"})
        else:
            pages.append({"n": i + 1, "text": t, "method": "pdftotext"})
    return pages, (len(need_ocr) if ocr_available else 0)


def _get_pdf(entry: dict, files_dir: Path | None, tmp: Path) -> Path | None:
    name = f"{entry['sha256']}.{entry.get('ext', 'pdf')}"
    if files_dir and (files_dir / name).exists():
        return files_dir / name
    if not entry.get("copy_url"):
        return None
    target = tmp / name
    req = urllib.request.Request(entry["copy_url"], headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=300) as r, target.open("wb") as fh:
        shutil.copyfileobj(r, fh)
    return target


def run(data_dir: Path, files_dir: Path | None, max_ocr_pages: int, max_docs: int | None = None) -> dict:
    state = json.loads((data_dir / "state.json").read_text("utf-8"))
    text_dir = data_dir / "text"
    text_dir.mkdir(parents=True, exist_ok=True)
    ocr_available = shutil.which("tesseract") is not None and shutil.which("pdftoppm") is not None
    tools = tool_versions()
    budget = max_ocr_pages
    summary = {"done": 0, "already": 0, "deferred_ocr": 0, "errors": 0, "pages": 0, "ocr_pages": 0,
               "ocr_available": ocr_available}

    todo: dict[str, dict] = {}
    for e in state.values():
        if e.get("sha256") and e.get("ext") == "pdf":
            todo.setdefault(e["sha256"], e)
    order = sorted(todo.values(), key=lambda e: (KIND_ORDER.get(e["kind"], 9), e.get("bytes", 0)))

    with tempfile.TemporaryDirectory() as tmp:
        for e in order:
            out = text_dir / f"{e['sha256']}.json.gz"
            if out.exists():
                summary["already"] += 1
                continue
            if max_docs is not None and summary["done"] >= max_docs:
                break
            try:
                pdf = _get_pdf(e, files_dir, Path(tmp))
                if pdf is None:
                    raise FileNotFoundError("no local file or copy_url")
                pages, used = extract(pdf, budget, ocr_available)
            except Exception as ex:  # one bad PDF must not stop the run
                print(f"error: {e['key']} {e['sha256'][:12]}: {ex}", file=sys.stderr)
                summary["errors"] += 1
                continue
            if pages is None:
                summary["deferred_ocr"] += 1
                continue
            budget -= used
            doc = {
                "sha256": e["sha256"], "key": e["key"], "title": e["title"], "kind": e["kind"],
                "date": e["date"], "pages": pages,
                "ocr_pages": [p["n"] for p in pages if p["method"] == "ocr"],
                "no_text_pages": [p["n"] for p in pages if len(p["text"].strip()) < MIN_CHARS],
                "extracted_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                "tools": tools,
            }
            with gzip.open(out, "wt", encoding="utf-8") as fh:
                json.dump(doc, fh, ensure_ascii=False)
            if pdf.parent == Path(tmp):
                pdf.unlink()
            summary["done"] += 1
            summary["pages"] += len(pages)
            summary["ocr_pages"] += used
    return summary


def load_text(data_dir: Path, sha256: str) -> dict | None:
    p = data_dir / "text" / f"{sha256}.json.gz"
    if not p.exists():
        return None
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m opencivic.extract")
    ap.add_argument("--data-dir", type=Path, default=Path("data"))
    ap.add_argument("--files-dir", type=Path, help="local copies named <sha256>.<ext> (else downloads copy_url)")
    ap.add_argument("--max-ocr-pages", type=int, default=600)
    ap.add_argument("--max-docs", type=int)
    args = ap.parse_args(argv)
    summary = run(args.data_dir, args.files_dir, args.max_ocr_pages, args.max_docs)
    print(json.dumps(summary), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
