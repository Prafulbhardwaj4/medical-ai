/* ScribeKare Super Admin, part 3: cross-linking, preserved filters, keyboard shortcuts, mobile polish.
   Loaded LAST on superadmin.html (after superadmin-search.js). Design decisions:
   - Every list section (#/upgrade-requests, #/hospital-leads, #/plan-inquiries, #/suggestions) understands
     ?id=<record> (scroll to it, flash it; suggestions also open the detail modal) and ?status=<status>.
     Leads also keep q, state and city in the hash. Analytics keeps its pane (?pane=).
   - Filters are remembered per section in sessionStorage; breadcrumb and "g" shortcuts restore them,
     sidebar clicks stay a clean start.
   - Old loaders (loadUpgradeRequests ...) are wrapped, not rewritten: behaviour is unchanged, we only add
     a loading skeleton, an inline error with Retry, status chips, next-action lines and record focus.
   - Notification ids look like "plan_inquiry-12"; that is how a notification finds its exact record.
     Request, lead, inquiry and suggestion notifications are "unread" by their own status (new / sent),
     which flips when the record is handled; computed alerts are marked seen by the existing handler.
   - Database text is only written with text nodes. No inline handlers, no new libraries. */
(function () {
  'use strict';
  var SA = window.SA;
  if (!SA) return;
  var h = SA.h, a = SA.a;
  var KEY = 'sa.filters.';
  var LIST_ROUTES = ['hospitals', 'activity', 'upgrade-requests', 'hospital-leads', 'plan-inquiries', 'suggestions'];
  var NOT_REMEMBERED = ['id', 'audit', 'page'];
  var FOCUS_MS = 3500;
  var handled = {};

  var FOLLOW = [['', 'All'], ['new', 'New'], ['contacted', 'Contacted'], ['converted', 'Converted'], ['closed', 'Closed']];
  var LISTS = {
    'upgrade-requests': { load: 'loadUpgradeRequests', list: 'upgrade-requests-list', kind: 'upgrade_request', statuses: FOLLOW, noun: 'upgrade requests' },
    'hospital-leads': { load: 'loadHospitalLeads', list: 'hospital-leads-list', kind: 'hospital_lead', statuses: FOLLOW, noun: 'hospital leads' },
    'plan-inquiries': { load: 'loadPlanInquiries', list: 'plan-inquiries-list', kind: 'plan_inquiry', statuses: [['', 'All'], ['new', 'New'], ['contacted', 'Contacted']], noun: 'plan inquiries' },
    'suggestions': { load: 'loadSuggestions', list: 'suggestions-list', kind: 'suggestion', statuses: null, noun: 'suggestions' }
  };
  var NOTIF_ROUTE = { plan_inquiry: 'plan-inquiries', hospital_lead: 'hospital-leads', upgrade_request: 'upgrade-requests', suggestion: 'suggestions' };

  function $(id) { return document.getElementById(id); }
  function btn(label, cls, fn) { var b = h('button', cls, label); b.type = 'button'; if (fn) b.addEventListener('click', fn); return b; }
  function notify(msg, type) { if (typeof toast === 'function') toast(msg, type || 'info'); }

  // ---------------------------------------------------------------- one badge colour per status
  var STATUS = {
    'new': ['New', 'badge-amber'], contacted: ['Contacted', 'badge-teal'], converted: ['Converted', 'badge-green'], closed: ['Closed', 'badge-grey'],
    sent: ['Received', 'badge-grey'], seen: ['Seen', 'badge-teal'], in_progress: ['In progress', 'badge-amber'], rejected: ['Rejected', 'badge-red'], completed: ['Completed', 'badge-green']
  };
  SA.statusBadge = function (status) {
    var s = STATUS[status] || [String(status || '-').replace(/_/g, ' '), 'badge-grey'];
    return h('span', 'badge ' + s[1], s[0]);
  };

  // ---------------------------------------------------------------- hash parameters + remembered filters
  function store(route, qs) { try { if (qs) sessionStorage.setItem(KEY + route, qs); else sessionStorage.removeItem(KEY + route); } catch (e) { } }
  function recall(route) { try { return sessionStorage.getItem(KEY + route) || ''; } catch (e) { return ''; } }
  SA.recallHash = function (route) { var q = LIST_ROUTES.indexOf(route) >= 0 ? recall(route) : ''; return '#/' + route + (q ? '?' + q : ''); };

  function remember() {
    var p = SA.parse();
    if (LIST_ROUTES.indexOf(p.route) < 0) return;
    if (p.params.has('id') || p.params.has('audit')) return;   // a link to one record must not wipe the saved filters
    var q = new URLSearchParams(p.params.toString());
    NOT_REMEMBERED.forEach(function (k) { q.delete(k); });
    store(p.route, q.toString());
  }
  ['pushState', 'replaceState'].forEach(function (fn) {
    var orig = history[fn];
    history[fn] = function () {
      var r = orig.apply(this, arguments);
      if (fn === 'pushState') handled = {};
      try { remember(); } catch (e) { }
      return r;
    };
  });
  window.addEventListener('hashchange', function () { try { remember(); } catch (e) { } });

  function setParam(route, obj) {
    var p = SA.parse();
    if (p.route !== route) return;
    var q = new URLSearchParams(p.params.toString());
    Object.keys(obj).forEach(function (k) { var v = obj[k]; if (v === '' || v === null || v === undefined) q.delete(k); else q.set(k, v); });
    var s = q.toString();
    history.replaceState(null, '', '#/' + route + (s ? '?' + s : ''));
  }

  // Breadcrumb links back to a list bring the saved filters with them.
  document.addEventListener('click', function (e) {
    var el = e.target.closest ? e.target.closest('#sa-crumbs a') : null;
    if (!el) return;
    var m = /^#\/([a-z-]+)$/.exec(el.getAttribute('href') || '');
    if (!m || !recall(m[1])) return;
    e.preventDefault();
    SA.go(SA.recallHash(m[1]));
  }, true);

  // ---------------------------------------------------------------- list sections: chips, next action, focus
  function rowsOf(route) {
    var box = $(LISTS[route].list);
    if (!box) return [];
    return Array.prototype.map.call(box.querySelectorAll('[data-rec]'), function (n) { return { name: n, card: n.closest('.card') || n }; });
  }

  function ensureBar(route) {
    var cfg = LISTS[route];
    if (!cfg.statuses) return null;
    var bar = $('sa-status-' + route);
    if (bar) return bar;
    var box = $(cfg.list);
    if (!box || !box.parentNode) return null;
    bar = h('div', 'sa-chips sa-status-bar');
    bar.id = 'sa-status-' + route;
    bar.setAttribute('role', 'group');
    bar.setAttribute('aria-label', 'Filter ' + cfg.noun + ' by status');
    cfg.statuses.forEach(function (s) {
      var b = h('button', 'sa-chip', s[1]);
      b.type = 'button'; b.dataset.status = s[0]; b.dataset.label = s[1];
      bar.append(b);
    });
    bar.addEventListener('click', function (e) {
      var b = e.target.closest('button[data-status]');
      if (!b) return;
      setParam(route, { status: b.dataset.status });
      applyStatus(route);
    });
    var note = h('div', 'sa-empty');
    note.id = 'sa-none-' + route;
    note.style.display = 'none';
    box.parentNode.insertBefore(bar, box);
    box.parentNode.insertBefore(note, box.nextSibling);
    return bar;
  }

  function nextAction(route, st, follow) {
    if (st === 'new') return 'Contact them';
    if (st === 'contacted') return follow ? 'Follow up on ' + SA.fmtDate(follow) : 'Set a follow-up date';
    return 'Nothing pending';
  }
  function decorate(route, r) {
    if (r.name.dataset.sa) return;
    r.name.dataset.sa = '1';
    var host = r.name.parentNode, st = r.name.dataset.status, extra = [];
    if (route !== 'suggestions') extra.push('Next action: ' + nextAction(route, st, r.name.dataset.follow));
    if (route === 'hospital-leads' && !r.name.dataset.hospital) extra.push('No hospital created yet');
    if (extra.length && host) host.append(h('div', 'sa-next', extra.join(' \u00B7 ')));
  }

  function applyStatus(route) {
    var cfg = LISTS[route];
    var rows = rowsOf(route);
    rows.forEach(function (r) { decorate(route, r); });
    var bar = ensureBar(route);
    if (!bar) return;
    var want = SA.parse().route === route ? (SA.parse().params.get('status') || '') : '';
    var counts = {}, shown = 0;
    rows.forEach(function (r) { var s = r.name.dataset.status || ''; counts[s] = (counts[s] || 0) + 1; });
    rows.forEach(function (r) {
      var on = !want || r.name.dataset.status === want;
      r.card.style.display = on ? '' : 'none';
      if (on) shown++;
    });
    Array.prototype.forEach.call(bar.querySelectorAll('button'), function (b) {
      var s = b.dataset.status;
      b.textContent = b.dataset.label + ' (' + (s ? (counts[s] || 0) : rows.length) + ')';
      b.setAttribute('aria-pressed', s === want ? 'true' : 'false');
    });
    var note = $('sa-none-' + route);
    if (note) {
      var msg = rows.length && !shown ? 'No ' + cfg.noun + ' with this status.' : '';
      note.textContent = msg;
      note.style.display = msg ? '' : 'none';
    }
  }

  function findRecord(route, id) {
    var el = $(LISTS[route].list).querySelector('[data-rec="' + LISTS[route].kind + ':' + id + '"]');
    if (!el) return null;
    var card = el.closest('.card') || el;
    return card.style.display === 'none' ? null : card;
  }
  function clearFilters(route) {
    // Returns true when a reload is under way (the caller must wait for the next afterList()).
    if (route === 'suggestions') {
      if (typeof suggestionsStatusFilter !== 'undefined' && suggestionsStatusFilter && typeof filterSuggestions === 'function') { filterSuggestions(''); return true; }
      return false;
    }
    setParam(route, { status: '' });
    if (route === 'hospital-leads') {
      var s = $('lead-search'), st = $('lead-filter-state'), c = $('lead-filter-city');
      if (s) s.value = '';
      [st, c].forEach(function (sel) { if (sel) { sel.value = ''; sel.dispatchEvent(new Event('change', { bubbles: true })); } });
      setParam(route, { q: '', state: '', city: '' });
      if (typeof renderHospitalLeads === 'function') renderHospitalLeads();
    } else applyStatus(route);
    return false;
  }
  function focusRecord(route) {
    var p = SA.parse();
    var id = parseInt(p.params.get('id'), 10) || 0;
    if (!id) { handled[route] = 0; return; }
    if (handled[route] === id) return;
    handled[route] = id;
    var card = findRecord(route, id);
    if (!card && clearFilters(route)) { handled[route] = 0; return; }
    if (!card) card = findRecord(route, id);
    if (!card) {
      if (route === 'suggestions' && typeof openSuggestionModal === 'function') { openSuggestionModal(id); return; }
      notify('That record is no longer in this list.', 'info');
      return;
    }
    card.classList.add('sa-flash');
    card.setAttribute('tabindex', '-1');
    try { card.focus({ preventScroll: true }); } catch (e) { }
    card.scrollIntoView({ block: 'center', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
    setTimeout(function () { card.classList.remove('sa-flash'); }, FOCUS_MS);
    if (route === 'suggestions' && typeof openSuggestionModal === 'function') openSuggestionModal(id);
  }

  function applyLeadFields() {
    var q = SA.parse().params;
    var s = $('lead-search'), st = $('lead-filter-state'), c = $('lead-filter-city');
    if (s) s.value = q.get('q') || '';
    [[st, q.get('state')], [c, q.get('city')]].forEach(function (x) {
      if (!x[0]) return;
      var before = x[0].value;
      x[0].value = x[1] || '';
      if (x[0].value !== before) x[0].dispatchEvent(new Event('change', { bubbles: true }));   // keeps the themed dropdown label in step
    });
  }

  function afterList(route) {
    var cfg = LISTS[route], box = $(cfg.list);
    if (!box) return;
    var first = box.firstElementChild;
    if (first && first.tagName === 'P' && /danger|c0392b/.test(first.getAttribute('style') || '')) {
      var msg = first.textContent;
      box.textContent = '';
      box.append(SA.errorBox(msg, function () { window[cfg.load](); }));
      return;
    }
    var onRoute = SA.parse().route === route;
    if (route === 'suggestions' && onRoute) {
      var want = SA.parse().params.get('status') || '';
      if (typeof suggestionsStatusFilter !== 'undefined' && want !== suggestionsStatusFilter && typeof filterSuggestions === 'function') { filterSuggestions(want); return; }
    }
    if (route === 'hospital-leads' && onRoute) applyLeadFields();
    if (route === 'hospital-leads' && typeof renderHospitalLeads === 'function') renderHospitalLeads(); else applyStatus(route);
    if (onRoute) focusRecord(route);
  }

  function wrapLoader(route) {
    var cfg = LISTS[route], orig = window[cfg.load];
    if (typeof orig !== 'function') return;
    window[cfg.load] = function () {
      var box = $(cfg.list);
      if (box && !box.firstElementChild) { box.textContent = ''; box.append(SA.skeleton(4)); }
      var r = orig.apply(this, arguments);
      return Promise.resolve(r).then(function (v) { try { afterList(route); } catch (e) { console.error('superadmin-links', route, e); } return v; });
    };
  }
  function wrapAfter(name, fn) {
    var orig = window[name];
    if (typeof orig !== 'function') return;
    window[name] = function () { var r = orig.apply(this, arguments); try { fn.apply(null, arguments); } catch (e) { } return r; };
  }

  Object.keys(LISTS).forEach(wrapLoader);
  wrapAfter('renderHospitalLeads', function () { applyStatus('hospital-leads'); });
  wrapAfter('filterSuggestions', function (status) { setParam('suggestions', { status: status || '' }); });
  wrapAfter('setAnalyticsPane', function (pane) { setParam('analytics', { pane: pane === 'overview' ? '' : pane }); });

  (function bindLeadFilters() {
    var s = $('lead-search'), st = $('lead-filter-state'), c = $('lead-filter-city');
    function save() { setParam('hospital-leads', { q: s ? s.value.trim() : '', state: st ? st.value : '', city: c ? c.value : '' }); }
    if (s) s.addEventListener('input', save);
    [st, c].forEach(function (el) { if (el) el.addEventListener('change', save); });
  })();

  // ---------------------------------------------------------------- notifications open the exact record
  SA.openNotification = function (section, hospitalId, nid) {
    nid = String(nid || '');
    var m = /^(plan_inquiry|hospital_lead|upgrade_request|suggestion)-(\d+)$/.exec(nid);
    if (m) { SA.go('#/' + NOTIF_ROUTE[m[1]] + '?id=' + m[2]); return true; }
    if (hospitalId) {
      var tab = /^hospital_limit-/.test(nid) ? 'ai' : 'billing';
      SA.go('#/hospital/' + Number(hospitalId) + '/' + tab);
      return true;
    }
    return false;
  };
  (function keyboardNotifications() {
    var body = $('notif-panel-body');
    if (!body || !window.MutationObserver) return;
    new MutationObserver(function () {
      Array.prototype.forEach.call(body.querySelectorAll('.notif-item:not([data-kb])'), function (it) {
        it.dataset.kb = '1'; it.setAttribute('role', 'button'); it.setAttribute('tabindex', '0');
      });
    }).observe(body, { childList: true });
    body.addEventListener('keydown', function (e) {
      if ((e.key === 'Enter' || e.key === ' ') && e.target.classList && e.target.classList.contains('notif-item')) { e.preventDefault(); e.target.click(); }
    });
  })();

  // ---------------------------------------------------------------- section hook (analytics pane, bottom nav)
  var prevShow = window.showSection;
  window.showSection = function (name) {
    var r = prevShow.apply(this, arguments);
    try {
      if (name === 'analytics') {
        var pane = SA.parse().params.get('pane');
        if (pane && typeof analyticsPane !== 'undefined' && pane !== analyticsPane && typeof setAnalyticsPane === 'function') setAnalyticsPane(pane);
      }
      var b = $('tab-btn-' + name);
      if (b && b.scrollIntoView) b.scrollIntoView({ inline: 'center', block: 'nearest' });
    } catch (e) { }
    return r;
  };

  // ---------------------------------------------------------------- keyboard shortcuts + help
  var GO = {
    o: ['home', 'Overview'], h: ['hospitals', 'Hospitals'], a: ['activity', 'Activity'], r: ['overview', 'Revenue & plans'],
    n: ['analytics', 'Platform analytics'], l: ['hospital-leads', 'Hospital leads'], u: ['upgrade-requests', 'Upgrade requests'],
    i: ['plan-inquiries', 'Plan inquiries'], s: ['suggestions', 'Suggestions'], m: ['master-catalogs', 'Master catalogs']
  };
  var helpEl = null, helpFocus = null, armed = false, armTimer = null;

  function kbd(t) { return h('kbd', 'sa-kbd', t); }
  function helpRow(keys, label) {
    var k = h('span', 'sa-keys');
    keys.forEach(function (x, i) { if (i) k.append(' then '); k.append(kbd(x)); });
    return [k, h('span', null, label)];
  }
  function buildHelp() {
    helpEl = h('div', 'sa-pal-overlay');
    var box = h('div', 'sa-pal');
    box.setAttribute('role', 'dialog'); box.setAttribute('aria-modal', 'true'); box.setAttribute('aria-labelledby', 'sa-help-title');
    var title = h('h2', 'sa-help-title', 'Keyboard shortcuts'); title.id = 'sa-help-title';
    var close = btn('Close', 'btn btn-outline btn-sm', closeHelp); close.id = 'sa-help-close';
    var grid = h('div', 'sa-help-grid');
    var rows = [
      [['Ctrl', 'K'], 'Search and quick jump (or press /)'],
      [['n'], 'Open notifications'],
      [['?'], 'Show this list'],
      [['Esc'], 'Close a dialog or panel']
    ];
    Object.keys(GO).forEach(function (k) { rows.push([['g', k], 'Go to ' + GO[k][1]]); });
    rows.forEach(function (r) { var c = helpRow(r[0], r[1]); grid.append(c[0], c[1]); });
    box.append(h('div', 'sa-help-head', [title, close]), grid, h('div', 'sa-pal-foot', [h('span', null, 'Shortcuts are off while you type in a field.')]));
    helpEl.append(box);
    helpEl.addEventListener('mousedown', function (e) { if (e.target === helpEl) closeHelp(); });
    box.addEventListener('keydown', function (e) { if (e.key === 'Tab') { e.preventDefault(); close.focus(); } });
    document.body.append(helpEl);
  }
  function helpOpen() { return helpEl && helpEl.classList.contains('open'); }
  function openHelp() {
    if (!helpEl) buildHelp();
    helpFocus = document.activeElement;
    helpEl.classList.add('open');
    $('sa-help-close').focus();
  }
  function closeHelp() {
    if (!helpEl) return;
    helpEl.classList.remove('open');
    if (helpFocus && helpFocus.focus) helpFocus.focus();
  }
  SA.openHelp = openHelp;

  function typing(el) {
    if (!el) return false;
    var t = el.tagName;
    return t === 'INPUT' || t === 'TEXTAREA' || t === 'SELECT' || el.isContentEditable;
  }
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      if (helpOpen()) { e.preventDefault(); closeHelp(); return; }
      var panel = $('notif-panel');
      if (panel && panel.classList.contains('open') && typeof closeNotifPanel === 'function') { e.preventDefault(); closeNotifPanel(); }
      return;
    }
    if (e.ctrlKey || e.metaKey || e.altKey || typing(document.activeElement)) return;
    if (document.querySelector('.modal-overlay.open, .sa-pal-overlay.open')) return;
    if (e.key === '?') { e.preventDefault(); openHelp(); return; }
    if (armed) {
      armed = false; clearTimeout(armTimer);
      var d = GO[String(e.key).toLowerCase()];
      if (d) { e.preventDefault(); SA.go(SA.recallHash(d[0])); }
      return;
    }
    if (e.key === 'g') { armed = true; armTimer = setTimeout(function () { armed = false; }, 1200); return; }
    if (e.key === 'n' && typeof toggleNotifPanel === 'function') { e.preventDefault(); toggleNotifPanel(); }
  });

  // ---------------------------------------------------------------- header "?" button and phone bottom navigation
  function addHelpButton() {
    var bar = document.querySelector('.topbar');
    if (!bar || $('sa-help-btn')) return;
    var b = h('button', 'sa-search-btn sa-help-btn', '?');
    b.id = 'sa-help-btn'; b.type = 'button';
    b.setAttribute('aria-label', 'Keyboard shortcuts');
    b.style.marginLeft = '0';
    b.addEventListener('click', openHelp);
    var doctor = bar.querySelector('.topbar-doctor');
    if (doctor) bar.insertBefore(b, doctor); else bar.append(b);
  }
  var NAV_ICON = {
    activity: 'M13 10V3L4 14h7v7l9-11h-7z',
    overview: 'M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z',
    'master-catalogs': 'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4'
  };
  function extendBottomNav() {
    var nav = document.querySelector('nav.bottom-nav');
    if (!nav) return;
    [['activity', 'Activity'], ['overview', 'Revenue'], ['master-catalogs', 'Catalogs']].forEach(function (x) {
      if ($('tab-btn-' + x[0])) return;
      var b = h('button', 'bottom-nav-item');
      b.id = 'tab-btn-' + x[0]; b.type = 'button';
      b.innerHTML = '<svg width="20" height="20" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="' + NAV_ICON[x[0]] + '"/></svg>';
      b.append(x[1]);
      b.addEventListener('click', function () { SA.go('#/' + x[0]); });
      nav.append(b);
    });
  }
  addHelpButton();
  setTimeout(extendBottomNav, 50);   // after the shell has renamed the Overview tab to Home
})();