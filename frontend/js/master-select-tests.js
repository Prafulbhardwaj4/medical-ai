/* "Add from master list" for the hospital Test Catalog (admin, sub_admin; super_admin on behalf of a hospital).
   Talks to /admin/master-select/tests/*. Every value that came from the server or from a spreadsheet goes
   through sanitize() (api.js) before it reaches innerHTML, and every button uses data-action plus ONE
   delegated listener, so nothing from a cell ever lands in an inline onclick. */
(function () {
  "use strict";
  const BASE = "/admin/master-select/tests";
  const MAX_PRICE = 1000000;
  const MAX_ROWS_SHOWN = 500;
  const MAX_LIST = 200;

  const me = typeof getDoctor === "function" ? getDoctor() : null;
  const IS_SUPER = !!(me && me.role === "super_admin");
  const HID = IS_SUPER ? Number(new URLSearchParams(window.location.search).get("hospital_id")) || 0 : 0;
  window.MS_SUPER_MODE = IS_SUPER && HID > 0;   // the page's own catalog list is skipped in this mode

  const state = { items: [], sel: new Map(), categories: [], previewId: null, timer: null, loaded: false, open: new Set() };
  const $ = (id) => document.getElementById(id);
  const esc = (v) => sanitize(v);

  // Only a super_admin ever sends hospital_id (the server refuses it for everybody else).
  function url(path, extra) {
    const p = new URLSearchParams();
    Object.keys(extra || {}).forEach((k) => { if (extra[k] !== "" && extra[k] != null) p.set(k, extra[k]); });
    if (HID) p.set("hospital_id", String(HID));
    const s = p.toString();
    return BASE + path + (s ? "?" + s : "");
  }

  function validPrice(v) {
    const n = Number(v);
    return v !== "" && v != null && isFinite(n) && n > 0 && n <= MAX_PRICE;
  }

  // ---------------------------------------------------------------- left side: the master list
  function rowHtml(t) {
    const id = Number(t.id);
    const done = !!t.already_added;
    const ticked = !done && state.sel.has(id);
    const price = ticked ? state.sel.get(id) : "";
    const names = Array.isArray(t.parameters) ? t.parameters : [];
    const hasParams = !!t.is_panel && names.length > 0;
    const isOpen = hasParams && state.open.has(id);
    const caret = hasParams
      ? `<button type="button" class="ms-caret" data-action="toggle" data-id="${id}" aria-expanded="${isOpen}" aria-label="${isOpen ? "Hide" : "Show"} parameters" title="${isOpen ? "Hide" : "Show"} parameters"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="6 9 12 15 18 9"></polyline></svg></button>`
      : "";
    const params = hasParams
      ? `<div class="ms-params"><div class="ms-params-title">Includes ${names.length} parameter${names.length === 1 ? "" : "s"}</div><ul>${names.map((n) => `<li>${esc(n)}</li>`).join("")}</ul></div>`
      : "";
    const badge = t.is_panel
      ? `<span class="badge badge-navy">Panel - ${esc(t.parameter_count)} parameters</span>`
      : `<span class="badge badge-grey">Single</span>`;
    const right = done
      ? `<span class="ms-already">Already added${t.already_inactive ? " (inactive)" : ""}</span>`
      : `<input type="number" class="form-control ms-price" data-price="${id}" placeholder="Rs" min="0" step="0.01" inputmode="decimal" value="${esc(price)}" ${ticked ? "" : "disabled"} aria-label="Price for ${esc(t.test_name)}" />`;
    return `<div class="ms-row${done ? " ms-done" : ""}${isOpen ? " ms-open" : ""}">
      <label class="ms-check"><input type="checkbox" data-id="${id}" ${ticked ? "checked" : ""} ${done ? "disabled" : ""} />
        <span class="ms-name">${esc(t.test_name)}${t.category ? `<small>${esc(t.category)}</small>` : ""}</span></label>
      ${badge}${caret}${right}${params}</div>`;
  }

  function renderList() {
    $("ms-list").innerHTML = state.items.length
      ? state.items.map(rowHtml).join("")
      : '<p style="color:var(--slate-light);padding:12px 0">No tests found in the master list. If you did not type a search, the master list has not been loaded yet. Please contact support.</p>';
    updateFooter();
  }

  function renderCategories() {
    const sel = $("ms-category");
    const cur = sel.value;
    sel.innerHTML = '<option value="">All Categories</option>' +
      state.categories.map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join("");
    sel.value = cur;
  }

  async function loadList() {
    try {
      const d = await api("GET", url("/list", { search: $("ms-search").value.trim(), category: $("ms-category").value }), null, false, true);
      state.items = d.items || [];
      if (!state.loaded || !$("ms-category").value) { state.categories = d.categories || []; renderCategories(); }
      state.loaded = true;
      state.items.forEach((t) => { if (t.already_added) state.sel.delete(Number(t.id)); });
      if (d.hospital && d.hospital.name) {
        $("ms-hospital").textContent = IS_SUPER ? "Hospital: " + d.hospital.name : "";
      }
      renderList();
    } catch (e) { toast(e.message, "error"); }
  }

  function updateFooter() {
    let need = 0;
    state.sel.forEach((p) => { if (!validPrice(p)) need += 1; });
    const n = state.sel.size;
    $("ms-footer-text").textContent = `${n} selected, ${need} need a price`;
    $("ms-add-btn").disabled = !(n > 0 && need === 0);
  }

  function showResult(r) {
    $("ms-result").innerHTML = `<div class="ms-resultbox"><strong>${esc(r.message)}</strong>
      <a href="#" data-action="undo" data-id="${esc(Number(r.import_id))}">Undo this</a></div>`;
  }

  function refreshHospitalList() {
    if (!window.MS_SUPER_MODE && typeof loadTests === "function") loadTests();
  }

  async function addSelected() {
    const items = [];
    state.sel.forEach((p, id) => items.push({ master_test_id: Number(id), price: Number(p) }));
    if (!items.length) return;
    try {
      const r = await api("POST", url("/add"), { items });
      state.sel.clear();
      showResult(r);
      toast(r.message, "success");
      await loadList();
      refreshHospitalList();
    } catch (e) {
      toast(e.message, "error");
      loadList();
    }
  }

  async function undoBatch(id) {
    const ok = await confirmModal(
      "This removes the tests you just added from your catalog. It is refused if any of them has already been used in an order.",
      { title: "Undo this?", okLabel: "Undo", danger: true });
    if (!ok) return;
    try {
      const r = await api("POST", url(`/undo/${Number(id)}`));
      $("ms-result").innerHTML = "";
      toast(r.message, "success");
      await loadList();
      refreshHospitalList();
    } catch (e) {
      const probs = e.data && e.data.problems ? e.data.problems : [];
      await alertModal([e.message].concat(probs.map((p) => "- " + p)).join("\n"), { title: "Cannot undo" });
    }
  }

  // ---------------------------------------------------------------- right side: Excel upload and preview
  function resetPreview() {
    state.previewId = null;
    ["ms-status", "ms-summary", "ms-errors", "ms-warnings", "ms-table"].forEach((id) => { $(id).innerHTML = ""; });
    $("ms-confirm").style.display = "none";
    $("ms-confirm").disabled = true;
  }

  function setStatus(msg, kind) {
    const color = kind === "error" ? "var(--danger,#dc2626)" : kind === "ok" ? "var(--success,#059669)" : "var(--slate)";
    $("ms-status").innerHTML = msg
      ? `<div class="ms-status" style="color:${color}">${esc(msg)}</div>` : "";
  }

  function issueList(items, title, open) {
    if (!items || !items.length) return "";
    const shown = items.slice(0, MAX_LIST).map((i) => `<li>${esc(i.text || i.message || i)}</li>`).join("");
    const more = items.length > MAX_LIST ? `<li>…and ${items.length - MAX_LIST} more</li>` : "";
    return `<details ${open ? "open" : ""} class="ms-issues"><summary>${esc(title)} (${items.length})</summary><ul>${shown}${more}</ul></details>`;
  }

  const STATUS = {
    ok: ["badge-green", "OK"], already: ["badge-grey", "Already added"], ignored: ["badge-grey", "Ignored"],
    not_found: ["badge-red", "Not found"], duplicate: ["badge-red", "Duplicate in file"],
    bad_price: ["badge-red", "Bad price"], price_missing: ["badge-red", "Price missing"],
  };

  function previewRowHtml(r) {
    const s = STATUS[r.status] || ["badge-grey", r.status];
    const sugg = (r.suggestions || []).length
      ? `<div class="ms-sugg">Did you mean: ${r.suggestions.map((x) =>
        `<button type="button" class="btn btn-outline btn-sm" data-action="accept" data-row="${esc(Number(r.row))}" data-mid="${esc(Number(x.master_test_id))}">${esc(x.name)}</button>`).join(" ")}</div>`
      : "";
    const shownName = r.master_name && r.master_name !== r.name ? `${esc(r.name)} <small>(${esc(r.master_name)})</small>` : esc(r.name);
    return `<tr><td>${esc(r.row)}</td><td>${shownName}</td><td>${r.price != null ? "Rs." + esc(r.price) : "-"}</td>
      <td><span class="badge ${s[0]}">${esc(s[1])}</span>${r.message ? `<div class="ms-msg">${esc(r.message)}</div>` : ""}${sugg}</td></tr>`;
  }

  function renderPreview(p) {
    $("ms-summary").innerHTML = p.summary_text ? `<div class="ms-summarybox">${esc(p.summary_text)}</div>` : "";
    $("ms-errors").innerHTML = issueList(p.errors, "Problems to fix (nothing is saved until these are fixed)", true);
    $("ms-warnings").innerHTML = issueList(p.warnings, "Notes (these do not block saving)", false);
    const rows = p.rows || [];
    if (rows.length) {
      $("ms-table").innerHTML = `<div class="table-wrap" style="max-height:46vh;overflow-y:auto"><table><thead><tr><th>Row</th><th>Test</th><th>Price</th><th>Status</th></tr></thead><tbody>${
        rows.slice(0, MAX_ROWS_SHOWN).map(previewRowHtml).join("")}</tbody></table></div>` +
        (rows.length > MAX_ROWS_SHOWN ? `<p class="ms-msg">Only the first ${MAX_ROWS_SHOWN} rows are shown. Every row in the file is checked.</p>` : "");
    } else {
      $("ms-table").innerHTML = "";
    }
    state.previewId = p.preview_id || null;
    if (p.errors && p.errors.length) {
      setStatus("This file has problems. Fix them in Excel and upload it again. Nothing was saved.", "error");
    } else if (p.nothing_to_add) {
      setStatus("Every test in this file is already added. Nothing to add.", "ok");
    } else if (!p.can_confirm) {
      setStatus("Fix the red lines (click a suggestion, or correct the file and upload it again). Nothing is saved yet.", "error");
    } else {
      setStatus(`File is OK. Check the summary, then press Confirm. (This preview is valid for ${Number(p.expires_in_minutes) || 30} minutes.)`, "ok");
    }
    $("ms-confirm").style.display = p.can_confirm ? "" : "none";
    $("ms-confirm").disabled = !p.can_confirm;
  }

  async function onFileChosen(file) {
    resetPreview();
    if (!file) return;
    setStatus("Checking your file…", "info");
    try {
      const fd = new FormData();
      fd.append("file", file);
      const p = await api("POST", url("/preview"), fd, true);
      if (p) renderPreview(p);
    } catch (e) { setStatus(e.message || "Could not check the file.", "error"); }
  }

  async function onAccept(row, mid) {
    if (!state.previewId) return;
    try {
      const p = await api("POST", url(`/preview/${encodeURIComponent(state.previewId)}/accept`), { row: Number(row), master_test_id: Number(mid) });
      if (p) renderPreview(p);
    } catch (e) { toast(e.message, "error"); }
  }

  async function onConfirm() {
    if (!state.previewId) return;
    const ok = await confirmModal(
      "This adds the tests in this file to the hospital's live test catalog with the prices in the file. You can undo it afterwards, but only while none of these tests has been used in an order.",
      { title: "Add these tests?", okLabel: "Confirm" });
    if (!ok) return;
    try {
      const r = await api("POST", url("/confirm"), { preview_id: state.previewId });
      resetPreview();
      showResult(r);
      toast(r.message, "success");
      await loadList();
      refreshHospitalList();
    } catch (e) {
      state.previewId = null;
      $("ms-confirm").disabled = true;
      const errs = e.data && e.data.errors ? e.data.errors : null;
      if (errs) $("ms-errors").innerHTML = issueList(errs, "Problems", true);
      setStatus(e.message || "Nothing was saved. Please upload the file again.", "error");
    }
  }

  // ---------------------------------------------------------------- panel open / close
  function openPanel() {
    $("ms-panel").style.display = "";
    resetPreview();
    loadList();
    document.body.style.overflow = "hidden";
  }

  function closePanel() {
    if (window.MS_SUPER_MODE) { window.location.href = "superadmin.html"; return; }
    $("ms-panel").style.display = "none";
    document.body.style.overflow = "";
    resetPreview();
    $("ms-result").innerHTML = "";
  }

  function init() {
    const panel = $("ms-panel");
    if (!panel) return;
    const openBtn = $("ms-open-btn");
    if (openBtn) openBtn.addEventListener("click", openPanel);

    panel.addEventListener("click", (ev) => {
      const el = ev.target.closest("[data-action]");
      if (!el) return;
      const a = el.getAttribute("data-action");
      if (a === "undo") { ev.preventDefault(); undoBatch(el.getAttribute("data-id")); }
      else if (a === "toggle") {
        const tid = Number(el.getAttribute("data-id"));
        if (state.open.has(tid)) state.open.delete(tid); else state.open.add(tid);
        const open = state.open.has(tid);
        const row = el.closest(".ms-row");
        if (row) row.classList.toggle("ms-open", open);
        el.setAttribute("aria-expanded", String(open));
        el.setAttribute("aria-label", (open ? "Hide" : "Show") + " parameters");
        el.title = (open ? "Hide" : "Show") + " parameters";
      }
      else if (a === "close") closePanel();
      else if (a === "add") addSelected();
      else if (a === "template") downloadFile(`${BASE}/template`, "MedScribe_Select_Tests_Template.xlsx");
      else if (a === "choose") $("ms-file").click();
      else if (a === "confirm") onConfirm();
      else if (a === "accept") onAccept(el.getAttribute("data-row"), el.getAttribute("data-mid"));
    });

    panel.addEventListener("change", (ev) => {
      const t = ev.target;
      if (t.id === "ms-category") { loadList(); return; }
      if (t.id === "ms-file") { const f = t.files && t.files[0]; t.value = ""; onFileChosen(f); return; }
      if (t.matches("input[type=checkbox][data-id]")) {
        const id = Number(t.getAttribute("data-id"));
        const box = panel.querySelector(`input[data-price="${id}"]`);
        if (t.checked) { state.sel.set(id, box ? box.value : ""); if (box) { box.disabled = false; box.focus(); } }
        else { state.sel.delete(id); if (box) { box.value = ""; box.disabled = true; } }
        updateFooter();
      }
    });

    panel.addEventListener("input", (ev) => {
      const t = ev.target;
      if (t.id === "ms-search") { clearTimeout(state.timer); state.timer = setTimeout(loadList, 300); return; }
      if (t.matches("input[data-price]")) {
        const id = Number(t.getAttribute("data-price"));
        if (state.sel.has(id)) state.sel.set(id, t.value);
        t.classList.toggle("ms-bad", t.value !== "" && !validPrice(t.value));
        updateFooter();
      }
    });

    if (window.MS_SUPER_MODE) {
      const list = document.querySelector(".main-content > .card:not(#ms-panel)");
      if (list) list.style.display = "none";
      $("ms-super-note").style.display = "";
      openPanel();
    } else if (new URLSearchParams(window.location.search).get("master") === "1") {
      openPanel();
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();