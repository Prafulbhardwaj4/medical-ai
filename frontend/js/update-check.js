(function () {
  if (window.__msUpdateCheck) return;
  window.__msUpdateCheck = true;

  var MS_BUILD_ID = "dev";
  if (MS_BUILD_ID === "dev") return;

  var POLL_MS = 12 * 60 * 1000;
  var MIN_GAP_MS = 15 * 1000;
  var IDLE_MS = 5 * 60 * 1000;
  var LOGIN_QUIET_MS = 5 * 1000;
  var AUTO_RELOAD_GAP_MS = 5 * 60 * 1000;

  var pending = false;
  var inFlight = false;
  var lastCheck = 0;
  var lastActivity = Date.now();

  var isLoginPage = /^\/(pages\/login(\.html)?\/?)?$/.test(location.pathname);
  var isConsultation = /\/consultation(\.html)?\/?$/.test(location.pathname);

  ["pointerdown", "keydown", "touchstart", "scroll", "input"].forEach(function (ev) {
    window.addEventListener(ev, function () { lastActivity = Date.now(); }, { passive: true, capture: true });
  });

  var SKIP_TYPES = /^(hidden|search|button|submit|reset|image|file)$/i;
  var SKIP_NAMES = /search|filter|query/i;

  function formsDirty() {
    var els = document.querySelectorAll("input, textarea, select");
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      if (el.closest && el.closest("[data-ms-nodirty]")) continue;
      var tag = el.tagName;
      if (tag === "INPUT") {
        if (SKIP_TYPES.test(el.type)) continue;
        if (SKIP_NAMES.test((el.id || "") + " " + (el.name || "") + " " + (el.placeholder || ""))) continue;
        if (el.type === "checkbox" || el.type === "radio") {
          if (el.checked !== el.defaultChecked) return true;
          continue;
        }
        if (el.value !== el.defaultValue) return true;
      } else if (tag === "TEXTAREA") {
        if (el.value !== el.defaultValue) return true;
      } else if (tag === "SELECT") {
        if (SKIP_NAMES.test((el.id || "") + " " + (el.name || ""))) continue;
        for (var j = 0; j < el.options.length; j++) {
          if (el.options[j].selected !== el.options[j].defaultSelected) return true;
        }
      }
    }
    return false;
  }

  function hasUnsavedWork() {
    try {
      if (isConsultation) return true;
      if (typeof window.msKeepSessionAlive === "function" && window.msKeepSessionAlive()) return true;
      if (document.querySelector(".modal-overlay.open")) return true;
      return formsDirty();
    } catch (e) {
      return true;
    }
  }

  function showBanner() {
    if (document.getElementById("ms-update-banner")) return;
    if (!document.body) { document.addEventListener("DOMContentLoaded", showBanner); return; }

    var bar = document.createElement("div");
    bar.id = "ms-update-banner";
    bar.setAttribute("role", "status");
    bar.setAttribute("aria-live", "polite");
    bar.style.cssText =
      "position:fixed;left:0;right:0;bottom:0;z-index:2147483000;display:flex;flex-wrap:wrap;" +
      "align-items:center;justify-content:center;gap:12px;padding:14px 16px calc(14px + env(safe-area-inset-bottom));" +
      "background:#0f172a;color:#fff;font:600 16px/1.35 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;" +
      "box-shadow:0 -4px 16px rgba(0,0,0,.25);text-align:center";

    var msg = document.createElement("span");
    msg.textContent = "A new version is available. Tap to update";

    var btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = "Update now";
    btn.style.cssText =
      "min-height:48px;min-width:140px;padding:12px 24px;border:0;border-radius:10px;background:#22c55e;" +
      "color:#052e16;font:700 16px system-ui,-apple-system,Segoe UI,Roboto,sans-serif;cursor:pointer;" +
      "touch-action:manipulation";
    btn.addEventListener("click", function () {
      if (hasUnsavedWork() &&
          !window.confirm("You have unsaved work on this page. Update anyway? Unsaved changes will be lost.")) {
        return;
      }
      reload();
    });

    bar.appendChild(msg);
    bar.appendChild(btn);
    document.body.appendChild(bar);
  }

  function reload() { location.reload(); }

  function recentlyAutoReloaded() {
    try {
      var t = Number(sessionStorage.getItem("ms_auto_reload_at")) || 0;
      return Date.now() - t < AUTO_RELOAD_GAP_MS;
    } catch (e) { return false; }
  }

  function maybeAutoReload() {
    if (!pending || hasUnsavedWork() || recentlyAutoReloaded()) return;
    var quiet = Date.now() - lastActivity;
    var allowed = isLoginPage ? quiet >= LOGIN_QUIET_MS : quiet >= IDLE_MS;
    if (!allowed) return;
    try { sessionStorage.setItem("ms_auto_reload_at", String(Date.now())); } catch (e) { }
    reload();
  }

  function check(force) {
    var now = Date.now();
    if (inFlight || (!force && now - lastCheck < MIN_GAP_MS)) return;
    inFlight = true;
    lastCheck = now;
    fetch("/version.json?t=" + now, { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (data && data.v && data.v !== MS_BUILD_ID) {
          pending = true;
          showBanner();
          maybeAutoReload();
        }
      })
      .catch(function () { })
      .then(function () { inFlight = false; });
  }

  document.addEventListener("visibilitychange", function () { if (!document.hidden) check(false); });
  window.addEventListener("pageshow", function (e) { check(!!e.persisted); });
  setInterval(function () { check(true); }, POLL_MS);
  setInterval(maybeAutoReload, 30 * 1000);

  window.msCheckForUpdate = function () { check(true); };
  check(true);
})();