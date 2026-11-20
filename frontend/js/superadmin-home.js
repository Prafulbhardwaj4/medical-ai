/* ScribeKare Super Admin: Overview home ("Needs attention", KPI tiles, renewals, AI usage,
   waiting requests, activity feed, unread notifications) and the Activity page.
   One aggregated call: GET /admin/sa/overview. Activity: GET /admin/sa/activity.
   No patient data exists in these responses. All text goes in through text nodes. */
(function () {
  'use strict';
  var SA = window.SA;
  if (!SA) return;
  var h = SA.h, a = SA.a, hospLink = SA.hospLink, fmtDate = SA.fmtDate, fmtDateTime = SA.fmtDateTime, inr = SA.inr;
  var ATTENTION_PREVIEW = 8;
  var homeSeq = 0, actSeq = 0, homeTimer = null, hospitalsCache = null;

  function tierName(t) { return (typeof tierLabel === 'function') ? tierLabel(t) : t; }
  function actionText(s) { s = String(s || '').replace(/_/g, ' '); return s.charAt(0).toUpperCase() + s.slice(1); }
  function btn(label, cls, fn) { var b = h('button', cls, label); b.type = 'button'; b.addEventListener('click', fn); return b; }
  function card(title, badge, extra) {
    var head = h('div', 'card-header', [h('h2', null, title)]);
    if (badge !== null && badge !== undefined) head.append(h('span', 'badge ' + (badge ? 'badge-red' : 'badge-grey'), String(badge)));
    var c = h('section', 'card sa-card', [head]);
    if (extra) c.append(extra);
    return c;
  }
  function empty(text) { return h('div', 'sa-empty', text); }

  function targetHref(it) {
    var t = it.target_type, id = it.target_id;
    if (t === 'hospital' && id) return '#/hospital/' + Number(id);
    if (t === 'doctor' && it.hospital_id) return '#/hospital/' + Number(it.hospital_id) + '/staff';
    if (t === 'hospital_lead' && id) return '#/hospital-leads?id=' + Number(id);
    if (t === 'upgrade_request' && id) return '#/upgrade-requests?id=' + Number(id);
    if (t === 'plan_inquiry' && id) return '#/plan-inquiries?id=' + Number(id);
    return it.hospital_id ? '#/hospital/' + Number(it.hospital_id) + '/activity' : null;
  }
  function targetNode(it) {
    var label = it.target_label || String(it.target_type || '').replace(/_/g, ' ');
    var href = targetHref(it);
    return href ? a(href, 'sa-link', label) : document.createTextNode(label);
  }

  // ---------------------------------------------------------------- Overview home
  function attentionCard(att) {
    var c = card('Needs attention', att.total);
    var list = h('div', 'sa-list');
    var foot = h('div', 'sa-card-foot');
    var expanded = false;
    function paint() {
      list.textContent = '';
      if (!att.items.length) { list.append(empty('Nothing needs attention today.')); }
      att.items.slice(0, expanded ? att.items.length : ATTENTION_PREVIEW).forEach(function (it) {
        list.append(h('div', 'sa-row sev-' + it.severity, [
          h('span', 'sa-dot'),
          h('div', 'sa-row-main', [
            h('div', 'sa-row-title', [a(it.link, 'sa-link', it.title)]),
            h('div', 'sa-row-sub', [hospLink(it.hospital_id, it.hospital_name), ' \u00B7 ' + it.detail])
          ]),
          a(it.link, 'btn btn-outline btn-sm', 'Open')
        ]));
      });
      foot.textContent = '';
      if (att.items.length > ATTENTION_PREVIEW) {
        foot.append(btn(expanded ? 'Show fewer' : 'Show all ' + att.items.length, 'btn btn-outline btn-sm', function () { expanded = !expanded; paint(); }));
      }
      if (att.total > att.items.length) foot.append(h('span', 'sa-row-sub', 'Showing the ' + att.items.length + ' most urgent of ' + att.total + '.'));
    }
    paint();
    c.append(list);
    c.append(foot);
    return c;
  }

  function kpiTile(label, value, sub, href) {
    return a(href, 'sa-kpi', [h('div', 'sa-kpi-label', label), h('div', 'sa-kpi-value', String(value)), h('div', 'sa-kpi-sub', sub)]);
  }
  function kpiGrid(k) {
    var g = h('div', 'sa-kpis');
    g.append(kpiTile('Active hospitals', k.active_hospitals, 'of ' + k.total_hospitals + ' total \u00B7 +' + k.new_hospitals_this_month + ' this month', '#/hospitals?status=active'));
    g.append(kpiTile('Inactive hospitals', k.inactive_hospitals, 'deactivated', '#/hospitals?status=inactive'));
    g.append(kpiTile('Staff accounts', k.staff_active, k.staff_total + ' in total across hospitals', '#/hospitals'));
    g.append(kpiTile('Expected MRR', inr(k.expected_mrr), 'list price, active hospitals', '#/overview'));
    g.append(kpiTile('Collected this month', inr(k.collected_this_month), k.collected_this_month_count + ' payments \u00B7 last month ' + inr(k.collected_last_month), '#/overview'));
    g.append(kpiTile('Collected, all time', inr(k.collected_total), 'renewals and pilot fees recorded', '#/overview'));
    return g;
  }
  function planMixCard(mix) {
    var chips = h('div', 'sa-chips');
    var keys = Object.keys(mix || {});
    keys.forEach(function (t) { chips.append(a('#/hospitals?plan=' + encodeURIComponent(t), 'sa-chip', [tierName(t), h('strong', null, String(mix[t]))])); });
    return card('Plan mix (active hospitals)', null, keys.length ? chips : empty('No active hospitals yet.'));
  }

  var STATUS = { overdue: ['Overdue', 'badge-red'], grace: ['In grace', 'badge-red'], due_soon: ['Due soon', 'badge-amber'], upcoming: ['Upcoming', 'badge-grey'] };
  function renewalsCard(rows) {
    var list = h('div', 'sa-list');
    if (!rows.length) list.append(empty('No renewals due in the next 7 days.'));
    rows.forEach(function (r) {
      var st = STATUS[r.status] || ['', 'badge-grey'];
      var paid = r.last_paid_amount !== null && r.last_paid_amount !== undefined
        ? 'Last paid ' + inr(r.last_paid_amount) + ' on ' + fmtDate(r.last_paid_at)
        : 'No payment recorded yet';
      list.append(h('div', 'sa-row', [
        h('div', 'sa-row-main', [
          h('div', 'sa-row-title', [hospLink(r.hospital_id, r.hospital_name)]),
          h('div', 'sa-row-sub', tierName(r.tier) + ' \u00B7 ' + r.billing_period + ' \u00B7 ends ' + fmtDate(r.cycle_end)),
          h('div', 'sa-row-sub', paid + (r.expected_amount ? ' \u00B7 expected ' + inr(r.expected_amount) : ''))
        ]),
        h('span', 'badge ' + st[1], st[0])
      ]));
    });
    return card('Renewals and payments', rows.length, list);
  }

  function scribeCard(rows) {
    var list = h('div', 'sa-list');
    if (!rows.length) list.append(empty('No hospital is near its AI scribe limit.'));
    rows.forEach(function (r) {
      var pct = Math.max(0, Math.min(100, Number(r.percent) || 0));
      var color = r.percent >= 100 ? 'var(--danger)' : r.percent >= 80 ? 'var(--warn)' : 'var(--teal)';
      var fill = h('div', 'mini-progress-fill');
      fill.style.width = pct + '%';
      fill.style.background = color;
      var scope = r.kind === 'pilot_week' ? 'pilot week ' + r.week + ' of ' + r.total_weeks : r.kind === 'yearly' ? 'yearly pool' : 'this month';
      list.append(h('div', 'sa-row', [
        h('div', 'sa-row-main', [
          h('div', 'sa-row-title', [hospLink(r.hospital_id, r.hospital_name)]),
          h('div', 'sa-row-sub', r.used + ' of ' + r.cap + ' \u00B7 ' + scope),
          h('div', 'mini-progress-track', [fill])
        ]),
        h('span', 'badge ' + (r.percent >= 100 ? 'badge-red' : 'badge-amber'), r.percent + '%')
      ]));
    });
    return card('AI scribe usage', null, list);
  }

  var WAIT = [
    ['plan_inquiries', 'Plan inquiries', '#/plan-inquiries'],
    ['hospital_leads', 'Hospital leads', '#/hospital-leads'],
    ['upgrade_requests', 'Upgrade requests', '#/upgrade-requests'],
    ['suggestions', 'Suggestions', '#/suggestions']
  ];
  function waitingCard(w) {
    var total = 0;
    var body = h('div');
    WAIT.forEach(function (def) {
      var g = w[def[0]] || { new: 0, latest: [] };
      total += g.new;
      body.append(h('div', 'sa-subhead', [a(def[2] + (g.new ? '?status=' + (def[0] === 'suggestions' ? 'sent' : 'new') : ''), 'sa-link', def[1]), h('span', 'badge ' + (g.new ? 'badge-red' : 'badge-grey'), g.new + ' new')]));
      if (!g.latest.length) { body.append(h('div', 'sa-row-sub', 'Nothing waiting.')); return; }
      g.latest.forEach(function (x) {
        body.append(h('div', 'sa-row', [
          h('div', 'sa-row-main', [
            h('div', 'sa-row-title', [x.hospital_id ? hospLink(x.hospital_id, x.label) : a(def[2] + '?id=' + Number(x.id), 'sa-link', x.label)]),
            h('div', 'sa-row-sub', x.sub || '')
          ]),
          h('div', 'sa-row-end', fmtDateTime(x.created_at))
        ]));
      });
    });
    return card('Waiting for you', total, body);
  }

  function activityCard(items) {
    var list = h('div', 'sa-list');
    if (!items.length) list.append(empty('No recent activity.'));
    items.forEach(function (it) {
      list.append(h('div', 'sa-row', [
        h('div', 'sa-row-main', [
          h('div', 'sa-row-title', [it.actor_name + ' ', h('span', 'sa-row-sub', '(' + it.actor_role + ')')]),
          h('div', 'sa-row-sub', [actionText(it.action) + ' \u00B7 ', targetNode(it), it.hospital_id ? ' \u00B7 ' : '', it.hospital_id ? hospLink(it.hospital_id, it.hospital_name) : null])
        ]),
        h('div', 'sa-row-end', fmtDateTime(it.created_at))
      ]));
    });
    var c = card('Recent activity', null, list);
    c.append(h('div', 'sa-card-foot', [a('#/activity', 'btn btn-outline btn-sm', 'View all activity')]));
    return c;
  }

  function notificationsCard(n) {
    var list = h('div', 'sa-list');
    if (!n.items.length) list.append(empty('You are all caught up.'));
    n.items.forEach(function (x) {
      var row = h('button', 'sa-row sa-row-btn sev-' + (x.severity === 'critical' || x.severity === 'danger' ? 'critical' : x.severity === 'warning' ? 'warning' : 'info'), [
        h('span', 'sa-dot'),
        h('div', 'sa-row-main', [h('div', 'sa-row-title', x.title), h('div', 'sa-row-sub', x.message)]),
        h('div', 'sa-row-end', fmtDateTime(x.created_at))
      ]);
      row.type = 'button';
      row.addEventListener('click', function () {
        // Existing handler: marks computed alerts as seen, then opens the section and the hospital.
        if (typeof onNotifClick === 'function') onNotifClick(x.nav_section, x.hospital_id || null, x.computed ? x.id : '', x.id);
      });
      list.append(row);
    });
    var c = card('Unread notifications', n.unread_count, list);
    c.append(h('div', 'sa-card-foot', [btn('Open notification panel', 'btn btn-outline btn-sm', function () { if (typeof toggleNotifPanel === 'function') toggleNotifPanel(); })]));
    return c;
  }

  function renderHome(root, d) {
    root.textContent = '';
    var head = h('div', 'page-header sa-head', [
      h('div', null, [h('h1', null, 'Overview'), h('p', null, 'Updated ' + fmtDateTime(d.generated_at) + ' IST')]),
      btn('Refresh', 'btn btn-outline btn-sm', loadHome)
    ]);
    root.append(head);
    root.append(attentionCard(d.attention));
    root.append(kpiGrid(d.kpis));
    root.append(h('div', 'sa-grid-2', [renewalsCard(d.renewals), scribeCard(d.scribe_usage)]));
    root.append(h('div', 'sa-grid-2', [waitingCard(d.waiting), notificationsCard(d.notifications)]));
    root.append(h('div', 'sa-grid-2', [activityCard(d.activity), planMixCard(d.kpis.plan_mix)]));
  }

  async function loadHome() {
    var root = document.getElementById('section-home');
    if (!root) return;
    var my = ++homeSeq;
    if (!root.firstChild) { root.append(h('div', 'page-header', [h('h1', null, 'Overview')])); root.append(SA.skeleton(6)); }
    try {
      var d = await api('GET', '/admin/sa/overview', null, false, true);
      if (my !== homeSeq) return;
      renderHome(root, d);
    } catch (e) {
      if (my !== homeSeq) return;
      root.textContent = '';
      root.append(h('div', 'page-header', [h('h1', null, 'Overview')]));
      root.append(SA.errorBox(e.message || 'Could not load the overview.', loadHome));
    }
  }
  if (homeTimer) clearInterval(homeTimer);
  homeTimer = setInterval(function () {
    var el = document.getElementById('section-home');
    if (el && el.style.display !== 'none' && !document.hidden) loadHome();
  }, 60000);

  // ---------------------------------------------------------------- Activity page
  async function getHospitals() {
    if (hospitalsCache) return hospitalsCache;
    var src = (typeof allHospitalsCache !== 'undefined' && allHospitalsCache && allHospitalsCache.length) ? allHospitalsCache : null;
    try { if (!src) src = await api('GET', '/admin/hospitals-list', null, false, true); } catch (e) { src = []; }
    hospitalsCache = (src || []).map(function (x) { return { id: x.id, name: x.name }; })
      .sort(function (p, q) { return String(p.name).localeCompare(String(q.name)); });
    return hospitalsCache;
  }

  async function loadActivity() {
    var root = document.getElementById('section-activity');
    if (!root) return;
    var my = ++actSeq;
    var p = SA.parse();
    var hospitalId = parseInt(p.params.get('hospital'), 10) || 0;
    var page = Math.max(1, parseInt(p.params.get('page'), 10) || 1);
    var auditId = parseInt(p.params.get('audit'), 10) || 0;   // ?audit=<id> shows exactly one entry (linked from a payment)
    function link(hid, pg) {
      var q = [];
      if (hid) q.push('hospital=' + hid);
      if (pg > 1) q.push('page=' + pg);
      return '#/activity' + (q.length ? '?' + q.join('&') : '');
    }

    root.textContent = '';
    root.append(h('div', 'page-header', [h('h1', null, 'Activity'), h('p', null, 'Important actions across hospitals: who did what, and when (IST).')]));
    var filters = h('div', 'sa-filters');
    var sel = h('select', 'form-control');
    sel.setAttribute('aria-label', 'Filter by hospital');
    sel.style.width = 'auto';
    sel.append(new Option('All hospitals', ''));
    filters.append(sel);
    if (auditId) filters.append(h('span', 'sa-row-sub', 'Showing one entry.'), a(link(hospitalId, 1), 'btn btn-outline btn-sm', 'Show all entries'));
    root.append(filters);
    var body = h('div');
    body.append(SA.skeleton(6));
    root.append(body);

    getHospitals().then(function (list) {
      if (my !== actSeq) return;
      list.forEach(function (x) { sel.append(new Option(x.name, String(x.id))); });
      sel.value = hospitalId ? String(hospitalId) : '';
    });
    sel.addEventListener('change', function () { SA.go(link(parseInt(sel.value, 10) || 0, 1)); });

    try {
      var d = await api('GET', '/admin/sa/activity?page=' + page + '&page_size=25' + (hospitalId ? '&hospital_id=' + hospitalId : '') + (auditId ? '&audit_id=' + auditId : ''), null, false, true);
      if (my !== actSeq) return;
      body.textContent = '';
      if (!d.items.length) { body.append(empty('No activity found.')); return; }
      var table = h('table', 'sa-table');
      table.append(h('thead', null, [h('tr', null, ['When (IST)', 'Who', 'Action', 'Target', 'Hospital'].map(function (t) { return h('th', null, t); }))]));
      var tb = h('tbody');
      d.items.forEach(function (it) {
        tb.append(h('tr', null, [
          h('td', null, fmtDateTime(it.created_at)),
          h('td', null, [it.actor_name, h('div', 'sa-row-sub', it.actor_role)]),
          h('td', null, [actionText(it.action), it.details ? h('div', 'sa-row-sub', it.details) : null]),
          h('td', null, [targetNode(it)]),
          h('td', null, [it.hospital_id ? hospLink(it.hospital_id, it.hospital_name) : '-'])
        ]));
      });
      table.append(tb);
      body.append(h('div', 'sa-table-scroll', [h('div', 'table-wrap', [table])]));
      var from = (d.page - 1) * d.page_size + 1, to = from + d.items.length - 1;
      var prev = d.page > 1 ? a(link(hospitalId, d.page - 1), 'btn btn-outline btn-sm', 'Previous') : h('span');
      var next = d.has_more ? a(link(hospitalId, d.page + 1), 'btn btn-outline btn-sm', 'Next') : h('span');
      body.append(h('div', 'sa-pager', [prev, h('span', null, from + '\u2013' + to + ' of ' + d.total), next]));
    } catch (e) {
      if (my !== actSeq) return;
      body.textContent = '';
      body.append(SA.errorBox(e.message || 'Could not load activity.', loadActivity));
    }
  }

  SA.targetNode = targetNode;
  SA.actionText = actionText;
  SA.home = { load: loadHome };
  SA.activity = { load: loadActivity };
})();