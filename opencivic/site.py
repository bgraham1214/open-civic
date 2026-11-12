# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright 2026 Brock Graham and Open Civic Web contributors
"""The shared page shell, and the site-wide files that help people and machines find their way.

Every public page goes through `page()`, so every page has the same skip link, header,
breadcrumb trail, landmarks, footer and metadata (description, canonical link,
schema.org JSON-LD). Write once, accessible everywhere.

Site-wide files written by `write_common()`:

  plain.css, fonts/   the one stylesheet (Atkinson Hyperlegible, self-hosted, SIL OFL)
  index.html          the front door: "where do you live?"
  learn/index.html    every term we explain, with sources
  data.html           downloads and feeds for researchers, described as schema.org Datasets
  sitemap.xml         every page, for search engines
  llms.txt            a plain-text map of the site for AI tools (https://llmstxt.org)

Design rules (see the project guide, Principles): write for a resident who has never read an
agenda, lead with one plain sentence, show votes by shape as well as colour, keep pages light.
"""

from __future__ import annotations

import html
import json
import re
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .jurisdictions import JURISDICTIONS

STATIC = Path(__file__).parent / "static"
REPO = "https://github.com/bgraham1214/open-civic"
NAME = "Open Civic Web"

# Set once per build by configure(); pages render without it (tests), just without absolute URLs.
SITE_URL = ""
BUILT = ""


def configure(site_url: str, built: str = "") -> None:
    global SITE_URL, BUILT
    SITE_URL = site_url.rstrip("/") + "/" if site_url else ""
    BUILT = built


def e(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def absolute(path: str) -> str:
    return SITE_URL + path if SITE_URL else ""


def long_date(d: str) -> str:
    y, m, dd = (int(x) for x in d[:10].split("-"))
    return f"{date(y, m, dd):%B} {dd}, {y}"


def weekday_date(d: str) -> str:
    y, m, dd = (int(x) for x in d[:10].split("-"))
    return f"{date(y, m, dd):%A}, {date(y, m, dd):%B} {dd}, {y}"


def to_eastern(iso: str) -> datetime:
    """UTC ISO time -> Eastern wall-clock time, by the US daylight-time rule (2nd Sunday of March to 1st Sunday of November)."""
    t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    y = t.year

    def nth_sunday(month: int, n: int) -> datetime:
        d = datetime(y, month, 1, tzinfo=timezone.utc)
        d += timedelta(days=(6 - d.weekday()) % 7 + 7 * (n - 1))
        return d
    dst = nth_sunday(3, 2) + timedelta(hours=7) <= t < nth_sunday(11, 1) + timedelta(hours=6)
    return t + timedelta(hours=-4 if dst else -5)


def eastern(iso: str) -> str:
    """'2026-11-10T02:49:00Z' -> 'November 9, 2026 at 9:49 PM Eastern'."""
    if not iso:
        return ""
    local = to_eastern(iso)
    hour = local.hour % 12 or 12
    return f"{local:%B} {local.day}, {local.year} at {hour}:{local:%M} {'AM' if local.hour < 12 else 'PM'} Eastern"


def ld(obj: dict) -> str:
    """A schema.org JSON-LD block. '</' is escaped so text can never close the script tag."""
    text = json.dumps(_drop_none({"@context": "https://schema.org", **obj}), ensure_ascii=False, separators=(",", ":"))
    text = text.replace("</", "<\\/")
    return f'<script type="application/ld+json">{text}</script>'


def _drop_none(x):
    """Leave out unknown values (None) rather than publishing nulls."""
    if isinstance(x, dict):
        return {k: _drop_none(v) for k, v in x.items() if v is not None}
    if isinstance(x, list):
        return [_drop_none(v) for v in x]
    return x


PUBLISHER = {"@type": "Organization", "name": NAME, "url": REPO}


def page(title: str, body: str, depth: int, *, path: str = "", description: str = "",
         crumbs: list[tuple[str, str]] | tuple = (), jsonld: list[dict] | tuple = (),
         feeds: list[tuple[str, str]] | tuple = (), note: str = "", og_type: str = "website", here: str = "") -> str:
    """One public page.

    depth: how many folders below the site root the page sits (for relative links).
    path: the page's path from the site root, for its canonical URL and breadcrumbs.
    crumbs: [(label, path from root), ...] between Home and this page; this page is added last.
    note: page-specific source notes, shown at the top of the footer (HTML).
    here: this page's short label in the breadcrumb trail (default: the title before any colon).
    feeds: [(title, path from root)] RSS feeds to announce in <head>.
    """
    up = "../" * depth
    desc = re.sub(r"\s+", " ", description).strip()
    canon = absolute(path)
    head = [f"<title>{e(title)}</title>"]
    if desc:
        head.append(f'<meta name="description" content="{e(desc)}">')
    if canon:
        head.append(f'<link rel="canonical" href="{e(canon)}">')
        head.append(f'<meta property="og:url" content="{e(canon)}">')
    head += [f'<meta property="og:title" content="{e(title)}">', f'<meta property="og:type" content="{og_type}">',
             f'<meta property="og:site_name" content="{NAME}">']
    if desc:
        head.append(f'<meta property="og:description" content="{e(desc)}">')
    if SITE_URL:  # the share card for links posted on social media and in group chats
        head += [f'<meta property="og:image" content="{e(absolute("share.png"))}">',
                 '<meta property="og:image:width" content="1200">', '<meta property="og:image:height" content="630">',
                 f'<meta property="og:image:alt" content="{NAME}: what your local government decided, in plain words">',
                 '<meta name="twitter:card" content="summary_large_image">']
    head += [f'<link rel="alternate" type="application/rss+xml" title="{e(t)}" href="{up}{e(p)}">' for t, p in feeds]
    trail = [("Home", "index.html")] + list(crumbs)
    crumb_html = ""
    blocks = list(jsonld)
    if path and path != "index.html":
        items = "".join(f'<li><a href="{up}{e(p)}">{e(label)}</a></li>' for label, p in trail)
        here = here or _short(title)
        crumb_html = (f'<nav class="crumbs" aria-label="You are here"><ol>{items}'
                      f'<li><span aria-current="page">{e(here)}</span></li></ol></nav>')
        if SITE_URL:
            blocks.append({"@type": "BreadcrumbList", "itemListElement": [
                {"@type": "ListItem", "position": i + 1, "name": label, "item": absolute(p)}
                for i, (label, p) in enumerate(trail + [(here, path)])]})
    head += [ld(b) for b in blocks]
    updated = f" Updated {e(eastern(BUILT))}." if BUILT else ""
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
{chr(10).join(head)}
<link rel="stylesheet" href="{up}plain.css"></head>
<body><a class="skip" href="#main">Skip to main content</a>
<header class="site"><div class="wrap"><a class="brand" href="{up}index.html">{NAME}</a>
<nav aria-label="Site"><ul><li><a href="{up}index.html#areas">Your area</a></li><li><a href="{up}spotlight.html">Spotlight</a></li><li><a href="{up}companies.html">Money</a></li><li><a href="{up}learn/index.html">Learn</a></li><li><a href="{up}data.html">Data</a></li></ul></nav></div></header>
<div class="wrap">{crumb_html}
<main id="main" tabindex="-1">
{body}
</main>
<footer class="site">{f'<div class="source">{note}</div>' if note else ''}
<p>{NAME} is a free, nonpartisan public project. Every night it collects public records from official
government websites and keeps a fingerprinted copy, so anyone can check what was decided and whether a
record later changed.{updated}</p>
<p><a href="{up}data.html">Data and downloads</a> · <a href="{REPO}">How it works</a> ·
<a href="{REPO}/issues">Report a mistake</a></p></footer></div>
</body></html>
"""


def _short(title: str) -> str:
    """Breadcrumb label: the part of the title before a colon ('Wednesday, … : what happened' -> 'Wednesday, …')."""
    return title.split(": ")[0] if ": " in title else title


CSS = """
@font-face{font-family:"Atkinson Hyperlegible";src:url(fonts/atkinson-hyperlegible-latin-400-normal.woff2) format("woff2");font-weight:400;font-display:swap}
@font-face{font-family:"Atkinson Hyperlegible";src:url(fonts/atkinson-hyperlegible-latin-700-normal.woff2) format("woff2");font-weight:700;font-display:swap}
:root{--ink:#16324F;--paper:#FFFFFF;--mark:#FFE45C;--quiet:#5F6B7A;--line:#D5DCE4;--soft:#F3F6F9}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;text-size-adjust:100%}
body{margin:0;background:var(--paper);color:var(--ink);font:1.125rem/1.6 "Atkinson Hyperlegible",system-ui,sans-serif}
.wrap{max-width:38rem;margin:0 auto;padding:0 1.25rem}
main{padding:0 0 3rem}
main:focus{outline:none}
a{color:var(--ink);text-decoration-thickness:2px;text-underline-offset:3px}
a:hover{text-decoration-thickness:3px}
:focus-visible{outline:3px solid var(--ink);outline-offset:3px}
a:focus-visible,summary:focus-visible{background:var(--mark)}
.skip{position:absolute;left:.5rem;top:-4rem;background:var(--mark);padding:.6rem 1rem;font-weight:700;z-index:10}
.skip:focus{top:.5rem}
header.site{border-bottom:1px solid var(--line);margin-bottom:1.25rem}
header.site .wrap{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:.25rem 1rem;padding-top:.6rem;padding-bottom:.6rem}
.brand{font-weight:700;text-decoration:none;padding:.4rem 0}
header.site ul{display:flex;gap:1.1rem;list-style:none;margin:0;padding:0}
header.site nav a{display:inline-block;padding:.4rem 0;font-size:1rem}
.crumbs ol{list-style:none;margin:0 0 1.75rem;padding:0;font-size:.95rem;color:var(--quiet)}
.crumbs li{display:inline}
.crumbs li+li::before{content:"›";margin:0 .45rem;color:var(--quiet)}
.crumbs a{color:var(--quiet);text-decoration-thickness:1px}
.crumbs [aria-current]{color:var(--quiet)}
h1{font-size:2.6rem;line-height:1.1;margin:0 0 .4rem;letter-spacing:-.01em}
.role{color:var(--quiet);margin:0 0 1.75rem}
.lede{font-size:1.35rem;line-height:1.5;font-weight:700;margin:0 0 1rem}
.lede mark,.hl{background:linear-gradient(transparent 12%,var(--mark) 12%,var(--mark) 88%,transparent 88%);color:inherit;padding:0 .15em;-webkit-box-decoration-break:clone;box-decoration-break:clone}
.fair{color:var(--quiet);font-size:1rem;margin:0 0 2.5rem}
h2{font-size:1.5rem;line-height:1.25;margin:3rem 0 .5rem}
h2+p{margin-top:0}
h3{font-size:1.2rem;margin:1.5rem 0 .3rem}
.decisions{list-style:none;padding:0;margin:1rem 0}
.decisions>li{padding:1.1rem 0;border-top:1px solid var(--line)}
.when{font-size:.95rem;color:var(--quiet);margin:0 0 .2rem}
.what{margin:0 0 .3rem}
.motion{font-size:1rem;color:var(--quiet);margin:0 0 .6rem}
.tally{display:flex;flex-wrap:wrap;gap:5px;margin:.4rem 0 .3rem}
.m{width:18px;height:18px;display:inline-block;border:2px solid var(--ink);flex:none}
.m.yes{background:var(--ink)}
.m.no{background:var(--mark);position:relative}
.m.no::before,.m.no::after{content:"";position:absolute;left:50%;top:-1px;width:2px;height:16px;background:var(--ink);transform:rotate(45deg)}
.m.no::after{transform:rotate(-45deg)}
.m.none{border-color:var(--quiet);border-radius:50%}
.m.me{outline:3px solid var(--ink);outline-offset:2px}
.outcome{font-size:1rem;margin:0 0 .3rem}
.said.no{background:var(--mark);padding:0 .2em}
.raw{color:var(--quiet)}
.src{font-size:1rem;margin:0}
.empty{color:var(--quiet)}
details{margin:.5rem 0 1rem}
summary{cursor:pointer;font-weight:700;padding:.5rem 0}
.key{display:flex;flex-wrap:wrap;gap:.4rem 1.25rem;font-size:1rem;margin:0 0 1rem;padding:0;list-style:none}
.key li{display:flex;align-items:center;gap:.45rem}
.people{list-style:none;padding:0;margin:1rem 0}
.people li{padding:1rem 0;border-top:1px solid var(--line)}
.people a{font-size:1.35rem;font-weight:700}
.people p{margin:.2rem 0 0}
.words dt{font-weight:700;margin-top:1.25rem;scroll-margin-top:1rem}
.words dd{margin:0}
.headline{font-weight:700;margin:0 0 .3rem}
.spot{margin:0 0 .35rem;line-height:1.9}
.tag{display:inline-block;font-size:.9rem;font-weight:700;line-height:1.3;padding:.1rem .5rem;border:2px solid var(--ink);text-decoration:none;margin-right:.35rem}
.tag.restriction{background:var(--ink);color:#fff}
.tag.business{border-style:dashed}
.tag.restriction:focus-visible{color:var(--ink)}
.tag.look{border-style:dotted}
.amount{font-weight:700;margin:0 0 .3rem}
.subject{font-size:1rem;color:var(--quiet);margin:0 0 .3rem}
.facts{margin:.2rem 0 .5rem;padding-left:1.2rem}
.facts li{margin:.1rem 0}
.means{font-size:1rem;margin:.3rem 0}
.means summary,.official summary{font-weight:400;padding:.2rem 0;text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:3px}
.means p,.official p{margin:.3rem 0 .6rem;padding-left:.9rem;border-left:3px solid var(--line)}
.who-voted{font-size:1rem;margin:0 0 .3rem}
.topic-count{color:var(--quiet);font-weight:400}
.meetings,.records{list-style:none;padding:0;margin:.5rem 0}
.meetings li,.records li{padding:.7rem 0;border-top:1px solid var(--line)}
.meetings a{font-weight:700}
.meetings p,.records p{margin:.1rem 0 0;font-size:1rem;color:var(--quiet)}
.records .title{font-weight:700;color:var(--ink);font-size:1.125rem;margin:0}
.learn{background:var(--soft);padding:.9rem 1rem;margin:1.5rem 0;font-size:1rem}
.areas{list-style:none;padding:0;margin:1rem 0}
.areas>li{border:2px solid var(--ink);padding:1rem 1.1rem;margin:0 0 1rem}
.areas h3{font-size:1.5rem;margin:0}
.areas .gov{color:var(--quiet);margin:0 0 .5rem;font-size:1rem}
.areas .go{list-style:none;padding:0;margin:.4rem 0 0}
.areas .go li{margin:.35rem 0}
.areas .go a{font-weight:700}
.areas .next{font-size:1rem;margin:.6rem 0 0}
.pager ul{list-style:none;padding:0;margin:2.5rem 0 0}
.pager li{margin:.5rem 0}
.links{padding-left:1.2rem}
.links li{margin:.35rem 0}
form.search{margin:1rem 0 .5rem}
form.search label{display:block;font-weight:700;margin:0 0 .3rem}
form.search .row{display:flex;gap:.5rem}
input[type=search]{flex:1;min-width:0;font:inherit;padding:.55rem .7rem;border:2px solid var(--ink);border-radius:0;color:var(--ink)}
button{font:inherit;font-weight:700;padding:.55rem 1rem;border:2px solid var(--ink);background:var(--ink);color:#fff;cursor:pointer}
fieldset{border:0;padding:0;margin:.6rem 0}
legend{font-size:1rem;color:var(--quiet);padding:0}
fieldset label{display:inline-flex;align-items:center;gap:.35rem;margin:.2rem 1.25rem .2rem 0;font-size:1rem}
input[type=radio]{width:1.1rem;height:1.1rem;accent-color:var(--ink)}
.small{font-size:1rem;color:var(--quiet)}
code{font-size:.95em}
footer.site{margin-top:2rem;padding:1rem 0 3rem;border-top:1px solid var(--line);font-size:.95rem;color:var(--quiet)}
footer.site a{color:var(--quiet)}
footer.site .source p{margin:0 0 .6rem}
@media (max-width:30rem){h1{font-size:2.1rem}.lede{font-size:1.2rem}}
@media (forced-colors:active){.m{forced-color-adjust:none;border-color:CanvasText}.m.yes{background:CanvasText}
.m.no{background:Canvas}.m.no::before,.m.no::after{background:CanvasText}.m.none{background:Canvas}
.lede mark,.hl,.said.no{forced-color-adjust:none;background:Mark;color:MarkText}}
@media print{.skip,header.site nav,.crumbs,form.search{display:none}a{text-decoration:none}
main a[href^="http"]::after{content:" (" attr(href) ")";font-size:.8em;word-break:break-all}}
"""


def write_assets(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "plain.css").write_text(CSS, "utf-8")
    fonts = out / "fonts"
    fonts.mkdir(exist_ok=True)
    for f in (STATIC / "fonts").iterdir():
        shutil.copy(f, fonts / f.name)
    if (STATIC / "share.png").exists():
        shutil.copy(STATIC / "share.png", out / "share.png")


# --- The front door -----------------------------------------------------------------------

AREAS = [  # (area, jurisdiction) in the order people asked for them
    ("Temple Terrace", "templeterrace"),
    ("Brandon", "hillsborough"),
    ("Lutz", "hillsborough"),
    ("Wesley Chapel", "pasco"),
    ("Spring Hill", "hernando"),
    ("New Smyrna Beach", "newsmyrnabeach"),  # added Nov 12, 2026 (Volusia County)
    ("Edgewater", "edgewater"),
    ("Oak Hill", "oakhill"),
]


def _meeting_dates(out: Path, county: str) -> list[str]:
    d = out / "meetings" / county
    return sorted(p.stem for p in d.glob("*.html")) if d.is_dir() else []


def home(out: Path, today: str, tt: dict, latest: dict[str, str] | None = None) -> str:
    """tt: {'latest': date, 'removed': n} for Temple Terrace. latest: {slug: newest meeting date} for
    governments without meeting pages (Oak Hill)."""
    latest = latest or {}
    cards = []
    for area, j in AREAS:
        jur = JURISDICTIONS[j]
        go: list[str] = []
        when = ""
        hub = jur.get("hub") or ("", "")
        if jur["govt"] == "city":
            gov = f"Has its own city government: the {e(jur['short'])} {e(jur['body'])}."
            if jur.get("county"):
                gov += f" In {e(jur['county'])} County."
        else:
            gov = (f"Has no city government. Local decisions are made by the "
                   f"{e(jur['name'])} Commission.")
        dates = _meeting_dates(out, j)
        if dates:
            go.append(f'<a href="meetings/{j}.html">What happened at each meeting</a>')
        if (out / jur["people_dir"] / f"{j}.html").exists():
            go.append(f'<a href="{jur["people_dir"]}/{j}.html">How each {jur["member"]} voted</a>')
        if j == "templeterrace":
            go.append('<a href="templeterrace.html">Search agendas and minutes, and see removed records</a>')
            if tt.get("latest") and not dates:
                when = f'Newest record: {e(long_date(tt["latest"]))}.'
        elif jur.get("blocked"):
            go.append(f'<a href="{e(jur["official_records"])}">The city\'s own agendas and minutes</a>')
            when = e(jur["blocked"])
        elif jur["govt"] == "city":
            go.append(f'<a href="{hub[1]}#{j}">'
                      + ("Agendas and minutes, archived and searchable" if not dates else "Search agendas, minutes and votes")
                      + "</a>")
            if latest.get(j) and not dates:
                when = f'Latest meeting on record: {e(weekday_date(latest[j]))}. Votes aren\'t read from its minutes yet.'
        past = [d for d in dates if d <= today]
        coming = [d for d in dates if d > today]
        bits = []
        if past:
            bits.append(f'Latest meeting: <a href="meetings/{j}/{past[-1]}.html">{e(weekday_date(past[-1]))}</a>.')
        if coming:
            bits.append(f'Next on the calendar: <a href="meetings/{j}/{coming[0]}.html">{e(weekday_date(coming[0]))}</a>.')
        if j == "hillsborough":
            bits.append("The Clerk publishes votes a few weeks after each meeting.")
        if j in ("pasco", "templeterrace"):
            bits.append("Votes are read from the Clerk's minutes, which come out a few weeks after each meeting.")
        if past or coming:
            when = " ".join(bits)
        feed = ("feed.xml" if j == "templeterrace" else f"feeds/{j}.xml" if jur["govt"] == "city"
                else f"feeds/area-{area.lower().replace(' ', '-')}.xml")
        if not jur.get("blocked"):
            go.append(f'<a href="{feed}">Get updates (RSS feed)</a>')
        cards.append(f'<li id="{area.lower().replace(" ", "-")}"><h3>{e(area)}</h3><p class="gov">{gov}</p>'
                     f'<ul class="go">{"".join(f"<li>{g}</li>" for g in go)}</ul>'
                     + (f'<p class="next">{when}</p>' if when else "") + "</li>")
    removed = ""
    if tt.get("removed"):
        n = tt["removed"]
        removed = (f'<h2>Records that disappeared</h2><p>The City of Temple Terrace has taken down '
                   f'{n} {"document" if n == 1 else "documents"} we archived. Our copies are still here, unchanged. '
                   f'<a href="templeterrace.html#removed">See what was removed</a>.</p>')
    body = f"""<h1>What your local government decided, in plain words</h1>
<p class="lede">Free, nonpartisan records of local government meetings around Tampa Bay and in southeast
Volusia County: what was decided, who voted which way, and the official papers, collected every night.</p>
<p class="fair">Everything here comes from official government websites and links back to them. We explain
what a decision was. We never say whether it was right.</p>
<h2 id="areas">Where do you live?</h2>
<p>If you live outside a city, your county commission is your local government. It decides zoning, roads
and county taxes for your neighborhood.</p>
<ul class="areas">{''.join(cards)}</ul>
<p class="small">More places are planned. Search <a href="counties.html">all three counties' records</a> or
<a href="volusia.html">southeast Volusia city records</a>.</p>
<h2>Spotlight</h2>
<p>New bans, moratoriums, fines and penalties, and tax breaks, incentives, land deals and no-bid purchases for
companies, across every government we follow. Each is tagged by fixed rules from the official wording.
<a href="spotlight.html">See the spotlight</a>.</p>
<h2>Public money to companies</h2>
<p>Every company the record shows these governments agreed to pay, with each decision, its vote and the
official record, plus plain facts worth a second look (no competitive bidding, money added to a contract,
approval over a no vote). <a href="companies.html">See who gets paid</a>.</p>
<h2>New to this?</h2>
<ul class="links"><li><a href="learn/land.html">How building and land decisions work</a></li>
<li><a href="learn/money.html">How county money works</a></li>
<li><a href="learn/index.html">Words you'll see, explained</a></li></ul>
<h2>Get updates</h2>
<p>Each area has an RSS feed: a list of new records that a feed reader app (for example Feedly, Inoreader or
NetNewsWire) checks for you. Email and text alerts are planned.</p>
{removed}
<h2>For researchers and reporters</h2>
<p>Every record is also available as a searchable database and as downloadable files.
<a href="data.html">Data and downloads</a>.</p>"""
    return page(f"{NAME}: what your local government decided", body, 0, path="index.html",
                description=("Free, nonpartisan, plain-language records of what Temple Terrace, Edgewater, Oak Hill and the "
                             "Hillsborough, Pasco and Hernando county commissions decided, and how each member voted."),
                jsonld=[{"@type": "WebSite", "name": NAME, "url": absolute("") or None, "inLanguage": "en",
                         "publisher": PUBLISHER, "isAccessibleForFree": True,
                         "about": [{"@type": "GovernmentOrganization", "name": JURISDICTIONS[j]["name"]}
                                   for j in JURISDICTIONS]}],
                feeds=[("Temple Terrace: new records", "feed.xml")]
                + [(f"{a}: county agenda items", f"feeds/area-{a.lower().replace(' ', '-')}.xml")
                   for a, j in AREAS if JURISDICTIONS[j]["govt"] == "county"]
                + [(f"{JURISDICTIONS[j]['name']}: new records", f"feeds/{j}.xml") for a, j in AREAS
                   if j != "templeterrace" and JURISDICTIONS[j]["govt"] == "city" and not JURISDICTIONS[j].get("blocked")])


# --- The glossary ----------------------------------------------------------------------------

MONEY_TERMS = ("millage", "contract", "grant", "budget", "cdd", "incentive")


def glossary() -> str:
    from .explain import TERMS
    groups = {"Land and building": [k for k in TERMS if k not in MONEY_TERMS and k not in ("consent", "ordinance")],
              "Money": [k for k in TERMS if k in MONEY_TERMS],
              "How meetings work": [k for k in TERMS if k in ("consent", "ordinance")]}
    blocks = []
    for g, keys in groups.items():
        items = []
        for k in keys:
            name, text, src = TERMS[k]
            items.append(f'<dt id="{e(k)}">{e(name)}</dt><dd>{e(text)}'
                         + (f' <a href="{e(src)}">Source</a>' if src else "") + "</dd>")
        if items:
            blocks.append(f'<h2>{e(g)}</h2><dl class="words">{"".join(items)}</dl>')
    body = f"""<h1>Words you'll see</h1>
<p class="lede">Agendas are written in clerk shorthand. Here is what the terms on our pages mean, each with
the official source where one exists.</p>
<ul class="links"><li><a href="land.html">How building and land decisions work</a></li>
<li><a href="money.html">How county money works</a></li></ul>
{''.join(blocks)}"""
    terms = [{"@type": "DefinedTerm", "@id": absolute(f"learn/index.html#{k}") or None, "termCode": k,
              "name": TERMS[k][0], "description": TERMS[k][1], **({"url": TERMS[k][2]} if TERMS[k][2] else {})}
             for k in TERMS]
    return page("Words you'll see", body, 1, path="learn/index.html", crumbs=[],
                description="Plain-language meanings of the zoning, land-use and budget terms in local government agendas, with sources.",
                jsonld=[{"@type": "DefinedTermSet", "name": "Local government terms, in plain words",
                         "url": absolute("learn/index.html") or None, "hasDefinedTerm": terms}])


# --- Data and downloads ----------------------------------------------------------------------

def _size(p: Path) -> str:
    if not p.exists():
        return ""
    n = p.stat().st_size
    return f"{n / 1e6:.0f} MB" if n >= 1e6 else f"{max(1, round(n / 1e3))} KB"


def data_page(out: Path, lite: dict[str, str]) -> str:
    """lite: {database file name: its Datasette Lite URL}."""
    def dl(name: str, label: str, fmt: str, what: str, browse: str = "") -> tuple[str, dict]:
        size = _size(out / name)
        html_ = (f'<li><p class="title"><a href="{e(name)}">{e(label)}</a></p>'
                 f'<p>{e(fmt)}{", " + size if size else ""}. {what}'
                 + (f' <a href="{e(browse)}">Browse it in your browser</a> (downloads the whole file first).' if browse else "")
                 + "</p></li>")
        return html_, {"@type": "DataDownload", "name": label, "encodingFormat": fmt,
                       "contentUrl": absolute(name) or name, **({"contentSize": size} if size else {})}

    tt_db, tt_db_ld = dl("templeterrace.db", "Temple Terrace database", "SQLite",
                         "Every archived agenda, packet and minutes page (full-text searchable), agenda items, roll-call "
                         "votes read from the minutes, contracts, vendors and the change log.",
                         lite.get("templeterrace.db", ""))
    tt_ftm, tt_ftm_ld = dl("templeterrace.ftm.jsonl", "Temple Terrace entities", "FollowTheMoney JSON lines",
                           "Officials, organisations, contracts and meetings in the open FollowTheMoney format.")
    c_db, c_db_ld = dl("counties.db", "County commissions database", "SQLite",
                       "Meetings, agenda items and each commissioner's vote for Hillsborough (votes since 2014), "
                       "Pasco (votes read from the Clerk's minutes) and Hernando (since 2025), with archived document pages.",
                       lite.get("counties.db", ""))
    c_ftm, c_ftm_ld = dl("counties.ftm.jsonl", "County entities", "FollowTheMoney JSON lines",
                         "Each county and board, each commissioner and their membership, each meeting and archived document.")
    v_db, v_db_ld = dl("volusia.db", "Southeast Volusia cities database", "SQLite",
                       "Meetings, agenda items and each council member's vote for Edgewater (from 2025), and Oak Hill's "
                       "archived agendas and minutes (full-text searchable).", lite.get("volusia.db", ""))
    v_ftm, v_ftm_ld = dl("volusia.ftm.jsonl", "Southeast Volusia entities", "FollowTheMoney JSON lines",
                         "Each city and board, each council member and their membership, each meeting and archived document.")
    if not (out / "volusia.ftm.jsonl").exists():
        v_ftm, v_ftm_ld = "", None
    feeds = sorted(p.name for p in (out / "feeds").glob("*.xml")) if (out / "feeds").is_dir() else []
    feed_items = ['<li><a href="feed.xml">Temple Terrace: everything new</a></li>'] + [
        f'<li><a href="feeds/{e(f)}">{e(_feed_label(f))}</a></li>' for f in feeds]
    body = f"""<h1>Data and downloads</h1>
<p class="lede">Everything on this site is free to download, query and republish. Each record links to the
official source it came from.</p>
<p class="fair">These are public records, read by software. Votes, amounts and names can be misread: check the
official record before relying on a detail, and <a href="{REPO}/issues">tell us</a> if something is wrong.</p>
<h2>Databases</h2>
<ul class="records">{tt_db}{c_db}{v_db}</ul>
<p class="small">Tables are described inside each database (Datasette shows the descriptions).
SQLite opens in <a href="https://datasette.io">Datasette</a>, DB Browser for SQLite, Python, R and most data tools.</p>
<h2>People, organisations and meetings</h2>
<ul class="records">{tt_ftm}{c_ftm}{v_ftm}</ul>
<p class="small"><a href="https://followthemoney.tech">FollowTheMoney</a> is the open data model used by
OpenSanctions and Aleph. People appear only in their public roles (from roll-call votes), never from public comment.</p>
<h2>Feeds</h2>
<ul class="links">{''.join(feed_items)}</ul>
<h2>Raw files and history</h2>
<p>The <a href="{REPO}/tree/main/data">data folder on GitHub</a> holds every listing, the fingerprint
log (<code>manifest.jsonl</code>: when each document appeared, changed or was removed) and the extracted
text. Copies of every document version are in the
<a href="{REPO}/releases/tag/files">files release</a>, named by their SHA-256 fingerprint.</p>
<h2>For software and AI tools</h2>
<p>A plain-text map of this site is at <a href="llms.txt">llms.txt</a>, and every page is listed in
<a href="sitemap.xml">sitemap.xml</a>. Pages carry schema.org data (meetings as Events, commissioners as
People, terms as DefinedTerms). Please identify your tool and keep request rates low.</p>"""
    common = {"creator": PUBLISHER, "isAccessibleForFree": True, "inLanguage": "en",
              "isBasedOn": "Official public records of each government; every record links to its source."}
    datasets = [
        {"@type": "Dataset", "name": "Temple Terrace City Council records",
         "description": "Agendas, packets, minutes, agenda items, roll-call votes and contracts of the Temple Terrace, Florida City Council, archived nightly with SHA-256 fingerprints and a change log.",
         "spatialCoverage": "Temple Terrace, Florida", "temporalCoverage": "2025-10/..",
         "distribution": [tt_db_ld, tt_ftm_ld], **common},
        {"@type": "Dataset", "name": "Tampa Bay county commission records",
         "description": "Meetings, agenda items and per-member roll-call votes of the Hillsborough (2014 on), Pasco and Hernando (2025 on) county commissions in Florida.",
         "spatialCoverage": ["Hillsborough County, Florida", "Pasco County, Florida", "Hernando County, Florida"],
         "temporalCoverage": "2014-01/..", "distribution": [c_db_ld, c_ftm_ld], **common},
        {"@type": "Dataset", "name": "Southeast Volusia city records",
         "description": "Meetings, agenda items and per-member roll-call votes of the Edgewater, Florida City Council, and the archived agendas and minutes of the Oak Hill, Florida City Commission, from 2025.",
         "spatialCoverage": ["Edgewater, Florida", "Oak Hill, Florida"],
         "temporalCoverage": "2025-01/..", "distribution": [x for x in (v_db_ld, v_ftm_ld) if x], **common},
    ]
    return page("Data and downloads", body, 0, path="data.html",
                description="Free downloads of Temple Terrace, Tampa Bay county commission and southeast Volusia city records: SQLite databases, FollowTheMoney entities, RSS feeds and raw files.",
                jsonld=[{"@type": "DataCatalog", "name": f"{NAME} data", "url": absolute("data.html") or None,
                         "publisher": PUBLISHER, "dataset": datasets}])


def _feed_label(name: str) -> str:
    stem = name[:-4]
    if stem.startswith("area-"):
        return f"{stem[5:].replace('-', ' ').title()}: county agenda items naming the area"
    if stem in JURISDICTIONS:
        return f"{JURISDICTIONS[stem]['name']}: everything new"
    return f"Temple Terrace: {stem.replace('-', ' ')}"


# --- For machines ----------------------------------------------------------------------------

def sitemap(out: Path) -> str:
    urls = sorted(p.relative_to(out).as_posix() for p in out.rglob("*.html"))
    first = ["index.html", "learn/index.html", "data.html"]
    urls = [u for u in first if u in urls] + [u for u in urls if u not in first]
    body = "".join(f"<url><loc>{e(absolute(u))}</loc></url>\n" for u in urls)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{body}</urlset>\n')


def llms_txt(out: Path) -> str:
    def u(p: str) -> str:
        return absolute(p) or p
    lines = []
    for j in JURISDICTIONS:
        jur = JURISDICTIONS[j]
        if (out / "meetings" / f"{j}.html").exists():
            lines.append(f"- [{jur['board']} meetings]({u(f'meetings/{j}.html')}): one page per meeting, decisions "
                         "grouped by topic with plain headlines, outcomes and who voted no")
        if (out / jur["people_dir"] / f"{j}.html").exists():
            lines.append(f"- [{jur['board']} members]({u(jur['people_dir'] + '/' + j + '.html')}): each member's recorded votes")
    counties = "\n".join(lines)
    people = ""
    return f"""# {NAME}

> Free, nonpartisan, plain-language public records of local government in Florida: around Tampa Bay, the
> Temple Terrace City Council and the Hillsborough, Pasco and Hernando county commissions (which govern
> Brandon, Lutz, Wesley Chapel and Spring Hill); in southeast Volusia County, the Edgewater City Council and
> the Oak Hill City Commission. Collected nightly from official sources; every record links to its source.
> Headlines are produced by fixed rules, not AI, and the official wording is always shown.

Pages count recorded votes; they never say why anyone voted or whether a decision was good. Hillsborough votes
come from the Clerk's Master Voting Record (2014 on); Pasco and Temple Terrace votes are read from the Clerk's minutes;
Hernando and Edgewater votes come from their Legistar records. New Smyrna Beach isn't collected: its records site asks
automated tools not to.

## Start here

- [Home: pick an area]({u('index.html')})
- [Temple Terrace City Council records]({u('templeterrace.html')})
- [County commission records and search]({u('counties.html')})
- [Southeast Volusia city records and search]({u('volusia.html')}): Edgewater, Oak Hill, New Smyrna Beach
- [Public money to companies]({u('companies.html')}): companies and organizations the governments agreed to pay (contracts, purchases, change orders, grants), decision by decision, with approved amounts (not payments) and factual flags (no competitive bidding, money added to a contract, approved over a no vote, $1 million or more on consent, conflict-of-interest abstentions)
- [Spotlight]({u('spotlight.html')}): decisions tagged by fixed rules as new restrictions (bans, moratoriums, fines) or as money, land or breaks for companies (tax breaks, incentives, land sales and leases, no-bid purchases of $100,000 or more)
{counties}
{people}

## Explanations

- [Words you'll see]({u('learn/index.html')}): defined terms with official sources
- [How building and land decisions work]({u('learn/land.html')})
- [How county money works]({u('learn/money.html')})

## Data

- [Data and downloads]({u('data.html')}): SQLite databases, FollowTheMoney entities, RSS feeds
- [Sitemap]({u('sitemap.xml')})
- [Source code and raw data]({REPO})

## Optional

- [Temple Terrace database (SQLite)]({u('templeterrace.db')})
- [County commissions database (SQLite)]({u('counties.db')})
- [Southeast Volusia cities database (SQLite)]({u('volusia.db')})
"""


def write_common(out: Path, *, today: str, tt: dict, lite: dict[str, str] | None = None,
                 latest: dict[str, str] | None = None) -> dict:
    """Write the front door, glossary, data page, sitemap and llms.txt. Call after every other page exists."""
    write_assets(out)
    (out / "learn").mkdir(parents=True, exist_ok=True)
    (out / "learn" / "index.html").write_text(glossary(), "utf-8")
    (out / "data.html").write_text(data_page(out, lite or {}), "utf-8")
    (out / "index.html").write_text(home(out, today, tt, latest), "utf-8")
    (out / "llms.txt").write_text(llms_txt(out), "utf-8")
    sm = sitemap(out)
    if SITE_URL:
        (out / "sitemap.xml").write_text(sm, "utf-8")
    return {"pages": sm.count("<url>")}
