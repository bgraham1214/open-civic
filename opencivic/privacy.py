# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""Wording kept off the site for people who aren't public officials.

Volunteers removed from a board (the user, Nov 17, 2026: "don't name the volunteers"). Residents serve on
city and county advisory boards without pay. When a motion removes one from a board, the site shows the
motion without the person's name: a removal reads as a judgment about someone who never ran for office, and
the review gate (Guardrails) keeps any claim tying a named person to possible wrongdoing off the site.

Seen in the records on Nov 17, 2026 (names replaced here):
  Oak Hill    "To permanently remove the two volunteers (Jane Doe & Mary Roe) from all city boards"
  Hollywood   "to remove Jane Doe from the Historic Preservation Board and replace ..."
  Brevard     "The Board approved removing Jane Doe from the Election Canvassing Board"

Elected officials are still named ("removing Commissioner Smith from the TPO board"), and so are people
appointed to a board: appointment is a public role, and the user hasn't asked otherwise.

The government's own documents (minutes PDFs and our archived copies) are left as they are.
"""

from __future__ import annotations

import re

_WORD = r"[A-Z][\w'’-]+"
_NAME = rf"(?:(?:Mr|Ms|Mrs|Miss|Dr)\.?\s+)?{_WORD}(?:\s+[A-Z]\.)?(?:\s+{_WORD}){{1,2}}"
_NAMES = rf"{_NAME}(?:\s*(?:,|&|\band\b)\s*{_NAME})*"
# a title an elected official or staff member carries: those names stay
_OFFICIAL = r"(?:Commissioner|Council\s?(?:member|woman|man)|Councilor|Mayor|Vice|Chair\w*|Judge|Sheriff|Clerk|Supervisor|Director|Manager)\b"
_BOARD = r"(?i:boards?|committees?|commissions?|councils?|panels?|task force)\b"

REMOVAL = re.compile(r"\b(?:remov|dismiss|suspend|terminat|expel)\w*\b", re.I)
# Names must start with capitals, so only the verbs and board words ignore case.
# Not a sponsor in brackets: Tarpon Springs writes "Request to Remove Planning & Zoning Board Member
# (Commissioner Jane Doe)", where the name is the commissioner who asked.
_PAREN = re.compile(rf"\b((?i:volunteers?|members?|appointees?))\s*\(\s*(?!{_OFFICIAL}|(?:Mr|Ms|Mrs|Dr)\.?\s+{_OFFICIAL}){_NAMES}\s*\)")
_REMOVE_NAMED = re.compile(
    rf"\b((?i:remov(?:e|ed|es|ing|al of)|dismiss(?:ed|es|ing|al of)?|suspend(?:ed|s|ing)?|terminat(?:e|ed|es|ing))\s+)"
    rf"(?!{_OFFICIAL})({_NAMES})(\s+(?i:from)\s+(?:(?i:the|all)\s+)?(?:[\w'’&/-]+\s+){{0,6}}?{_BOARD})")


def _count(names: str) -> int:
    return len(re.findall(rf"{_NAME}", names))


def unname_removals(text: str) -> str:
    """A removal from a board without the removed people's names. Other text is returned unchanged."""
    if not text or not REMOVAL.search(text):
        return text
    text = _PAREN.sub(lambda m: m.group(1), text)

    def one(m: re.Match) -> str:
        n = _count(m.group(2))
        who = "a member" if n == 1 else "two members" if n == 2 else "members"
        return m.group(1) + who + m.group(3)

    return _REMOVE_NAMED.sub(one, text)


FIELDS = ("title", "motion", "action_text", "description")


def unname_item(item: dict) -> dict:
    """The same item with unname_removals applied to its wording (changed in place, and returned)."""
    for f in FIELDS:
        if isinstance(item.get(f), str):
            item[f] = unname_removals(item[f])
    return item
