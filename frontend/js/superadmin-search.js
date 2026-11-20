/* ScribeKare Super Admin: global search + quick-jump command palette.
   Open with Ctrl+K (Cmd+K) or "/". Type to search hospitals, staff accounts, leads, plan inquiries, upgrade requests,
   payments and activity (GET /admin/sa/search, never patients). Arrow keys move, Enter opens, Esc closes.
   Results are grouped by type with the hospital name next to each. Text is written with text nodes only. */
(function () {
  'use strict';
  var SA = window.SA;
  if (!SA) return;
  var h = SA.h;
  var GROUPS = [['hospitals', 'Hospitals'], ['staff', 'Staff accounts'], ['leads', 'Hospital leads'], ['inquiries', 'Plan inquiries'],
    ['requests', 'Upgrade requests'], ['payments', 'Payments'], ['audit', 'Activity']];
  var COMMANDS = [
    { label: 'Overview', href: '#/home' }, { label: 'Hospitals', href: '#/hospitals' }, { label: 'Revenue & plans', href: '#/overview' },
    { label: 'Platform analytics', href: '#/analytics' }, { label: 'Master catalogs', href: '#/master-catalogs' },
    { label: 'Upgrade requests', href: '#/upgrade-requests' }, { label: 'Hospital leads', href: '#/hospital-leads' },
    { label: 'Plan inquiries', href: '#/plan-inquiries' }, { label: 'Suggestions', href: '#/suggestions' }, { label: 'Activity', href: '#/activity' },
    { label: 'Open notifications', run: function () { if (typeof toggleNotifPanel === 'function') toggleNotifPanel(); } },
    { label: 'Add hospital', run: function () { if (typeof openHospitalModal === 'function') openHospitalModal(); } },
    { label: 'My account & security', run: function () { if (typeof openEditDetailsModal === 'function') openEditDetailsModal(); } }
  ];

  var overlay, input, list, items = [], idx = -1, timer = null, seq = 0, lastFocus = null;

  function build() {
    overlay = h('div', 'sa-pal-overlay');
    var box = h('div', 'sa-pal');
    box.setAttribute('role', 'dialog'); box.setAttribute('aria-modal', 'true'); box.setAttribute('aria-label', 'Search and quick jump');
    input = h('input', 'sa-pal-input');
    input.type = 'text'; input.placeholder = 'Search hospitals, staff, leads, payments\u2026 or jump to a section';
    input.setAttribute('role', 'combobox'); input.setAttribute('aria-expanded', 'true'); input.setAttribute('aria-controls', 'sa-pal-list');
    input.setAttribute('aria-autocomplete', 'list'); input.setAttribute('autocomplete', 'off'); input.setAttribute('spellcheck', 'false');
    list = h('div', 'sa-pal-list'); list.id = 'sa-pal-list'; list.setAttribute('role', 'listbox');
    var foot = h('div', 'sa-pal-foot', [h('span', null, '\u2191\u2193 move'), h('span', null, 'Enter open'), h('span', null, 'Esc close')]);
    box.append(input, list, foot);
    overlay.append(box);
    document.body.append(overlay);
    overlay.addEventListener('mousedown', function (e) { if (e.target === overlay) close(); });
    input.addEventListener('input', onType);
    input.addEventListener('keydown', onKey);
    list.addEventListener('mousemove', function (e) { var el = e.target.closest('.sa-pal-item'); if (el) select(items.indexOf(el._item)); });
    list.addEventListener('click', function (e) { var el = e.target.closest('.sa-pal-item'); if (el) activate(el._item); });
  }

  function open() {
    if (!overlay) build();
    lastFocus = document.activeElement;
    overlay.classList.add('open');
    input.value = '';
    renderResults('', null, false);
    input.focus();
  }
  function close() {
    if (!overlay) return;
    overlay.classList.remove('open');
    clearTimeout(timer); seq++;
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }
  function isOpen() { return overlay && overlay.classList.contains('open'); }

  function select(i) {
    if (!items.length) { idx = -1; input.removeAttribute('aria-activedescendant'); return; }
    idx = (i + items.length) % items.length;
    items.forEach(function (it, n) { it.el.setAttribute('aria-selected', n === idx ? 'true' : 'false'); });
    input.setAttribute('aria-activedescendant', items[idx].el.id);
    items[idx].el.scrollIntoView({ block: 'nearest' });
  }
  function activate(it) {
    if (!it) return;
    close();
    if (it.run) it.run(); else if (it.href) SA.go(it.href);
  }

  function addGroup(title) { list.append(h('div', 'sa-pal-group', title)); }
  function addItem(label, sub, chip, target) {
    var el = h('div', 'sa-pal-item');
    el.id = 'sa-opt-' + items.length;
    el.setAttribute('role', 'option'); el.setAttribute('aria-selected', 'false');
    el.append(h('div', 'sa-pal-main', [h('div', 'sa-pal-label', label), sub ? h('div', 'sa-pal-sub', sub) : null]));
    if (chip) el.append(h('span', 'sa-pal-chip', chip));
    var it = { el: el, href: target.href, run: target.run };
    el._item = it;
    items.push(it);
    list.append(el);
  }

  function renderResults(q, data, loading, error) {
    list.textContent = '';
    items = []; idx = -1;
    var ql = q.toLowerCase();
    var cmds = COMMANDS.filter(function (c) { return !ql || c.label.toLowerCase().indexOf(ql) >= 0; }).slice(0, ql ? 5 : 13);
    if (cmds.length) {
      addGroup(ql ? 'Quick jump' : 'Go to');
      cmds.forEach(function (c) { addItem(c.label, null, null, c); });
    }
    if (q.length >= 2) {
      if (loading) list.append(h('div', 'sa-pal-note', 'Searching\u2026'));
      else if (error) list.append(h('div', 'sa-pal-note', error));
      else if (data) {
        var any = false;
        GROUPS.forEach(function (g) {
          var rows = data[g[0]] || [];
          if (!rows.length) return;
          any = true;
          addGroup(g[1]);
          rows.forEach(function (r) {
            var label = g[0] === 'payments' ? SA.inr(r.amount) + ' \u00B7 ' + r.label : r.label;
            var chip = r.hospital_name && r.hospital_name !== r.label ? r.hospital_name : null;
            addItem(label, r.sub, chip, { href: r.link });
          });
        });
        if (!any) list.append(h('div', 'sa-pal-note', 'No matches for \u201C' + q + '\u201D.'));
      }
    } else if (q.length === 1) {
      list.append(h('div', 'sa-pal-note', 'Type at least 2 characters to search.'));
    }
    select(0);
  }

  function onType() {
    var q = input.value.trim();
    clearTimeout(timer);
    var my = ++seq;
    if (q.length < 2) { renderResults(q, null, false); return; }
    renderResults(q, null, true);
    timer = setTimeout(function () {
      api('GET', '/admin/sa/search?q=' + encodeURIComponent(q), null, false, true).then(function (d) {
        if (my === seq && isOpen()) renderResults(q, d, false);
      }).catch(function (e) {
        if (my === seq && isOpen()) renderResults(q, null, false, e.message || 'Search failed. Try again.');
      });
    }, 250);
  }

  function onKey(e) {
    if (e.key === 'ArrowDown') { e.preventDefault(); select(idx + 1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); select(idx - 1); }
    else if (e.key === 'Enter') { e.preventDefault(); if (idx >= 0) activate(items[idx]); }
    else if (e.key === 'Escape') { e.preventDefault(); close(); }
    else if (e.key === 'Tab') { e.preventDefault(); }
  }

  function isEditable(el) {
    if (!el) return false;
    var t = el.tagName;
    return t === 'INPUT' || t === 'TEXTAREA' || t === 'SELECT' || el.isContentEditable;
  }
  document.addEventListener('keydown', function (e) {
    if ((e.ctrlKey || e.metaKey) && !e.altKey && (e.key === 'k' || e.key === 'K')) { e.preventDefault(); if (isOpen()) close(); else open(); return; }
    if (e.key === '/' && !e.ctrlKey && !e.metaKey && !e.altKey && !isOpen() && !isEditable(document.activeElement)) { e.preventDefault(); open(); }
  });

  function addTopbarButton() {
    var bar = document.querySelector('.topbar');
    if (!bar || document.getElementById('sa-search-btn')) return;
    var b = h('button', 'sa-search-btn');
    b.id = 'sa-search-btn'; b.type = 'button';
    b.setAttribute('aria-label', 'Search (Ctrl+K)');
    b.innerHTML = '<svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path stroke-linecap="round" d="M21 21l-4.35-4.35"/></svg>';
    b.append(h('span', 'sa-search-text', 'Search'), h('span', 'sa-kbd', 'Ctrl K'));
    b.addEventListener('click', open);
    var doctor = bar.querySelector('.topbar-doctor');
    if (doctor) bar.insertBefore(b, doctor); else bar.append(b);
  }
  addTopbarButton();
  SA.openSearch = open;
})();