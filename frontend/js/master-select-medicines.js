/* "Add from master list" for the hospital Medicine Catalog (admin, sub_admin, pharmacy; super_admin on behalf of a hospital).
   Talks to /admin/master-select/medicines/*. Every value that came from the server or from a spreadsheet goes
   through sanitize() (api.js) before it reaches innerHTML, and every button uses data-action plus ONE
   delegated listener, so nothing from a cell ever lands in an inline onclick. */
(function () {
  "use strict";
  const BASE = "/admin/master-select/medicines";
  const MAX_PRICE = 1000000;
  const MAX_PACK = 10000;
  const MAX_THRESHOLD = 1000000;
  const MAX_ROWS_SHOWN = 500;
  const MAX_LIST = 200;

  const me = typeof getDoctor === "function" ? getDoctor() : null;
  const IS_SUPER = !!(me && me.role === "super_admin");
  const HID = IS_SUPER ? Number(new URLSearchParams(window.location.search).get("hospital_id")) || 0 : 0;
  window.MS_SUPER_MODE = IS_SUPER && HID > 0;   // the page's own catalog list is skipped in this mode

  const state = { items: [], sel: new Map(), schedules: [], forms: [], previewId: null, timer: null, loaded: false };
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

  // ---------------------------------------------------------------- validation (same limits as the server)
  function validMrp(v) {
    const n = Number(v);
    return v !== "" && v != null && isFinite(n) && n > 0 && n <= MAX_PRICE;
  }
  function validPack(v) {
    const n = Number(v);
    return v !== "" && v != null && Number.isInteger(n) && n >= 1 && n <= MAX_PACK;
  }
  function validOptNum(v, max) {
    if (v === "" || v == null) return true;
    const n = Number(v);
    return isFinite(n) && n >= 0 && n <= max;
  }
  function validOptInt(v, max) {
    if (v === "" || v == null) return true;
    const n = Number(v);
    return Number.isInteger(n) && n >= 0 && n <= max;
  }
  function priceProblem(s) { return !validMrp(s.mrp) || !validPack(s.pack); }
  function otherProblem(s) {
    if (!validOptNum(s.nppa, MAX_PRICE) || !validOptInt(s.thr, MAX_THRESHOLD) || String(s.hsn || "").length > 20) return true;
    return s.brands.some((b) => (b.name || "").trim().length > 100 || !(b.mrp === "" || validMrp(b.mrp)));
  }

  function badge(schedule) {
    const s = String(schedule || "otc").toLowerCase();
    const cls = (s === "x" || s === "h1") ? "badge-red" : (s === "h" ? "badge-navy" : "badge-grey");
    return `<span class="badge ${cls}">${esc(s.toUpperCase())}</span>`;
  }

  // ---------------------------------------------------------------- left side: the master list
  function brandHtml(id, b, i, count) {
    return `<div class="ms-brand">
      <input type="text" class="form-control" data-m="${id}" data-f="bname" data-i="${i}" maxlength="100" placeholder="Brand name" value="${esc(b.name)}" aria-label="Brand name" />
      <input type="number" class="form-control${b.mrp !== "" && !validMrp(b.mrp) ? " ms-bad" : ""}" data-m="${id}" data-f="bmrp" data-i="${i}" min="0" step="0.01" inputmode="decimal" placeholder="MRP per pack (blank = same)" value="${esc(b.mrp)}" aria-label="Brand MRP per pack" />
      ${count > 1 ? `<button type="button" class="btn btn-outline btn-sm" data-action="rmbrand" data-id="${id}" data-i="${i}" aria-label="Remove brand">×</button>` : ""}
    </div>`;
  }

  function extraHtml(id, s) {
    const more = s.more ? `<div class="ms-more">
        <div class="ms-fields">
          <label>HSN code<input type="text" class="form-control${String(s.hsn || "").length > 20 ? " ms-bad" : ""}" data-m="${id}" data-f="hsn" maxlength="20" value="${esc(s.hsn)}" /></label>
          <label>NPPA ceiling price (Rs per unit)<input type="number" class="form-control${validOptNum(s.nppa, MAX_PRICE) ? "" : " ms-bad"}" data-m="${id}" data-f="nppa" min="0" step="0.01" inputmode="decimal" value="${esc(s.nppa)}" /></label>
          <label>Low-stock alert at<input type="number" class="form-control${validOptInt(s.thr, MAX_THRESHOLD) ? "" : " ms-bad"}" data-m="${id}" data-f="thr" min="0" step="1" inputmode="numeric" placeholder="25" value="${esc(s.thr)}" /></label>
        </div>
        ${s.brands.map((b, i) => brandHtml(id, b, i, s.brands.length)).join("")}
        <div class="ms-chips"><button type="button" class="ms-chip ms-chip-dashed" data-action="addbrand" data-id="${id}">+ Add another brand</button></div>
      </div>` : "";
    return `<div class="ms-extra">
      <div class="ms-fields">
        <label>MRP per pack (Rs)*<input type="number" class="form-control${s.mrp !== "" && !validMrp(s.mrp) ? " ms-bad" : ""}" data-m="${id}" data-f="mrp" min="0" step="0.01" inputmode="decimal" value="${esc(s.mrp)}" /></label>
        <label>Units per pack*<input type="number" class="form-control${s.pack !== "" && !validPack(s.pack) ? " ms-bad" : ""}" data-m="${id}" data-f="pack" min="1" step="1" inputmode="numeric" value="${esc(s.pack)}" /></label>
      </div>
      <div class="ms-chips"><button type="button" class="ms-chip${s.more ? " open" : ""}" data-action="more" data-id="${id}" aria-expanded="${s.more ? "true" : "false"}">${s.more ? "Hide optional fields" : "More (optional)"}<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="6 9 12 15 18 9"></polyline></svg></button></div>
      ${more}
    </div>`;
  }

  function rowHtml(m) {
    const id = Number(m.id);
    const done = !!m.already_added;
    const s = done ? null : state.sel.get(id);
    const meta = [`${Number(m.default_pack_size) || 1} per pack`, m.gst_percent != null ? `GST ${m.gst_percent}%` : "", m.category || ""].filter(Boolean).join(" · ");
    const right = done ? `<span class="ms-already">Already added</span>` : badge(m.schedule);
    return `<div class="ms-row ms-item${done ? " ms-done" : ""}" data-item="${id}">
      <label class="ms-check"><input type="checkbox" data-id="${id}" ${s ? "checked" : ""} ${done ? "disabled" : ""} />
        <span class="ms-name">${esc(m.display_name)}<small>${esc(meta)}</small></span></label>
      ${right}
      ${s ? extraHtml(id, s) : ""}</div>`;
  }

  function renderRow(id) {
    const m = state.items.find((x) => Number(x.id) === Number(id));
    const el = $("ms-list").querySelector(`[data-item="${Number(id)}"]`);
    if (m && el) el.outerHTML = rowHtml(m);
  }

  function renderList() {
    $("ms-list").innerHTML = state.items.length
      ? state.items.map(rowHtml).join("")
      : '<p style="color:var(--slate-light);padding:12px 0">No medicines found in the master list. If you did not type a search, the master list has not been loaded yet. Please contact support.</p>';
    updateFooter();
  }

  function renderFilters() {
    const sc = $("ms-schedule"), fm = $("ms-form");
    const cs = sc.value, cf = fm.value;
    sc.innerHTML = '<option value="">All Schedules</option>' +
      state.schedules.map((x) => `<option value="${esc(x)}">${esc(String(x).toUpperCase())}</option>`).join("");
    fm.innerHTML = '<option value="">All Forms</option>' +
      state.forms.map((x) => `<option value="${esc(x)}">${esc(x)}</option>`).join("");
    sc.value = cs;
    fm.value = cf;
  }

  async function loadList() {
    try {
      const d = await api("GET", url("/list", { search: $("ms-search").value.trim(), schedule: $("ms-schedule").value, form: $("ms-form").value }), null, false, true);
      state.items = d.items || [];
      if (!state.loaded) { state.schedules = d.schedules || []; state.forms = d.forms || []; renderFilters(); }
      state.loaded = true;
      state.items.forEach((m) => { if (m.already_added) state.sel.delete(Number(m.id)); });
      if (d.hospital && d.hospital.name) {
        $("ms-hospital").textContent = IS_SUPER ? "Hospital: " + d.hospital.name : "";
      }
      renderList();
    } catch (e) { toast(e.message, "error"); }
  }

  function updateFooter() {
    let need = 0, other = 0;
    state.sel.forEach((s) => { if (priceProblem(s)) need += 1; else if (otherProblem(s)) other += 1; });
    const n = state.sel.size;
    let t = `${n} selected, ${need} ${need === 1 ? "needs" : "need"} a price`;
    if (other) t += `, ${other} with a wrong optional value`;
    $("ms-footer-text").textContent = t;
    $("ms-add-btn").disabled = !(n > 0 && need === 0 && other === 0);
  }

  function showResult(r) {
    const warns = (r.warnings || []).map((w) => `<div class="ms-msg">${esc(w)}</div>`).join("");
    $("ms-result").innerHTML = `<div class="ms-resultbox"><strong>${esc(r.message)}</strong>
      <a href="#" data-action="undo" data-id="${esc(Number(r.import_id))}">Undo this</a>${warns}</div>`;
  }

  function refreshHospitalList() {
    if (window.MS_SUPER_MODE) return;
    if (typeof loadMedicines === "function") loadMedicines();
    else if (typeof loadStockMedicines === "function") loadStockMedicines();
  }

  async function addSelected() {
    const items = [];
    state.sel.forEach((s, id) => {
      items.push({
        master_medicine_id: Number(id),
        price_per_pack: Number(s.mrp),
        pack_size: Number(s.pack),
        hsn_code: String(s.hsn || "").trim() || null,
        nppa_ceiling_price: s.nppa === "" ? null : Number(s.nppa),
        low_stock_threshold: s.thr === "" ? null : Number(s.thr),
        brands: s.brands.filter((b) => (b.name || "").trim()).map((b) => ({
          brand_name: b.name.trim(), price_per_pack: b.mrp === "" ? null : Number(b.mrp),
        })),
      });
    });
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
      "This removes the medicines you just added from your catalog. It is refused if any of them has already been used in an order or has stock.",
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
    ok: ["badge-green", "OK"], already: ["badge-grey", "Already added"],
    not_found: ["badge-red", "Not found"], duplicate: ["badge-red", "Duplicate in file"],
    bad_price: ["badge-red", "Bad price"], price_missing: ["badge-red", "MRP missing"],
    bad_pack: ["badge-red", "Bad pack or brand"],
  };

  function previewRowHtml(r) {
    const s = STATUS[r.status] || ["badge-grey", r.status];
    const sugg = (r.suggestions || []).length
      ? `<div class="ms-sugg">Did you mean: ${r.suggestions.map((x) =>
        `<button type="button" class="btn btn-outline btn-sm" data-action="accept" data-row="${esc(Number(r.row))}" data-mid="${esc(Number(x.master_medicine_id))}">${esc(x.name)}</button>`).join(" ")}</div>`
      : "";
    const shownName = r.master_name && r.master_name !== r.name ? `${esc(r.name)} <small>(${esc(r.master_name)})</small>` : esc(r.name);
    return `<tr><td>${esc(r.row)}</td><td>${shownName}</td><td>${r.brand ? esc(r.brand) : "-"}</td>
      <td>${r.mrp != null ? "Rs." + esc(r.mrp) : "-"}</td><td>${r.pack != null ? esc(r.pack) : "-"}</td>
      <td><span class="badge ${s[0]}">${esc(s[1])}</span>${r.message ? `<div class="ms-msg">${esc(r.message)}</div>` : ""}${sugg}</td></tr>`;
  }

  function renderPreview(p) {
    $("ms-summary").innerHTML = p.summary_text ? `<div class="ms-summarybox">${esc(p.summary_text)}</div>` : "";
    $("ms-errors").innerHTML = issueList(p.errors, "Problems to fix (nothing is saved until these are fixed)", true);
    $("ms-warnings").innerHTML = issueList(p.warnings, "Notes (these do not block saving)", false);
    const rows = p.rows || [];
    if (rows.length) {
      $("ms-table").innerHTML = `<div class="table-wrap" style="max-height:46vh;overflow-y:auto"><table><thead><tr><th>Row</th><th>Medicine</th><th>Brand</th><th>MRP</th><th>Units</th><th>Status</th></tr></thead><tbody>${
        rows.slice(0, MAX_ROWS_SHOWN).map(previewRowHtml).join("")}</tbody></table></div>` +
        (rows.length > MAX_ROWS_SHOWN ? `<p class="ms-msg">Only the first ${MAX_ROWS_SHOWN} rows are shown. Every row in the file is checked.</p>` : "");
    } else {
      $("ms-table").innerHTML = "";
    }
    state.previewId = p.preview_id || null;
    if (p.errors && p.errors.length) {
      setStatus("This file has problems. Fix them in Excel and upload it again. Nothing was saved.", "error");
    } else if (p.nothing_to_add) {
      setStatus("Every medicine in this file is already added. Nothing to add.", "ok");
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
      const p = await api("POST", url(`/preview/${encodeURIComponent(state.previewId)}/accept`), { row: Number(row), master_medicine_id: Number(mid) });
      if (p) renderPreview(p);
    } catch (e) { toast(e.message, "error"); }
  }

  async function onConfirm() {
    if (!state.previewId) return;
    const ok = await confirmModal(
      "This adds the medicines in this file to the hospital's live medicine catalog with the MRP in the file (stock 0). You can undo it afterwards, but only while none of them has been used or has stock.",
      { title: "Add these medicines?", okLabel: "Confirm" });
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
      const id = Number(el.getAttribute("data-id"));
      if (a === "undo") { ev.preventDefault(); undoBatch(el.getAttribute("data-id")); }
      else if (a === "close") closePanel();
      else if (a === "add") addSelected();
      else if (a === "template") downloadFile(`${BASE}/template`, "MedScribe_Select_Medicines_Template.xlsx");
      else if (a === "choose") $("ms-file").click();
      else if (a === "confirm") onConfirm();
      else if (a === "accept") onAccept(el.getAttribute("data-row"), el.getAttribute("data-mid"));
      else if (a === "more") {
        ev.preventDefault();
        const s = state.sel.get(id);
        if (s) { s.more = !s.more; renderRow(id); updateFooter(); }
      } else if (a === "addbrand") {
        ev.preventDefault();
        const s = state.sel.get(id);
        if (s && s.brands.length < 10) { s.brands.push({ name: "", mrp: "" }); renderRow(id); updateFooter(); }
      } else if (a === "rmbrand") {
        const s = state.sel.get(id);
        const i = Number(el.getAttribute("data-i"));
        if (s && s.brands.length > 1 && i >= 0 && i < s.brands.length) { s.brands.splice(i, 1); renderRow(id); updateFooter(); }
      }
    });

    panel.addEventListener("change", (ev) => {
      const t = ev.target;
      if (t.id === "ms-schedule" || t.id === "ms-form") { loadList(); return; }
      if (t.id === "ms-file") { const f = t.files && t.files[0]; t.value = ""; onFileChosen(f); return; }
      if (t.matches("input[type=checkbox][data-id]")) {
        const id = Number(t.getAttribute("data-id"));
        const m = state.items.find((x) => Number(x.id) === id);
        if (t.checked && m) {
          state.sel.set(id, { mrp: "", pack: String(Number(m.default_pack_size) || 1), hsn: "", nppa: "", thr: "25", more: false, brands: [{ name: "", mrp: "" }] });
        } else {
          state.sel.delete(id);
        }
        renderRow(id);
        updateFooter();
        if (t.checked) {
          const box = panel.querySelector(`input[data-m="${id}"][data-f="mrp"]`);
          if (box) box.focus();
        }
      }
    });

    panel.addEventListener("input", (ev) => {
      const t = ev.target;
      if (t.id === "ms-search") { clearTimeout(state.timer); state.timer = setTimeout(loadList, 300); return; }
      if (t.hasAttribute("data-m")) {
        const id = Number(t.getAttribute("data-m"));
        const s = state.sel.get(id);
        if (!s) return;
        const f = t.getAttribute("data-f");
        const v = t.value;
        if (f === "bname" || f === "bmrp") {
          const b = s.brands[Number(t.getAttribute("data-i"))];
          if (!b) return;
          if (f === "bname") { b.name = v; t.classList.toggle("ms-bad", v.trim().length > 100); }
          else { b.mrp = v; t.classList.toggle("ms-bad", v !== "" && !validMrp(v)); }
        } else {
          s[f] = v;
          const bad = f === "mrp" ? (v !== "" && !validMrp(v))
            : f === "pack" ? (v !== "" && !validPack(v))
            : f === "nppa" ? !validOptNum(v, MAX_PRICE)
            : f === "thr" ? !validOptInt(v, MAX_THRESHOLD)
            : f === "hsn" ? v.length > 20 : false;
          t.classList.toggle("ms-bad", bad);
        }
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