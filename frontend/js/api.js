const BASE = window.MEDSCRIBE_API_BASE || "https://medical-ai-mvv1.onrender.com";

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
      throw new Error("Could not reach backend. If /health works, this is usually a backend 500 or CORS error. Check Render deploy/runtime logs.");
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
  const fullName = doc.title ? `${doc.title} ${doc.name}` : doc.name;
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
        <div style="display:flex;gap:8px;align-items:center;margin-bottom:8px">
          <select class="form-control" id="od-hour" style="flex:1">
            ${Array.from({length:12},(_,i)=>i+1).map(h=>`<option value="${h}">${h}</option>`).join('')}
          </select>
          <span style="font-weight:600">:</span>
          <input class="form-control" id="od-minute" list="od-minute-list" placeholder="00" maxlength="2"
            style="flex:1;text-align:center" />
          <datalist id="od-minute-list">
            <option value="00"></option><option value="15"></option><option value="30"></option><option value="45"></option>
          </datalist>
          <select class="form-control" id="od-ampm" style="flex:1">
            <option value="AM">AM</option>
            <option value="PM">PM</option>
          </select>
        </div>
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
      const hour12 = parseInt(overlay.querySelector("#od-hour").value, 10);
      const minuteRaw = overlay.querySelector("#od-minute").value.trim();
      const ampm = overlay.querySelector("#od-ampm").value;
      const minute = minuteRaw === "" ? NaN : parseInt(minuteRaw, 10);
      if (!hour12 || isNaN(minute) || minute < 0 || minute > 59) {
        overlay.querySelector("#od-time-err").textContent = "Pick or type a valid time, or tap Skip.";
        return;
      }
      let hour24 = hour12 % 12;
      if (ampm === "PM") hour24 += 12;
      const d = new Date();
      d.setHours(hour24, minute, 0, 0);
      if (d < new Date()) d.setDate(d.getDate() + 1);
      cleanup(d.toISOString());
    });
  });
}

async function markAttendanceCommon(status, room_id, extra, alreadyActive) {
  let expected_off_duty_at = null;
  if (status === "present" && !alreadyActive) {
    expected_off_duty_at = await promptOffDutyTime();
  }
  return api("POST", "/doctors/attendance", { status, room_id, expected_off_duty_at, ...(extra || {}) });
}