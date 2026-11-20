/* ScribeKare Super Admin: hospitals table (search, plan/status/state filters, sort, pagination, state kept in the
   URL hash) and Hospital 360 (tabs: Overview, Plan & billing, AI usage, Staff, Payments, Requests & leads,
   Activity, Notes, Analytics, Import data). Existing cards and their buttons are MOVED, not rewritten, so their
   behaviour is unchanged. All database text is written with text nodes. No inline handlers. */
(function () {
  'use strict';
  var SA = window.SA;
  if (!SA || typeof window.openDetail !== 'function') return;
  var h = SA.h, a = SA.a, hospLink = SA.hospLink, fmtDate = SA.fmtDate, fmtDateTime = SA.fmtDateTime, inr = SA.inr;

  function tierName(t) { return (typeof tierLabel === 'function') ? tierLabel(t) : t; }
  function btn(label, cls, fn) { var b = h('button', cls, label); b.type = 'button'; b.addEventListener('click', fn); return b; }
  function empty(t) { return h('div', 'sa-empty', t); }
  function hid() { return (typeof currentHospitalId !== 'undefined') ? currentHospitalId : null; }
  function getJson(path) { return api('GET', path, null, false, true); }
  function tableOf(heads, rows) {
    var t = h('table', 'sa-table');
    t.append(h('thead', null, [h('tr', null, heads.map(function (x) { return h('th', null, x); }))]));
    var tb = h('tbody');
    rows.forEach(function (r) { tb.append(h('tr', null, r.map(function (c) { return h('td', null, [c]); }))); });
    t.append(tb);
    return h('div', 'sa-table-scroll', [h('div', 'table-wrap', [t])]);
  }
  function card(title, extra) { var c = h('div', 'card sa-card', [h('div', 'card-header', [h('h2', null, title)])]); if (extra) c.append(extra); return c; }
  function badge(text, cls) { return h('span', 'badge ' + (cls || 'badge-grey'), text); }

  // ================================================================ Hospitals table
  var PAGE = 25, hp = new URLSearchParams(), ui = null, searchTimer = null;

  function readParams() { var p = SA.parse(); if (p.route === 'hospitals') hp = p.params; return hp; }
  function hospitalsHash() { var s = hp.toString(); return '#/hospitals' + (s ? '?' + s : ''); }
  SA.hospitalsHash = hospitalsHash;
  function setParams(obj, keepPage) {
    readParams();
    Object.keys(obj).forEach(function (k) { var v = obj[k]; if (v === '' || v === null || v === undefined) hp.delete(k); else hp.set(k, v); });
    if (!keepPage) hp.delete('page');
    if (SA.parse().route === 'hospitals') history.replaceState(null, '', hospitalsHash());
    renderHospitals();
  }
  function billingEnd(x) { return x.is_pilot ? x.pilot_end_date : (x.plan_end_date || x.billing_cycle_end); }
  function billingText(x) {
    if (x.is_pilot) return (x.pilot_label || 'Pilot') + (x.pilot_phase === 'grace' ? ' (grace)' : '') + ' \u00B7 ends ' + fmtDate(x.pilot_end_date);
    var end = billingEnd(x);
    return end ? (x.billing_period === 'yearly' ? 'Yearly \u00B7 ends ' : 'Renews ') + fmtDate(end) : 'Cycle not started';
  }

  function buildHospitalsUI() {
    var view = document.getElementById('hospitals-list-view');
    if (!view) return;
    var oldBar = view.querySelector('.hospitals-filter-bar');
    if (oldBar) oldBar.style.display = 'none';
    var oldList = document.getElementById('hospitals-list');
    if (oldList) oldList.style.display = 'none';
    ui = {};
    ui.root = h('div'); ui.root.id = 'sa-hosp-ui';
    ui.q = h('input', 'form-control sa-grow'); ui.q.type = 'search'; ui.q.placeholder = 'Search by name, code or city\u2026'; ui.q.setAttribute('aria-label', 'Search hospitals');
    ui.status = h('select', 'form-control'); ui.status.setAttribute('aria-label', 'Filter by status');
    [['', 'All statuses'], ['active', 'Active'], ['inactive', 'Inactive']].forEach(function (o) { ui.status.append(new Option(o[1], o[0])); });
    ui.plan = h('select', 'form-control'); ui.plan.setAttribute('aria-label', 'Filter by plan');
    ui.state = h('select', 'form-control'); ui.state.setAttribute('aria-label', 'Filter by state');
    ui.clear = btn('Clear filters', 'btn btn-outline btn-sm', function () { setParams({ q: '', status: '', plan: '', state: '' }); });
    ui.count = h('span', 'sa-row-sub');
    ui.body = h('div'); ui.body.append(SA.skeleton(6));
    ui.pager = h('div', 'sa-pager');
    ui.root.append(h('div', 'sa-filters', [ui.q, ui.status, ui.plan, ui.state, ui.clear]), h('div', 'sa-row-sub', [ui.count]), ui.body, ui.pager);
    view.append(ui.root);
    ui.q.addEventListener('input', function () { clearTimeout(searchTimer); searchTimer = setTimeout(function () { setParams({ q: ui.q.value.trim() }); }, 250); });
    ui.status.addEventListener('change', function () { setParams({ status: ui.status.value }); });
    ui.plan.addEventListener('change', function () { setParams({ plan: ui.plan.value }); });
    ui.state.addEventListener('change', function () { setParams({ state: ui.state.value }); });
    ui.body.addEventListener('click', function (e) {
      var b = e.target.closest('button[data-act]');
      if (!b) return;
      var id = Number(b.dataset.id);
      if (b.dataset.act === 'tests' && typeof goMasterSetup === 'function') goMasterSetup('tests', id);
      else if (b.dataset.act === 'meds' && typeof goMasterSetup === 'function') goMasterSetup('medicines', id);
      else if (b.dataset.act === 'toggle' && typeof toggleHospitalActive === 'function') toggleHospitalActive(id, b.dataset.active === '1');
    });
  }

  function fillSelect(sel, first, values, current, labelFn) {
    sel.textContent = '';
    sel.append(new Option(first, ''));
    values.forEach(function (v) { sel.append(new Option(labelFn ? labelFn(v) : v, v)); });
    sel.value = values.indexOf(current) >= 0 ? current : '';
  }

  function renderHospitals() {
    readParams();
    if (!ui) buildHospitalsUI();
    if (!ui) return;
    var data = (typeof allHospitalsCache !== 'undefined' && allHospitalsCache) ? allHospitalsCache : [];
    var tiers = [], states = [];
    data.forEach(function (x) { if (x.tier && tiers.indexOf(x.tier) < 0) tiers.push(x.tier); if (x.state && states.indexOf(x.state) < 0) states.push(x.state); });
    states.sort();
    fillSelect(ui.plan, 'All plans', tiers, hp.get('plan') || '', tierName);
    fillSelect(ui.state, 'All states', states, hp.get('state') || '');
    ui.status.value = hp.get('status') || '';
    if (document.activeElement !== ui.q) ui.q.value = hp.get('q') || '';

    var q = (hp.get('q') || '').toLowerCase(), status = hp.get('status') || '', plan = hp.get('plan') || '', st = hp.get('state') || '';
    var rows = data.filter(function (x) {
      if (status === 'active' && !x.is_active) return false;
      if (status === 'inactive' && x.is_active) return false;
      if (plan && x.tier !== plan) return false;
      if (st && (x.state || '') !== st) return false;
      if (q && !((x.name || '').toLowerCase().indexOf(q) >= 0 || (x.hospital_code || '').toLowerCase().indexOf(q) >= 0 ||
        (x.city || '').toLowerCase().indexOf(q) >= 0)) return false;
      return true;
    });
    var sort = hp.get('sort') || 'name', dir = hp.get('dir') === 'desc' ? -1 : 1;
    function key(x) {
      if (sort === 'city') return ((x.city || '') + ' ' + (x.state || '')).toLowerCase();
      if (sort === 'plan') return String(tierName(x.tier)).toLowerCase();
      if (sort === 'status') return x.is_active ? 0 : 1;
      if (sort === 'billing') return billingEnd(x) || '9999';
      return (x.name || '').toLowerCase();
    }
    rows.sort(function (p, q2) { var A = key(p), B = key(q2); return (A < B ? -1 : A > B ? 1 : 0) * dir; });

    var pages = Math.max(1, Math.ceil(rows.length / PAGE));
    var page = Math.min(pages, Math.max(1, parseInt(hp.get('page'), 10) || 1));
    var slice = rows.slice((page - 1) * PAGE, page * PAGE);
    ui.count.textContent = rows.length + ' of ' + data.length + ' hospitals';

    ui.body.textContent = '';
    if (!data.length) { ui.body.append(SA.skeleton(6)); ui.pager.textContent = ''; return; }
    if (!rows.length) { ui.body.append(empty('No hospitals match these filters.')); ui.pager.textContent = ''; return; }

    var heads = [['name', 'Hospital'], ['city', 'Place'], ['plan', 'Plan'], ['billing', 'Billing'], [null, 'AI scribe'], ['status', 'Status'], [null, 'Actions']];
    var tr = h('tr');
    heads.forEach(function (c) {
      var th = h('th');
      if (c[0]) {
        var active = sort === c[0];
        th.setAttribute('aria-sort', active ? (dir === 1 ? 'ascending' : 'descending') : 'none');
        th.append(btn(c[1] + (active ? (dir === 1 ? ' \u2191' : ' \u2193') : ''), 'sa-sort', function () {
          setParams({ sort: c[0], dir: active && dir === 1 ? 'desc' : 'asc' });
        }));
      } else th.append(c[1]);
      tr.append(th);
    });
    var table = h('table', 'sa-table');
    table.append(h('thead', null, [tr]));
    var tb = h('tbody');
    slice.forEach(function (x) {
      var scribe = h('span');
      if (typeof aiScribeUsageBadgeHtml === 'function') scribe.innerHTML = aiScribeUsageBadgeHtml(x);   // numbers and fixed labels only
      var actions = h('div', 'sa-actions');
      [['tests', 'Tests setup', 'btn btn-outline btn-sm'], ['meds', 'Medicines setup', 'btn btn-outline btn-sm'],
        ['toggle', x.is_active ? 'Deactivate' : 'Activate', 'btn ' + (x.is_active ? 'btn-outline' : 'btn-primary') + ' btn-sm']].forEach(function (d) {
        var b = btn(d[1], d[2], function () { });
        b.dataset.act = d[0]; b.dataset.id = String(x.id); b.dataset.active = x.is_active ? '1' : '0';
        actions.append(b);
      });
      tb.append(h('tr', null, [
        h('td', null, [hospLink(x.id, x.name), h('div', 'sa-row-sub', [x.hospital_code || '', ' \u00B7 ', x.hospital_type === 'government' ? 'Government' : 'Private'])]),
        h('td', null, [[x.city, x.state].filter(Boolean).join(', ') || '-']),
        h('td', 'sa-nowrap', [badge(tierName(x.tier))]),
        h('td', null, billingText(x)),
        h('td', null, [scribe]),
        h('td', null, [badge(x.is_active ? 'Active' : 'Inactive', x.is_active ? 'badge-teal' : 'badge-grey')]),
        h('td', null, [actions])
      ]));
    });
    table.append(tb);
    ui.body.append(h('div', 'sa-table-scroll', [h('div', 'table-wrap', [table])]));

    ui.pager.textContent = '';
    ui.pager.append(
      page > 1 ? btn('Previous', 'btn btn-outline btn-sm', function () { setParams({ page: String(page - 1) }, true); }) : h('span'),
      h('span', null, 'Page ' + page + ' of ' + pages),
      page < pages ? btn('Next', 'btn btn-outline btn-sm', function () { setParams({ page: String(page + 1) }, true); }) : h('span')
    );
  }
  window.renderHospitalsList = renderHospitals;   // loadHospitals() / setHospitalFilter() now draw the new table

  // ================================================================ Hospital 360
  var TABS = [['overview', 'Overview'], ['billing', 'Plan & billing'], ['ai', 'AI usage'], ['staff', 'Staff'], ['payments', 'Payments'],
    ['requests', 'Requests & leads'], ['activity', 'Activity'], ['notes', 'Notes'], ['analytics', 'Analytics'], ['import', 'Import data']];
  var PANE = { overview: 'info', billing: 'aiscribe', analytics: 'analytics', import: 'import', ai: 'ai360', staff: 'staff360', payments: 'pay360', requests: 'req360', activity: 'act360', notes: 'notes360' };
  var active = 'overview', loaded = {}, loadedFor = null, summary = null, summaryP = null, boxes = {};

  function init360() {
    var detail = document.getElementById('hospital-detail');
    if (!detail) return;
    var nav = detail.querySelector('.detail-subnav');
    nav.textContent = '';
    TABS.forEach(function (t) {
      var b = h('button', 'detail-subnav-btn', t[1]); b.type = 'button'; b.id = 'dsn-' + t[0]; b.dataset.tab = t[0]; nav.append(b);
    });
    nav.addEventListener('click', function (e) { var b = e.target.closest('button[data-tab]'); if (b) SA.openTab(b.dataset.tab); });
    ['ai360', 'staff360', 'pay360', 'req360', 'act360', 'notes360'].forEach(function (id) {
      var p = h('div', 'detail-pane'); p.id = 'detail-pane-' + id; p.style.display = 'none'; detail.append(p);
    });
    // Existing cards are moved into their new tabs with ids and handlers intact.
    var summaryCard = h('div', 'card'); summaryCard.id = 'sa360-summary';
    var grid = document.querySelector('#detail-pane-info .hospital-detail-grid');
    var adm = document.getElementById('detail-admins');
    if (grid) grid.append(summaryCard);
    boxes.summary = summaryCard;
    boxes.ai = h('div'); boxes.staff = h('div'); boxes.pay = h('div'); boxes.req = h('div'); boxes.act = h('div'); boxes.notes = h('div');
    document.getElementById('detail-pane-ai360').append(boxes.ai);
    var use = document.getElementById('detail-usage-card');
    if (use) document.getElementById('detail-pane-ai360').append(use);
    if (adm && adm.closest('.card')) document.getElementById('detail-pane-staff360').append(adm.closest('.card'));
    document.getElementById('detail-pane-staff360').append(boxes.staff);
    document.getElementById('detail-pane-pay360').append(boxes.pay);
    document.getElementById('detail-pane-req360').append(boxes.req);
    document.getElementById('detail-pane-act360').append(boxes.act);
    document.getElementById('detail-pane-notes360').append(boxes.notes);
  }

  function resetState(id) {
    loaded = {}; summary = null; summaryP = null; loadedFor = id;
    ['ai', 'staff', 'pay', 'req', 'act', 'notes'].forEach(function (k) { if (boxes[k]) boxes[k].textContent = ''; });
    if (boxes.summary) { boxes.summary.textContent = ''; boxes.summary.append(SA.skeleton(5)); }
  }

  function fetchSummary() {
    var id = hid();
    if (summary && summary.hospital_id === id) return Promise.resolve(summary);
    if (!summaryP || summaryP._id !== id) {
      summaryP = getJson('/admin/sa/hospital/' + id + '/360').then(function (d) { if (id === hid()) summary = d; return d; });
      summaryP._id = id;
    }
    return summaryP;
  }

  SA.openTab = function (tab) {
    if (!PANE[tab]) tab = 'overview';
    active = tab;
    var id = hid();
    if (id !== null && loadedFor !== id) resetState(id);
    document.querySelectorAll('#hospital-detail .detail-subnav-btn').forEach(function (b) {
      var on = b.dataset.tab === tab; b.classList.toggle('active', on); b.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    document.querySelectorAll('#hospital-detail .detail-pane').forEach(function (p) { p.style.display = 'none'; });
    var pane = document.getElementById('detail-pane-' + PANE[tab]);
    if (pane) pane.style.display = 'block';
    if (id !== null) history.replaceState(null, '', '#/hospital/' + id + (tab === 'overview' ? '' : '/' + tab));
    if (id === null || loaded[tab]) { if (tab === 'ai') renderAi(); return; }
    loaded[tab] = true;
    if (tab === 'overview') loadOverview();
    else if (tab === 'ai') renderAi();
    else if (tab === 'staff') loadStaff();
    else if (tab === 'payments') loadPayments(1);
    else if (tab === 'requests') loadRequests();
    else if (tab === 'activity') loadActivity(1);
    else if (tab === 'notes') loadNotes();
  };
  window.setDetailPane = function (pane) { SA.openTab({ info: 'overview', aiscribe: 'billing' }[pane] || pane); };

  var prevOpen = window.openDetail;
  window.openDetail = function (id) {
    var sameHospital = loadedFor === Number(id), keep = active;
    resetState(Number(id));
    var p = Promise.resolve(prevOpen(id));
    p.then(function () {
      if (sameHospital && keep && keep !== 'overview') SA.openTab(keep);
      else if (active === 'ai') renderAi();
    });
    return p;
  };

  function tabLink(tab, text) {
    var id = hid();
    var el = a('#/hospital/' + id + '/' + tab, 'sa-info-link', text);
    el.addEventListener('click', function (e) { e.preventDefault(); SA.openTab(tab); });
    return el;
  }
  function infoRow(label, value) { return h('div', 'info-row', [h('span', 'info-label', label), h('span', 'info-value', [value])]); }

  // ---- Overview: key numbers
  function loadOverview() {
    var id = hid();
    fetchSummary().then(function (s) {
      if (id !== hid()) return;
      var box = boxes.summary;
      box.textContent = '';
      box.append(h('div', 'card-header', [h('h2', null, 'Key numbers')]));
      var roles = Object.keys(s.staff.by_role).map(function (r) { return r + ' ' + s.staff.by_role[r]; }).join(' \u00B7 ');
      box.append(infoRow('Staff accounts', h('span', null, [tabLink('staff', s.staff.active + ' active of ' + s.staff.total)])));
      if (roles) box.append(infoRow('By role', h('span', null, roles)));
      box.append(infoRow('Collected so far', h('span', null, [tabLink('payments', inr(s.payments.total) + ' \u00B7 ' + s.payments.count + ' payments')])));
      box.append(infoRow('Last payment', h('span', null, s.payments.last_at ? inr(s.payments.last_amount) + ' on ' + fmtDate(s.payments.last_at) : 'None recorded')));
      box.append(infoRow('Upgrade requests', h('span', null, [tabLink('requests', s.requests.upgrade_new + ' new of ' + s.requests.upgrade_total)])));
      box.append(infoRow('Suggestions waiting', h('span', null, String(s.requests.suggestions_new))));
      box.append(infoRow('Activity, last 30 days', h('span', null, [tabLink('activity', String(s.activity.last_30_days))])));
      box.append(infoRow('Last activity', h('span', null, s.activity.last_at ? fmtDateTime(s.activity.last_at) : '-')));
      box.append(infoRow('Notes', h('span', null, [tabLink('notes', s.notes ? 'Open notes' : 'Add a note')])));
    }).catch(function (e) {
      if (id !== hid()) return;
      boxes.summary.textContent = '';
      boxes.summary.append(SA.errorBox(e.message || 'Could not load key numbers.', function () { loaded.overview = false; summary = null; summaryP = null; SA.openTab('overview'); }));
    });
  }

  // ---- AI usage (from the hospital record already loaded by the existing detail code)
  function renderAi() {
    var d = (typeof currentHospitalData !== 'undefined') ? currentHospitalData : null;
    var box = boxes.ai;
    if (!box) return;
    box.textContent = '';
    if (!d || d.id !== hid()) { box.append(SA.skeleton(3)); return; }
    var c = card('AI scribe at a glance');
    if (d.is_pilot) {
      var used = Number(d.pilot_week_used || 0), cap = Number(d.pilot_weekly_cap || 0);
      c.append(infoRow('Plan', h('span', null, d.pilot_label + ' \u00B7 week ' + d.pilot_week + ' of ' + d.pilot_total_weeks)));
      c.append(infoRow('This pilot week', h('span', null, used + ' of ' + cap)));
      c.append(infoRow('Pilot dates', h('span', null, fmtDate(d.pilot_start_date) + ' to ' + fmtDate(d.pilot_end_date))));
    } else if (!d.has_ai_scribe) {
      c.append(empty('AI scribe is not part of this hospital\u2019s plan.'));
    } else {
      c.append(infoRow('Used this ' + (d.billing_period === 'yearly' ? 'term' : 'cycle'), h('span', null, d.ai_scribe_cap === null ? d.ai_scribe_used + ' (unlimited plan)' : d.ai_scribe_used + ' of ' + d.ai_scribe_cap)));
      c.append(infoRow('Top-up left', h('span', null, String(d.ai_scribe_topup_remaining || 0))));
      c.append(infoRow('Total left', h('span', null, d.ai_scribe_total_remaining === null ? 'Unlimited' : String(d.ai_scribe_total_remaining))));
      c.append(infoRow('Cycle ends', h('span', null, fmtDate(d.billing_cycle_end))));
    }
    c.append(h('div', 'sa-card-foot', [tabLink('billing', 'Change plan, renew or top up \u2192')]));
    box.append(c);
  }

  // ---- Staff
  function loadStaff() {
    var id = hid(), box = boxes.staff;
    box.textContent = '';
    box.append(SA.skeleton(5));
    getJson('/admin/sa/hospital/' + id + '/staff').then(function (d) {
      if (id !== hid()) return;
      var byId = {};
      d.items.forEach(function (s) { byId[s.id] = s; });
      var search = h('input', 'form-control'); search.type = 'search'; search.placeholder = 'Search staff by name, email or phone\u2026'; search.setAttribute('aria-label', 'Search staff');
      var holder = h('div');
      var c = card('All staff accounts (' + d.items.length + ')');
      c.append(h('div', 'sa-filters', [search]), holder);
      function paint() {
        var q = search.value.trim().toLowerCase();
        var rows = d.items.filter(function (s) { return !q || (s.name + ' ' + s.email + ' ' + s.phone).toLowerCase().indexOf(q) >= 0; });
        holder.textContent = '';
        if (!rows.length) { holder.append(empty('No staff accounts found.')); return; }
        var body = tableOf(['Name', 'Role', 'Email', 'Phone', 'Status', 'Actions'], rows.map(function (s) {
          var actions = h('div', 'sa-actions');
          [['edit', 'Edit', 'btn btn-outline btn-sm'], ['reset', 'Reset password', 'btn btn-outline btn-sm'], ['toggle', s.is_active ? 'Deactivate' : 'Activate', 'btn ' + (s.is_active ? 'btn-outline' : 'btn-primary') + ' btn-sm']].forEach(function (x) {
            var b = btn(x[1], x[2], function () { }); b.dataset.act = x[0]; b.dataset.id = String(s.id); actions.append(b);
          });
          var flags = h('div', 'sa-actions', [badge(s.is_active ? 'Active' : 'Inactive', s.is_active ? 'badge-teal' : 'badge-grey')]);
          if (s.locked) flags.append(badge('Locked', 'badge-red'));
          if (s.must_change_password) flags.append(badge('Must change password', 'badge-amber'));
          return [h('span', null, [(s.title + ' ' + s.name).trim()]), badge(s.role, 'badge-navy'), s.email, s.phone, flags, actions];
        }));
        holder.append(body);
      }
      search.addEventListener('input', paint);
      holder.addEventListener('click', function (e) {
        var b = e.target.closest('button[data-act]');
        if (!b) return;
        var s = byId[b.dataset.id];
        if (!s) return;
        if (b.dataset.act === 'edit' && typeof openEditAccount === 'function') openEditAccount({ id: s.id, name: (s.title + ' ' + s.name).trim(), email: s.email, phone: s.phone });
        else if (b.dataset.act === 'reset' && typeof resetAccountPassword === 'function') resetAccountPassword(s.id);
        else if (b.dataset.act === 'toggle' && typeof toggleAccountActive === 'function') toggleAccountActive(s.id);
      });
      paint();
      box.textContent = '';
      box.append(c);
    }).catch(function (e) {
      if (id !== hid()) return;
      box.textContent = '';
      box.append(SA.errorBox(e.message || 'Could not load staff.', function () { loaded.staff = false; SA.openTab('staff'); }));
    });
  }

  // ---- Payments
  function loadPayments(page) {
    var id = hid(), box = boxes.pay;
    box.textContent = '';
    box.append(SA.skeleton(5));
    getJson('/admin/sa/hospital/' + id + '/payments?page=' + page).then(function (d) {
      if (id !== hid()) return;
      box.textContent = '';
      var c = card('Subscription payments');
      c.append(h('div', 'sa-row-sub', 'Collected so far: ' + inr(d.collected_total) + ' across ' + d.total + ' payments.'));
      if (!d.items.length) c.append(empty('No payments recorded yet. They appear here when a cycle is renewed.'));
      else c.append(tableOf(['Recorded (IST)', 'Plan', 'Period covered', 'Amount', 'Collected by', 'Note', 'Audit'], d.items.map(function (p) {
        return [fmtDateTime(p.created_at), tierName(p.tier) + ' \u00B7 ' + p.billing_period, fmtDate(p.period_start) + ' to ' + fmtDate(p.period_end), inr(p.amount),
          p.collected_by || '-', p.note || '', p.audit_id ? a('#/activity?hospital=' + id + '&audit=' + Number(p.audit_id), 'sa-link', 'View entry') : '-'];
      })));
      if (d.total > d.page_size) {
        c.append(h('div', 'sa-pager', [
          d.page > 1 ? btn('Previous', 'btn btn-outline btn-sm', function () { loadPayments(d.page - 1); }) : h('span'),
          h('span', null, 'Page ' + d.page),
          d.has_more ? btn('Next', 'btn btn-outline btn-sm', function () { loadPayments(d.page + 1); }) : h('span')
        ]));
      }
      box.append(c);
      var t = card('AI scribe top-ups');
      if (!d.topups.length) t.append(empty('No top-ups bought.'));
      else t.append(tableOf(['Bought (IST)', 'Block', 'Used', 'Price', 'Payment', 'Expires'], d.topups.map(function (x) {
        return [fmtDateTime(x.purchased_at), String(x.block_size), x.used + ' of ' + x.granted, inr(x.price_paid), badge(x.payment_collected ? 'Collected' : 'Not collected', x.payment_collected ? 'badge-green' : 'badge-amber'), fmtDate(x.expires_at)];
      })));
      box.append(t);
    }).catch(function (e) {
      if (id !== hid()) return;
      box.textContent = '';
      box.append(SA.errorBox(e.message || 'Could not load payments.', function () { loadPayments(page); }));
    });
  }

  // ---- Requests and leads
  function nextAction(r) {
    if (r.status === 'new') return 'Contact them';
    if (r.status === 'contacted') return r.next_follow_up_at ? 'Follow up on ' + fmtDate(r.next_follow_up_at) : 'Set a follow-up date';
    return 'Nothing pending';
  }
  function loadRequests() {
    var id = hid(), box = boxes.req;
    box.textContent = '';
    box.append(SA.skeleton(5));
    getJson('/admin/sa/hospital/' + id + '/requests').then(function (d) {
      if (id !== hid()) return;
      box.textContent = '';
      var up = card('Upgrade requests');
      if (!d.upgrade_requests.length) up.append(empty('No upgrade requests from this hospital.'));
      else up.append(tableOf(['Requested (IST)', 'Plan', 'Contact', 'Status', 'Next action', ''], d.upgrade_requests.map(function (r) {
        return [fmtDateTime(r.created_at), tierName(r.requested_tier), r.contact_name, SA.statusBadge(r.status), nextAction(r), a('#/upgrade-requests?id=' + r.id, 'sa-link', 'Open')];
      })));
      box.append(up);
      var ld = card('Leads converted into this hospital');
      if (!d.leads.length) ld.append(empty('No leads were converted into this hospital.'));
      else ld.append(tableOf(['Received (IST)', 'Lead', 'Place', 'Status', ''], d.leads.map(function (l) {
        return [fmtDateTime(l.created_at), l.hospital_name, l.city, SA.statusBadge(l.status), a('#/hospital-leads?id=' + l.id, 'sa-link', 'Open')];
      })));
      box.append(ld);
      var sg = card('Suggestions from this hospital');
      if (!d.suggestions.length) sg.append(empty('No suggestions.'));
      else sg.append(tableOf(['Sent (IST)', 'From role', 'Status', ''], d.suggestions.map(function (s) {
        return [fmtDateTime(s.created_at), s.submitted_by_role, SA.statusBadge(s.status), a('#/suggestions?id=' + s.id, 'sa-link', 'Open')];
      })));
      box.append(sg);
    }).catch(function (e) {
      if (id !== hid()) return;
      box.textContent = '';
      box.append(SA.errorBox(e.message || 'Could not load requests.', function () { loaded.requests = false; SA.openTab('requests'); }));
    });
  }

  // ---- Activity
  function loadActivity(page) {
    var id = hid(), box = boxes.act;
    box.textContent = '';
    box.append(SA.skeleton(5));
    getJson('/admin/sa/activity?hospital_id=' + id + '&page=' + page + '&page_size=20').then(function (d) {
      if (id !== hid()) return;
      box.textContent = '';
      var c = card('Activity for this hospital');
      if (!d.items.length) c.append(empty('No activity recorded yet.'));
      else c.append(tableOf(['When (IST)', 'Who', 'Action', 'Target'], d.items.map(function (it) {
        return [fmtDateTime(it.created_at), h('span', null, [it.actor_name, h('div', 'sa-row-sub', it.actor_role)]),
          h('span', null, [SA.actionText(it.action), it.details ? h('div', 'sa-row-sub', it.details) : null]), SA.targetNode(it)];
      })));
      if (d.total > d.page_size) {
        c.append(h('div', 'sa-pager', [
          d.page > 1 ? btn('Previous', 'btn btn-outline btn-sm', function () { loadActivity(d.page - 1); }) : h('span'),
          h('span', null, 'Page ' + d.page + ' \u00B7 ' + d.total + ' entries'),
          d.has_more ? btn('Next', 'btn btn-outline btn-sm', function () { loadActivity(d.page + 1); }) : h('span')
        ]));
      }
      c.append(h('div', 'sa-card-foot', [a('#/activity?hospital=' + id, 'btn btn-outline btn-sm', 'Open in Activity page')]));
      box.append(c);
    }).catch(function (e) {
      if (id !== hid()) return;
      box.textContent = '';
      box.append(SA.errorBox(e.message || 'Could not load activity.', function () { loadActivity(page); }));
    });
  }

  // ---- Notes
  function loadNotes() {
    var id = hid(), box = boxes.notes;
    box.textContent = '';
    box.append(SA.skeleton(4));
    fetchSummary().then(function (s) {
      if (id !== hid()) return;
      box.textContent = '';
      var c = card('Private notes');
      c.append(h('div', 'sa-row-sub', 'Only you can see these notes. Hospital staff never do.'));
      var ta = h('textarea', 'form-control sa-notes'); ta.maxLength = 4000; ta.value = s.notes || ''; ta.setAttribute('aria-label', 'Private notes about this hospital');
      var status = h('span', null, '');
      var count = h('span', null, '');
      var save = btn('Save notes', 'btn btn-primary btn-sm', function () {
        save.disabled = true;
        status.textContent = 'Saving\u2026';
        api('PUT', '/admin/sa/hospital/' + id + '/notes', { notes: ta.value }, false, true).then(function (r) {
          if (summary && summary.hospital_id === id) summary.notes = r.notes;
          status.textContent = 'Saved ' + fmtDateTime(r.updated_at) + ' IST';
        }).catch(function (e) { status.textContent = e.message || 'Could not save.'; }).then(function () { save.disabled = false; });
      });
      function tick() { count.textContent = ta.value.length + ' / 4000'; }
      ta.addEventListener('input', tick);
      tick();
      c.append(ta, h('div', 'sa-notes-bar', [h('span', null, [count, ' \u00B7 ', status]), save]));
      box.append(c);
    }).catch(function (e) {
      if (id !== hid()) return;
      box.textContent = '';
      box.append(SA.errorBox(e.message || 'Could not load notes.', function () { loaded.notes = false; SA.openTab('notes'); }));
    });
  }

  init360();
})();