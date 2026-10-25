// whatsapp-messages.js
// The whole "WhatsApp messages" screen: header button + badge, modal, list, filters, bubble view.
// Loaded (after api.js) on every staff page whose header can be used by super_admin, admin or receptionist.
// The messages live in the database (GET /whatsapp-messages); this file only shows them.
// Message text, names and numbers are only ever written with textContent / text nodes. No innerHTML, no inline handlers.
(function () {
  "use strict";
  if (window.__waMessagesLoaded) return;
  window.__waMessagesLoaded = true;

  var ROLES = ["super_admin", "admin", "receptionist"];
  var doc = (typeof getDoctor === "function") ? getDoctor() : null;
  if (!doc || ROLES.indexOf(doc.role) === -1 || typeof api !== "function") return;
  var IS_SUPER = doc.role === "super_admin";
  var API = "/whatsapp-messages";
  var PAGE_SIZE = 15;

  var STATUS_OPTIONS = [
    ["all", "All"], ["due", "Due now"], ["pending", "Pending"], ["scheduled", "Scheduled"],
    ["sent", "Sent"], ["expired", "Expired"], ["cancelled", "Cancelled"]
  ];

  var state = {
    status: "all", q: "", older: false, page: 1, total: 0, hasMore: false,
    items: [], expanded: null, view: "whatsapp", loading: false, listError: ""
  };
  var revealed = {};   // id -> full text of a secret message, only while "Show" is on
  var rowError = {};   // id -> inline red line
  var copied = {};     // id -> "msg" | "num" (button label feedback)
  var busy = {};       // id -> true while a request for that row is running
  var modalEl = null, listEl = null, pagerEl = null, topErrEl = null, badgeEl = null;
  var reqSeq = 0, searchTimer = null, sampleBusy = false;

  // ---------------------------------------------------------------- helpers
  function h(tag, cls, text) {
    var el = document.createElement(tag);
    if (cls) el.className = cls;
    if (text !== undefined && text !== null) el.textContent = text;
    return el;
  }

  function actionBtn(label, action, id, cls, disabled) {
    var b = h("button", "btn btn-outline btn-sm wa-act" + (cls ? " " + cls : ""), label);
    b.type = "button";
    b.setAttribute("data-action", action);
    b.setAttribute("data-id", String(id));
    if (disabled) b.disabled = true;
    return b;
  }

  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  // Server times are naive IST: read the digits as written, never convert them to the browser's time zone.
  function parseIst(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(iso || "");
    if (!m) return null;
    return { y: +m[1], mo: +m[2], d: +m[3], h: +m[4], mi: +m[5] };
  }
  function fmtTime(p) {
    var hr = p.h % 12 === 0 ? 12 : p.h % 12;
    return (hr < 10 ? "0" : "") + hr + ":" + (p.mi < 10 ? "0" : "") + p.mi + " " + (p.h >= 12 ? "PM" : "AM");
  }
  function fmtDateTime(iso) {
    var p = parseIst(iso);
    if (!p) return "";
    return p.d + " " + MONTHS[p.mo - 1] + " " + p.y + ", " + fmtTime(p);
  }
  function fmtClock(iso) {
    var p = parseIst(iso);
    return p ? fmtTime(p) : "";
  }

  function roleWord(r) { return String(r || "").replace(/_/g, "-"); }

  function phoneFull(p) {
    var d = String(p || "").replace(/\D/g, "");
    return d.length === 10 ? "+91" + d : (String(p || "").charAt(0) === "+" ? "+" + d : d);
  }
  function phoneShown(p) {
    var d = String(p || "").replace(/\D/g, "");
    return d.length === 10 ? "+91 " + d.slice(0, 5) + " " + d.slice(5) : String(p || "");
  }

  function statusInfo(m) {
    switch (m.status) {
      case "due": return { label: "Due now", cls: "badge-red" };
      case "pending": return { label: "Pending", cls: "badge-amber" };
      case "scheduled": return { label: "Scheduled for " + fmtDateTime(m.due_at), cls: "badge-navy" };
      case "sent": return { label: "Sent", cls: "badge-green" };
      case "expired": return { label: "Expired", cls: "badge-grey" };
      case "cancelled": return { label: "Cancelled", cls: "badge-grey" };
      default: return { label: String(m.status || ""), cls: "badge-grey" };
    }
  }

  function findItem(id) {
    for (var i = 0; i < state.items.length; i++) if (state.items[i].id === id) return state.items[i];
    return null;
  }

  function shownText(m) {
    if (m.is_secret && revealed[m.id] !== undefined) return revealed[m.id];
    return m.text;
  }

  // *bold* -> real bold, everything else stays as typed (line breaks, emojis, divider lines).
  function appendFormatted(container, text) {
    var re = /\*([^*\n]+)\*/g, last = 0, m;
    while ((m = re.exec(text))) {
      if (m.index > last) container.appendChild(document.createTextNode(text.slice(last, m.index)));
      var s = document.createElement("strong");
      s.textContent = m[1];
      container.appendChild(s);
      last = m.index + m[0].length;
    }
    if (last < text.length) container.appendChild(document.createTextNode(text.slice(last)));
  }

  function copyToClipboard(text) {
    return new Promise(function (resolve) {
      function legacy() {
        try {
          var ta = document.createElement("textarea");
          ta.value = text;
          ta.setAttribute("readonly", "");
          ta.style.cssText = "position:fixed;top:0;left:0;opacity:0";
          document.body.appendChild(ta);
          ta.select();
          var ok = document.execCommand("copy");
          ta.remove();
          resolve(!!ok);
        } catch (e) { resolve(false); }
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () { resolve(true); }, legacy);
      } else {
        legacy();
      }
    });
  }

  function call(method, path, body) {
    return api(method, path, body || null, false, true);
  }

  // ---------------------------------------------------------------- styles
  function injectStyles() {
    if (document.getElementById("wa-styles")) return;
    var css = [
      ".wa-header-btn{position:relative;display:inline-flex;align-items:center;gap:6px;background:var(--white);border:1px solid var(--border);color:var(--navy);padding:5px 11px;border-radius:6px;font-size:.78rem;font-weight:600;cursor:pointer;font-family:inherit;white-space:nowrap}",
      ".wa-header-btn:hover{border-color:#25d366;color:#128c7e}",
      ".wa-header-btn svg{color:#25d366;flex-shrink:0}",
      ".wa-header-badge{position:absolute;top:-7px;right:-7px;background:#dc2626;color:#fff;font-size:10px;font-weight:700;min-width:17px;height:17px;border-radius:9px;display:none;align-items:center;justify-content:center;padding:0 4px;line-height:1}",
      "@media (min-width:901px){.wa-header-btn{margin-left:auto;margin-right:14px}.wa-header-btn + .topbar-doctor{margin-left:0 !important}}",
      "@media (max-width:900px){.wa-header-btn{margin-right:6px}}",
      "@media (max-width:520px){.wa-header-label{display:none}.wa-header-btn{padding:6px 8px}}",
      ".wa-modal{max-width:820px;width:100%;padding:22px}",
      ".wa-modal .modal-header{margin-bottom:12px;padding-bottom:12px}",
      ".wa-toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:10px}",
      ".wa-toolbar select,.wa-toolbar input{border:1px solid var(--border-mid);border-radius:6px;padding:7px 10px;font-size:.85rem;font-family:inherit;background:var(--white);color:var(--navy)}",
      ".wa-toolbar input{flex:1;min-width:150px}",
      ".wa-samples{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px;padding:8px 10px;background:var(--smoke);border:1px dashed var(--border-mid);border-radius:8px;align-items:center}",
      ".wa-samples span{font-size:.75rem;color:var(--slate);margin-right:auto}",
      ".wa-err{color:#b91c1c;font-size:.8rem;margin:6px 0;display:block}",
      ".wa-empty{padding:30px 10px;text-align:center;color:var(--slate);font-size:.9rem}",
      ".wa-row{border:1px solid var(--border);border-radius:10px;margin-bottom:8px;background:var(--white);overflow:hidden}",
      ".wa-row.is-due{border-left:4px solid #dc2626;background:#fff7f7}",
      ".wa-row.is-open{box-shadow:var(--shadow-sm)}",
      ".wa-row-head{display:flex;align-items:center;gap:10px;width:100%;background:none;border:none;padding:10px 12px;cursor:pointer;text-align:left;font-family:inherit;color:inherit}",
      ".wa-row-main{flex:1;min-width:0;display:flex;flex-direction:column;gap:3px}",
      ".wa-row-line1{display:flex;gap:8px;align-items:center;flex-wrap:wrap}",
      ".wa-row-name{font-weight:700;font-size:.92rem;color:var(--navy)}",
      ".wa-row-role{font-size:.72rem;background:var(--smoke-mid);color:var(--slate);padding:1px 8px;border-radius:10px}",
      ".wa-row-line2{display:flex;gap:6px 12px;flex-wrap:wrap;font-size:.78rem;color:var(--slate)}",
      ".wa-sample-tag{font-size:.68rem;font-weight:700;background:#ede9fe;color:#6d28d9;padding:1px 7px;border-radius:10px;letter-spacing:.04em}",
      ".wa-arrow{flex-shrink:0;width:18px;height:18px;color:var(--slate);transition:transform .15s}",
      ".wa-row.is-open .wa-arrow{transform:rotate(180deg)}",
      ".wa-row-body{display:none;padding:4px 12px 12px;border-top:1px solid var(--border)}",
      ".wa-row.is-open .wa-row-body{display:block}",
      ".wa-switch{display:inline-flex;margin:8px 0;border:1px solid var(--border-mid);border-radius:20px;overflow:hidden}",
      ".wa-switch button{background:var(--white);border:none;padding:4px 12px;font-size:.75rem;cursor:pointer;font-family:inherit;color:var(--slate)}",
      ".wa-switch button.on{background:#128c7e;color:#fff}",
      ".wa-chat{background:#efeae2;border:1px solid var(--border);border-radius:10px;padding:14px 12px;display:flex;justify-content:flex-start}",
      ".wa-bubble{background:#d9fdd3;border-radius:8px 8px 8px 2px;padding:7px 9px 5px;max-width:min(100%,420px);box-shadow:0 1px 1px rgba(0,0,0,.13);color:#111b21;font-size:.86rem;line-height:1.4}",
      ".wa-bubble-text{white-space:pre-wrap;word-break:break-word;overflow-wrap:anywhere}",
      ".wa-bubble-meta{display:flex;justify-content:flex-end;align-items:center;gap:3px;font-size:.68rem;color:#667781;margin-top:2px}",
      ".wa-ticks{color:#53bdeb;font-weight:700;letter-spacing:-2px;font-size:.8rem}",
      ".wa-plain{white-space:pre-wrap;word-break:break-word;overflow-wrap:anywhere;border:1.5px solid var(--border-mid);border-radius:8px;padding:10px 12px;font-size:.85rem;font-family:'DM Mono',monospace;background:var(--smoke);margin:0;color:var(--navy)}",
      ".wa-acts{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}",
      ".wa-note{font-size:.78rem;color:var(--slate);margin-top:8px}",
      ".wa-pager{display:flex;gap:10px;align-items:center;justify-content:center;margin-top:10px;font-size:.82rem;color:var(--slate)}"
    ].join("\n");
    var st = document.createElement("style");
    st.id = "wa-styles";
    st.textContent = css;
    document.head.appendChild(st);
  }

  // ---------------------------------------------------------------- header button + badge
  function svgWhatsapp() {
    var ns = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("width", "16"); svg.setAttribute("height", "16");
    svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor"); svg.setAttribute("stroke-width", "2");
    var p = document.createElementNS(ns, "path");
    p.setAttribute("stroke-linecap", "round"); p.setAttribute("stroke-linejoin", "round");
    p.setAttribute("d", "M3 21l1.65-4.95A8.5 8.5 0 1112 20.5a8.4 8.4 0 01-4.1-1.05L3 21z");
    svg.appendChild(p);
    return svg;
  }

  function injectHeaderButton() {
    if (document.getElementById("wa-header-btn")) return;
    var anchor = document.querySelector(".topbar .topbar-doctor") || document.querySelector(".topbar-doctor");
    if (!anchor || !anchor.parentNode) return;
    var btn = h("button", "wa-header-btn");
    btn.type = "button";
    btn.id = "wa-header-btn";
    btn.setAttribute("aria-label", "WhatsApp messages");
    btn.appendChild(svgWhatsapp());
    btn.appendChild(h("span", "wa-header-label", "WhatsApp"));
    badgeEl = h("span", "wa-header-badge", "0");
    btn.appendChild(badgeEl);
    btn.addEventListener("click", openModal);
    anchor.parentNode.insertBefore(btn, anchor);
  }

  function setBadge(n) {
    if (!badgeEl) return;
    if (n > 0) {
      badgeEl.textContent = n > 99 ? "99+" : String(n);
      badgeEl.style.display = "flex";
    } else {
      badgeEl.style.display = "none";
    }
  }

  function refreshBadge() {
    return call("GET", API + "/badge").then(function (r) {
      if (r && typeof r.count === "number") setBadge(r.count);
    }).catch(function () { /* the badge just keeps its last value */ });
  }

  // ---------------------------------------------------------------- modal
  function buildModal() {
    modalEl = h("div", "modal-overlay");
    modalEl.id = "wa-modal";
    var box = h("div", "modal wa-modal");
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-label", "WhatsApp messages");

    var head = h("div", "modal-header");
    head.appendChild(h("h2", "", "WhatsApp messages"));
    var close = h("button", "modal-close", "\u00d7");
    close.type = "button";
    close.setAttribute("aria-label", "Close");
    close.setAttribute("data-wa", "close");
    head.appendChild(close);
    box.appendChild(head);

    var bar = h("div", "wa-toolbar");
    var sel = document.createElement("select");
    sel.setAttribute("data-wa", "status");
    sel.setAttribute("aria-label", "Status");
    STATUS_OPTIONS.forEach(function (o) {
      var op = document.createElement("option");
      op.value = o[0]; op.textContent = o[1];
      sel.appendChild(op);
    });
    bar.appendChild(sel);
    var inp = document.createElement("input");
    inp.type = "search";
    inp.placeholder = "Search name or mobile number";
    inp.setAttribute("data-wa", "search");
    inp.setAttribute("aria-label", "Search name or mobile number");
    inp.maxLength = 60;
    bar.appendChild(inp);
    var older = h("button", "btn btn-outline btn-sm", "Show older");
    older.type = "button";
    older.setAttribute("data-wa", "older");
    bar.appendChild(older);
    box.appendChild(bar);

    if (IS_SUPER) {
      var sb = h("div", "wa-samples");
      sb.appendChild(h("span", "", "Super admin: review every template with made-up details"));
      var mk = h("button", "btn btn-outline btn-sm", "Create sample messages");
      mk.type = "button"; mk.setAttribute("data-wa", "sample-create");
      var clr = h("button", "btn btn-outline btn-sm", "Clear samples");
      clr.type = "button"; clr.setAttribute("data-wa", "sample-clear");
      sb.appendChild(mk); sb.appendChild(clr);
      box.appendChild(sb);
    }

    topErrEl = h("span", "wa-err");
    topErrEl.style.display = "none";
    box.appendChild(topErrEl);

    listEl = h("div", "wa-list");
    box.appendChild(listEl);
    pagerEl = h("div", "wa-pager");
    box.appendChild(pagerEl);

    modalEl.appendChild(box);
    document.body.appendChild(modalEl);

    modalEl.addEventListener("click", function (e) {
      if (e.target === modalEl) { closeModal(); return; }
      var t = e.target.closest("[data-wa]");
      if (!t) return;
      var k = t.getAttribute("data-wa");
      if (k === "close") closeModal();
      else if (k === "older") { state.older = !state.older; state.page = 1; state.expanded = null; clearSecrets(); syncToolbar(); loadList(); }
      else if (k === "prev") { if (state.page > 1) { state.page--; state.expanded = null; clearSecrets(); loadList(); } }
      else if (k === "next") { if (state.hasMore) { state.page++; state.expanded = null; clearSecrets(); loadList(); } }
      else if (k === "sample-create") sampleAction("create");
      else if (k === "sample-clear") sampleAction("clear");
    });
    modalEl.addEventListener("change", function (e) {
      if (e.target.getAttribute("data-wa") === "status") {
        state.status = e.target.value; state.page = 1; state.expanded = null; clearSecrets(); loadList();
      }
    });
    modalEl.addEventListener("input", function (e) {
      if (e.target.getAttribute("data-wa") !== "search") return;
      var v = e.target.value;
      clearTimeout(searchTimer);
      searchTimer = setTimeout(function () {
        state.q = v.trim(); state.page = 1; state.expanded = null; clearSecrets(); loadList();
      }, 300);
    });
    listEl.addEventListener("click", onListClick);
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && modalEl && modalEl.classList.contains("open")) closeModal();
    });
  }

  function syncToolbar() {
    var o = modalEl.querySelector('[data-wa="older"]');
    if (o) o.textContent = state.older ? "Last 7 days only" : "Show older";
  }

  function showTopError(msg) {
    if (!topErrEl) return;
    topErrEl.textContent = msg || "";
    topErrEl.style.display = msg ? "block" : "none";
  }

  function openModal() {
    if (!modalEl) buildModal();
    state.expanded = null;
    clearSecrets();
    syncToolbar();
    modalEl.classList.add("open");
    if (typeof syncBodyScrollLock === "function") { try { syncBodyScrollLock(); } catch (e) { } }
    loadList();
  }

  function closeModal() {
    if (!modalEl) return;
    modalEl.classList.remove("open");
    clearSecrets();
    state.expanded = null;
    if (typeof syncBodyScrollLock === "function") { try { syncBodyScrollLock(); } catch (e) { } }
    refreshBadge();
  }

  function clearSecrets() { revealed = {}; }

  // ---------------------------------------------------------------- list
  function loadList(silent) {
    var seq = ++reqSeq;
    if (!silent) { state.loading = true; state.listError = ""; renderList(); }
    var qs = "?status=" + encodeURIComponent(state.status) + "&page=" + state.page + "&page_size=" + PAGE_SIZE +
      (state.older ? "&older=true" : "") + (state.q ? "&q=" + encodeURIComponent(state.q) : "");
    return call("GET", API + qs).then(function (r) {
      if (seq !== reqSeq || !r) return;
      state.items = r.items || [];
      state.total = r.total || 0;
      state.hasMore = !!r.has_more;
      state.loading = false;
      state.listError = "";
      renderList();
    }).catch(function (e) {
      if (seq !== reqSeq) return;
      state.loading = false;
      state.listError = (e && e.message) || "Could not load messages.";
      renderList();
    });
  }

  function renderList() {
    if (!listEl) return;
    listEl.textContent = "";
    if (state.loading) { listEl.appendChild(h("div", "wa-empty", "Loading\u2026")); renderPager(); return; }
    if (state.listError) { listEl.appendChild(h("span", "wa-err", state.listError)); renderPager(); return; }
    if (!state.items.length) {
      listEl.appendChild(h("div", "wa-empty", "No messages here."));
      renderPager();
      return;
    }
    state.items.forEach(function (m) { listEl.appendChild(buildRow(m)); });
    renderPager();
  }

  function renderPager() {
    if (!pagerEl) return;
    pagerEl.textContent = "";
    var pages = Math.max(1, Math.ceil(state.total / PAGE_SIZE));
    if (pages <= 1 && state.page === 1) return;
    var prev = h("button", "btn btn-outline btn-sm", "Previous");
    prev.type = "button"; prev.setAttribute("data-wa", "prev"); prev.disabled = state.page <= 1;
    var next = h("button", "btn btn-outline btn-sm", "Next");
    next.type = "button"; next.setAttribute("data-wa", "next"); next.disabled = !state.hasMore;
    pagerEl.appendChild(prev);
    pagerEl.appendChild(h("span", "", "Page " + state.page + " of " + pages));
    pagerEl.appendChild(next);
  }

  function arrowSvg() {
    var ns = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("class", "wa-arrow");
    svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor"); svg.setAttribute("stroke-width", "2.5");
    var p = document.createElementNS(ns, "path");
    p.setAttribute("stroke-linecap", "round"); p.setAttribute("stroke-linejoin", "round");
    p.setAttribute("d", "M19 9l-7 7-7-7");
    svg.appendChild(p);
    return svg;
  }

  function buildRow(m) {
    var open = state.expanded === m.id;
    var row = h("div", "wa-row" + (open ? " is-open" : "") + (m.status === "due" ? " is-due" : ""));
    row.setAttribute("data-row", String(m.id));

    var head = h("button", "wa-row-head");
    head.type = "button";
    head.setAttribute("data-action", "toggle");
    head.setAttribute("data-id", String(m.id));
    head.setAttribute("aria-expanded", open ? "true" : "false");

    var main = h("span", "wa-row-main");
    var l1 = h("span", "wa-row-line1");
    l1.appendChild(h("span", "wa-row-name", m.recipient_name));
    l1.appendChild(h("span", "wa-row-role", roleWord(m.recipient_role)));
    if (m.is_sample) l1.appendChild(h("span", "wa-sample-tag", "SAMPLE"));
    var si = statusInfo(m);
    l1.appendChild(h("span", "badge " + si.cls, si.label));
    main.appendChild(l1);

    var l2 = h("span", "wa-row-line2");
    l2.appendChild(h("span", "", phoneShown(m.recipient_phone)));
    l2.appendChild(h("span", "", m.type_label));
    if (IS_SUPER && m.hospital_name) l2.appendChild(h("span", "", m.hospital_name));
    l2.appendChild(h("span", "", "Created " + fmtDateTime(m.created_at)));
    main.appendChild(l2);

    head.appendChild(main);
    head.appendChild(arrowSvg());
    row.appendChild(head);

    var body = h("div", "wa-row-body");
    if (open) fillBody(body, m);
    row.appendChild(body);
    return row;
  }

  function fillBody(body, m) {
    var text = shownText(m);

    var sw = h("div", "wa-switch");
    var b1 = h("button", state.view === "whatsapp" ? "on" : "", "WhatsApp view");
    b1.type = "button"; b1.setAttribute("data-action", "view-wa"); b1.setAttribute("data-id", String(m.id));
    var b2 = h("button", state.view === "plain" ? "on" : "", "Plain text");
    b2.type = "button"; b2.setAttribute("data-action", "view-plain"); b2.setAttribute("data-id", String(m.id));
    sw.appendChild(b1); sw.appendChild(b2);
    body.appendChild(sw);

    if (state.view === "plain") {
      var pre = h("pre", "wa-plain");
      pre.textContent = text;
      pre.setAttribute("data-plain", String(m.id));
      body.appendChild(pre);
    } else {
      var chat = h("div", "wa-chat");
      var bubble = h("div", "wa-bubble");
      var tx = h("div", "wa-bubble-text");
      appendFormatted(tx, text);
      bubble.appendChild(tx);
      var meta = h("div", "wa-bubble-meta");
      meta.appendChild(h("span", "", fmtClock(m.created_at)));
      meta.appendChild(h("span", "wa-ticks", "\u2713\u2713"));
      bubble.appendChild(meta);
      chat.appendChild(bubble);
      body.appendChild(chat);
    }

    var isBusy = !!busy[m.id];
    var acts = h("div", "wa-acts");
    acts.appendChild(actionBtn(copied[m.id] === "msg" ? "Copied \u2713" : "Copy message", "copy-msg", m.id, "", isBusy || (m.is_secret && !m.secret_available)));
    acts.appendChild(actionBtn(copied[m.id] === "num" ? "Copied \u2713" : "Copy number", "copy-num", m.id, "", false));
    if (m.is_secret && m.secret_available) {
      acts.appendChild(actionBtn(revealed[m.id] !== undefined ? "Hide" : "Show", revealed[m.id] !== undefined ? "hide" : "show", m.id, "", isBusy));
    }
    if (m.can_mark_sent) acts.appendChild(actionBtn("Mark as sent", "mark-sent", m.id, "btn-primary", isBusy));
    if (m.can_cancel) acts.appendChild(actionBtn("Cancel", "cancel", m.id, "", isBusy));
    if (m.can_undo) acts.appendChild(actionBtn("Undo", "undo", m.id, "", isBusy));
    body.appendChild(acts);

    if (m.status === "sent" && m.sent_marked_at) {
      body.appendChild(h("div", "wa-note", "Marked as sent" + (m.sent_marked_by_name ? " by " + m.sent_marked_by_name : "") + " on " + fmtDateTime(m.sent_marked_at)));
    }
    if (m.status === "scheduled") {
      body.appendChild(h("div", "wa-note", "Scheduled for " + fmtDateTime(m.due_at)));
    }
    if (rowError[m.id]) body.appendChild(h("span", "wa-err", rowError[m.id]));
  }

  function refreshRow(id) {
    var m = findItem(id);
    var old = listEl && listEl.querySelector('[data-row="' + id + '"]');
    if (!m || !old) return;
    old.replaceWith(buildRow(m));
  }

  // ---------------------------------------------------------------- row actions
  function onListClick(e) {
    var t = e.target.closest("[data-action]");
    if (!t || !listEl.contains(t)) return;
    var id = parseInt(t.getAttribute("data-id"), 10);
    var m = findItem(id);
    if (!m) return;
    var a = t.getAttribute("data-action");
    if (a === "toggle") return toggleRow(m);
    if (a === "view-wa") { state.view = "whatsapp"; return refreshRow(id); }
    if (a === "view-plain") { state.view = "plain"; return refreshRow(id); }
    if (busy[id] && a !== "copy-num") return;
    if (a === "copy-msg") return copyMessage(m);
    if (a === "copy-num") return copyNumber(m);
    if (a === "show") return showSecret(m);
    if (a === "hide") { delete revealed[id]; return refreshRow(id); }
    if (a === "mark-sent") return changeStatus(m, "mark-sent");
    if (a === "cancel") return changeStatus(m, "cancel");
    if (a === "undo") return changeStatus(m, "undo");
  }

  function toggleRow(m) {
    var prev = state.expanded;
    if (prev !== null) { delete revealed[prev]; delete rowError[prev]; }
    state.expanded = prev === m.id ? null : m.id;
    if (prev !== null) refreshRow(prev);
    if (state.expanded !== null) refreshRow(state.expanded);
  }

  function flashCopied(id, kind) {
    copied[id] = kind;
    refreshRow(id);
    setTimeout(function () { delete copied[id]; refreshRow(id); }, 1600);
  }

  function copyBlocked(m) {
    rowError[m.id] = "Copy is blocked by this browser. Select the text below and copy it by hand.";
    state.view = "plain";
    refreshRow(m.id);
    var pre = listEl.querySelector('[data-plain="' + m.id + '"]');
    if (pre) {
      var r = document.createRange();
      r.selectNodeContents(pre);
      var s = window.getSelection();
      s.removeAllRanges();
      s.addRange(r);
    }
  }

  function copyMessage(m) {
    delete rowError[m.id];
    if (!m.is_secret) {
      return copyToClipboard(m.text).then(function (ok) { ok ? flashCopied(m.id, "msg") : copyBlocked(m); });
    }
    // Secret: the real text only comes from the server, after the role and hospital are checked again.
    if (revealed[m.id] !== undefined) {
      return copyToClipboard(revealed[m.id]).then(function (ok) { ok ? flashCopied(m.id, "msg") : copyBlocked(m); });
    }
    busy[m.id] = true;
    refreshRow(m.id);
    call("POST", API + "/" + m.id + "/reveal").then(function (r) {
      busy[m.id] = false;
      if (!r || typeof r.text !== "string") { refreshRow(m.id); return; }
      return copyToClipboard(r.text).then(function (ok) {
        if (ok) flashCopied(m.id, "msg");
        else {
          revealed[m.id] = r.text;  // browser blocked the copy: show it so it can be copied by hand
          copyBlocked(m);
        }
      });
    }).catch(function (err) {
      busy[m.id] = false;
      rowError[m.id] = (err && err.message) || "Could not copy this message.";
      refreshRow(m.id);
    });
  }

  function copyNumber(m) {
    delete rowError[m.id];
    copyToClipboard(phoneFull(m.recipient_phone)).then(function (ok) {
      if (ok) flashCopied(m.id, "num");
      else { rowError[m.id] = "Copy is blocked by this browser. The number is " + phoneFull(m.recipient_phone); refreshRow(m.id); }
    });
  }

  function showSecret(m) {
    delete rowError[m.id];
    busy[m.id] = true;
    refreshRow(m.id);
    call("POST", API + "/" + m.id + "/reveal").then(function (r) {
      busy[m.id] = false;
      if (r && typeof r.text === "string") revealed[m.id] = r.text;
      refreshRow(m.id);
    }).catch(function (err) {
      busy[m.id] = false;
      rowError[m.id] = (err && err.message) || "Could not show this message.";
      refreshRow(m.id);
    });
  }

  function changeStatus(m, action) {
    delete rowError[m.id];
    busy[m.id] = true;
    refreshRow(m.id);
    call("POST", API + "/" + m.id + "/" + action).then(function (updated) {
      busy[m.id] = false;
      delete revealed[m.id];
      if (updated) {
        for (var i = 0; i < state.items.length; i++) if (state.items[i].id === m.id) { state.items[i] = updated; break; }
      }
      refreshRow(m.id);
      refreshBadge();
    }).catch(function (err) {
      busy[m.id] = false;
      rowError[m.id] = (err && err.message) || "That did not work. Try again.";
      refreshRow(m.id);
    });
  }

  // ---------------------------------------------------------------- samples (super admin)
  function sampleAction(kind) {
    if (!IS_SUPER || sampleBusy) return;
    sampleBusy = true;
    showTopError("");
    var hid = parseInt(new URLSearchParams(window.location.search).get("hospital_id"), 10);
    var req = kind === "create"
      ? call("POST", API + "/samples", { hospital_id: hid > 0 ? hid : null })
      : call("DELETE", API + "/samples");
    req.then(function () {
      sampleBusy = false;
      state.page = 1; state.expanded = null; clearSecrets();
      loadList();
    }).catch(function (err) {
      sampleBusy = false;
      showTopError((err && err.message) || "Could not do that.");
    });
  }

  // ---------------------------------------------------------------- start
  function tick() {
    if (document.hidden) return;
    refreshBadge();
    if (modalEl && modalEl.classList.contains("open") && state.expanded === null && !state.loading) loadList(true);
  }

  function boot() {
    injectStyles();
    injectHeaderButton();
    refreshBadge();
    setInterval(tick, 60 * 1000);
    document.addEventListener("visibilitychange", function () { if (!document.hidden) refreshBadge(); });
  }

  window.openWhatsappMessages = openModal;
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();