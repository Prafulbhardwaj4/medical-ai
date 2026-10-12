/* Super Admin: import medicines / lab tests FOR the hospital whose detail card is open (Phase 6).
   Talks to /superadmin/import/{hospital_id}/{kind}/... (super_admin only on the server).
   Every value that came from a spreadsheet goes through sanitize() (api.js) before innerHTML, and
   buttons use data-action / data-kind with one delegated listener (no inline onclick). */
(function () {
  const KINDS = {
    medicines: { title: "Medicines and stock", file: "MedScribe_Medicines_Template.xlsx" },
    tests: { title: "Lab tests", file: "MedScribe_Tests_Template.xlsx" },
  };
  const MAX_LIST = 200;
  const previews = { medicines: null, tests: null };

  const $ = (id) => document.getElementById(id);
  const esc = (v) => sanitize(v);
  const hid = () => (typeof currentDetailHospitalId !== "undefined" && currentDetailHospitalId) ? Number(currentDetailHospitalId) : null;
  const base = (kind) => `/superadmin/import/${Number(hid())}/${kind}`;
  const validKind = (k) => Object.prototype.hasOwnProperty.call(KINDS, k) ? k : null;

  function fmtDate(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    return isNaN(d) ? esc(iso) : esc(d.toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }));
  }
  function badge(action) {
    const cls = { create: "badge-green", update: "badge-amber", unchanged: "badge-grey", skip: "badge-grey" }[action] || "badge-grey";
    const label = { create: "New", update: "Update", unchanged: "No change", skip: "Skipped" }[action] || action;
    return `<span class="badge ${cls}">${esc(label)}</span>`;
  }
  function issueList(items, title, open) {
    if (!items || !items.length) return "";
    const shown = items.slice(0, MAX_LIST).map((i) => `<li>${esc(i.text || i.message || i)}</li>`).join("");
    const more = items.length > MAX_LIST ? `<li>…and ${items.length - MAX_LIST} more</li>` : "";
    return `<details ${open ? "open" : ""} class="xi-issues"><summary>${esc(title)} (${items.length})</summary><ul>${shown}${more}</ul></details>`;
  }
  function setStatus(kind, msg, tone) {
    const color = tone === "error" ? "var(--danger,#dc2626)" : tone === "ok" ? "var(--green,#059669)" : "var(--slate)";
    $(`si-${kind}-status`).innerHTML = msg ? `<div style="padding:10px 12px;border-radius:8px;background:var(--smoke);color:${color};font-size:13px;font-weight:600">${esc(msg)}</div>` : "";
  }
  function resetKind(kind) {
    previews[kind] = null;
    ["status", "counts", "errors", "warnings", "tables"].forEach((p) => { const el = $(`si-${kind}-${p}`); if (el) el.innerHTML = ""; });
    const c = $(`si-${kind}-confirm`);
    c.disabled = true;
    c.style.display = "none";
  }

  function sectionHtml(kind) {
    const k = KINDS[kind];
    return `<div class="card" style="margin-bottom:20px">
      <div class="card-header"><h2>${esc(k.title)}</h2></div>
      <div style="display:flex;gap:10px;flex-wrap:wrap">
        <button class="btn btn-outline btn-sm" data-action="template" data-kind="${kind}">Download template</button>
        <button class="btn btn-primary btn-sm" data-action="choose" data-kind="${kind}">Choose Excel file (.xlsx)</button>
        <input type="file" id="si-${kind}-file" data-kind="${kind}" accept=".xlsx" style="display:none" />
      </div>
      <div id="si-${kind}-status" style="margin-top:12px"></div>
      <div id="si-${kind}-counts"></div>
      <div id="si-${kind}-errors"></div>
      <div id="si-${kind}-warnings"></div>
      <div id="si-${kind}-tables" style="max-height:40vh;overflow-y:auto"></div>
      <div style="margin-top:12px"><button class="btn btn-primary" id="si-${kind}-confirm" data-action="confirm" data-kind="${kind}" style="display:none" disabled>Confirm &amp; Save</button></div>
      <div id="si-${kind}-history"></div>
    </div>`;
  }

  function renderPane() {
    const root = $("si-root");
    if (!root) return;
    const nameEl = $("detail-name");
    $("si-hospital").textContent = nameEl ? nameEl.textContent : "";
    root.innerHTML = sectionHtml("medicines") + sectionHtml("tests");
    Object.keys(KINDS).forEach((k) => { previews[k] = null; loadHistory(k); });
  }

  function renderCounts(kind, c) {
    const cells = kind === "medicines"
      ? [["New medicines", c.medicines_to_create], ["Updated", c.medicines_to_update], ["Unchanged", c.medicines_unchanged],
         ["Batches to add", c.batches_to_create], ["Batches skipped", c.batches_skipped], ["Units of stock", c.units_to_add]]
      : [["New tests", c.tests_to_create], ["Updated tests", c.tests_to_update], ["Unchanged", c.tests_unchanged],
         ["New parameters", c.params_to_create], ["Updated parameters", c.params_to_update], ["Deactivated parameters", c.params_to_deactivate]];
    $(`si-${kind}-counts`).innerHTML = `<div class="xi-grid">${cells.map(([l, v]) =>
      `<div class="xi-cell"><div class="xi-num">${esc(v || 0)}</div><div class="xi-lbl">${esc(l)}</div></div>`).join("")}</div>`;
  }

  function renderTables(kind, p) {
    let html = "";
    if (kind === "medicines") {
      const meds = p.medicines_preview || [];
      if (meds.length) html += `<h4 class="xi-h">Medicines</h4><div class="table-wrap"><table><thead><tr><th>Row</th><th>Action</th><th>Medicine</th><th>What changes</th></tr></thead><tbody>${
        meds.map((m) => `<tr><td>${esc(m.row)}</td><td>${badge(m.action)}</td><td>${esc(m.label)}</td><td>${esc((m.changes || []).join(", "))}</td></tr>`).join("")}</tbody></table></div>`;
      const st = p.stock_preview || [];
      if (st.length) html += `<h4 class="xi-h">Stock batches</h4><div class="table-wrap"><table><thead><tr><th>Row</th><th>Action</th><th>Batch</th><th>Units</th><th>Expiry</th></tr></thead><tbody>${
        st.map((s) => `<tr><td>${esc(s.row)}</td><td>${badge(s.action)}</td><td>${esc(s.batch)}${s.expired ? ' <span class="badge badge-red">Expired</span>' : ""}</td><td>${esc(s.units)}</td><td>${esc(s.expiry)}</td></tr>`).join("")}</tbody></table></div>`;
    } else {
      const rows = p.tests_preview || [];
      if (rows.length) html += `<h4 class="xi-h">Tests</h4><div class="table-wrap"><table><thead><tr><th>Row</th><th>Action</th><th>Test</th><th>Type</th><th>Parameters</th><th>What changes</th></tr></thead><tbody>${
        rows.map((t) => `<tr><td>${esc(t.row)}</td><td>${badge(t.action)}</td><td>${esc(t.name)}</td><td>${t.panel ? "Panel" : "Single test"}</td><td>${t.panel ? esc(t.parameters) : "-"}</td><td>${esc((t.changes || []).join(", "))}</td></tr>`).join("")}</tbody></table></div>`;
    }
    if (html) html += `<p class="xi-note">Only the first rows are shown. Everything in the file is checked and imported.</p>`;
    $(`si-${kind}-tables`).innerHTML = html;
  }

  async function onFile(kind, file) {
    resetKind(kind);
    if (!file || !hid()) return;
    setStatus(kind, "Checking your file…", "info");
    try {
      const fd = new FormData();
      fd.append("file", file);
      const p = await api("POST", `${base(kind)}/preview`, fd, true);
      if (!p) return;
      renderCounts(kind, p.counts || {});
      $(`si-${kind}-errors`).innerHTML = issueList(p.errors, "Problems to fix (nothing is saved until these are fixed)", true);
      $(`si-${kind}-warnings`).innerHTML = issueList(p.warnings, "Warnings (these do not block the import)", false);
      renderTables(kind, p);
      if (!p.ok) setStatus(kind, "This file has problems. Fix them in Excel and upload it again. Nothing was saved.", "error");
      else if (p.nothing_to_change) setStatus(kind, "Everything in this file is already in the hospital's catalog. Nothing to import.", "ok");
      else {
        previews[kind] = p.preview_id;
        setStatus(kind, `File is OK. Review the summary, then click Confirm & Save. (Valid for ${Number(p.expires_in_minutes) || 30} minutes.)`, "ok");
        $(`si-${kind}-confirm`).style.display = "";
        $(`si-${kind}-confirm`).disabled = false;
      }
    } catch (e) {
      setStatus(kind, e.message || "Could not check the file.", "error");
    }
  }

  async function onConfirm(kind) {
    if (!previews[kind] || !hid()) return;
    const hospital = $("si-hospital").textContent || "this hospital";
    const ok = await confirmModal(
      `You are about to change the live ${kind === "medicines" ? "medicines and stock" : "lab test catalog"} of "${hospital}". This is recorded in the audit log under your name.`,
      { title: "Save this import for the hospital?", okLabel: "Confirm & Save" });
    if (!ok) return;
    try {
      await api("POST", `${base(kind)}/confirm`, { preview_id: previews[kind] });
      toast("Import saved for the hospital.", "success");
      resetKind(kind);
      loadHistory(kind);
    } catch (e) {
      previews[kind] = null;
      $(`si-${kind}-confirm`).disabled = true;
      const errs = e.data && e.data.errors ? e.data.errors : null;
      if (errs) $(`si-${kind}-errors`).innerHTML = issueList(errs, "Problems", true);
      setStatus(kind, e.message || "Import failed. Nothing was saved.", "error");
    }
  }

  async function loadHistory(kind) {
    const box = $(`si-${kind}-history`);
    if (!box) return;
    box.innerHTML = "";
    if (!hid()) return;
    try {
      const rows = await api("GET", `${base(kind)}/history`, null, false, true);
      const last = (rows || []).find((r) => r.is_latest_applied);
      if (!last) return;
      box.innerHTML = `<div class="xi-last"><div><strong>Last import:</strong> ${esc(last.file_name)}<br>
        <span class="xi-note">${fmtDate(last.created_at)} by ${esc(last.created_by)} (${esc(last.created_by_role)})</span></div>
        <button class="btn btn-outline btn-sm" data-action="undo" data-kind="${kind}" data-id="${esc(Number(last.id))}">Undo last import</button></div>`;
    } catch (e) { /* history is optional */ }
  }

  async function onUndo(kind, id) {
    const ok = await confirmModal(
      "This removes what the last import added and restores values it changed. It is refused if any of it has already been used or edited.",
      { title: "Undo last import?", okLabel: "Undo import", danger: true });
    if (!ok) return;
    try {
      await api("POST", `${base(kind)}/${Number(id)}/undo`);
      toast("Import undone.", "success");
      loadHistory(kind);
    } catch (e) {
      const probs = e.data && e.data.problems ? e.data.problems : [];
      await alertModal([e.message].concat(probs.map((p) => "- " + p)).join("\n"), { title: "Cannot undo" });
    }
  }

  function init() {
    const tab = $("dsn-import");
    const root = $("si-root");
    if (!tab || !root) return;
    tab.addEventListener("click", renderPane);
    root.addEventListener("change", (ev) => {
      const input = ev.target.closest("input[type=file][data-kind]");
      if (!input) return;
      const kind = validKind(input.getAttribute("data-kind"));
      const f = input.files && input.files[0];
      input.value = "";
      if (kind) onFile(kind, f);
    });
    root.addEventListener("click", (ev) => {
      const el = ev.target.closest("[data-action]");
      if (!el) return;
      const kind = validKind(el.getAttribute("data-kind"));
      if (!kind) return;
      const a = el.getAttribute("data-action");
      if (a === "template") downloadFile(`/superadmin/import/template/${kind}`, KINDS[kind].file);
      else if (a === "choose") $(`si-${kind}-file`).click();
      else if (a === "confirm") onConfirm(kind);
      else if (a === "undo") onUndo(kind, el.getAttribute("data-id"));
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();