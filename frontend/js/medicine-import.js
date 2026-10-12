/* Excel import for the medicine catalog (Phase 3).
   Talks to /admin/medicine-import/*. Every value that came from the spreadsheet is passed through
   sanitize() (api.js) before it goes into innerHTML, and buttons use data-action + one delegated
   listener, so nothing from a cell ever lands in an inline onclick. */
(function () {
  const ROOT_ID = "modal-excel-import";
  const MAX_LIST = 200;
  let previewId = null;

  const $ = (id) => document.getElementById(id);
  const esc = (v) => sanitize(v);

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

  function resetView() {
    previewId = null;
    ["xi-status", "xi-counts", "xi-errors", "xi-warnings", "xi-meds", "xi-stock"].forEach((id) => { const el = $(id); if (el) el.innerHTML = ""; });
    $("xi-confirm").disabled = true;
    $("xi-confirm").style.display = "none";
  }

  function openModal() {
    resetView();
    $(ROOT_ID).classList.add("open");
    loadHistory();
  }

  function closeModal() {
    $(ROOT_ID).classList.remove("open");
    resetView();
  }

  function setStatus(msg, kind) {
    const color = kind === "error" ? "var(--danger,#dc2626)" : kind === "ok" ? "var(--green,#059669)" : "var(--slate)";
    $("xi-status").innerHTML = msg ? `<div style="padding:10px 12px;border-radius:8px;background:var(--smoke);color:${color};font-size:13px;font-weight:600">${esc(msg)}</div>` : "";
  }

  function issueList(items, title, open) {
    if (!items || !items.length) return "";
    const shown = items.slice(0, MAX_LIST).map((i) => `<li>${esc(i.text || i.message || i)}</li>`).join("");
    const more = items.length > MAX_LIST ? `<li>…and ${items.length - MAX_LIST} more</li>` : "";
    return `<details ${open ? "open" : ""} class="xi-issues"><summary>${esc(title)} (${items.length})</summary><ul>${shown}${more}</ul></details>`;
  }

  function renderCounts(c) {
    const cells = [
      ["New medicines", c.medicines_to_create], ["Updated", c.medicines_to_update], ["Unchanged", c.medicines_unchanged],
      ["Batches to add", c.batches_to_create], ["Batches skipped", c.batches_skipped], ["Units of stock", c.units_to_add],
    ];
    $("xi-counts").innerHTML = `<div class="xi-grid">${cells.map(([l, v]) =>
      `<div class="xi-cell"><div class="xi-num">${esc(v)}</div><div class="xi-lbl">${esc(l)}</div></div>`).join("")}</div>`;
  }

  function renderTables(p) {
    const meds = p.medicines_preview || [];
    if (meds.length) {
      $("xi-meds").innerHTML = `<h4 class="xi-h">Medicines</h4><div class="table-wrap"><table><thead><tr><th>Row</th><th>Action</th><th>Medicine</th><th>What changes</th></tr></thead><tbody>${
        meds.map((m) => `<tr><td>${esc(m.row)}</td><td>${badge(m.action)}</td><td>${esc(m.label)}</td><td>${esc((m.changes || []).join(", "))}</td></tr>`).join("")
      }</tbody></table></div>`;
    }
    const stock = p.stock_preview || [];
    if (stock.length) {
      $("xi-stock").innerHTML = `<h4 class="xi-h">Stock batches</h4><div class="table-wrap"><table><thead><tr><th>Row</th><th>Action</th><th>Batch</th><th>Units</th><th>Expiry</th></tr></thead><tbody>${
        stock.map((s) => `<tr><td>${esc(s.row)}</td><td>${badge(s.action)}</td><td>${esc(s.batch)}${s.expired ? ' <span class="badge badge-red">Expired</span>' : ""}</td><td>${esc(s.units)}</td><td>${esc(s.expiry)}</td></tr>`).join("")
      }</tbody></table></div>`;
    }
    const c = p.counts || {};
    const totalMeds = (c.medicines_to_create || 0) + (c.medicines_to_update || 0) + (c.medicines_unchanged || 0);
    if (totalMeds > meds.length || (c.batches_to_create || 0) + (c.batches_skipped || 0) > stock.length) {
      $("xi-stock").innerHTML += `<p class="xi-note">Only the first rows are shown here. Everything in the file is checked and imported.</p>`;
    }
  }

  async function onFileChosen(file) {
    resetView();
    if (!file) return;
    setStatus("Checking your file…", "info");
    try {
      const fd = new FormData();
      fd.append("file", file);
      const p = await api("POST", "/admin/medicine-import/preview", fd, true);
      if (!p) return;
      renderCounts(p.counts || {});
      $("xi-errors").innerHTML = issueList(p.errors, "Problems to fix (nothing is saved until these are fixed)", true);
      $("xi-warnings").innerHTML = issueList(p.warnings, "Warnings (these do not block the import)", false);
      renderTables(p);
      if (!p.ok) {
        setStatus("This file has problems. Fix them in Excel and upload it again. Nothing was saved.", "error");
      } else if (p.nothing_to_change) {
        setStatus("Everything in this file is already in your catalog. Nothing to import.", "ok");
      } else {
        previewId = p.preview_id;
        setStatus(`File is OK. Review the summary, then click Confirm & Save. (This preview is valid for ${Number(p.expires_in_minutes) || 30} minutes.)`, "ok");
        $("xi-confirm").style.display = "";
        $("xi-confirm").disabled = false;
      }
    } catch (e) {
      setStatus(e.message || "Could not check the file.", "error");
    }
  }

  async function onConfirm() {
    if (!previewId) return;
    const ok = await confirmModal(
      "This will add medicines and stock to your live catalog and can change prices. You can undo the most recent import later, but only if nothing from it has been sold.",
      { title: "Save this import?", okLabel: "Confirm & Save" });
    if (!ok) return;
    try {
      const r = await api("POST", "/admin/medicine-import/confirm", { preview_id: previewId });
      const s = (r && r.summary) || {};
      toast(`Import saved: ${s.medicines_to_create || 0} new, ${s.medicines_to_update || 0} updated, ${s.batches_to_create || 0} batches.`, "success");
      closeModal();
      if (typeof loadMedicines === "function") loadMedicines();
      if (typeof loadExpiringSoon === "function") loadExpiringSoon();
      if (typeof loadLowStock === "function") loadLowStock();
    } catch (e) {
      previewId = null;
      $("xi-confirm").disabled = true;
      const errs = e.data && e.data.errors ? e.data.errors : null;
      if (errs) $("xi-errors").innerHTML = issueList(errs, "Problems", true);
      setStatus(e.message || "Import failed. Nothing was saved.", "error");
    }
  }

  async function loadHistory() {
    const box = $("xi-history");
    box.innerHTML = "";
    try {
      const rows = await api("GET", "/admin/medicine-import/history", null, false, true);
      const last = (rows || []).find((r) => r.is_latest_applied);
      if (!last) return;
      const s = last.summary || {};
      box.innerHTML = `<div class="xi-last"><div><strong>Last import:</strong> ${esc(last.file_name)}<br>
        <span class="xi-note">${fmtDate(last.created_at)} by ${esc(last.created_by)} · ${esc(s.medicines_to_create || 0)} new, ${esc(s.medicines_to_update || 0)} updated, ${esc(s.batches_to_create || 0)} batches</span></div>
        <button class="btn btn-outline btn-sm" data-action="undo" data-id="${esc(Number(last.id))}">Undo last import</button></div>`;
    } catch (e) { /* history is optional; ignore */ }
  }

  async function onUndo(id) {
    const ok = await confirmModal(
      "This removes the medicines and stock from your last import and restores any prices it changed. It is refused if any of it has already been sold or edited.",
      { title: "Undo last import?", okLabel: "Undo import", danger: true });
    if (!ok) return;
    try {
      await api("POST", `/admin/medicine-import/${Number(id)}/undo`);
      toast("Import undone.", "success");
      loadHistory();
      if (typeof loadMedicines === "function") loadMedicines();
      if (typeof loadExpiringSoon === "function") loadExpiringSoon();
      if (typeof loadLowStock === "function") loadLowStock();
    } catch (e) {
      const probs = e.data && e.data.problems ? e.data.problems : [];
      await alertModal([e.message].concat(probs.map((p) => "- " + p)).join("\n"), { title: "Cannot undo" });
    }
  }

  function init() {
    const root = $(ROOT_ID);
    const openBtn = $("xi-open-btn");
    if (!root || !openBtn) return;
    openBtn.addEventListener("click", openModal);
    $("xi-file").addEventListener("change", (ev) => {
      const f = ev.target.files && ev.target.files[0];
      ev.target.value = "";
      onFileChosen(f);
    });
    root.addEventListener("click", (ev) => {
      if (ev.target === root) return closeModal();
      const el = ev.target.closest("[data-action]");
      if (!el) return;
      const a = el.getAttribute("data-action");
      if (a === "close") closeModal();
      else if (a === "template") downloadFile("/admin/medicine-import/template", "MedScribe_Medicines_Template.xlsx");
      else if (a === "choose") $("xi-file").click();
      else if (a === "confirm") onConfirm();
      else if (a === "undo") onUndo(el.getAttribute("data-id"));
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();