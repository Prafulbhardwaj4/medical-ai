/* Excel import for the lab test catalog (Phase 5).
   Talks to /admin/test-import/*. Every value that came from the spreadsheet is passed through
   sanitize() (api.js) before it goes into innerHTML, and buttons use data-action + one delegated
   listener, so nothing from a cell ever lands in an inline onclick. */
(function () {
  const ROOT_ID = "modal-test-import";
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
    const cls = { create: "badge-green", update: "badge-amber", unchanged: "badge-grey" }[action] || "badge-grey";
    const label = { create: "New", update: "Update", unchanged: "No change" }[action] || action;
    return `<span class="badge ${cls}">${esc(label)}</span>`;
  }

  function resetView() {
    previewId = null;
    ["xt-status", "xt-counts", "xt-errors", "xt-warnings", "xt-tests"].forEach((id) => { const el = $(id); if (el) el.innerHTML = ""; });
    $("xt-confirm").disabled = true;
    $("xt-confirm").style.display = "none";
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
    $("xt-status").innerHTML = msg ? `<div style="padding:10px 12px;border-radius:8px;background:var(--smoke);color:${color};font-size:13px;font-weight:600">${esc(msg)}</div>` : "";
  }

  function issueList(items, title, open) {
    if (!items || !items.length) return "";
    const shown = items.slice(0, MAX_LIST).map((i) => `<li>${esc(i.text || i.message || i)}</li>`).join("");
    const more = items.length > MAX_LIST ? `<li>…and ${items.length - MAX_LIST} more</li>` : "";
    return `<details ${open ? "open" : ""} class="xi-issues"><summary>${esc(title)} (${items.length})</summary><ul>${shown}${more}</ul></details>`;
  }

  function renderCounts(c) {
    const cells = [
      ["New tests", c.tests_to_create], ["Updated tests", c.tests_to_update], ["Unchanged", c.tests_unchanged],
      ["New parameters", c.params_to_create], ["Updated parameters", c.params_to_update], ["Deactivated parameters", c.params_to_deactivate],
    ];
    $("xt-counts").innerHTML = `<div class="xi-grid">${cells.map(([l, v]) =>
      `<div class="xi-cell"><div class="xi-num">${esc(v || 0)}</div><div class="xi-lbl">${esc(l)}</div></div>`).join("")}</div>`;
  }

  function renderTable(p) {
    const rows = p.tests_preview || [];
    if (!rows.length) return;
    $("xt-tests").innerHTML = `<h4 class="xi-h">Tests</h4><div class="table-wrap"><table><thead><tr><th>Row</th><th>Action</th><th>Test</th><th>Type</th><th>Parameters</th><th>What changes</th></tr></thead><tbody>${
      rows.map((t) => `<tr><td>${esc(t.row)}</td><td>${badge(t.action)}</td><td>${esc(t.name)}</td><td>${t.panel ? "Panel" : "Single test"}</td><td>${t.panel ? esc(t.parameters) : "-"}</td><td>${esc((t.changes || []).join(", "))}</td></tr>`).join("")
    }</tbody></table></div>`;
    const c = p.counts || {};
    const total = (c.tests_to_create || 0) + (c.tests_to_update || 0) + (c.tests_unchanged || 0);
    if (total > rows.length) {
      $("xt-tests").innerHTML += `<p class="xi-note">Only the first ${rows.length} tests are shown here. Everything in the file is checked and imported.</p>`;
    }
  }

  async function onFileChosen(file) {
    resetView();
    if (!file) return;
    setStatus("Checking your file…", "info");
    try {
      const fd = new FormData();
      fd.append("file", file);
      const p = await api("POST", "/admin/test-import/preview", fd, true);
      if (!p) return;
      renderCounts(p.counts || {});
      $("xt-errors").innerHTML = issueList(p.errors, "Problems to fix (nothing is saved until these are fixed)", true);
      $("xt-warnings").innerHTML = issueList(p.warnings, "Warnings (these do not block the import)", false);
      renderTable(p);
      if (!p.ok) {
        setStatus("This file has problems. Fix them in Excel and upload it again. Nothing was saved.", "error");
      } else if (p.nothing_to_change) {
        setStatus("Everything in this file is already in your test catalog. Nothing to import.", "ok");
      } else {
        previewId = p.preview_id;
        setStatus(`File is OK. Review the summary, then click Confirm & Save. (This preview is valid for ${Number(p.expires_in_minutes) || 30} minutes.)`, "ok");
        $("xt-confirm").style.display = "";
        $("xt-confirm").disabled = false;
      }
    } catch (e) {
      setStatus(e.message || "Could not check the file.", "error");
    }
  }

  async function onConfirm() {
    if (!previewId) return;
    const ok = await confirmModal(
      "This will add tests to your live catalog and can change prices of existing tests. You can undo the most recent import later, but only if nothing from it has been ordered or edited.",
      { title: "Save this import?", okLabel: "Confirm & Save" });
    if (!ok) return;
    try {
      const r = await api("POST", "/admin/test-import/confirm", { preview_id: previewId });
      const s = (r && r.summary) || {};
      toast(`Import saved: ${s.tests_to_create || 0} new tests, ${s.tests_to_update || 0} updated, ${s.params_to_create || 0} new parameters.`, "success");
      closeModal();
      if (typeof loadTests === "function") loadTests();
    } catch (e) {
      previewId = null;
      $("xt-confirm").disabled = true;
      const errs = e.data && e.data.errors ? e.data.errors : null;
      if (errs) $("xt-errors").innerHTML = issueList(errs, "Problems", true);
      setStatus(e.message || "Import failed. Nothing was saved.", "error");
    }
  }

  async function loadHistory() {
    const box = $("xt-history");
    box.innerHTML = "";
    try {
      const rows = await api("GET", "/admin/test-import/history", null, false, true);
      const last = (rows || []).find((r) => r.is_latest_applied);
      if (!last) return;
      const s = last.summary || {};
      box.innerHTML = `<div class="xi-last"><div><strong>Last import:</strong> ${esc(last.file_name)}<br>
        <span class="xi-note">${fmtDate(last.created_at)} by ${esc(last.created_by)} · ${esc(s.tests_to_create || 0)} new, ${esc(s.tests_to_update || 0)} updated tests, ${esc(s.params_to_create || 0)} new parameters</span></div>
        <button class="btn btn-outline btn-sm" data-action="undo" data-id="${esc(Number(last.id))}">Undo last import</button></div>`;
    } catch (e) { /* history is optional; ignore */ }
  }

  async function onUndo(id) {
    const ok = await confirmModal(
      "This removes the tests from your last import and restores any values it changed. It is refused if any of it has already been ordered or edited.",
      { title: "Undo last import?", okLabel: "Undo import", danger: true });
    if (!ok) return;
    try {
      await api("POST", `/admin/test-import/${Number(id)}/undo`);
      toast("Import undone.", "success");
      loadHistory();
      if (typeof loadTests === "function") loadTests();
    } catch (e) {
      const probs = e.data && e.data.problems ? e.data.problems : [];
      await alertModal([e.message].concat(probs.map((p) => "- " + p)).join("\n"), { title: "Cannot undo" });
    }
  }

  function init() {
    const root = $(ROOT_ID);
    const openBtn = $("xt-open-btn");
    if (!root || !openBtn) return;
    openBtn.addEventListener("click", openModal);
    $("xt-file").addEventListener("change", (ev) => {
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
      else if (a === "template") downloadFile("/admin/test-import/template", "MedScribe_Tests_Template.xlsx");
      else if (a === "choose") $("xt-file").click();
      else if (a === "confirm") onConfirm();
      else if (a === "undo") onUndo(el.getAttribute("data-id"));
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();