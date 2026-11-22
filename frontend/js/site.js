/* ScribeKare public-page helpers (home, privacy, terms). Loaded in <head>.
   1. Theme: light / dark. Remembers the choice, otherwise follows the device. Any [data-theme-toggle] button switches it.
   2. Clean links: in-page links (#plans, #contact ...) scroll smoothly and never leave "#something" in the address bar.
   3. Section hand-off: <a href="home.html" data-go="contact"> opens the home page and scrolls to that section,
      so other pages can point to a section without putting "#contact" in the URL.
   4. Small header bits for pages that use data-hdr / data-menu-btn (privacy and terms). */
(function () {
  "use strict";
  var KEY = "sk_theme", GO = "sk_go";
  var root = document.documentElement;
  var mq = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---------------------------------------------------------------- theme (runs immediately, before first paint)
  function stored() { try { var v = localStorage.getItem(KEY); return v === "light" || v === "dark" ? v : null; } catch (e) { return null; } }
  function current() { return stored() || (mq && mq.matches ? "dark" : "light"); }
  function paintButtons(t) {
    var next = t === "dark" ? "light" : "dark";
    document.querySelectorAll("[data-theme-toggle]").forEach(function (b) {
      b.setAttribute("aria-label", "Switch to " + next + " theme");
      b.setAttribute("title", "Switch to " + next + " theme");
      b.setAttribute("aria-pressed", t === "dark" ? "true" : "false");
    });
  }
  function apply(t) { root.setAttribute("data-theme", t); paintButtons(t); }
  apply(current());
  if (mq && mq.addEventListener) mq.addEventListener("change", function () { if (!stored()) apply(current()); });
  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest("[data-theme-toggle]");
    if (!b) return;
    var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
    try { localStorage.setItem(KEY, next); } catch (err) { /* storage blocked: the choice lasts for this page only */ }
    apply(next);
  });

  // ---------------------------------------------------------------- clean in-page links
  function cleanUrl() {
    if (location.hash && window.history && history.replaceState) history.replaceState(null, "", location.pathname + location.search);
  }
  function goTo(target) {
    target.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
    if (!target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
    try { target.focus({ preventScroll: true }); } catch (e) { /* older browsers */ }
    cleanUrl();
  }
  document.addEventListener("click", function (e) {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var a = e.target.closest && e.target.closest('a[href^="#"]');
    if (!a) return;
    var href = a.getAttribute("href");
    if (!href || href === "#") return;
    var id;
    try { id = decodeURIComponent(href.slice(1)); } catch (err) { return; }
    var target = document.getElementById(id);
    if (!target) return;
    e.preventDefault();
    goTo(target);
  });

  // ---------------------------------------------------------------- hand-off from other pages
  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("a[data-go]");
    if (!a) return;
    try { sessionStorage.setItem(GO, a.getAttribute("data-go")); } catch (err) { /* ignore */ }
  });
  function arrive() {
    var id = null;
    try { id = sessionStorage.getItem(GO); sessionStorage.removeItem(GO); } catch (e) { id = null; }
    if (!id && location.hash) { try { id = decodeURIComponent(location.hash.slice(1)); } catch (e) { id = null; } }
    cleanUrl();
    if (!id) return;
    var target = document.getElementById(id);
    if (target) setTimeout(function () { goTo(target); }, 80);
  }
  function ready() {
    paintButtons(root.getAttribute("data-theme"));
    if (document.getElementById("main") && document.getElementById("contact")) arrive();   // home page only
    var hdr = document.querySelector("[data-hdr]");
    if (hdr) {
      var onScroll = function () { hdr.classList.toggle("scrolled", window.scrollY > 6); };
      window.addEventListener("scroll", onScroll, { passive: true });
      onScroll();
    }
    var menuBtn = document.querySelector("[data-menu-btn]");
    if (menuBtn) {
      var menu = document.getElementById(menuBtn.getAttribute("aria-controls"));
      menuBtn.addEventListener("click", function () {
        var open = menu.hidden;
        menu.hidden = !open;
        menuBtn.setAttribute("aria-expanded", open ? "true" : "false");
      });
      menu.addEventListener("click", function (e) { if (e.target.closest("a")) { menu.hidden = true; menuBtn.setAttribute("aria-expanded", "false"); } });
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", ready); else ready();
})();