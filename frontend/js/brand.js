// ScribeKare brand constants. A future rename is a one-line change here
// (plus BRAND_NAME / COMPANY_LEGAL_NAME in backend/app/config.py).
// BRAND_NAME = the product name. COMPANY_LEGAL_NAME = the registered company
// name (change it after incorporation, e.g. "ScribeKare Private Limited").
// Elements with data-brand get BRAND_NAME; elements with data-company-legal
// get COMPANY_LEGAL_NAME. Text is set with textContent only.
const BRAND_NAME = "ScribeKare";
const COMPANY_LEGAL_NAME = "ScribeKare";
window.BRAND_NAME = BRAND_NAME;
window.COMPANY_LEGAL_NAME = COMPANY_LEGAL_NAME;
// Grievance Officer details shown at the end of the Terms and the Privacy Policy (js/legal-content.js).
// Fill these in once the company is incorporated. Anything left empty is simply not shown; the contact link to the
// home page Contact section is always shown.
window.LEGAL_CONTACT = { name: "", email: "support@scribekare.com", address: "" };
(function () {
  function apply() {
    document.querySelectorAll("[data-brand]").forEach(function (el) { el.textContent = BRAND_NAME; });
    document.querySelectorAll("[data-company-legal]").forEach(function (el) { el.textContent = COMPANY_LEGAL_NAME; });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", apply);
  else apply();
})();