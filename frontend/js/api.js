const BASE = "http://localhost:8000";

function getToken() {
  return localStorage.getItem("ms_token");
}

function getDoctor() {
  try { return JSON.parse(localStorage.getItem("ms_doctor")); }
  catch { return null; }
}

function saveSession(token, doctor) {
  localStorage.setItem("ms_token", token);
  localStorage.setItem("ms_doctor", JSON.stringify(doctor));
}

function clearSession() {
  localStorage.removeItem("ms_token");
  localStorage.removeItem("ms_doctor");
}

function requireAuth() {
  if (!getToken()) {
    window.location.href = "/pages/login.html";
    return false;
  }
  return true;
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
    setTimeout(() => window.location.href = "/pages/dashboard.html", 1500);
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

async function logout() {
  try {
    await api("POST", "/auth/logout");
  } catch(e) {}
  clearSession();
  window.location.href = "/pages/login.html";
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
  if (!password || password.length < 6) return "Password must be at least 6 characters.";
  return null;
}