/* Super Admin: "Master catalogs" page (Phase 3). Two tabs: Master tests and Master medicines.
   Talks to /superadmin/master/... (super_admin only on the server). There is no price anywhere here.
   Every value that came from the server or a spreadsheet goes through sanitize() (api.js) before innerHTML,
   and buttons use data-action with ONE delegated listener (no inline onclick built from data). */
(function () {
  const esc = (v) => sanitize(v);
  const $ = (id) => document.getElementById(id);
  const BASE = "/superadmin/master";
  const MAX_LIST = 200;
  const SCHED_LABEL = { otc: "OTC", h: "H", h1: "H1", x: "X" };
  const BILLING_LABEL = { per_pack: "Per pack", per_unit: "Per unit" };
  const FALLBACK_META = { forms: ["Tablet", "Capsule", "Syrup", "Injection", "Other"], schedules: ["otc", "h", "h1", "x"],
    billing_modes: ["per_unit", "per_pack"], gst_choices: [0, 5, 12, 18, 28] };

  const st = {
    tab: "tests", built: false, meta: null, categories: [],
    tests: { items: [], total: 0, search: "", category: "" },
    medicines: { items: [], total: 0, search: "", schedule: "" },
    byId: { tests: {}, medicines: {} },
    preview: { tests: null, medicines: null },
    edit: null, params: [], timer: null,
  };

  // ------------------------------------------------------------------ shell
  function shellHtml() {
    return `
      <div class="mc-tabs">
        <button class="chat-filter-tab active" data-action="tab" data-tab="tests" id="mc-tab-tests">Master tests</button>
        <button class="chat-filter-tab" data-action="tab" data-tab="medicines" id="mc-tab-medicines">Master medicines</button>
      </div>
      <div class="card" id="mc-pane-tests"></div>
      <div class="card" id="mc-pane-medicines" style="display:none"></div>
      <div class="modal-overlay" id="mc-modal"><div class="modal" id="mc-modal-box" style="max-width:760px;width:95%;max-height:90vh;overflow-y:auto"></div></div>
      <div class="modal-overlay" id="mc-upload-modal"><div class="modal" style="max-width:900px;width:95%;max-height:90vh;overflow-y:auto">
        <div class="modal-header"><h2 id="mc-up-title">Upload master list</h2><button class="modal-close" data-action="up-close" aria-label="Close">&times;</button></div>
        <div id="mc-up-body"></div>
      </div></div>`;
  }

  function paneHtml(kind) {
    const isT = kind === "tests";
    const filter = isT
      ? `<select class="form-control" id="mc-filter-tests" data-filter="category" style="width:auto;min-width:160px"><option value="">All categories</option></select>`
      : `<select class="form-control" id="mc-filter-medicines" data-filter="schedule" style="width:auto;min-width:140px">
           <option value="">All schedules</option><option value="otc">OTC</option><option value="h">H</option><option value="h1">H1</option><option value="x">X</option></select>`;
    return `
      <div class="mc-toolbar">
        <input class="form-control" id="mc-search-${kind}" data-search="${kind}" placeholder="${isT ? "Search master tests…" : "Search master medicines…"}" style="flex:1;min-width:180px" />
        ${filter}
        <button class="btn btn-primary btn-sm" data-action="add" data-kind="${kind}">${isT ? "Add master test" : "Add master medicine"}</button>
        <button class="btn btn-outline btn-sm" data-action="upload" data-kind="${kind}">Upload master list (Excel)</button>
      </div>
      <div id="mc-count-${kind}" class="xi-note" style="margin:8px 0"></div>
      <div class="table-wrap" id="mc-table-${kind}"><p style="color:var(--slate);padding:12px 0">Loading…</p></div>`;
  }

  function build() {
    const root = $("mc-root");
    if (!root || st.built) return;
    root.innerHTML = shellHtml();
    $("mc-pane-tests").innerHTML = paneHtml("tests");
    $("mc-pane-medicines").innerHTML = paneHtml("medicines");
    st.built = true;
  }

  function open() {
    build();
    if (!st.meta) loadMeta();
    setTab(st.tab);
  }

  async function loadMeta() {
    try { st.meta = await api("GET", `${BASE}/medicines/meta`, null, false, true); } catch (e) { st.meta = FALLBACK_META; }
  }

  function setTab(tab) {
    st.tab = tab === "medicines" ? "medicines" : "tests";
    ["tests", "medicines"].forEach((k) => {
      $(`mc-tab-${k}`).classList.toggle("active", k === st.tab);
      $(`mc-pane-${k}`).style.display = k === st.tab ? "" : "none";
    });
    load(st.tab);
  }

  // ------------------------------------------------------------------ lists
  async function load(kind) {
    const s = st[kind];
    const qs = new URLSearchParams({ limit: "1000" });
    if (s.search) qs.set("search", s.search);
    if (kind === "tests" && s.category) qs.set("category", s.category);
    if (kind === "medicines" && s.schedule) qs.set("schedule", s.schedule);
    try {
      const data = await api("GET", `${BASE}/${kind}?${qs.toString()}`, null, false, true);
      s.items = (data && data.items) || [];
      s.total = (data && data.total) || 0;
      st.byId[kind] = {};
      s.items.forEach((it) => { st.byId[kind][Number(it.id)] = it; });
      if (kind === "tests") await loadCategories();
      renderList(kind);
    } catch (e) {
      $(`mc-table-${kind}`).innerHTML = `<p style="color:var(--danger,#dc2626);padding:12px 0">${esc(e.message || "Could not load the list.")}</p>`;
    }
  }

  async function loadCategories() {
    try {
      const cats = await api("GET", `${BASE}/tests/categories`, null, false, true);
      st.categories = cats || [];
      const sel = $("mc-filter-tests");
      if (!sel) return;
      const keep = st.tests.category;
      sel.innerHTML = `<option value="">All categories</option>` + st.categories.map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join("");
      sel.value = st.categories.includes(keep) ? keep : "";
    } catch (e) { /* the filter is optional */ }
  }

  function toggleHtml(kind, it) {
    return `<label class="mc-switch" title="${it.is_active ? "Active" : "Inactive"}"><input type="checkbox" data-toggle="${kind}" data-id="${esc(Number(it.id))}" ${it.is_active ? "checked" : ""} /><span class="mc-slider"></span></label>`;
  }

  function renderList(kind) {
    const s = st[kind];
    const box = $(`mc-table-${kind}`);
    $(`mc-count-${kind}`).textContent = s.total ? `${s.total} item${s.total === 1 ? "" : "s"}` : "";
    if (!s.items.length) {
      box.innerHTML = `<p style="color:var(--slate);padding:12px 0">${s.search || s.category || s.schedule ? "Nothing matches your search." : "The master list is empty. Add an item or upload an Excel file."}</p>`;
      return;
    }
    if (kind === "tests") {
      box.innerHTML = `<table><thead><tr><th>Test name</th><th>Category</th><th>Panel?</th><th>Active</th><th></th></tr></thead><tbody>${
        s.items.map((t) => `<tr class="${t.is_active ? "" : "mc-inactive"}">
          <td>${esc(t.test_name)}</td><td>${esc(t.category || "-")}</td>
          <td>${t.is_panel ? `<span class="badge badge-navy">Panel - ${esc(Number(t.parameter_count) || 0)} parameters</span>` : `<span class="badge badge-grey">Single</span>`}</td>
          <td>${toggleHtml(kind, t)}</td>
          <td><button class="btn btn-outline btn-sm" data-action="edit" data-kind="tests" data-id="${esc(Number(t.id))}">Edit</button></td></tr>`).join("")}</tbody></table>`;
    } else {
      box.innerHTML = `<table><thead><tr><th>Medicine</th><th>Schedule</th><th>Default units per pack</th><th>GST %</th><th>Active</th><th></th></tr></thead><tbody>${
        s.items.map((m) => `<tr class="${m.is_active ? "" : "mc-inactive"}">
          <td>${esc(m.display_name)}</td><td><span class="badge badge-grey">${esc(SCHED_LABEL[m.schedule] || m.schedule)}</span></td>
          <td>${esc(m.default_pack_size)}</td><td>${esc(m.gst_percent)}%</td>
          <td>${toggleHtml(kind, m)}</td>
          <td><button class="btn btn-outline btn-sm" data-action="edit" data-kind="medicines" data-id="${esc(Number(m.id))}">Edit</button></td></tr>`).join("")}</tbody></table>`;
    }
  }

  async function setActive(kind, id, checkbox) {
    const want = checkbox.checked;
    try {
      await api("PATCH", `${BASE}/${kind}/${Number(id)}/active`, { is_active: want });
      const it = st.byId[kind][Number(id)];
      if (it) it.is_active = want;
      const tr = checkbox.closest("tr");
      if (tr) tr.classList.toggle("mc-inactive", !want);
      toast(want ? "Activated. Hospitals can now choose it." : "Deactivated. Hospitals no longer see it. Their copies are not affected.", "success");
    } catch (e) {
      checkbox.checked = !want;
      toast(e.message || "Could not change the status.", "error");
    }
  }

  // ------------------------------------------------------------------ edit forms
  function openModal_(html) {
    $("mc-modal-box").innerHTML = html;
    $("mc-modal").classList.add("open");
  }
  function closeModal_() { $("mc-modal").classList.remove("open"); st.edit = null; }

  const field = (label, inner, extra) => `<div class="form-group" style="margin-bottom:12px;${extra || ""}"><label class="form-label">${label}</label>${inner}</div>`;

  function openTestForm(id) {
    const t = id ? st.byId.tests[Number(id)] : null;
    st.edit = { kind: "tests", id: id ? Number(id) : null };
    openModal_(`<div class="modal-header"><h2>${t ? "Edit master test" : "Add master test"}</h2><button class="modal-close" data-action="m-close" aria-label="Close">&times;</button></div>
      <div id="mc-form-body"><p style="color:var(--slate)">Loading…</p></div>`);
    if (!t) { fillTestForm({ parameters: [], is_panel: false }); return; }
    api("GET", `${BASE}/tests/${Number(id)}`, null, false, true).then(fillTestForm).catch((e) => {
      $("mc-form-body").innerHTML = `<p style="color:var(--danger,#dc2626)">${esc(e.message || "Could not load this test.")}</p>`;
    });
  }

  function fillTestForm(t) {
    st.params = (t.parameters || []).map((p) => ({ name: p.name || "", unit: p.unit || "", reference_range_male: p.reference_range_male || "",
      reference_range_female: p.reference_range_female || "", purpose: p.purpose || "",
      critical_low: p.critical_low == null ? "" : p.critical_low, critical_high: p.critical_high == null ? "" : p.critical_high }));
    const v = (x) => esc(x == null ? "" : x);
    $("mc-form-body").innerHTML = `
      ${field("Test / panel name", `<input class="form-control" id="mf-name" maxlength="150" value="${v(t.test_name)}" />`)}
      ${field("Other names (comma-separated)", `<input class="form-control" id="mf-aliases" maxlength="500" placeholder="e.g. CBC, Hemogram" value="${v(t.aliases)}" />`)}
      <div class="mc-row3">
        <div class="form-group"><label class="form-label">Category</label><input class="form-control" id="mf-category" maxlength="100" value="${v(t.category)}" /></div>
        <div class="form-group"><label class="form-label">Sample tube</label><input class="form-control" id="mf-tube" maxlength="100" list="mc-tube-options" placeholder="e.g. EDTA (purple top)" value="${v(t.required_tube)}" />
          <datalist id="mc-tube-options"><option value="EDTA (purple top)"></option><option value="Fluoride (grey top)"></option><option value="Citrate (blue top)"></option><option value="Plain/Clot activator (red top)"></option><option value="Gel separator (gold/yellow top)"></option><option value="Heparin (green top)"></option><option value="Sterile container"></option></datalist></div>
        <div class="form-group"><label class="form-label">Turnaround (hours)</label><input class="form-control" id="mf-tat" type="number" min="1" max="10000" step="1" value="${v(t.turnaround_hours)}" /></div>
      </div>
      <label class="mc-check"><input type="checkbox" id="mf-fasting" ${t.fasting_required ? "checked" : ""} /> Fasting required</label>
      <label class="mc-check"><input type="checkbox" id="mf-panel" data-change="panel" ${t.is_panel ? "checked" : ""} /> This is a panel with several parameters (for example CBC, LFT, Lipid Profile)</label>
      <div id="mf-single" style="${t.is_panel ? "display:none" : ""}">
        <div class="mc-row3">
          <div class="form-group"><label class="form-label">Reference range (Male)</label><input class="form-control" id="mf-rm" maxlength="200" value="${v(t.reference_range_male)}" /></div>
          <div class="form-group"><label class="form-label">Reference range (Female)</label><input class="form-control" id="mf-rf" maxlength="200" value="${v(t.reference_range_female)}" /></div>
          <div class="form-group"><label class="form-label">Unit</label><input class="form-control" id="mf-unit" maxlength="50" placeholder="e.g. mg/dL" value="${v(t.unit)}" /></div>
        </div>
        <div class="mc-row3">
          <div class="form-group"><label class="form-label">Critical low (optional)</label><input class="form-control" id="mf-cl" type="number" step="any" value="${v(t.critical_low)}" /></div>
          <div class="form-group"><label class="form-label">Critical high (optional)</label><input class="form-control" id="mf-ch" type="number" step="any" value="${v(t.critical_high)}" /></div>
        </div>
      </div>
      <div id="mf-panelbox" style="${t.is_panel ? "" : "display:none"}">
        <div style="display:flex;justify-content:space-between;align-items:center;margin:4px 0 8px">
          <label class="form-label" style="margin:0">Parameters (printed in this order)</label>
          <button class="btn btn-outline btn-sm" data-action="p-add">+ Add parameter</button>
        </div>
        <div id="mf-params"></div>
      </div>
      ${field("Purpose (optional)", `<textarea class="form-control" id="mf-purpose" maxlength="1000" style="min-height:50px">${v(t.purpose)}</textarea>`)}
      <div class="err-msg" id="mf-err" style="margin-bottom:12px"></div>
      <div style="display:flex;gap:12px"><button class="btn btn-primary" style="flex:1" data-action="m-save">Save</button><button class="btn btn-outline" style="flex:1" data-action="m-close">Cancel</button></div>`;
    renderParams();
  }

  function renderParams() {
    const box = $("mf-params");
    if (!box) return;
    if (!st.params.length) { box.innerHTML = `<p class="xi-note">No parameters yet. Click "+ Add parameter".</p>`; return; }
    box.innerHTML = st.params.map((p, i) => `
      <div class="mc-param">
        <div class="mc-param-top">
          <span class="mc-param-n">${i + 1}</span>
          <input class="form-control" data-p="${i}" data-f="name" maxlength="150" placeholder="Parameter name" value="${esc(p.name)}" />
          <button class="btn btn-outline btn-sm" data-action="p-up" data-i="${i}" ${i === 0 ? "disabled" : ""} aria-label="Move up">&uarr;</button>
          <button class="btn btn-outline btn-sm" data-action="p-down" data-i="${i}" ${i === st.params.length - 1 ? "disabled" : ""} aria-label="Move down">&darr;</button>
          <button class="btn btn-outline btn-sm" data-action="p-del" data-i="${i}" aria-label="Remove">&times;</button>
        </div>
        <div class="mc-param-grid">
          <input class="form-control" data-p="${i}" data-f="unit" maxlength="50" placeholder="Unit" value="${esc(p.unit)}" />
          <input class="form-control" data-p="${i}" data-f="reference_range_male" maxlength="200" placeholder="Range (M)" value="${esc(p.reference_range_male)}" />
          <input class="form-control" data-p="${i}" data-f="reference_range_female" maxlength="200" placeholder="Range (F)" value="${esc(p.reference_range_female)}" />
          <input class="form-control" data-p="${i}" data-f="critical_low" type="number" step="any" placeholder="Critical low" value="${esc(p.critical_low)}" />
          <input class="form-control" data-p="${i}" data-f="critical_high" type="number" step="any" placeholder="Critical high" value="${esc(p.critical_high)}" />
        </div>
      </div>`).join("");
  }

  const num = (id) => { const x = $(id).value; return x === "" ? null : Number(x); };
  const txt = (id) => $(id).value.trim();

  async function saveTest() {
    const err = $("mf-err");
    err.textContent = "";
    const isPanel = $("mf-panel").checked;
    const name = txt("mf-name");
    if (!name) { err.textContent = "Test name is required."; return; }
    if (isPanel && !st.params.some((p) => p.name.trim())) { err.textContent = "Add at least one parameter for a panel."; return; }
    const tat = num("mf-tat");
    const payload = {
      test_name: name, aliases: txt("mf-aliases"), category: txt("mf-category"), required_tube: txt("mf-tube"),
      fasting_required: $("mf-fasting").checked, turnaround_hours: tat == null ? null : Math.round(tat), is_panel: isPanel,
      purpose: txt("mf-purpose"), unit: isPanel ? "" : txt("mf-unit"),
      reference_range_male: isPanel ? "" : txt("mf-rm"), reference_range_female: isPanel ? "" : txt("mf-rf"),
      critical_low: isPanel ? null : num("mf-cl"), critical_high: isPanel ? null : num("mf-ch"),
      parameters: isPanel ? st.params.filter((p) => p.name.trim()).map((p) => ({
        name: p.name.trim(), unit: p.unit, reference_range_male: p.reference_range_male, reference_range_female: p.reference_range_female,
        purpose: p.purpose || "", critical_low: p.critical_low === "" ? null : Number(p.critical_low),
        critical_high: p.critical_high === "" ? null : Number(p.critical_high) })) : null,
    };
    const id = st.edit && st.edit.id;
    try {
      await api(id ? "PUT" : "POST", id ? `${BASE}/tests/${id}` : `${BASE}/tests`, payload);
      toast(id ? "Master test updated. Hospital copies are not changed." : "Master test added.", "success");
      closeModal_();
      load("tests");
    } catch (e) { err.textContent = e.message || "Could not save."; }
  }

  function openMedicineForm(id) {
    const m = id ? st.byId.medicines[Number(id)] : null;
    st.edit = { kind: "medicines", id: id ? Number(id) : null };
    const meta = st.meta || FALLBACK_META;
    const v = (x) => esc(x == null ? "" : x);
    const opt = (val, label, sel) => `<option value="${esc(val)}" ${String(sel) === String(val) ? "selected" : ""}>${esc(label)}</option>`;
    const forms = (meta.forms || []).map((f) => opt(f, f, m ? m.dosage_form : "Tablet")).join("");
    const scheds = (meta.schedules || []).map((s) => opt(s, SCHED_LABEL[s] || s, m ? m.schedule : "otc")).join("");
    const modes = (meta.billing_modes || []).map((b) => opt(b, BILLING_LABEL[b] || b, m ? m.default_billing_mode : "per_unit")).join("");
    const gsts = (meta.gst_choices || []).map((g) => opt(g, `${g}%`, m ? m.gst_percent : 12)).join("");
    openModal_(`<div class="modal-header"><h2>${m ? "Edit master medicine" : "Add master medicine"}</h2><button class="modal-close" data-action="m-close" aria-label="Close">&times;</button></div>
      ${field("Generic name", `<input class="form-control" id="mf-generic" maxlength="200" placeholder="e.g. Paracetamol" value="${v(m && m.generic_name)}" />`)}
      <div class="mc-row3">
        <div class="form-group"><label class="form-label">Strength</label><input class="form-control" id="mf-strength" maxlength="50" placeholder="e.g. 500 mg" value="${v(m && m.strength)}" /></div>
        <div class="form-group"><label class="form-label">Form</label><select class="form-control" id="mf-form">${forms}</select></div>
        <div class="form-group"><label class="form-label">Schedule</label><select class="form-control" id="mf-sched">${scheds}</select></div>
      </div>
      <div class="mc-row3">
        <div class="form-group"><label class="form-label">Default units per pack</label><input class="form-control" id="mf-pack" type="number" min="1" max="10000" step="1" value="${v(m ? m.default_pack_size : 10)}" /></div>
        <div class="form-group"><label class="form-label">Default billing mode</label><select class="form-control" id="mf-mode">${modes}</select></div>
        <div class="form-group"><label class="form-label">GST %</label><select class="form-control" id="mf-gst">${gsts}</select></div>
      </div>
      <div class="mc-row3">
        <div class="form-group"><label class="form-label">HSN code (optional)</label><input class="form-control" id="mf-hsn" maxlength="20" value="${v(m && m.hsn_code)}" /></div>
        <div class="form-group" style="grid-column:span 2"><label class="form-label">Category (optional)</label><input class="form-control" id="mf-mcat" maxlength="100" value="${v(m && m.category)}" /></div>
      </div>
      <div class="err-msg" id="mf-err" style="margin-bottom:12px"></div>
      <div style="display:flex;gap:12px"><button class="btn btn-primary" style="flex:1" data-action="m-save">Save</button><button class="btn btn-outline" style="flex:1" data-action="m-close">Cancel</button></div>`);
  }

  async function saveMedicine() {
    const err = $("mf-err");
    err.textContent = "";
    if (!txt("mf-generic") || !txt("mf-strength")) { err.textContent = "Generic name and strength are required."; return; }
    const pack = num("mf-pack");
    if (pack == null || pack < 1) { err.textContent = "Units per pack must be at least 1."; return; }
    const payload = {
      generic_name: txt("mf-generic"), strength: txt("mf-strength"), dosage_form: $("mf-form").value, schedule: $("mf-sched").value,
      default_pack_size: Math.round(pack), default_billing_mode: $("mf-mode").value, gst_percent: Number($("mf-gst").value),
      hsn_code: txt("mf-hsn"), category: txt("mf-mcat"),
    };
    const id = st.edit && st.edit.id;
    try {
      await api(id ? "PUT" : "POST", id ? `${BASE}/medicines/${id}` : `${BASE}/medicines`, payload);
      toast(id ? "Master medicine updated. Hospital copies are not changed." : "Master medicine added.", "success");
      closeModal_();
      load("medicines");
    } catch (e) { err.textContent = e.message || "Could not save."; }
  }

  // ------------------------------------------------------------------ Excel master-list upload
  function issueList(items, title, openIt) {
    if (!items || !items.length) return "";
    const shown = items.slice(0, MAX_LIST).map((i) => `<li>${esc(i.text || i.message || i)}</li>`).join("");
    const more = items.length > MAX_LIST ? `<li>…and ${items.length - MAX_LIST} more</li>` : "";
    return `<details ${openIt ? "open" : ""} class="xi-issues"><summary>${esc(title)} (${items.length})</summary><ul>${shown}${more}</ul></details>`;
  }
  function actionBadge(a) {
    const cls = { create: "badge-green", update: "badge-amber", unchanged: "badge-grey", ignored: "badge-grey" }[a] || "badge-grey";
    const label = { create: "New", update: "Update", unchanged: "No change", ignored: "Ignored" }[a] || a;
    return `<span class="badge ${cls}">${esc(label)}</span>`;
  }
  function upStatus(msg, tone) {
    const color = tone === "error" ? "var(--danger,#dc2626)" : tone === "ok" ? "var(--green,#059669)" : "var(--slate)";
    $("mc-up-status").innerHTML = msg ? `<div style="padding:10px 12px;border-radius:8px;background:var(--smoke);color:${color};font-size:13px;font-weight:600">${esc(msg)}</div>` : "";
  }

  function openUpload(kind) {
    st.upKind = kind;
    st.preview[kind] = null;
    $("mc-up-title").textContent = kind === "tests" ? "Upload master test list (Excel)" : "Upload master medicine list (Excel)";
    $("mc-up-body").innerHTML = `
      <p style="color:var(--slate);font-size:13px;margin-bottom:12px">Same template and columns as the hospital import. ${kind === "tests" ? "" : "Brand, MRP, NPPA and low-stock cells are ignored: the master list has no price and no brand. "}Nothing is saved until you press Confirm. Any problem blocks the whole file.</p>
      <div style="display:flex;gap:10px;flex-wrap:wrap">
        <button class="btn btn-outline btn-sm" data-action="up-template">Download template</button>
        <button class="btn btn-primary btn-sm" data-action="up-choose">Choose Excel file (.xlsx)</button>
        <input type="file" id="mc-up-file" accept=".xlsx" style="display:none" />
      </div>
      <div id="mc-up-status" style="margin-top:12px"></div>
      <div id="mc-up-counts"></div><div id="mc-up-errors"></div><div id="mc-up-warnings"></div>
      <div id="mc-up-table" style="max-height:40vh;overflow-y:auto"></div>
      <div style="margin-top:12px"><button class="btn btn-primary" id="mc-up-confirm" data-action="up-confirm" style="display:none" disabled>Confirm &amp; Save</button></div>`;
    $("mc-upload-modal").classList.add("open");
  }

  async function onUploadFile(file) {
    const kind = st.upKind;
    st.preview[kind] = null;
    ["mc-up-counts", "mc-up-errors", "mc-up-warnings", "mc-up-table"].forEach((i) => { $(i).innerHTML = ""; });
    const cb = $("mc-up-confirm");
    cb.disabled = true; cb.style.display = "none";
    if (!file) return;
    upStatus("Checking your file…", "info");
    try {
      const fd = new FormData();
      fd.append("file", file);
      const p = await api("POST", `${BASE}/${kind}/preview`, fd, true);
      if (!p) return;
      const c = p.counts || {};
      const cells = [["New", c.to_create], ["Updated", c.to_update], ["Unchanged", c.unchanged], ["Ignored", c.ignored], ["Problems", c.errors], ["Warnings", c.warnings]];
      $("mc-up-counts").innerHTML = `<div class="xi-grid">${cells.map(([l, n]) => `<div class="xi-cell"><div class="xi-num">${esc(n || 0)}</div><div class="xi-lbl">${esc(l)}</div></div>`).join("")}</div>`;
      $("mc-up-errors").innerHTML = issueList(p.errors, "Problems to fix (nothing is saved until these are fixed)", true);
      $("mc-up-warnings").innerHTML = issueList(p.warnings, "Warnings (these do not block the upload)", false);
      const rows = p.rows || [];
      if (rows.length) {
        $("mc-up-table").innerHTML = `<h4 class="xi-h">${kind === "tests" ? "Tests" : "Medicines"}</h4><div class="table-wrap"><table><thead><tr><th>Row</th><th>Action</th><th>${kind === "tests" ? "Test" : "Medicine"}</th>${kind === "tests" ? "<th>Type</th>" : ""}<th>What changes</th></tr></thead><tbody>${
          rows.map((r) => `<tr><td>${esc(r.row)}</td><td>${actionBadge(r.action)}</td><td>${esc(r.name)}</td>${kind === "tests" ? `<td>${r.panel ? "Panel" : "Single"}</td>` : ""}<td>${esc((r.changes || []).join(", "))}</td></tr>`).join("")}</tbody></table></div>${
          p.rows_total > p.rows_shown ? `<p class="xi-note">Only the first ${esc(p.rows_shown)} rows are shown. Everything in the file is checked and saved.</p>` : ""}`;
      }
      if (!p.ok) upStatus("This file has problems. Fix them in Excel and upload it again. Nothing was saved.", "error");
      else if (p.nothing_to_change) upStatus("Everything in this file is already in the master list. Nothing to save.", "ok");
      else {
        st.preview[kind] = p.preview_id;
        upStatus(`File is OK. Review the summary, then press Confirm & Save. (Valid for ${Number(p.expires_in_minutes) || 30} minutes.)`, "ok");
        cb.style.display = ""; cb.disabled = false;
      }
    } catch (e) { upStatus(e.message || "Could not check the file.", "error"); }
  }

  async function onUploadConfirm() {
    const kind = st.upKind;
    if (!st.preview[kind]) return;
    const ok = await confirmModal(`This changes the platform-wide master ${kind === "tests" ? "test" : "medicine"} list. Hospital copies are not affected. It is recorded in the audit log under your name.`,
      { title: "Save this master list upload?", okLabel: "Confirm & Save" });
    if (!ok) return;
    try {
      await api("POST", `${BASE}/${kind}/confirm`, { preview_id: st.preview[kind] });
      toast("Master list saved.", "success");
      $("mc-upload-modal").classList.remove("open");
      st.preview[kind] = null;
      load(kind);
    } catch (e) {
      st.preview[kind] = null;
      $("mc-up-confirm").disabled = true;
      const errs = e.data && e.data.errors ? e.data.errors : null;
      if (errs) $("mc-up-errors").innerHTML = issueList(errs, "Problems", true);
      upStatus(e.message || "Upload failed. Nothing was saved.", "error");
    }
  }

  // ------------------------------------------------------------------ hospital "set up from master list"
  // Opens the hospital's own screens for THAT hospital. Only super_admin reaches here; the server re-checks the role.
  function goMasterSetup(kind, hospitalId) {
    const hid = Number(hospitalId);
    if (!hid || (kind !== "tests" && kind !== "medicines")) return;
    const page = kind === "tests" ? "tests-catalog.html" : "medicines.html";
    window.location.href = `${page}?hospital_id=${hid}&master=1`;
  }

  // ------------------------------------------------------------------ events
  function init() {
    const root = $("mc-root");
    if (!root) return;
    root.addEventListener("click", (ev) => {
      const el = ev.target.closest("[data-action]");
      if (!el) return;
      const a = el.getAttribute("data-action");
      const kind = el.getAttribute("data-kind");
      const id = el.getAttribute("data-id");
      const i = Number(el.getAttribute("data-i"));
      if (a === "tab") setTab(el.getAttribute("data-tab"));
      else if (a === "add") { if (kind === "tests") openTestForm(null); else if (kind === "medicines") openMedicineForm(null); }
      else if (a === "edit") { if (kind === "tests") openTestForm(id); else if (kind === "medicines") openMedicineForm(id); }
      else if (a === "upload") { if (kind === "tests" || kind === "medicines") openUpload(kind); }
      else if (a === "m-close") closeModal_();
      else if (a === "m-save") { if (st.edit && st.edit.kind === "tests") saveTest(); else if (st.edit) saveMedicine(); }
      else if (a === "p-add") { st.params.push({ name: "", unit: "", reference_range_male: "", reference_range_female: "", purpose: "", critical_low: "", critical_high: "" }); renderParams(); }
      else if (a === "p-del") { st.params.splice(i, 1); renderParams(); }
      else if (a === "p-up" && i > 0) { const t = st.params[i]; st.params[i] = st.params[i - 1]; st.params[i - 1] = t; renderParams(); }
      else if (a === "p-down" && i < st.params.length - 1) { const t = st.params[i]; st.params[i] = st.params[i + 1]; st.params[i + 1] = t; renderParams(); }
      else if (a === "up-close") $("mc-upload-modal").classList.remove("open");
      else if (a === "up-template") downloadFile(`${BASE}/template/${st.upKind}`, st.upKind === "tests" ? "MedScribe_Master_Tests_Template.xlsx" : "MedScribe_Master_Medicines_Template.xlsx");
      else if (a === "up-choose") $("mc-up-file").click();
      else if (a === "up-confirm") onUploadConfirm();
    });
    root.addEventListener("change", (ev) => {
      const t = ev.target;
      if (t.matches("input[data-toggle]")) { setActive(t.getAttribute("data-toggle"), t.getAttribute("data-id"), t); return; }
      if (t.matches("select[data-filter]")) {
        const kind = t.id === "mc-filter-tests" ? "tests" : "medicines";
        st[kind][t.getAttribute("data-filter")] = t.value;
        load(kind);
        return;
      }
      if (t.matches("#mf-panel")) {
        $("mf-single").style.display = t.checked ? "none" : "";
        $("mf-panelbox").style.display = t.checked ? "" : "none";
        if (t.checked && !st.params.length) { st.params.push({ name: "", unit: "", reference_range_male: "", reference_range_female: "", purpose: "", critical_low: "", critical_high: "" }); renderParams(); }
        return;
      }
      if (t.id === "mc-up-file") { const f = t.files && t.files[0]; t.value = ""; onUploadFile(f); }
    });
    root.addEventListener("input", (ev) => {
      const t = ev.target;
      if (t.matches("input[data-p]")) {
        const p = st.params[Number(t.getAttribute("data-p"))];
        if (p) p[t.getAttribute("data-f")] = t.value;
        return;
      }
      if (t.matches("input[data-search]")) {
        const kind = t.getAttribute("data-search");
        clearTimeout(st.timer);
        st.timer = setTimeout(() => { st[kind].search = t.value.trim(); load(kind); }, 300);
      }
    });
  }

  window.MasterCatalogs = { open };
  window.goMasterSetup = goMasterSetup;
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();