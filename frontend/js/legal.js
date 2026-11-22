/* ScribeKare legal UI. Loaded on every app page (js/api.js adds it) and directly by privacy.html and terms.html.
   - Legal.mountPage(el, "terms"|"privacy")  full page: audience cards, searchable contents, one section at a time
                                             (or all sections), progress bar, previous / next
   - Legal.open("terms"|"privacy")           reader dialog (profile menu > Settings > Privacy Policy / Terms of Service)
   - first sign-in: a dialog with both documents that must be accepted once per version (staff and portal accounts)
   - Legal.whenAccepted()                    promise that resolves when acceptance is not needed or has been given
   All document text comes from js/legal-content.js and is written with textContent only.
   The address bar is never changed by these pages (no #section in the URL). */
(function () {
  "use strict";
  if (window.Legal) return;
  var D = window.LEGAL_DOCS;
  if (!D) return;

  var path = location.pathname || "";
  var ON_PUBLIC = path === "/" || /(^|\/)(home|login|privacy|terms|verify|index)(\.html)?\/?$/i.test(path);
  var PORTAL = /\/my-(health|appointments)(\.html)?\/?$/i.test(path);
  var DEFAULT_AUD = PORTAL ? "patients" : "hospitals";
  var BRAND = window.BRAND_NAME || "ScribeKare";
  var COMPANY = window.COMPANY_LEGAL_NAME || BRAND;
  var DOC_TITLE = { terms: "Terms of Service", privacy: "Privacy Policy" };
  var DOC_PAGE = { terms: "terms.html", privacy: "privacy.html" };
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function tok(s) { return String(s).replace(/\{\{company\}\}/g, COMPANY).replace(/\{\{brand\}\}/g, BRAND); }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = text;
    return e;
  }
  function btn(label, cls, fn) { var b = el("button", cls, label); b.type = "button"; b.addEventListener("click", fn); return b; }

  // ------------------------------------------------------------------ document rendering
  var MAIL = "<svg width=\"22\" height=\"22\" fill=\"none\" viewBox=\"0 0 24 24\" stroke=\"currentColor\" stroke-width=\"2\" aria-hidden=\"true\"><rect x=\"3\" y=\"5\" width=\"18\" height=\"14\" rx=\"2\"/><path stroke-linecap=\"round\" stroke-linejoin=\"round\" d=\"M3 7l9 6 9-6\"/></svg>";

  function contactBlock(docKey) {
    var c = window.LEGAL_CONTACT || {};
    var email = c.email || "support@scribekare.com";
    var subject = (docKey === "terms" ? "Terms grievance" : docKey === "privacy" ? "Privacy grievance" : "Grievance");
    var box = el("div", "lg-contact");
    var ic = el("span", "lg-contact-ic");
    ic.innerHTML = MAIL;
    var tx = el("div", "lg-contact-tx");
    tx.append(el("strong", "", c.name ? "Grievance Officer, " + c.name : "Grievance Officer"), el("span", "", COMPANY));
    if (c.address) tx.append(el("span", "", c.address));
    var line = el("span", "", "Email: ");
    line.append(el("strong", "lg-mailtext", email));   // plain text on purpose: no link, no button
    tx.append(line);
    box.append(ic, tx);
    return box;
  }

  function renderBlock(b, parent, docKey) {
    if (typeof b === "string") { parent.append(el("p", "", tok(b))); return; }
    if (b.h) { parent.append(el("h4", "lg-sub", tok(b.h))); return; }
    if (b.ul || b.ol) {
      var list = el(b.ul ? "ul" : "ol", "lg-list");
      (b.ul || b.ol).forEach(function (t) { list.append(el("li", "", tok(t))); });
      parent.append(list);
      return;
    }
    if (b.note) { parent.append(el("div", "lg-note", tok(b.note))); return; }
    if (b.table) {
      var wrap = el("div", "lg-tablewrap");
      var t = el("table", "lg-table");
      var tr = el("tr");
      b.table.head.forEach(function (h) { tr.append(el("th", "", tok(h))); });
      var thead = el("thead");
      thead.append(tr);
      t.append(thead);
      var tb = el("tbody");
      b.table.rows.forEach(function (r) {
        var row = el("tr");
        r.forEach(function (c) { row.append(el("td", "", tok(c))); });
        tb.append(row);
      });
      t.append(tb);
      wrap.append(t);
      parent.append(wrap);
      return;
    }
    if (b.contact) parent.append(contactBlock(docKey));
  }

  function glanceNode(d) {
    var g = el("div", "lg-glance");
    g.append(el("div", "lg-glance-t", "At a glance"));
    var ul = el("ul");
    d.summary.forEach(function (s) { ul.append(el("li", "", tok(s))); });
    g.append(ul);
    return g;
  }
  function sectionNode(s, k, docKey, fancy, level) {
    var sec = el("section", "lg-sec");
    var h;
    if (fancy) {
      h = el(level || "h2", "lg-h lg-h-fancy");
      h.append(el("span", "lg-num", String(k + 1)), el("span", "", tok(s.title)));
    } else {
      h = el(level || "h3", "lg-h", (k + 1) + ". " + tok(s.title));
    }
    sec.append(h);
    s.blocks.forEach(function (b) { renderBlock(b, sec, docKey); });
    return sec;
  }
  function overviewNode(d) {
    var sec = el("section", "lg-sec");
    var h = el("h2", "lg-h lg-h-fancy");
    h.append(el("span", "lg-num", "i"), el("span", "", "Overview"));
    sec.append(h);
    if (d.lead) sec.append(el("p", "lg-lead", tok(d.lead)));
    if (d.summary) sec.append(glanceNode(d));
    return sec;
  }
  // Compact rendering for the dialogs: everything in one scroll.
  function renderDoc(docKey, aud) {
    var d = D[docKey][aud];
    var node = el("div", "lg-doc");
    if (d.lead) node.append(el("p", "lg-lead", tok(d.lead)));
    if (d.summary) node.append(glanceNode(d));
    d.sections.forEach(function (s, i) { node.append(sectionNode(s, i, docKey, false, "h3")); });
    return node;
  }
  function metaLine(docKey, aud) {
    return DOC_TITLE[docKey] + " \u00B7 " + D.audiences[aud].label + " \u00B7 Effective " + D.effective + " \u00B7 Version " + D.version;
  }

  // ------------------------------------------------------------------ viewer (tabs + scrolling text) for the dialogs
  function Viewer(docKey, aud) {
    var state = { doc: docKey, aud: aud };
    var root = el("div", "lg-viewer");
    var bar = el("div", "lg-tabbar");
    var docTabs = el("div", "lg-tabs"), audTabs = el("div", "lg-tabs");
    docTabs.setAttribute("role", "tablist"); audTabs.setAttribute("role", "tablist");
    docTabs.setAttribute("aria-label", "Document"); audTabs.setAttribute("aria-label", "Audience");
    var meta = el("div", "lg-meta");
    var scroll = el("div", "lg-scroll lg-doc");
    scroll.tabIndex = 0;
    scroll.setAttribute("aria-label", "Document text");
    var dBtns = {}, aBtns = {};
    ["terms", "privacy"].forEach(function (k) {
      var b = btn(DOC_TITLE[k], "lg-tab", function () { state.doc = k; paint(); });
      b.setAttribute("role", "tab"); dBtns[k] = b; docTabs.append(b);
    });
    ["hospitals", "patients"].forEach(function (k) {
      var b = btn(D.audiences[k].label, "lg-tab", function () { state.aud = k; paint(); });
      b.setAttribute("role", "tab"); aBtns[k] = b; audTabs.append(b);
    });
    function paint() {
      Object.keys(dBtns).forEach(function (k) { dBtns[k].setAttribute("aria-selected", k === state.doc ? "true" : "false"); });
      Object.keys(aBtns).forEach(function (k) { aBtns[k].setAttribute("aria-selected", k === state.aud ? "true" : "false"); });
      meta.textContent = metaLine(state.doc, state.aud);
      scroll.textContent = "";
      scroll.append(renderDoc(state.doc, state.aud));
      scroll.scrollTop = 0;
    }
    bar.append(docTabs);   // the dialog shows only the part for this person (staff or patient)
    root.append(bar, meta, scroll);
    paint();
    return { el: root, firstFocus: dBtns[docKey] };
  }

  // ------------------------------------------------------------------ first sign-in: two collapsed options, one opens at a time
  function Accordion(aud) {
    var root = el("div", "lg-acc");
    var rows = [], firstHead = null;
    ["terms", "privacy"].forEach(function (k) {
      var item = el("div", "lg-acc-item");
      var head = el("button", "lg-acc-head");
      head.type = "button";
      head.setAttribute("aria-expanded", "false");
      var panel = el("div", "lg-acc-panel lg-doc");
      panel.id = "lg-acc-" + k;
      panel.hidden = true;
      panel.tabIndex = 0;
      panel.setAttribute("role", "region");
      panel.setAttribute("aria-label", DOC_TITLE[k]);
      head.setAttribute("aria-controls", panel.id);
      var t = el("span", "lg-acc-t");
      t.append(el("strong", "", DOC_TITLE[k]), el("span", "", D.audiences[aud].label + " \u00B7 Effective " + D.effective));
      var chev = el("span", "lg-acc-chev");
      chev.innerHTML = CHEV;
      head.append(t, chev);
      head.addEventListener("click", function () {
        var open = panel.hidden;
        if (root.parentNode) root.parentNode.classList.toggle("has-open", open);   // hides the intro line so the text gets the room
        rows.forEach(function (r) { r.panel.hidden = true; r.head.setAttribute("aria-expanded", "false"); r.item.classList.remove("open"); });
        if (open) {
          if (!panel.firstChild) panel.append(renderDoc(k, aud));   // built only when opened
          panel.hidden = false;
          head.setAttribute("aria-expanded", "true");
          item.classList.add("open");
          panel.scrollTop = 0;
        }
      });
      item.append(head, panel);
      root.append(item);
      rows.push({ item: item, head: head, panel: panel });
      if (!firstHead) firstHead = head;
    });
    return { el: root, firstFocus: firstHead };
  }

  // ------------------------------------------------------------------ modal helper
  var lastFocus = null;
  function openModal(opts) {
    lastFocus = document.activeElement;
    var ov = el("div", "lg-ov");
    var box = el("div", "lg-modal");
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-modal", "true");
    box.setAttribute("aria-label", opts.title);
    var head = el("div", "lg-mhead");
    head.append(el("h2", "", opts.title));
    var api = { overlay: ov, box: box };
    api.close = function () {
      document.removeEventListener("keydown", onKey, true);
      ov.remove();
      if (lastFocus && lastFocus.focus) lastFocus.focus();
    };
    if (opts.dismissible) {
      var x = btn("\u00D7", "lg-x", api.close);
      x.setAttribute("aria-label", "Close");
      head.append(x);
    }
    box.append(head, opts.body);
    if (opts.footer) box.append(opts.footer);
    ov.append(box);
    if (opts.dismissible) ov.addEventListener("mousedown", function (e) { if (e.target === ov) api.close(); });
    function onKey(e) {
      if (e.key === "Escape" && opts.dismissible) { e.preventDefault(); api.close(); return; }
      if (e.key !== "Tab" || !box.contains(document.activeElement)) return;   // focus is in the sign-out confirmation: leave it alone
      var f = box.querySelectorAll("button:not([disabled]), a[href], input, [tabindex=\"0\"]");
      if (!f.length) return;
      var first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
    document.addEventListener("keydown", onKey, true);
    document.body.append(ov);
    return api;
  }

  // ------------------------------------------------------------------ reader dialog (profile > Settings)
  function openReader(docKey) {
    var key = docKey || "privacy";
    var viewer = Viewer(key, DEFAULT_AUD);
    var foot = el("div", "lg-mfoot");
    var full = el("a", "lg-link", "Open as a full page");
    full.target = "_blank";
    full.rel = "noopener";
    full.href = DOC_PAGE[key];
    foot.append(full);
    var m;
    foot.append(btn("Close", "lg-btn lg-btn-ghost", function () { m.close(); }));
    m = openModal({ title: "Privacy and Terms", body: viewer.el, footer: foot, dismissible: true });
    viewer.firstFocus.focus();
  }

  // ------------------------------------------------------------------ profile menu > Settings
  var GEAR = "<svg width=\"16\" height=\"16\" fill=\"none\" viewBox=\"0 0 24 24\" stroke=\"currentColor\" stroke-width=\"2\" aria-hidden=\"true\"><circle cx=\"12\" cy=\"12\" r=\"3\"/><path stroke-linecap=\"round\" stroke-linejoin=\"round\" d=\"M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z\"/></svg>";
  var CHEV = "<svg class=\"lg-chev\" width=\"14\" height=\"14\" fill=\"none\" viewBox=\"0 0 24 24\" stroke=\"currentColor\" stroke-width=\"2\" aria-hidden=\"true\"><path stroke-linecap=\"round\" stroke-linejoin=\"round\" d=\"M6 9l6 6 6-6\"/></svg>";

  function addSettings() {
    var menu = document.getElementById("profile-menu");
    if (!menu) return false;
    if (menu.querySelector("[data-legal-settings]")) return true;
    var wrap = el("div", "lg-settings");
    wrap.setAttribute("data-legal-settings", "");
    var head = el("button", "profile-menu-item lg-settings-head");
    head.type = "button";
    head.setAttribute("aria-expanded", "false");
    head.innerHTML = GEAR + "<span>Settings</span>" + CHEV;
    var sub = el("div", "lg-settings-sub");
    sub.hidden = true;
    [["privacy", "Privacy Policy"], ["terms", "Terms of Service"]].forEach(function (o) {
      var b = el("button", "profile-menu-item lg-sub-item", o[1]);
      b.type = "button";
      b.addEventListener("click", function () {
        if (typeof closeProfileMenu === "function") closeProfileMenu();
        openReader(o[0]);
      });
      sub.append(b);
    });
    head.addEventListener("click", function () {
      var open = sub.hidden;
      sub.hidden = !open;
      head.setAttribute("aria-expanded", open ? "true" : "false");
    });
    wrap.append(head, sub);
    var danger = menu.querySelector(".profile-menu-item.danger");
    if (danger) menu.insertBefore(wrap, danger); else menu.append(wrap);
    return true;
  }

  // ------------------------------------------------------------------ first sign-in acceptance
  var acceptedResolve;
  var acceptedPromise = new Promise(function (r) { acceptedResolve = r; });

  function showAccept(ep) {
    var wrap = el("div", "lg-acceptwrap");
    wrap.append(el("p", "lg-intro", "Before you continue, please read and accept our Terms of Service and Privacy Policy. They explain how " + BRAND + " works, how information is used and protected, and the choices you have. Tap either one to read it."));
    var acc = Accordion(DEFAULT_AUD);   // only the part for this person: staff see the hospital version, patients the patient version
    wrap.append(acc.el);

    var foot = el("div", "lg-mfoot lg-mfoot-col");
    var label = el("label", "lg-check");
    var cb = el("input");
    cb.type = "checkbox";
    label.append(cb, el("span", "", "I have read and agree to the Terms of Service and the Privacy Policy."));
    var row = el("div", "lg-row");
    var err = el("div", "lg-err");
    err.setAttribute("role", "alert");
    var m;
    var signOut = btn("Sign out", "lg-btn lg-btn-ghost", function () {
      if (typeof logout !== "function") return;
      logout();   // opens the "Sign out?" confirmation straight away; lift it above this dialog
      var ovs = document.querySelectorAll(".modal-overlay");
      if (ovs.length) ovs[ovs.length - 1].style.zIndex = "7000";
    });
    var go = btn("Accept and continue", "lg-btn lg-btn-primary", function () {
      go.disabled = true;
      err.textContent = "";
      api("POST", ep.accept, null, false, true).then(function () {
        m.close();
        acceptedResolve();
        window.dispatchEvent(new CustomEvent("legal:accepted"));
      }).catch(function (e) {
        err.textContent = (e && e.message) || "Could not save your acceptance. Please try again.";
        go.disabled = false;
      });
    });
    go.disabled = true;
    cb.addEventListener("change", function () { go.disabled = !cb.checked; });
    row.append(signOut, go);
    foot.append(label, err, row);
    m = openModal({ title: "Terms of Service and Privacy Policy", body: wrap, footer: foot, dismissible: false });
    acc.firstFocus.focus();
  }

  function runConsent() {
    if (ON_PUBLIC || typeof getToken !== "function" || !getToken() || typeof api !== "function") { acceptedResolve(); return; }
    var ep = PORTAL
      ? { status: "/portal/auth/consent-status", accept: "/portal/auth/consent" }
      : { status: "/legal/consent-status", accept: "/legal/consent" };
    api("GET", ep.status, null, false, true).then(function (s) {
      if (s && !s.accepted) showAccept(ep); else acceptedResolve();
    }).catch(function () { acceptedResolve(); });   // never block the page if this check fails
  }

  // ------------------------------------------------------------------ full page (privacy.html / terms.html)
  function mountPage(root, docKey) {
    var KEY = "sk_legal_view";
    var saved = {};
    try { saved = JSON.parse(sessionStorage.getItem(KEY) || "{}"); } catch (e) { saved = {}; }
    var st = { aud: saved.aud === "patients" ? "patients" : "hospitals", all: !!saved.all, i: 0, q: "" };
    function save() { try { sessionStorage.setItem(KEY, JSON.stringify({ aud: st.aud, all: st.all })); } catch (e) { /* ignore */ } }

    root.textContent = "";
    var tabs = el("div", "lg-pagetabs");
    tabs.setAttribute("role", "tablist");
    tabs.setAttribute("aria-label", "Who this applies to");
    var tBtns = {};
    ["hospitals", "patients"].forEach(function (k) {
      var b = el("button", "lg-ptab");
      b.type = "button";
      b.setAttribute("role", "tab");
      b.append(el("strong", "", D.audiences[k].label), el("span", "", D.audiences[k].short));
      b.addEventListener("click", function () {
        if (st.aud === k) return;
        st.aud = k; st.i = 0; st.q = ""; search.value = "";
        save(); paint(); toReaderTop();
      });
      tBtns[k] = b;
      tabs.append(b);
    });

    var shell = el("div", "lg-shell");
    var side = el("aside", "lg-side");
    side.setAttribute("aria-label", "Contents");
    var sideToggle = el("button", "lg-side-toggle");
    sideToggle.type = "button";
    sideToggle.setAttribute("aria-expanded", "false");
    var sideLabel = el("span", "", "Contents");
    sideToggle.append(sideLabel);
    var sideBody = el("div", "lg-side-body");
    var search = el("input", "lg-search");
    search.type = "search";
    search.placeholder = "Search this page";
    search.setAttribute("aria-label", "Search this page");
    var list = el("ul", "lg-navlist");
    sideBody.append(el("div", "lg-side-t", "Contents"), search, list);
    side.append(sideToggle, sideBody);

    var reader = el("section", "lg-reader");
    reader.setAttribute("aria-label", DOC_TITLE[docKey]);
    var lab = el("span", "lg-rlab");
    var prog = el("div", "lg-prog");
    var pbar = el("i");
    prog.append(pbar);
    var modeBtn = el("button", "lg-mode");
    modeBtn.type = "button";
    var bar = el("div", "lg-rbar");
    bar.append(lab, prog, modeBtn);
    var body = el("div", "lg-rbody lg-doc");
    body.tabIndex = -1;
    var foot = el("div", "lg-rfoot");
    var prevB = btn("\u2190 Previous", "lg-btn lg-btn-ghost", function () { go(st.i - 1); });
    var nextB = btn("Next \u2192", "lg-btn lg-btn-primary", function () { go(st.i + 1); });
    foot.append(prevB, nextB);
    reader.append(bar, body, foot);
    shell.append(side, reader);
    root.append(tabs, shell);

    var cache = {};
    function items(aud) {
      if (cache[aud]) return cache[aud];
      var d = D[docKey][aud];
      var out = [];
      var ov = overviewNode(d);
      out.push({ title: "Overview", n: "i", node: ov, text: ov.textContent.toLowerCase() });
      d.sections.forEach(function (s, k) {
        var node = sectionNode(s, k, docKey, true, "h2");
        out.push({ title: tok(s.title), n: String(k + 1), node: node, text: (tok(s.title) + " " + node.textContent).toLowerCase() });
      });
      cache[aud] = out;
      return out;
    }

    function renderList() {
      var its = items(st.aud), q = st.q.trim().toLowerCase(), shown = 0;
      list.textContent = "";
      its.forEach(function (it, k) {
        if (q && it.text.indexOf(q) < 0) return;
        shown++;
        var li = el("li");
        var b = el("button", "lg-ni" + (k === st.i ? " on" : ""));
        b.type = "button";
        b.dataset.i = String(k);
        if (k === st.i) b.setAttribute("aria-current", "true");
        b.append(el("span", "n", it.n), el("span", "t", it.title));
        li.append(b);
        list.append(li);
      });
      if (!shown) list.append(el("li", "lg-nomatch", "No section matches \u201C" + st.q.trim() + "\u201D."));
      sideLabel.textContent = "Contents \u00B7 " + its[st.i].title;
    }

    var spy = null;
    function stopSpy() { if (spy) { spy.disconnect(); spy = null; } }
    function startSpy() {
      stopSpy();
      if (!("IntersectionObserver" in window)) return;
      var its = items(st.aud), seen = {};
      spy = new IntersectionObserver(function (entries) {
        entries.forEach(function (en) { seen[en.target.getAttribute("data-k")] = en.isIntersecting; });
        var first = null;
        Object.keys(seen).map(Number).sort(function (a, b) { return a - b; }).some(function (k) { if (seen[k]) { first = k; return true; } return false; });
        if (first !== null && first !== st.i) { st.i = first; renderList(); }
      }, { rootMargin: "-90px 0px -60% 0px" });
      its.forEach(function (it, k) { it.node.setAttribute("data-k", String(k)); spy.observe(it.node); });
    }

    function renderReader() {
      var its = items(st.aud), n = its.length - 1;
      stopSpy();
      body.textContent = "";
      if (st.all) its.forEach(function (it) { body.append(it.node); });
      else body.append(its[st.i].node);
      lab.textContent = st.all ? "All sections" : (st.i === 0 ? "Overview" : "Section " + st.i + " of " + n);
      pbar.style.width = (st.all ? 100 : Math.round(st.i / n * 100)) + "%";
      modeBtn.textContent = st.all ? "Read one at a time" : "Read all sections";
      foot.hidden = st.all;
      prevB.disabled = st.i === 0;
      nextB.disabled = st.i === n;
      if (st.all) startSpy();
    }

    function paint() {
      Object.keys(tBtns).forEach(function (k) { tBtns[k].setAttribute("aria-selected", k === st.aud ? "true" : "false"); });
      renderList();
      renderReader();
    }

    function toReaderTop() {
      var r = reader.getBoundingClientRect();
      if (r.top < 70 || r.top > window.innerHeight * 0.7) window.scrollTo({ top: Math.max(0, r.top + window.scrollY - 84), behavior: reduce ? "auto" : "smooth" });
    }

    function go(k) {
      var its = items(st.aud);
      if (k < 0 || k >= its.length) return;
      st.i = k;
      side.classList.remove("open");
      sideToggle.setAttribute("aria-expanded", "false");
      if (st.all) {
        renderList();
        its[k].node.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
      } else {
        renderList();
        renderReader();
        toReaderTop();
        try { body.focus({ preventScroll: true }); } catch (e) { /* ignore */ }
      }
    }

    list.addEventListener("click", function (e) {
      var b = e.target.closest("button[data-i]");
      if (b) go(parseInt(b.dataset.i, 10));
    });
    search.addEventListener("input", function () { st.q = search.value; renderList(); });
    search.addEventListener("keydown", function (e) {
      if (e.key !== "Enter") return;
      e.preventDefault();
      var first = list.querySelector("button[data-i]");
      if (first) go(parseInt(first.dataset.i, 10));
    });
    sideToggle.addEventListener("click", function () {
      var open = !side.classList.contains("open");
      side.classList.toggle("open", open);
      sideToggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
    modeBtn.addEventListener("click", function () {
      st.all = !st.all;
      save();
      renderReader();
      if (st.all) { items(st.aud)[st.i].node.scrollIntoView({ block: "start" }); } else { toReaderTop(); }
    });
    document.addEventListener("keydown", function (e) {
      if (st.all || e.metaKey || e.ctrlKey || e.altKey) return;
      var t = e.target;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
      if (e.key === "ArrowRight") go(st.i + 1);
      else if (e.key === "ArrowLeft") go(st.i - 1);
    });
    var wasAll = null;
    window.addEventListener("beforeprint", function () { wasAll = st.all; if (!st.all) { st.all = true; renderReader(); } });
    window.addEventListener("afterprint", function () { if (wasAll === false) { st.all = false; renderReader(); } wasAll = null; });

    paint();
  }

  // ------------------------------------------------------------------ start
  function init() {
    if (!addSettings() && "MutationObserver" in window) {
      var obs = new MutationObserver(function () { if (addSettings()) obs.disconnect(); });
      obs.observe(document.body, { childList: true, subtree: true });
      setTimeout(function () { obs.disconnect(); }, 15000);
    }
    runConsent();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();

  window.Legal = { open: openReader, mountPage: mountPage, whenAccepted: function () { return acceptedPromise; } };
})();