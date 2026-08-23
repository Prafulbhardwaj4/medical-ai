const BASE = window.MEDSCRIBE_API_BASE || "https://medical-ai-mvv1.onrender.com";

function setRealVhUnit() {
  document.documentElement.style.setProperty('--real-vh', (window.innerHeight * 0.01) + 'px');
}
setRealVhUnit();
window.addEventListener('resize', setRealVhUnit);
window.addEventListener('orientationchange', setRealVhUnit);

function getToken() {
  try { return localStorage.getItem("ms_token"); }
  catch { return null; }
}

function getDoctor() {
  try { return JSON.parse(localStorage.getItem("ms_doctor")); }
  catch { return null; }
}

function saveSession(token, doctor) {
  try {
    localStorage.setItem("ms_token", token);
    localStorage.setItem("ms_doctor", JSON.stringify(doctor));
  } catch (e) {
    toast("Storage blocked. Please enable cookies in browser settings.", "error");
  }
}

function clearSession() {
  try {
    localStorage.removeItem("ms_token");
    localStorage.removeItem("ms_doctor");
  } catch (e) { }
}

function requireAuth() {
  try {
    if (!localStorage.getItem("ms_token")) {
      window.location.href = "/pages/login.html";
      return false;
    }
    return true;
  } catch (e) {
    window.location.href = "/pages/login.html";
    return false;
  }
}

function _showGlobalLoading() {
  let bar = document.getElementById("global-loading-bar");
  if (!bar) {
    bar = document.createElement("div");
    bar.id = "global-loading-bar";
    document.body.appendChild(bar);
  }
  bar.classList.remove("done");
  void bar.offsetWidth;
  bar.classList.add("active");
}

function _hideGlobalLoading() {
  const bar = document.getElementById("global-loading-bar");
  if (!bar) return;
  bar.classList.add("done");
  setTimeout(() => bar.classList.remove("active", "done"), 250);
}

let _activeRequests = 0;
let _visibleRequests = 0;

async function api(method, path, body = null, isFormData = false, silent = false) {
  const headers = { Authorization: `Bearer ${getToken()}` };
  if (!isFormData) headers["Content-Type"] = "application/json";

  const opts = { method, headers };
  if (body) opts.body = isFormData ? body : JSON.stringify(body);

  const triggerBtn = !silent && document.activeElement && document.activeElement.tagName === "BUTTON" ? document.activeElement : null;
  const alreadyDisabled = triggerBtn ? triggerBtn.disabled : true;
  if (triggerBtn && !alreadyDisabled) triggerBtn.disabled = true;

  _activeRequests++;
  if (triggerBtn) {
    _visibleRequests++;
    _showGlobalLoading();
  }

  try {
    let res;
    try {
      res = await fetch(BASE + path, opts);
    } catch (networkErr) {
      console.error("Network-level request failure:", networkErr);
      throw new Error(`Backend request failed (${networkErr.message || 'network error'}). Please try again once; if it repeats, contact admin.`);
    }

    if (res.status === 401) {
      clearSession();
      window.location.href = "/pages/login.html";
      return;
    }

    const text = await res.text();
    let data = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = { detail: text || "Server returned a non-JSON response" };
    }

    if (!res.ok) {
      const detail = data?.detail;
      const err = new Error(
        typeof detail === "string"
          ? detail
          : (detail?.message || `Request failed (${res.status})`)
      );
      err.status = res.status;
      err.data = detail;
      throw err;
    }

    return data;
  } finally {
    _activeRequests = Math.max(0, _activeRequests - 1);
    if (triggerBtn) {
      _visibleRequests = Math.max(0, _visibleRequests - 1);
      if (_visibleRequests === 0) _hideGlobalLoading();
    }
    if (triggerBtn && !alreadyDisabled) triggerBtn.disabled = false;
  }
}

// Global error boundary — catches uncaught JS errors and unhandled promise
// rejections that would otherwise leave the page silently blank (the root
// cause of the earlier dashboard.html incident). Shows a persistent,
// visible fallback instead of nothing. Included on every page via api.js,
// so this is a single change point rather than 24 separate ones.
let _errorBoundaryShown = false;
function _showErrorBoundary() {
  if (_errorBoundaryShown) return;
  _errorBoundaryShown = true;
  const el = document.createElement("div");
  el.id = "error-boundary";
  el.innerHTML = `<span>Something went wrong loading this page.</span><button onclick="location.reload()">Refresh</button>`;
  document.body.appendChild(el);
}
window.onerror = function () { _showErrorBoundary(); };
window.addEventListener("unhandledrejection", _showErrorBoundary);

// Toast notification
function toast(msg, type = "info") {
  let el = document.getElementById("toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "toast";
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.className = `show ${type}`;
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove("show"), 3500);
}

function openModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add("open");
}

function closeModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove("open");
}

// Fill topbar doctor info
function fillTopbar() {
  const doc = getDoctor();
  if (!doc) return;
  const displayTitle = doc.role === "super_admin" ? "Mr." : doc.title;
  const fullName = displayTitle ? `${displayTitle} ${doc.name}` : doc.name;
  const el = document.getElementById("topbar-doctor-name");
  if (el) el.textContent = fullName;
  const cl = document.getElementById("topbar-clinic");
  if (cl) cl.textContent = doc.clinic_name || "";
  const sb = document.getElementById("sidebar-doctor-name");
  if (sb) sb.textContent = fullName;
  const pmName = document.getElementById("profile-menu-name");
  if (pmName) pmName.textContent = fullName;
  const pmClinic = document.getElementById("profile-menu-clinic");
  if (pmClinic) pmClinic.textContent = doc.clinic_name || "";
}

// Mobile profile dropdown (header)
function toggleProfileMenu() {
  const menu = document.getElementById("profile-menu");
  const backdrop = document.getElementById("profile-menu-backdrop");
  if (!menu) return;
  const opening = !menu.classList.contains("open");
  menu.classList.toggle("open", opening);
  if (backdrop) backdrop.style.display = opening ? "block" : "none";
}

function closeProfileMenu() {
  document.getElementById("profile-menu")?.classList.remove("open");
  const backdrop = document.getElementById("profile-menu-backdrop");
  if (backdrop) backdrop.style.display = "none";
}

// Mobile full-screen "More" menu
function openMobileMenu() {
  document.getElementById("mobile-menu-sheet")?.classList.add("open");
}

function closeMobileMenu() {
  document.getElementById("mobile-menu-sheet")?.classList.remove("open");
}
// Mobile sidebar drawer
function toggleSidebar() {
  document.querySelector(".sidebar")?.classList.toggle("open");
  document.getElementById("sidebar-backdrop")?.classList.toggle("open");
}

// Auto-lock body scroll whenever any overlay (modal, notif panel, sidebar
// drawer, mobile menu sheet, profile dropdown) is visibly open — prevents
// the page underneath from scrolling while an overlay sits on top of it.
function isAnyOverlayOpen() {
  if (document.querySelector(".modal-overlay.open")) return true;
  if (document.querySelector(".notif-panel.open")) return true;
  if (document.querySelector(".sidebar.open")) return true;
  if (document.querySelector(".mobile-menu-sheet.open")) return true;
  if (document.querySelector(".profile-menu.open")) return true;
  const legacyModal = document.getElementById("modal-overlay");
  if (legacyModal && getComputedStyle(legacyModal).display !== "none") return true;
  return false;
}

function syncBodyScrollLock() {
  document.body.style.overflow = isAnyOverlayOpen() ? "hidden" : "";
}

document.addEventListener("DOMContentLoaded", function () {
  const watched = document.querySelectorAll(
    ".modal-overlay, #modal-overlay, .notif-panel, .sidebar, .mobile-menu-sheet, .profile-menu"
  );
  if (!watched.length) return;
  const observer = new MutationObserver(syncBodyScrollLock);
  watched.forEach(el => observer.observe(el, { attributes: true, attributeFilter: ["class", "style"] }));
});
function closeSidebar() {
  document.querySelector(".sidebar")?.classList.remove("open");
  document.getElementById("sidebar-backdrop")?.classList.remove("open");
}
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".sidebar .nav-item").forEach(item => {
    item.addEventListener("click", closeSidebar);
  });
});


async function logout() {
  clearSession();
  window.location.href = "/pages/login.html";
  try {
    await fetch(`${BASE}/auth/logout`, {
      method: "POST",
      headers: { "Content-Type": "application/json" }
    });
  } catch (e) { }
}

function sanitize(str) {
  const d = document.createElement("div");
  d.textContent = str;
  return d.innerHTML;
}

function validatePatient(name, phone, age) {
  if (!name || name.trim().length < 2) return "Name must be at least 2 characters.";
  if (!phone || !/^\+\d{10,15}$/.test(phone.trim())) return "Phone must include country code e.g. +919876543210";
  if (!age || age < 0 || age > 120) return "Age must be between 0 and 120.";
  return null;
}

function validateLogin(email, password) {
  if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return "Enter a valid email address.";
  if (!password) return "Please enter your password.";
  return null;
}

function redirectByRole(role) {
  if (role === 'doctor') {
    window.location.href = '/pages/dashboard.html';
  } else if (role === 'admin') {
    window.location.href = '/pages/analytics.html';
  } else if (role === 'sub_admin') {
    window.location.href = '/pages/dashboard.html';
  } else if (role === 'super_admin') {
    window.location.href = '/pages/superadmin.html';
  } else if (role === 'receptionist') {
    window.location.href = '/pages/receptionist.html';
  } else if (role === 'nurse') {
    window.location.href = '/pages/nurse.html';
  } else if (role === 'assistant') {
    window.location.href = '/pages/assistant.html';
  } else if (role === 'lab') {
    window.location.href = '/pages/lab.html';
  } else if (role === 'pharmacy') {
    window.location.href = '/pages/pharmacy.html';
  } else if (role === 'patient') {
    window.location.href = '/pages/my-health.html';
  } else {
    window.location.href = '/pages/dashboard.html';
  }
}

// Authenticated binary download (PDFs) — api() only handles JSON, so
// downloads need their own fetch with the Authorization header attached.
async function downloadFile(path, filename) {
  try {
    const res = await fetch(BASE + path, { headers: { Authorization: `Bearer ${getToken()}` } });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Download failed");
    }
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
  } catch (e) {
    toast(e.message, "error");
  }
}

// Shared "Edit My Details" modal — every role, name + contact/credential number only.
function ensureEditDetailsModal() {
  if (document.getElementById('modal-edit-details')) return;
  const wrap = document.createElement('div');
  wrap.innerHTML = `
    <div class="modal-overlay" id="modal-edit-details">
      <div class="modal" style="max-width:420px">
        <div class="modal-header">
          <h2>Settings</h2>
          <button class="modal-close" onclick="closeEditDetailsModal()">&times;</button>
        </div>
        <div style="font-size:13px;font-weight:600;color:var(--slate);margin-bottom:12px;text-transform:uppercase;letter-spacing:0.3px">Edit My Details</div>
        <div style="margin-bottom:12px">
          <label style="display:block;margin-bottom:6px;font-size:13px;color:var(--slate)">Name</label>
          <div style="display:flex;gap:10px">
            <select class="form-control" id="ed-title" style="width:100px;display:none">
              <option>Mr.</option>
              <option>Ms.</option>
            </select>
            <span id="ed-title-fixed" style="display:none;align-items:center;padding:0 12px;border:1.5px solid var(--border);border-radius:var(--radius);color:var(--slate);font-size:0.9rem;background:var(--smoke)">Dr.</span>
            <input class="form-control" id="ed-name" style="flex:1" />
          </div>
        </div>
        <div style="margin-bottom:12px">
          <label style="display:block;margin-bottom:6px;font-size:13px;color:var(--slate)">Contact Number</label>
          <input class="form-control" id="ed-phone" />
        </div>
        <div style="margin-bottom:16px">
          <label style="display:block;margin-bottom:6px;font-size:13px;color:var(--slate)">Registration / Credential No. <span style="color:var(--slate-light);font-weight:400">(optional)</span></label>
          <input class="form-control" id="ed-reg" />
        </div>
        <div class="err-msg" id="ed-err" style="margin-bottom:10px"></div>
        <div style="display:flex;gap:10px">
          <button class="btn btn-outline" style="flex:1" onclick="closeEditDetailsModal()">Cancel</button>
          <button class="btn btn-primary" style="flex:1" onclick="submitEditDetails()">Save</button>
        </div>
      </div>
    </div>`;
  document.body.appendChild(wrap.firstElementChild);
}

function openEditDetailsModal() {
  closeProfileMenu();
  ensureEditDetailsModal();
  const doc = getDoctor() || {};
  document.getElementById('ed-name').value = doc.name || '';
  document.getElementById('ed-phone').value = doc.phone || '';
  document.getElementById('ed-reg').value = doc.registration_number || '';
  document.getElementById('ed-err').textContent = '';
  const isDoctorRole = doc.role === 'doctor';
  document.getElementById('ed-title').style.display = isDoctorRole ? 'none' : '';
  document.getElementById('ed-title-fixed').style.display = isDoctorRole ? 'flex' : 'none';
  if (!isDoctorRole) document.getElementById('ed-title').value = (doc.title === 'Ms.') ? 'Ms.' : 'Mr.';
  document.getElementById('modal-edit-details').classList.add('open');
}

function closeEditDetailsModal() {
  document.getElementById('modal-edit-details')?.classList.remove('open');
}

function ensureChangePasswordModal() {
  if (document.getElementById('modal-change-password')) return;
  const wrap = document.createElement('div');
  wrap.innerHTML = `
    <div class="modal-overlay" id="modal-change-password">
      <div class="modal" style="max-width:400px">
        <div class="modal-header">
          <h2>Change Password</h2>
          <button class="modal-close" onclick="closeChangePasswordModal()">&times;</button>
        </div>
        <div style="margin-bottom:12px">
          <label style="display:block;margin-bottom:6px;font-size:13px;color:var(--slate)">Current Password</label>
          <input class="form-control" id="cp-old" type="password" />
        </div>
        <div style="margin-bottom:12px">
          <label style="display:block;margin-bottom:6px;font-size:13px;color:var(--slate)">New Password</label>
          <input class="form-control" id="cp-new" type="password" placeholder="At least 6 characters" />
        </div>
        <div style="margin-bottom:16px">
          <label style="display:block;margin-bottom:6px;font-size:13px;color:var(--slate)">Confirm New Password</label>
          <input class="form-control" id="cp-confirm" type="password" />
        </div>
        <div class="err-msg" id="cp-err" style="margin-bottom:10px"></div>
        <div style="display:flex;gap:10px">
          <button class="btn btn-outline" style="flex:1" onclick="closeChangePasswordModal()">Cancel</button>
          <button class="btn btn-primary" style="flex:1" id="cp-submit-btn" onclick="submitChangePassword()">Save</button>
        </div>
      </div>
    </div>`;
  document.body.appendChild(wrap.firstElementChild);
}

function openChangePasswordModal() {
  closeProfileMenu();
  ensureChangePasswordModal();
  document.getElementById('cp-old').value = '';
  document.getElementById('cp-new').value = '';
  document.getElementById('cp-confirm').value = '';
  document.getElementById('cp-err').textContent = '';
  document.getElementById('modal-change-password').classList.add('open');
}

function closeChangePasswordModal() {
  document.getElementById('modal-change-password')?.classList.remove('open');
}

async function submitChangePassword() {
  const errEl = document.getElementById('cp-err');
  const oldPw = document.getElementById('cp-old').value;
  const newPw = document.getElementById('cp-new').value;
  const confirmPw = document.getElementById('cp-confirm').value;

  if (!oldPw) { errEl.textContent = 'Enter your current password.'; return; }
  if (newPw.length < 6) { errEl.textContent = 'New password must be at least 6 characters.'; return; }
  if (newPw !== confirmPw) { errEl.textContent = 'New passwords do not match.'; return; }

  const btn = document.getElementById('cp-submit-btn');
  btn.disabled = true;
  try {
    await api("POST", "/portal/auth/change-password", { old_password: oldPw, new_password: newPw });
    toast("Password changed successfully", "success");
    closeChangePasswordModal();
  } catch (e) {
    errEl.textContent = e.message;
  } finally {
    btn.disabled = false;
  }
}

async function submitEditDetails() {
  const errEl = document.getElementById('ed-err');
  const name = document.getElementById('ed-name').value.trim();
  const phone = document.getElementById('ed-phone').value.trim();
  const registration_number = document.getElementById('ed-reg').value.trim();
  if (!name) { errEl.textContent = 'Name is required.'; return; }
  if (!phone) { errEl.textContent = 'Contact number is required.'; return; }
  const isDoctorRole = getDoctor()?.role === 'doctor';
  const title = isDoctorRole ? 'Dr.' : document.getElementById('ed-title').value;
  try {
    const updated = await api("PATCH", "/auth/me", { name, phone, registration_number, title });
    saveSession(getToken(), { ...getDoctor(), ...updated });
    fillTopbar();
    closeEditDetailsModal();
    toast('Details updated.', 'success');
  } catch (e) { errEl.textContent = e.message; }
}

function confirmDialog(message, confirmLabel = "Confirm") {
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.className = "modal-overlay open";
    overlay.innerHTML = `
      <div class="modal" style="max-width:380px">
        <div class="modal-header"><h2>Please Confirm</h2></div>
        <p style="font-size:13px;color:var(--navy);margin-bottom:18px">${message}</p>
        <div style="display:flex;gap:10px">
          <button class="btn btn-outline" style="flex:1" id="cf-cancel">Cancel</button>
          <button class="btn btn-primary" style="flex:1" id="cf-confirm">${confirmLabel}</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    const cleanup = (val) => { overlay.remove(); resolve(val); };
    overlay.querySelector("#cf-cancel").addEventListener("click", () => cleanup(false));
    overlay.querySelector("#cf-confirm").addEventListener("click", () => cleanup(true));
  });
}

function promptOffDutyTime() {
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.className = "modal-overlay open";
    overlay.innerHTML = `
      <div class="modal" style="max-width:360px">
        <div class="modal-header"><h2>Expected Off-Duty Time</h2></div>
        <p style="font-size:13px;color:var(--slate);margin-bottom:14px">
          What time do you expect to go off duty today? If you forget to mark yourself off duty, you'll be marked off duty automatically at this time.
        </p>
        <input type="time" class="form-control" id="od-time-input" style="margin-bottom:8px;font-size:16px" />
        <div class="err-msg" id="od-time-err"></div>
        <div style="display:flex;gap:10px;margin-top:10px">
          <button class="btn btn-outline" style="flex:1" id="od-time-skip">Skip</button>
          <button class="btn btn-primary" style="flex:1" id="od-time-confirm">Confirm</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    const cleanup = (value) => { overlay.remove(); resolve(value); };
    overlay.querySelector("#od-time-skip").addEventListener("click", () => cleanup(null));
    overlay.querySelector("#od-time-confirm").addEventListener("click", () => {
      const val = overlay.querySelector("#od-time-input").value;
      if (!val) {
        overlay.querySelector("#od-time-err").textContent = "Pick a time, or tap Skip.";
        return;
      }
      const [h, m] = val.split(":").map(Number);
      const d = new Date();
      d.setHours(h, m, 0, 0);
      if (d < new Date()) d.setDate(d.getDate() + 1);
      cleanup(d.toISOString());
    });
  });
}

function _parseRangeBounds(rangeStr) {
  if (!rangeStr) return null;
  const cleaned = String(rangeStr).replace(/,/g, "").trim();
  const lowTxt = cleaned.toLowerCase();
  if (cleaned.startsWith("<") || lowTxt.includes("less") || lowTxt.includes("upto") || lowTxt.includes("up to")) {
    const nums = cleaned.match(/\d+\.?\d*/g);
    return nums ? [null, parseFloat(nums[0])] : null;
  }
  if (cleaned.startsWith(">") || lowTxt.includes("greater") || lowTxt.includes("above")) {
    const nums = cleaned.match(/\d+\.?\d*/g);
    return nums ? [parseFloat(nums[0]), null] : null;
  }
  // Split only on a hyphen directly following a digit, so "0.6-1.1" splits
  // into two positive bounds instead of "-1.1" being read as negative.
  const parts = cleaned.split(/(?<=\d)\s*-\s*/);
  if (parts.length === 2) {
    const lowNums = parts[0].match(/\d+\.?\d*/g);
    const highNums = parts[1].match(/\d+\.?\d*/g);
    if (lowNums && highNums) return [parseFloat(lowNums[0]), parseFloat(highNums[0])];
  }
  return null;
}

function _isOutOfRange(valueStr, rangeStr) {
  const bounds = _parseRangeBounds(rangeStr);
  if (!bounds || !valueStr) return false;
  const nums = String(valueStr).replace(/,/g, "").match(/\d+\.?\d*/g);
  if (!nums) return false;
  const val = parseFloat(nums[0]);
  if (isNaN(val)) return false;
  const [low, high] = bounds;
  if (low !== null && val < low) return true;
  if (high !== null && val > high) return true;
  return false;
}

async function openReportsModal(patientId) {
  if (!patientId) {
    toast("Still loading this patient — try again in a moment.", "info");
    return;
  }
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay open";
  overlay.innerHTML = `
    <div class="modal" style="max-width:760px;width:92vw;max-height:88vh;overflow-y:auto">
      <div class="modal-header">
        <h2>Reports</h2>
        <button class="modal-close" id="reports-modal-close">&times;</button>
      </div>
      <div id="reports-modal-body"><p style="color:var(--slate)">Loading…</p></div>
    </div>
  `;
  document.body.appendChild(overlay);
  overlay.querySelector("#reports-modal-close").addEventListener("click", () => overlay.remove());
  overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.remove(); });

  try {
    const visits = await api("GET", `/lab/patient-reports/${patientId}`);
    const body = overlay.querySelector("#reports-modal-body");
    if (!visits.length) {
      body.innerHTML = `<p style="color:var(--slate)">No reports available yet for this patient.</p>`;
      return;
    }
    body.innerHTML = visits.map((v, i) => {
      const orderIdsKey = v.tests.map(t => t.order_id).join(',');
      return `
      <div style="border:1.5px solid var(--border);border-radius:var(--radius);margin-bottom:10px">
        <button type="button" onclick="this.nextElementSibling.style.display = this.nextElementSibling.style.display === 'none' ? '' : 'none'"
          style="width:100%;text-align:left;background:none;border:none;padding:12px 14px;cursor:pointer;display:flex;justify-content:space-between;align-items:center">
          <span><strong>${v.date ? new Date(v.date).toLocaleDateString('en-IN', {day:'numeric',month:'short',year:'numeric'}) : 'Date not recorded'}</strong>
            <span style="color:var(--slate);font-size:13px"> · Token ${v.token_number || '—'}</span></span>
          <span style="color:var(--slate)">${v.tests.length} test${v.tests.length > 1 ? 's' : ''} ▾</span>
        </button>
        <div style="display:${i === 0 ? '' : 'none'};padding:0 14px 14px">
          <button class="btn btn-outline btn-sm" style="margin-bottom:10px" onclick="downloadFile('/lab/reports/combined?order_ids=${orderIdsKey}', 'report_${orderIdsKey}.pdf')">📄 View Full Report (PDF)</button>
          ${v.tests.map(t => `
            <div style="padding:10px 0;border-top:1px solid var(--border)">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
                <strong>${t.test_name}</strong>
                ${t.is_critical ? '<span class="badge badge-red">Critical</span>' : ''}
              </div>
              ${t.results && t.results.length ? `
                <table style="width:100%;border-collapse:collapse;font-size:13px">
                  <thead>
                    <tr style="color:var(--slate);text-align:left">
                      <th style="padding:4px 8px 4px 0;font-weight:500">Parameter</th>
                      <th style="padding:4px 8px;font-weight:500">Value</th>
                      <th style="padding:4px 8px;font-weight:500">Unit</th>
                      <th style="padding:4px 0 4px 8px;font-weight:500">Range</th>
                    </tr>
                  </thead>
                  <tbody>
                    ${t.results.map(row => {
                      const out = _isOutOfRange(row.value, row.range);
                      const valueColor = out ? "#ef4444" : (row.value ? "#065f46" : "inherit");
                      const valueWeight = out ? "700" : "600";
                      return `
                      <tr style="border-top:1px solid var(--border)">
                        <td style="padding:5px 8px 5px 0">${row.name}</td>
                        <td style="padding:5px 8px;font-weight:${valueWeight};color:${valueColor}">${row.value}</td>
                        <td style="padding:5px 8px;color:var(--slate)">${row.unit || '—'}</td>
                        <td style="padding:5px 0 5px 8px;color:var(--slate)">${row.range || '—'}</td>
                      </tr>
                    `;
                    }).join('')}
                  </tbody>
                </table>
              ` : `<p style="font-size:13px;color:var(--slate-light)">No values recorded.</p>`}
            </div>
          `).join('')}
        </div>
      </div>
    `;
    }).join('');
  } catch (e) {
    overlay.querySelector("#reports-modal-body").innerHTML = `<p style="color:var(--red)">Couldn't load reports right now.</p>`;
  }
}

function openOffDutyTimeModal(confirmLabel) {
  confirmLabel = confirmLabel || "Mark Present";
  return new Promise((resolve) => {
    const roundToNearest5 = (date) => { const ms = 5 * 60 * 1000; return new Date(Math.round(date.getTime() / ms) * ms); };
    const def = roundToNearest5(new Date(Date.now() + 9 * 60 * 60 * 1000)); // default: 9-hour shift from now
    let hour24 = def.getHours();
    let minute = def.getMinutes();
    let period = hour24 >= 12 ? 'PM' : 'AM';
    let hour = hour24 % 12; if (hour === 0) hour = 12;

    const overlay = document.createElement("div");
    overlay.className = "modal-overlay open";
    overlay.innerHTML = `
      <style>
        .off-duty-step-btn { width:44px;height:36px;border-radius:var(--radius);border:1px solid var(--border);background:var(--smoke);color:var(--navy);font-size:14px;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:background .15s; }
        .off-duty-step-btn:hover { background:var(--smoke-mid); }
        .off-duty-step-btn:active { background:var(--teal);color:#fff; }
        .off-duty-ampm-btn { width:52px;height:38px;border-radius:var(--radius);border:1.5px solid var(--border);background:var(--white);color:var(--slate);font-size:13px;font-weight:700;cursor:pointer; }
        .off-duty-ampm-btn.active { background:var(--teal);border-color:var(--teal);color:#fff; }
      </style>
      <div class="modal" style="max-width:380px;text-align:center">
        <div class="modal-header" style="border-bottom:none;margin-bottom:4px;justify-content:center">
          <h2 style="margin:0;font-size:18px">When will you go off duty today?</h2>
        </div>
        <p style="color:var(--slate);font-size:13.5px;margin:0 0 20px">If you forget to mark yourself off duty, we'll do it for you at this time.</p>
        <div style="display:flex;align-items:center;justify-content:center;gap:8px;margin-bottom:22px">
          <div style="display:flex;flex-direction:column;align-items:center;gap:6px">
            <button type="button" class="off-duty-step-btn" id="odh-up">▲</button>
            <div id="odh-val" style="font-size:34px;font-weight:700;color:var(--navy);width:56px;text-align:center;font-variant-numeric:tabular-nums"></div>
            <button type="button" class="off-duty-step-btn" id="odh-down">▼</button>
          </div>
          <div style="font-size:34px;font-weight:700;color:var(--navy);margin-bottom:2px">:</div>
          <div style="display:flex;flex-direction:column;align-items:center;gap:6px">
            <button type="button" class="off-duty-step-btn" id="odm-up">▲</button>
            <div id="odm-val" style="font-size:34px;font-weight:700;color:var(--navy);width:56px;text-align:center;font-variant-numeric:tabular-nums"></div>
            <button type="button" class="off-duty-step-btn" id="odm-down">▼</button>
          </div>
          <div style="display:flex;flex-direction:column;gap:6px;margin-left:8px">
            <button type="button" class="off-duty-ampm-btn" id="odp-am">AM</button>
            <button type="button" class="off-duty-ampm-btn" id="odp-pm">PM</button>
          </div>
        </div>
        <div style="display:flex;gap:10px">
          <button type="button" class="btn btn-outline" style="flex:1" id="off-duty-cancel-btn">Cancel</button>
          <button type="button" class="btn btn-primary" style="flex:1" id="off-duty-confirm-btn">${confirmLabel}</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    const hourVal = overlay.querySelector("#odh-val");
    const minVal = overlay.querySelector("#odm-val");
    const amBtn = overlay.querySelector("#odp-am");
    const pmBtn = overlay.querySelector("#odp-pm");

    function render() {
      hourVal.textContent = String(hour).padStart(2, '0');
      minVal.textContent = String(minute).padStart(2, '0');
      amBtn.classList.toggle('active', period === 'AM');
      pmBtn.classList.toggle('active', period === 'PM');
    }
    render();

    overlay.querySelector("#odh-up").addEventListener("click", () => { hour = hour === 12 ? 1 : hour + 1; render(); });
    overlay.querySelector("#odh-down").addEventListener("click", () => { hour = hour === 1 ? 12 : hour - 1; render(); });
    overlay.querySelector("#odm-up").addEventListener("click", () => { minute = (minute + 5) % 60; render(); });
    overlay.querySelector("#odm-down").addEventListener("click", () => { minute = (minute - 5 + 60) % 60; render(); });
    amBtn.addEventListener("click", () => { period = 'AM'; render(); });
    pmBtn.addEventListener("click", () => { period = 'PM'; render(); });

    function cleanup(result) {
      document.removeEventListener("keydown", onKeydown);
      overlay.remove();
      resolve(result);
    }
    function doConfirm() {
      let hour24b = hour % 12;
      if (period === 'PM') hour24b += 12;
      const dt = new Date();
      dt.setHours(hour24b, minute, 0, 0);
      if (dt.getTime() <= Date.now()) dt.setDate(dt.getDate() + 1); // overnight shift — roll to tomorrow
      cleanup(dt.toISOString());
    }
    function onKeydown(e) {
      if (e.key === "Enter") { e.preventDefault(); doConfirm(); }
    }
    document.addEventListener("keydown", onKeydown);

    overlay.querySelector("#off-duty-cancel-btn").addEventListener("click", () => cleanup(null));
    overlay.addEventListener("click", (e) => { if (e.target === overlay) cleanup(null); });
    overlay.querySelector("#off-duty-confirm-btn").addEventListener("click", doConfirm);
  });
}

function toIST(iso) {
  return /[+-]\d\d:\d\d$|Z$/.test(iso) ? iso : iso + "+05:30";
}

function syncStatusHeading(badgeId, headingSpanId) {
  const badge = document.getElementById(badgeId);
  const span = document.getElementById(headingSpanId);
  if (!badge || !span) return;
  const update = () => { span.textContent = badge.textContent ? `(${badge.textContent})` : ''; };
  update();
  new MutationObserver(update).observe(badge, { childList: true, characterData: true, subtree: true });
}

function renderOffDutyTimeLine(containerId, isoTime) {
  const el = document.getElementById(containerId);
  if (!el) return;
  if (!isoTime) { el.innerHTML = ''; return; }
  const t = new Date(isoTime);
  const timeStr = t.toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit', hour12: true });
  el.innerHTML = `
    <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;border:1px solid var(--border);border-radius:var(--radius,8px);padding:6px 10px">
      <span>Off duty by <strong>${timeStr}</strong></span>
      <a href="javascript:void(0)" onclick="editOffDutyTime('${containerId}')">Edit</a>
    </div>`;
}

async function editOffDutyTime(containerId) {
  const newTime = await openOffDutyTimeModal("Save");
  if (!newTime) return;
  try {
    await api("PATCH", "/doctors/attendance/off-duty-time", { expected_off_duty_at: newTime });
    renderOffDutyTimeLine(containerId, newTime);
    toast("Off-duty time updated.", "success");
  } catch (e) { toast(e.message, "error"); }
}

async function markAttendanceCommon(status, room_id, extra, alreadyActive) {
  return api("POST", "/doctors/attendance", { status, room_id, ...(extra || {}) });
}