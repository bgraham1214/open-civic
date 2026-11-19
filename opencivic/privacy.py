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
appointed to a board: appointment is a public role, and the user hasn't asked otherwise. The exception: a person
a board removed is not named anywhere for that government, appointments included (region.removed_by_county),
so a search for their name can't lead to the removal. Their names are found at build time in the government's
own records and never stored.

The government's own documents (minutes PDFs and our archived copies) are left as they are.
"""

from __future__ import annotations

import re

_WORD = r"[A-Z][\w'’-]+"
_NAME = rf"(?:(?:Mr|Ms|Mrs|Miss|Dr)\.?\s+)?{_WORD}(?:\s+[A-Z]\.?)?(?:\s+{_WORD}){{1,2}}"
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


def removed_people(text: str) -> set[str]:
    """Names (person_key form) of the people a removal motion in this text removes from a board."""
    out = set()
    if not text or not REMOVAL.search(text):
        return out
    for m in list(_PAREN.finditer(text)):
        if REMOVAL.search(text[max(0, m.start() - 120):m.end() + 120]):
            inner = text[text.index("(", m.start()) + 1:text.rindex(")", m.start(), m.end())]
            out.update(person_key(n) for n in re.findall(_NAME, inner))
    for m in _REMOVE_NAMED.finditer(text):
        out.update(person_key(n) for n in re.findall(_NAME, m.group(2)))
    return {n for n in out if len(n.split()) >= 2}


def blank_names(text: str, names: set[str]) -> str:
    """Each of these people's full names (person_key form) replaced, however the text spaces or capitalizes it."""
    for n in names:
        if text and n:
            # a middle initial may come between the words ("Jane Q. Doe" is "jane doe")
            # and OCR may add a letter or two to the surname ("Welche")
            text = re.sub(r"\b" + r"(?:[\s.]+[a-z]\b\.?)?[\s.]+".join(re.escape(w) for w in n.split()) + r"[a-z]{0,2}\b",
                          NAME_OUT, text, flags=re.I)
    return text


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


# --- Residents in the searchable text of archived documents (the user, Nov 17, 2026: "blank the names, no need
# to dox anyone"). The search databases hold the machine-read text of minutes, agendas and packets. Minutes name
# the residents who speak, often with a home address ("Jane Doe 205 N. Brooks Cir asked the city for speed
# bumps", "Ms. Jane Doe spoke regarding the Northeast Rural Area Plan"). In the text that goes into search,
# speakers' names, "Mr./Ms. Name", street addresses, email addresses and phone numbers are replaced. The members
# of the government's board, and anyone written with an official title ("City Administrator Shira",
# "Commissioner Werning"), are kept. The archived PDFs and data/text are left as the government published them.

NAME_OUT, ADDRESS_OUT = "[name left out]", "[address left out]"
_TITLES = (r"(?:Mayor|Vice|Deputy|Commissioner|Commissioners|Council|Councilman|Councilwoman|Councilmember|Councilor|"
           r"Chair|Chairman|Chairwoman|Chairperson|Member|Members|Attorney|Administrator|Manager|Clerk|Director|Chief|"
           r"Sheriff|Captain|Lieutenant|Sergeant|Officer|Deputy|Judge|Engineer|Planner|Supervisor|Superintendent|"
           r"Representative|Senator|Governor|Secretary|Treasurer|President|Staff|Assistant|Coordinator|Specialist|"
           r"Officials?|Fire|Police|Building|Code|Finance|Public|Parks|Utilities|Interim|Acting|Board|City|County|Town|"
           r"Village|State|Saint|St|Mount|Lake|Fort|Port|North|South|East|West|New|Oak|Hall)")
_CAP = r"[A-Z][a-zA-Z'’-]+"
_STREET = (r"(?:St|Street|Ave|Avenue|Rd|Road|Dr|Drive|Ln|Lane|Ct|Court|Cir|Circle|Blvd|Boulevard|Way|Pl|Place|Ter|"
           r"Terrace|Trl|Trail|Hwy|Highway|Pkwy|Parkway|Loop|Run|Path|Pt|Point|Cv|Cove|Xing|Crossing|Sq|Square)")
ADDRESS = re.compile(rf"\b\d{{1,6}}\s+(?:[NSEW]\.?\s+|(?:North|South|East|West)\s+)?(?:(?:US|U\.S\.|SR|CR)\s+)?"
                     rf"(?:{_CAP}\.?\s+|\d+(?:st|nd|rd|th)\s+){{0,3}}{_STREET}\b\.?(?:\s+\d+)?")
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
PHONE = re.compile(r"(?:\(\d{3}\)\s*|\b\d{3}[-.\s])\d{3}[-.]\d{4}\b")
# "Ms. Jane Doe", "Mr. Doe", "Dr. Jane Q. Doe"
HONORIFIC = re.compile(rf"\b(?:Mr|Ms|Mrs|Miss|Dr)\.?\s+(?!Martin\s+Luther\b)((?:{_CAP}\s+)?(?:[A-Z]\.\s+)?{_CAP})")  # not the road
# A speaker at the start of a line or sentence: "Jane Doe 205 N. Brooks Cir asked …", "JANE DOE: spoke …",
# "Jane Doe, of Oak Hill, thanked …"
_SAYS = (r"(?:spoke|speaks|asked|asks|thanked|expressed|stated|states|said|says|congratulated|commented|addressed|"
         r"requested|complained|inquired|presented|voiced|questioned|noted|gave|read|urged|opposed|supported|"
         r"agreed|wanted|shared|discussed|explained|raised|is|was|would|had|has|came|appeared|provided|invited|"
         r"announced|reported|thanks|mentioned|suggested|recommended|encouraged|believes|believed|felt|feels|"
         r"objected|opposes|disagreed|praised|described|showed|distributed|submitted|reminded|announced|wished|"
         r"advised|delivered|complimented|informed|introduced|told|claimed|argued|added|continued|sought|"
         r"acknowledged|clarified|emphasized|highlighted|proposed|insisted|warned|pointed)")
# the address a speaker gives, even without a street word ("David Lee 130 N Putnam spoke")
_LOOSE_ADDRESS = (rf"\d{{1,6}}[ \t]{{1,3}}(?:[NSEW]\.?[ \t]{{1,3}})?(?:(?:{_CAP}|\d+(?:st|nd|rd|th))\.?[ \t]{{1,3}}){{1,4}}?"
                  rf"(?:{_STREET}\b\.?[ \t]{{0,3}})?(?:\d{{1,4}}[ \t]{{1,3}})?")
# a name stays on one line ("Citizens Comments⏎⏎Jane Doe" is a heading, then a name); two people can speak together
_ONE_NAME = rf"(?:{_CAP}|[A-Z]{{2,}})(?:[ \t]+(?:[A-Z]\.|{_CAP}|[A-Z]{{2,}})){{1,3}}"
_NAME_WORDS = rf"((?:{_CAP}[ \t]+(?:and|&)[ \t]+)?{_ONE_NAME}(?:[ \t]+(?:and|&)[ \t]+{_ONE_NAME})?)"
def _speaker(says: str, marks: bool = True) -> re.Pattern:
    """marks: a bracket or a dash after the name also marks a speaker ("3. Jane Doe — Complimented …"), as minutes
    write them; not in memos ("Pure Sports - Future Land Use (FLUM) Amendment")."""
    return re.compile(
    # where a speaker's name starts: a line (after any list number or OCR bullet), a sentence, or a heading's colon
    rf"(?m)((?:^|(?<=[.!?;\]]\s)(?<!\bSt\.\s)(?<!\bMt\.\s)(?<!\bFt\.\s)(?<!\bDr\.\s)(?<!\bNo\.\s)(?<!\b[NSEW]\.\s)|(?<=[.!?]\s\s)|(?<=:\s)|(?<=:\s\s)|(?<=\s[-–—]\s)|(?<=\S\s\s\s))(?:[ \t]{{0,3}}(?:\d{{1,2}}[.)]|[e•*·-])[ \t]{{1,3}}){{0,3}})(?!{_TITLES}\b)"
    + _NAME_WORDS +
    rf"([ \t]{{0,3}}[,:]?[ \t]{{0,3}}{_LOOSE_ADDRESS}(?=[ \t]{{0,3}},?[ \t]{{0,3}}{says}\b))?"
    rf"(?=[ \t]{{0,3}}(?:(?:,(?![ \t]*(?:which|that|where|located|in|on|at)\b)[^,.\n]{{1,60}}){{1,2}},?|[ \t]{{1,3}}(?:of|from|with)[ \t]{{1,3}}[^.:;\n]{{1,80}}?,?)?\s{{0,3}}"
    + (rf"(?:\((?:(?i:{says})\b|\d)|\s[-–—]\s|" if marks else "(?:") +
    rf":\s{{0,3}}(?:{_LOOSE_ADDRESS})?(?:(?i:resident|citizen|first|briefly|also|then|again|further)\s+)?"
    rf"(?i:{says})\b|(?<=\s){says}\b|\s{says}\b))")


SPEAKER = _speaker(_SAYS)
# In staff memos only verbs of speaking count: "The Department has granted …" is an organization, not a speaker.
_SPOKE = (r"(?:spoke|speaks|asked|thanked|expressed|stated|said|commented|addressed|requested|complained|inquired|"
          r"voiced|questioned|urged|opposed|objected|praised|advised|told|argued|delivered|complimented)")
SPEAKER_MEMO = _speaker(_SPOKE, marks=False)


# a name after the word that says who they are: "Resident Jane Doe spoke", "Applicant, Jane Doe, stated"
ROLE_NAME = re.compile(rf"\b((?i:residents?|citizens?|applicants?|homeowners?|property owners?|neighbors?|speakers?|"
                       rf"petitioners?|appellants?)(?:['’]s)?(?:\s+(?i:representative|agent|attorney))?\s*,?\s+)"
                       rf"(?!{_TITLES}\b|(?i:associations?|assoc)\b){_NAME_WORDS}")


# the last word of a heading or an organization, not a person ("Economic Development - …", "Consent Agenda:")
_NOT_A_PERSON = re.compile(r"\b(?:Development|Agenda|Items?|Comments?|Business|Reports?|Committee|Board|Discussion|"
                           r"Presentations?|Updates?|Modifications|Minutes|Session|Hearings?|Recreation|Works|Services|"
                           r"Department|Plan|Program|Project|Proclamations?|Announcements|Participation|Input|Matters|"
                           r"Inc|LLC|Corp|Company|Association|Alliance|Club|Church|Bank|Group|Office|Council|Commission|"
                           r"Authority|District|Center|Foundation|School|University|College|Team|Staff|Road|Avenue|"
                           r"Meeting|Purchase|Equipment|Request|Approval|Budget|Ordinance|Resolution|Pledge|"
                           r"Allegiance|Invocation|Adjournment|Agreement|Contract|Policy|Fund|Tech|Control|Proposal|"
                           r"Referendum|Election|Study|Survey|Review)\.?$", re.I)
# (not words that are also surnames: Bond, Park, Grant, Street, Chambers, Hall, Code, Order)
_NOT_A_PERSON_START = re.compile(r"(?:The|A|An|This|That|These|Each|All|Both|Any|No|District|Item|Section|Exhibit|"
                                 r"Phase|Unit|Tract|Lot|Parcel|Zone|Ward|Precinct|Region|Area|Agenda|Consent|Old|Other|"
                                 r"Miscellaneous|Approval|Roll|Senate|House|Resolution|Ordinance|Florida|"
                                 r"Pasco|Hillsborough|Volusia|Temple|Oak|Tampa|Regular|Special|Workshop)\b", re.I)
# Anyone a document names with an official title is a public official or staff, and stays: "City Manager John
# Barkley" keeps "Mr. Barkley" elsewhere in the same government's documents.
_OFFICE = (r"(?:Manager|Administrator|Attorney|Clerk|Director|Chief|Captain|Lieutenant|Sergeant|Commissioner|Councilman|"
           r"Councilwoman|Councilmember|Council\s+Member|Mayor|Assistant|Coordinator|Engineer|Planner|Sheriff|Judge|"
           r"Senator|Representative|Superintendent|Officer|Chairman|Chairwoman|Chair|Administrative\s+Assistant)")
OFFICIAL = re.compile(rf"\b(?i:{_OFFICE})[ \t]+((?:{_CAP}|[A-Z]{{2,}})(?:[ \t]+(?:[A-Z]\.|{_CAP}|[A-Z]{{2,}})){{0,2}})")


def officials_in(text: str) -> set[str]:
    """Lowercased names a text gives an official title ("City Administrator Janet Shira" -> "janet shira")."""
    out = set()
    for m in OFFICIAL.finditer(text or ""):
        if not _NOT_A_PERSON.search(m.group(1)) and person_key(m.group(1)):
            out.add(person_key(m.group(1)))
    return out


# who signed a letter in a packet: the line after "Sincerely," ("Sincerely,⏎⏎Jane Doe")
SIGNATURE = re.compile(rf"(?i:\b(?:sincerely|respectfully(?: submitted)?|regards|best|thank you|thanks),?)[ \t]*\n"
                       rf"(?:[ \t]*\n){{0,3}}[ \t]{{0,20}}(?:/s/[ \t]*)?((?:{_CAP}|[A-Z]\.)(?:[ \t]{{1,2}}(?:[A-Z]\.|{_CAP})){{1,3}})")


def _keep(name: str, keep: set[str]) -> bool:
    """keep holds the board members' names, lowercased ("ricky taylor"). A bare surname ("Mr. Taylor") is kept
    when a member has it; a fuller name only when it is a member's ("Janna Taylor" is a resident, not the
    Mayor)."""
    if (re.match(_TITLES + r"\b", name, re.I) or _NOT_A_PERSON.search(name) or _NOT_A_PERSON_START.match(name)
            or re.search(rf"\b(?i:{_OFFICE})\b", name)):  # "Senior Planner Jane Doe"
        return True
    words = person_key(name).split()
    if len(words) == 1:
        return any(k.split()[-1] == words[0] for k in keep)
    return " ".join(words) in keep or any(len(k.split()) > 1 and k.split()[-1] == words[-1] and k.split()[0] == words[0]
                                          for k in keep)


def person_key(name: str) -> str:
    """'Ronald E. Oakley' -> 'ronald oakley', the form scrub_text's keep holds."""
    return " ".join(w.strip(".,").lower() for w in name.split() if not re.fullmatch(r"[A-Z]\.?", w))


def scrub_text(text: str, keep: set[str] = frozenset(), addresses: bool = True) -> str:
    """Searchable document text without residents' names and contact details. keep: the board members' names,
    lowercased, which stay. addresses=False keeps street addresses that aren't a speaker's: in a staff memo the
    address is usually the property the decision is about ("annexation of the parcel located at …"), while
    minutes record the home addresses of the residents who speak."""
    if not text:
        return text
    keep = set(keep) | officials_in(text)
    # long runs of blank space (scanned drawings and tables) mean nothing to search, and make the patterns slow
    text = re.sub(r"[ \t]{4,}", "   ", text)
    text = re.sub(r"\n[ \t]*(?:\n[ \t]*){2,}", "\n\n", text)
    text = unname_removals(text)
    # speakers first: the address after a name is part of how a speaker is recognized
    text = (SPEAKER if addresses else SPEAKER_MEMO).sub(lambda m: m.group(0) if _keep(m.group(2), keep)
                       else m.group(1) + NAME_OUT + (f" {ADDRESS_OUT}" + (" " if m.group(3)[-1:].isspace() else "")
                                                     if m.group(3) else ""), text)
    text = SIGNATURE.sub(lambda m: m.group(0) if _keep(m.group(1), keep)
                         else m.group(0)[:m.start(1) - m.start(0)] + NAME_OUT, text)
    text = ROLE_NAME.sub(lambda m: m.group(0) if _keep(m.group(2), keep) else m.group(1) + NAME_OUT, text)
    text = HONORIFIC.sub(lambda m: m.group(0) if _keep(m.group(1), keep) else NAME_OUT, text)
    text = EMAIL.sub("[email left out]", text)
    text = PHONE.sub("[phone left out]", text)
    return ADDRESS.sub(ADDRESS_OUT, text) if addresses else text


# A resident who asked to speak, named in the item's title and on its speaker form ("Short-Term Rental Ordinance
# Enforcement - Robert Clifford", Destin, Apr 7, 2026). Speaker cards also ride along on hundreds of ordinary
# hearings (Venice, Pinellas), so only a surname shared by the title and the form counts (Nov 19, 2026: 2 items
# in every listing we hold, both Destin's).
_SPEAKER = re.compile(r"speaker (?:form|card|request)|request to (?:speak|address)", re.I)
_NOT_NAMES = {"City", "Council", "Commission", "Town", "Board", "Speaker", "Form", "Card", "Regular", "Special",
              "Meeting", "County", "Request", "Speak", "Address", "Public", "Comment", "Workshop", "Citizens",
              "Heard", "Received", "Letter", "Correspondence"}


def resident_speaker(item: dict) -> bool:
    """An item about a resident who asked to speak: never stored (florida.py) or grouped (glance.py)."""
    title = item.get("title") or ""
    for a in item.get("attachments") or []:
        name = a.get("name", "") if isinstance(a, dict) else str(a)
        if _SPEAKER.search(name):
            words = [w for w in re.findall(r"[A-Z][a-z]{2,}", _SPEAKER.sub(" ", name)) if w not in _NOT_NAMES]
            if any(re.search(rf"\b{re.escape(w)}\b", title) for w in words):
                return True
    return False
