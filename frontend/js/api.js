const BASE = "https://medical-ai-mvv1.onrender.com";

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

async function api(method, path, body = null, isFormData = false) {
  const headers = { Authorization: `Bearer ${getToken()}` };
  if (!isFormData) headers["Content-Type"] = "application/json";

  const opts = { method, headers };
  if (body) opts.body = isFormData ? body : JSON.stringify(body);

  const res = await fetch(BASE + path, opts);

  if (res.status === 401) {
    clearSession();
    window.location.href = "/pages/login.html";
    return;
  }

  if (res.status === 403 || res.status === 404) {
    toast("Access denied or resource not found.", "error");
    setTimeout(() => redirectByRole(getDoctor()?.role), 1500);
    return;
  }

  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Request failed");
  return data;
}

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

// Fill topbar doctor info
function fillTopbar() {
  const doc = getDoctor();
  if (!doc) return;
  const el = document.getElementById("topbar-doctor-name");
  if (el) el.textContent = `${doc.title} ${doc.name}`;
  const cl = document.getElementById("topbar-clinic");
  if (cl) cl.textContent = doc.clinic_name;
}
// Mobile sidebar drawer
function toggleSidebar() {
  document.querySelector(".sidebar")?.classList.toggle("open");
  document.getElementById("sidebar-backdrop")?.classList.toggle("open");
}
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
  } else {
    window.location.href = '/pages/dashboard.html';
  }
}