/* ScribeKare Super Admin shell. Loaded AFTER the inline script of superadmin.html.
   - Plain hash routes: #/home  #/hospitals?status=active  #/hospital/12/staff  #/activity?hospital=3&page=2
   - Wraps showSection / openDetail / closeDetail so every old button and notification also updates the URL.
   - Regroups the sidebar without changing any element id the old code uses (nav-<name>, *-nav-badge).
   - Shared helpers live on window.SA. Database text is only ever written with textContent / text nodes. */
(function () {
  'use strict';
  if (typeof window.showSection !== 'function') return;

  var SA = window.SA = window.SA || {};
  var ROUTES = {
    home: 'Overview', hospitals: 'Hospitals', overview: 'Revenue & plans', analytics: 'Platform analytics',
    'master-catalogs': 'Master catalogs', suggestions: 'Suggestions', 'upgrade-requests': 'Upgrade requests',
    'hospital-leads': 'Hospital leads', 'plan-inquiries': 'Plan inquiries', activity: 'Activity'
  };
  var NEW_SECTIONS = ['home', 'activity'];
  var DETAIL_PANE = { overview: 'info', staff: 'info', payments: 'info', requests: 'info', activity: 'info', notes: 'info', billing: 'aiscribe', ai: 'aiscribe' };
  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var routing = false;

  // ---------------------------------------------------------------- helpers
  function h(tag, cls, kids) {
    var el = document.createElement(tag);
    if (cls) el.className = cls;
    (Array.isArray(kids) ? kids : [kids]).forEach(function (k) {
      if (k === null || k === undefined || k === false) return;
      el.append(k);   // strings become text nodes, never HTML
    });
    return el;
  }
  function a(href, cls, text) { var el = h('a', cls, text); el.setAttribute('href', href); return el; }
  function parseNaive(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/.exec(String(iso || ''));
    return m ? { y: +m[1], mo: +m[2] - 1, d: +m[3], h: m[4] !== undefined ? +m[4] : null, mi: m[5] !== undefined ? +m[5] : 0 } : null;
  }
  // Server dates are naive IST; read the parts as written so the browser's own timezone never shifts them.
  function fmtDate(iso) { var p = parseNaive(iso); return p ? p.d + ' ' + MONTHS[p.mo] + ' ' + p.y : '-'; }
  function fmtDateTime(iso) {
    var p = parseNaive(iso);
    if (!p) return '-';
    if (p.h === null) return fmtDate(iso);
    return p.d + ' ' + MONTHS[p.mo] + ', ' + (p.h % 12 || 12) + ':' + String(p.mi).padStart(2, '0') + ' ' + (p.h < 12 ? 'am' : 'pm');
  }
  function inr(n) { return 'Rs ' + Math.round(Number(n) || 0).toLocaleString('en-IN'); }
  function hospLink(id, name) {
    if (!id) return h('span', null, name || '-');
    return a('#/hospital/' + Number(id), 'sa-link', name || ('Hospital #' + Number(id)));
  }
  function skeleton(n) {
    var box = h('div', null);
    for (var i = 0; i < (n || 4); i++) box.append(h('div', 'sa-skel' + (i % 3 === 1 ? ' w80' : i % 3 === 2 ? ' w60' : '')));
    return box;
  }
  function errorBox(msg, retry) {
    var box = h('div', 'sa-error', [h('span', null, msg || 'Something went wrong.')]);
    if (retry) {
      var b = h('button', 'btn btn-outline btn-sm', 'Retry');
      b.type = 'button';
      b.addEventListener('click', retry);
      box.append(b);
    }
    return box;
  }
  function setLabel(el, text) {
    for (var i = 0; i < el.childNodes.length; i++) {
      var n = el.childNodes[i];
      if (n.nodeType === 3 && n.nodeValue.trim()) { n.nodeValue = '\n        ' + text + '\n        '; return; }
    }
  }

  // ---------------------------------------------------------------- routing
  function parse() {
    var raw = (location.hash || '').replace(/^#\/?/, '');
    var qi = raw.indexOf('?');
    var path = qi >= 0 ? raw.slice(0, qi) : raw;
    var segs = path.split('/').filter(Boolean);
    return { route: segs[0] || 'home', id: segs[1], tab: segs[2], params: new URLSearchParams(qi >= 0 ? raw.slice(qi + 1) : '') };
  }
  function pushHash(hash) { if (location.hash !== hash) history.pushState(null, '', hash); }
  function go(hash) { pushHash(hash); apply(); }

  function setCrumbs(parts) {
    var box = document.getElementById('sa-crumbs');
    if (!box) return;
    box.textContent = '';
    box.append(a('#/home', null, 'Super Admin'));
    parts.forEach(function (p, i) {
      box.append(h('span', 'sa-sep', '\u203A'));
      box.append(p.href && i < parts.length - 1 ? a(p.href, null, p.label) : h('span', 'sa-here', p.label));
    });
  }
  function crumbsFor(route) { setCrumbs(route === 'home' ? [{ label: 'Overview' }] : [{ label: ROUTES[route] || route }]); }

  function applyHospitalParams(params) {
    var st = params.get('status');
    if ((st === 'active' || st === 'inactive' || st === 'all') && typeof setHospitalFilter === 'function') {
      var b = document.getElementById('filter-btn-' + st);
      if (b) setHospitalFilter(st, b);
    }
    var q = params.get('q');
    var inp = document.getElementById('hospital-search');
    if (q !== null && inp) { inp.value = q; if (typeof renderHospitalsList === 'function') renderHospitalsList(); }
  }

  function openHospital(id, tab) {
    var p = Promise.resolve(window.openDetail(id));
    p.then(function () {
      var name = (typeof currentHospitalData !== 'undefined' && currentHospitalData) ? currentHospitalData.name : ('Hospital #' + id);
      setCrumbs([{ label: 'Hospitals', href: '#/hospitals' }, { label: name }]);
      if (tab && typeof SA.openTab === 'function') SA.openTab(tab); else if (tab && DETAIL_PANE[tab] && typeof setDetailPane === 'function') setDetailPane(DETAIL_PANE[tab]);
    });
  }

  function apply() {
    var r = parse();
    routing = true;
    try {
      if (r.route === 'hospital') {
        var id = parseInt(r.id, 10);
        if (id > 0) {
          window.showSection('hospitals');
          setCrumbs([{ label: 'Hospitals', href: '#/hospitals' }, { label: 'Hospital #' + id }]);
          openHospital(id, r.tab);
          return;
        }
        r.route = 'hospitals';
      }
      if (!ROUTES[r.route]) r.route = 'home';
      window.showSection(r.route);
      if (r.route === 'hospitals') applyHospitalParams(r.params);
    } finally { routing = false; }
  }

  // ---------------------------------------------------------------- wrap the old navigation functions
  var origShow = window.showSection;
  window.showSection = function (name) {
    if (!ROUTES[name]) return origShow(name);
    origShow(name);   // hides the old sections, sets the active nav + bottom-nav item, runs old loaders
    NEW_SECTIONS.forEach(function (n) {
      var el = document.getElementById('section-' + n);
      if (el) el.style.display = n === name ? 'block' : 'none';
    });
    if (name === 'home' && SA.home) SA.home.load();
    if (name === 'activity' && SA.activity) SA.activity.load();
    if (!routing) pushHash('#/' + name);
    crumbsFor(name);
    if (typeof closeSidebar === 'function') closeSidebar();
    window.scrollTo(0, 0);
  };

  var origOpen = window.openDetail;
  if (typeof origOpen === 'function') {
    window.openDetail = function (id) {
      if (!routing) pushHash('#/hospital/' + Number(id));
      return origOpen(id);
    };
  }
  var origClose = window.closeDetail;
  if (typeof origClose === 'function') {
    window.closeDetail = function () {
      origClose();
      pushHash(typeof SA.hospitalsHash === 'function' ? SA.hospitalsHash() : '#/hospitals');
      crumbsFor('hospitals');
    };
  }

  // ---------------------------------------------------------------- shell DOM
  var ICON = {
    home: 'M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6',
    activity: 'M13 10V3L4 14h7v7l9-11h-7z',
    bell: 'M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9',
    user: 'M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z'
  };
  function navItem(id, label, iconKey, attrs) {
    var el = h('a', 'nav-item');
    el.id = id;
    el.setAttribute('href', '#');
    Object.keys(attrs || {}).forEach(function (k) { el.dataset[k] = attrs[k]; });
    el.innerHTML = '<svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="' + ICON[iconKey] + '"/></svg>';
    el.append('\n        ' + label + '\n        ');
    return el;
  }

  function buildNav() {
    var nav = document.querySelector('nav.sidebar');
    if (!nav || nav.dataset.saShell) return;
    nav.dataset.saShell = '1';
    var by = {};
    nav.querySelectorAll('a.nav-item[id^="nav-"]').forEach(function (el) { by[el.id.slice(4)] = el; });
    by.home = navItem('nav-home', 'Home', 'home', { route: 'home' });
    by.activity = navItem('nav-activity', 'Activity', 'activity', { route: 'activity' });
    by['@notifications'] = navItem('nav-notifications-action', 'Notifications', 'bell', { action: 'notifications' });
    by['@account'] = navItem('nav-account-action', 'My account & security', 'user', { action: 'account' });
    if (by.overview) setLabel(by.overview, 'Revenue & plans');
    if (by.analytics) setLabel(by.analytics, 'Platform analytics');

    var groups = [
      ['Overview', ['home', '@notifications']],
      ['Hospitals', ['hospitals']],
      ['Money', ['overview']],
      ['Requests & leads', ['upgrade-requests', 'hospital-leads', 'plan-inquiries', 'suggestions']],
      ['Activity', ['activity']],
      ['Platform analytics', ['analytics']],
      ['Master catalogs', ['master-catalogs']],
      ['Settings & security', ['@account']]
    ];
    nav.textContent = '';
    groups.forEach(function (g) {
      nav.append(h('div', 'sidebar-section-label sa-nav-group', g[0]));
      g[1].forEach(function (name) {
        var el = by[name];
        if (!el) return;
        el.removeAttribute('onclick');
        if (!el.dataset.action) { el.dataset.route = name; el.setAttribute('href', '#/' + name); }
        nav.append(el);
      });
    });
    nav.addEventListener('click', function (e) {
      var el = e.target.closest('a.nav-item');
      if (!el) return;
      e.preventDefault();
      if (el.dataset.action === 'notifications') { if (typeof toggleNotifPanel === 'function') toggleNotifPanel(); }
      else if (el.dataset.action === 'account') { if (typeof openEditDetailsModal === 'function') openEditDetailsModal(); }
      else if (el.dataset.route) go('#/' + el.dataset.route);
      if (typeof closeSidebar === 'function') closeSidebar();
    });
  }

  function buildBottomNav() {
    var btn = document.getElementById('tab-btn-overview');
    if (!btn) return;
    btn.id = 'tab-btn-home';
    btn.setAttribute('onclick', "showSection('home')");
    setLabel(btn, 'Home');
  }

  function buildContainers() {
    var main = document.querySelector('main.main-content');
    if (!main || document.getElementById('sa-crumbs')) return;
    var crumbs = h('nav', 'sa-crumbs');
    crumbs.id = 'sa-crumbs';
    crumbs.setAttribute('aria-label', 'Breadcrumb');
    var first = main.firstChild;
    main.insertBefore(crumbs, first);
    NEW_SECTIONS.forEach(function (n) {
      var sec = h('div');
      sec.id = 'section-' + n;
      sec.style.display = 'none';
      main.insertBefore(sec, first);
    });
  }

  // ---------------------------------------------------------------- public API + start
  SA.h = h; SA.a = a; SA.go = go; SA.parse = parse; SA.pushHash = pushHash;
  SA.fmtDate = fmtDate; SA.fmtDateTime = fmtDateTime; SA.inr = inr;
  SA.hospLink = hospLink; SA.skeleton = skeleton; SA.errorBox = errorBox;
  SA.esc = (typeof sanitize === 'function') ? sanitize : function (s) { return String(s == null ? '' : s); };

  function init() {
    buildContainers();
    buildNav();
    buildBottomNav();
    if (!location.hash) history.replaceState(null, '', '#/home');
    apply();
    window.addEventListener('hashchange', apply);
  }
  setTimeout(init, 0);   // runs after superadmin-home.js has registered SA.home / SA.activity
})();