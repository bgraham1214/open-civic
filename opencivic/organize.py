"""One way to organize a long list, for every page that has one.

The user (Nov 19, 2026): "organization for this site would be very beneficial. There's a lot of text, grouping
headers into categories and collapsing items to reduce clutter seems helpful", and for the Spotlight, "give me
options at the top of the page ... drop downs". We're "going to do the whole site in a similar style", so this is
the style: reuse it, adapt it where a page needs something else.

A list is a set of items (each an <li class="card"> carrying data attributes) shown in groups that fold, under a
bar of dropdowns: "Group by" (each item names its group under every grouping) and filters ("Show", "When", ...).
The page is built grouped by the first grouping with every filter off, so it reads the same without JavaScript;
organize.js (written once to the site root) regroups and filters in place, keeps the choice in the address
(?group=county&when=min:2026-08-21) so a view can be shared, and says how many items are shown.

Group order: "count" (most items first), "asc" or "desc" (by each group's sort value). Inside a group, items keep
the order they're given in (newest first, usually).

Filter values: "" shows everything; "min:YYYY-MM-DD" keeps items dated on or after; "after:YYYY-MM-DD" keeps items
dated after; "span:FROM:TO" keeps items dated FROM to TO; anything else must be one of the item's space-separated
values for that filter.
"""
from __future__ import annotations

import html
from dataclasses import dataclass, field


def _e(s) -> str:
    return html.escape(str(s or ""), quote=True)


@dataclass
class Grouping:
    key: str           # "topic"
    label: str         # "Topic"
    order: str = "count"


@dataclass
class Filter:
    key: str                          # "kind"
    label: str                        # "Show"
    options: list[tuple[str, str]]    # [(value, label)]; the first is the default


@dataclass
class Item:
    html: str                                   # inside the <li>
    groups: dict[str, tuple[str, str]]          # grouping key -> (group label, sort value)
    filters: dict[str, str] = field(default_factory=dict)
    date: str = ""


def _sorted_groups(names: dict[str, list], sort: dict[str, str], order: str) -> list[str]:
    if order == "asc":
        return sorted(names, key=lambda n: (n == "Other", sort.get(n, n).lower()))
    if order == "desc":
        return sorted(names, key=lambda n: (n != "Other", sort.get(n, n).lower()), reverse=True)
    return sorted(names, key=lambda n: (n == "Other", -len(names[n]), n.lower()))


def _li(it: Item) -> str:
    attrs = "".join(f' data-g-{_e(k)}="{_e(v[0])}"' + (f' data-s-{_e(k)}="{_e(v[1])}"' if v[1] != v[0] else "")
                    for k, v in it.groups.items())
    attrs += "".join(f' data-f-{_e(k)}="{_e(v)}"' for k, v in it.filters.items())
    if it.date:
        attrs += f' data-date="{_e(it.date)}"'
    return f'<li class="card"{attrs}>{it.html}</li>'


def render(list_id: str, items: list[Item], groupings: list[Grouping], filters: list[Filter] = (),
           level: int = 2, noun: tuple[str, str] = ("item", "items"), label: str = "Arrange this list") -> str:
    """The dropdown bar and the folded groups, grouped by groupings[0]."""
    g0 = groupings[0]
    buckets: dict[str, list[Item]] = {}
    sort: dict[str, str] = {}
    for it in items:
        name, s = it.groups.get(g0.key, ("Other", "~"))
        buckets.setdefault(name, []).append(it)
        sort.setdefault(name, s)
    groups = "".join(
        f'<details class="grp" data-group="{_e(n)}"><summary><h{level} class="grp-h">{_e(n)} '
        f'<span class="grp-n">({len(buckets[n]):,})</span></h{level}></summary>'
        f'<ol class="cards">{"".join(_li(it) for it in buckets[n])}</ol></details>'
        for n in _sorted_groups(buckets, sort, g0.order))
    gopts = "".join(f'<option value="{_e(g.key)}" data-order="{_e(g.order)}">{_e(g.label)}</option>' for g in groupings)
    fields = [f'<div class="org-field"><label for="{list_id}-group">Group by</label>'
              f'<select id="{list_id}-group" data-org="group">{gopts}</select></div>']
    for f in filters:
        opts = "".join(f'<option value="{_e(v)}">{_e(lab)}</option>' for v, lab in f.options)
        fields.append(f'<div class="org-field"><label for="{list_id}-{_e(f.key)}">{_e(f.label)}</label>'
                      f'<select id="{list_id}-{_e(f.key)}" data-org="filter" data-key="{_e(f.key)}">{opts}</select></div>')
    n = len(items)
    count = f'{n:,} {noun[0] if n == 1 else noun[1]} in {len(buckets)} {"group" if len(buckets) == 1 else "groups"}'
    return (f'<div class="org" id="{_e(list_id)}" data-level="{level}" data-noun="{_e(noun[0])}|{_e(noun[1])}">'
            f'<form class="org-bar" aria-label="{_e(label)}" hidden onsubmit="return false">{"".join(fields)}'
            f'<button type="button" data-org="all" aria-pressed="false">Open all</button></form>'
            f'<p class="org-count small" role="status">{_e(count)}</p>'
            f'<div class="org-groups">{groups}</div></div>')


JS = r"""/* organize.js: regroup and filter the lists built by opencivic/organize.py. */
(function () {
  function words(s) { return ' ' + (s || '') + ' '; }
  document.querySelectorAll('.org').forEach(function (org) {
    var bar = org.querySelector('.org-bar'), box = org.querySelector('.org-groups'), status = org.querySelector('.org-count');
    if (!bar || !box) return;
    bar.hidden = false;
    var items = Array.prototype.slice.call(org.querySelectorAll('li.card'));
    var gsel = bar.querySelector('[data-org=group]'), fsels = Array.prototype.slice.call(bar.querySelectorAll('[data-org=filter]'));
    var allBtn = bar.querySelector('[data-org=all]');
    var level = org.getAttribute('data-level') || '2', noun = (org.getAttribute('data-noun') || 'item|items').split('|');
    var multi = document.querySelectorAll('.org').length > 1, pre = multi ? org.id + '-' : '';
    var params = new URLSearchParams(location.search), lastKey = gsel.value;
    function setFrom(sel, name) {
      var v = params.get(pre + name);
      if (v !== null && Array.prototype.some.call(sel.options, function (o) { return o.value === v; })) sel.value = v;
    }
    setFrom(gsel, 'group');
    fsels.forEach(function (s) { setFrom(s, s.getAttribute('data-key')); });
    function pass(li) {
      for (var i = 0; i < fsels.length; i++) {
        var v = fsels[i].value, d = li.getAttribute('data-date') || '';
        if (!v) continue;
        if (v.indexOf('min:') === 0) { if (d < v.slice(4)) return false; }
        else if (v.indexOf('after:') === 0) { if (d <= v.slice(6)) return false; }
        else if (v.indexOf('span:') === 0) { var r = v.split(':'); if (d < r[1] || d > r[2]) return false; }
        else if (words(li.getAttribute('data-f-' + fsels[i].getAttribute('data-key'))).indexOf(' ' + v + ' ') < 0) return false;
      }
      return true;
    }
    function draw(initial) {
      var key = gsel.value, order = gsel.options[gsel.selectedIndex].getAttribute('data-order') || 'count';
      var open = {};
      if (key === lastKey) box.querySelectorAll('details.grp[open]').forEach(function (d) { open[d.getAttribute('data-group')] = 1; });
      var buckets = {}, names = [], shown = 0;
      items.forEach(function (li) {
        if (!pass(li)) return;
        var g = li.getAttribute('data-g-' + key) || 'Other';
        if (!buckets[g]) { buckets[g] = {li: [], s: (li.getAttribute('data-s-' + key) || g).toLowerCase()}; names.push(g); }
        buckets[g].li.push(li); shown++;
      });
      names.sort(function (a, b) {
        if ((a === 'Other') !== (b === 'Other')) return a === 'Other' ? 1 : -1;
        if (order === 'asc') return buckets[a].s < buckets[b].s ? -1 : buckets[a].s > buckets[b].s ? 1 : 0;
        if (order === 'desc') return buckets[a].s > buckets[b].s ? -1 : buckets[a].s < buckets[b].s ? 1 : 0;
        return (buckets[b].li.length - buckets[a].li.length) || (a.toLowerCase() < b.toLowerCase() ? -1 : 1);
      });
      var frag = document.createDocumentFragment();
      names.forEach(function (name) {
        var d = document.createElement('details'), s = document.createElement('summary'), h = document.createElement('h' + level);
        var n = document.createElement('span'), ol = document.createElement('ol');
        d.className = 'grp'; d.setAttribute('data-group', name); if (open[name]) d.open = true;
        h.className = 'grp-h'; h.appendChild(document.createTextNode(name + ' '));
        n.className = 'grp-n'; n.textContent = '(' + buckets[name].li.length.toLocaleString() + ')'; h.appendChild(n);
        s.appendChild(h); d.appendChild(s);
        ol.className = 'cards'; buckets[name].li.forEach(function (li) { ol.appendChild(li); }); d.appendChild(ol);
        frag.appendChild(d);
      });
      box.innerHTML = '';
      box.appendChild(frag);
      status.textContent = shown.toLocaleString() + ' ' + (shown === 1 ? noun[0] : noun[1]) + ' in ' + names.length +
        (names.length === 1 ? ' group' : ' groups') + (shown ? '' : '. Try another choice above.');
      allBtn.textContent = 'Open all'; allBtn.setAttribute('aria-pressed', 'false');
      lastKey = key;
      if (!initial) {
        var q = new URLSearchParams(location.search);
        [[gsel, 'group']].concat(fsels.map(function (f) { return [f, f.getAttribute('data-key')]; })).forEach(function (p) {
          if (p[0].selectedIndex) q.set(pre + p[1], p[0].value); else q.delete(pre + p[1]);
        });
        var qs = q.toString();
        history.replaceState(null, '', location.pathname + (qs ? '?' + qs : '') + location.hash);
      }
    }
    gsel.addEventListener('change', function () { draw(false); });
    fsels.forEach(function (s) { s.addEventListener('change', function () { draw(false); }); });
    allBtn.addEventListener('click', function () {
      var opening = allBtn.getAttribute('aria-pressed') !== 'true';
      box.querySelectorAll('details.grp').forEach(function (d) { d.open = opening; });
      allBtn.setAttribute('aria-pressed', opening ? 'true' : 'false');
      allBtn.textContent = opening ? 'Close all' : 'Open all';
    });
    draw(true);
  });
})();
"""

CSS = """
.org-bar{display:flex;flex-wrap:wrap;gap:.75rem 1rem;align-items:flex-end;margin:1.5rem 0 .4rem;padding:.9rem 1rem;background:var(--soft);border:1px solid var(--line);border-radius:8px}
.org-field{display:flex;flex-direction:column;gap:.2rem;flex:1 1 9rem;min-width:0}
.org-field label{font-size:.9rem;font-weight:700}
.org-field select{width:100%}
.org-bar button,.btn{font:inherit;font-size:1rem;padding:.5rem .9rem;border:2px solid var(--ink);border-radius:6px;background:#fff;color:var(--ink);cursor:pointer}
.org-bar button:hover,.btn:hover{background:var(--soft)}
.org-count{margin:.3rem 0 .6rem;color:var(--quiet)}
.org-groups{border-bottom:1px solid var(--line)}
details.grp{margin:0;border-top:1px solid var(--line)}
details.grp>summary{list-style:none;display:flex;align-items:center;gap:.7rem;padding:.8rem 0}
details.grp>summary::-webkit-details-marker{display:none}
details.grp>summary::before{content:"";flex:none;width:.6rem;height:.6rem;margin:0 .15rem 0 .2rem;border-right:2.5px solid var(--ink);border-bottom:2.5px solid var(--ink);transform:rotate(-45deg)}
details.grp[open]>summary::before{transform:rotate(45deg) translate(-2px,-2px)}
.grp-h{font-size:1.15rem;line-height:1.3;margin:0}
.grp-n{color:var(--quiet);font-weight:400}
ol.cards{list-style:none;padding:0;margin:0 0 1rem}
.cards>li{padding:.15rem 0 .15rem .9rem;border-left:3px solid var(--line);margin:0 0 1.1rem}
.cards .spot{margin:0 0 .2rem}
.cards .headline{margin:0 0 .1rem}
.meta{font-size:.95rem;color:var(--quiet);margin:0}
.meta a{color:var(--quiet);text-decoration-thickness:1px}
details.more{margin:.2rem 0 0;font-size:1rem}
details.more>summary{font-weight:400;padding:.15rem 0;text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:3px;color:var(--quiet)}
details.more[open]{padding-bottom:.3rem}
details.more .subject{margin-top:.3rem}
.soon{border:2px solid var(--ink);border-radius:8px;padding:.1rem 1rem .3rem;margin:1.5rem 0 0}
.soon h2{margin:.7rem 0 .2rem}
.soon .cards>li{margin-top:.8rem}
.org-field.wide{flex:2 1 14rem}
ol.rank{list-style:none;padding:0;margin:.6rem 0 1rem;counter-reset:r}
ol.rank>li{counter-increment:r;display:grid;grid-template-columns:2.4rem 1fr;column-gap:.8rem;padding:.75rem 0;border-top:1px solid var(--line)}
ol.rank>li:last-child{border-bottom:1px solid var(--line)}
ol.rank>li::before{content:counter(r);grid-row:1 / span 3;align-self:start;font-size:1.2rem;font-weight:700;line-height:2.2rem;text-align:center;background:var(--soft);border-radius:6px}
ol.rank>li:nth-child(-n+3)::before{background:var(--mark)}
ol.rank>li>*{grid-column:2}
.rank .nm{font-weight:700;margin:0;line-height:1.35}
.rank .fig{margin:.1rem 0 0;font-size:1rem}
.toplist h2{margin-top:2rem}
.toplist h2+.small{margin:0}
"""
