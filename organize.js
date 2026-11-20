/* organize.js: regroup and filter the lists built by opencivic/organize.py. */
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
