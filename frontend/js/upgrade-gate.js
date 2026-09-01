// upgrade-gate.js
// Single shared module for tier gating + the Upgrade Modal. Include on
// every staff role's page after api.js and tier-catalog.js:
//   <script src="../js/tier-catalog.js"></script>
//   <script src="../js/upgrade-gate.js"></script>
//
// Auto-locks any Admissions nav link on the page for Foundation-tier
// hospitals (no per-page wiring needed beyond the two script tags above).
// Chat's own lock lives in chat-widget.js since it already owns a single
// shared trigger element. Both call openUpgradeModal() from here.

function isFoundationTier() {
  const doc = (typeof getDoctor === "function") ? getDoctor() : null;
  return !!doc && (doc.hospital_tier || "growth") === "foundation";
}

function _ensureUpgradeModalStyles() {
  if (document.getElementById("upgrade-modal-styles")) return;
  const style = document.createElement("style");
  style.id = "upgrade-modal-styles";
  style.textContent = `
    .upgrade-modal { max-width: 960px; }
    .upgrade-modal-grid {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 14px;
    }
    @media (max-width: 860px) {
      .upgrade-modal-grid { grid-template-columns: repeat(2, 1fr); }
    }
    @media (max-width: 560px) {
      .upgrade-modal-grid { grid-template-columns: 1fr; }
      .upgrade-modal { padding: 20px 16px; }
    }
    .upgrade-tier-card {
      position: relative;
      border: 1.5px solid var(--border);
      border-radius: var(--radius-lg);
      padding: 18px 16px;
      background: var(--white);
      display: flex;
      flex-direction: column;
    }
    .upgrade-tier-card.current { border-color: var(--teal); background: var(--teal-subtle); }
    .upgrade-tier-card.premium { border-color: var(--navy); }
    .upgrade-current-badge, .upgrade-premium-badge {
      position: absolute; top: -11px; left: 14px;
      font-size: 11px; font-weight: 700; letter-spacing: 0.03em;
    }
    .upgrade-premium-badge {
      background: var(--navy); color: var(--white);
      padding: 3px 10px; border-radius: 999px;
    }
    .upgrade-tier-label { font-size: 15px; font-weight: 700; color: var(--navy); margin-top: 6px; }
    .upgrade-tier-price { font-size: 22px; font-weight: 800; color: var(--navy); margin-top: 4px; }
    .upgrade-tier-price span { font-size: 12px; font-weight: 500; color: var(--slate); }
    .upgrade-tier-scope { font-size: 12px; color: var(--slate); margin-top: 2px; margin-bottom: 12px; }
    .upgrade-tier-features { flex: 1; }
    .upgrade-tier-feature {
      display: flex; align-items: flex-start; gap: 6px;
      font-size: 12.5px; color: var(--navy); margin-bottom: 8px; line-height: 1.4;
    }
    .upgrade-tier-check { color: var(--teal); font-weight: 700; flex-shrink: 0; }
    .upgrade-tier-cta { width: 100%; text-align: center; margin-top: 14px; }
    .nav-locked { position: relative; opacity: 0.62; }
    .nav-locked::after {
      content: "\\1F512";
      position: absolute; top: 0; right: 2px; font-size: 10px; line-height: 1;
    }
  `;
  document.head.appendChild(style);
}

function _tierCardHtml(tier, currentTierKey) {
  const isCurrent = tier.key === currentTierKey;
  let cta;
  if (isCurrent) {
    cta = `<span class="btn btn-outline btn-sm upgrade-tier-cta" style="pointer-events:none">Current Plan</span>`;
  } else if (tier.comingSoon) {
    cta = `<span class="btn btn-outline btn-sm upgrade-tier-cta" style="pointer-events:none">Coming Soon</span>`;
  } else {
    cta = `<button class="btn btn-primary btn-sm upgrade-tier-cta" onclick="toast('Reach out to your MedScribe representative to upgrade this hospital.','info')">Contact Us to Upgrade</button>`;
  }
  return `
    <div class="upgrade-tier-card${isCurrent ? " current" : ""}${tier.premium ? " premium" : ""}">
      ${isCurrent ? '<span class="badge badge-teal upgrade-current-badge">Current Plan</span>' : ""}
      ${!isCurrent && tier.premium ? '<span class="upgrade-premium-badge">Most Powerful</span>' : ""}
      <div class="upgrade-tier-label">${tier.label}</div>
      <div class="upgrade-tier-price">${tier.price}<span>${tier.period}</span></div>
      <div class="upgrade-tier-scope">${tier.scope}</div>
      <div class="upgrade-tier-features">
        ${tier.features.map((f) => `<div class="upgrade-tier-feature"><span class="upgrade-tier-check">\u2713</span><span>${f}</span></div>`).join("")}
      </div>
      ${cta}
    </div>
  `;
}

function ensureUpgradeModal() {
  _ensureUpgradeModalStyles();
  if (document.getElementById("modal-upgrade")) return;
  const wrap = document.createElement("div");
  wrap.innerHTML = `
    <div class="modal-overlay" id="modal-upgrade">
      <div class="modal upgrade-modal">
        <div class="modal-header">
          <h2>Upgrade Your Plan</h2>
          <button class="modal-close" onclick="closeUpgradeModal()">&times;</button>
        </div>
        <div class="upgrade-modal-grid" id="upgrade-modal-grid"></div>
      </div>
    </div>`;
  document.body.appendChild(wrap.firstElementChild);
}

function openUpgradeModal() {
  ensureUpgradeModal();
  const doc = (typeof getDoctor === "function") ? getDoctor() : null;
  const currentTierKey = (doc && doc.hospital_tier) || "growth";
  document.getElementById("upgrade-modal-grid").innerHTML =
    TIER_CATALOG.map((t) => _tierCardHtml(t, currentTierKey)).join("");
  document.getElementById("modal-upgrade").classList.add("open");
}

function closeUpgradeModal() {
  document.getElementById("modal-upgrade")?.classList.remove("open");
}

// Locks any Admissions nav link/button on the current page for
// Foundation-tier hospitals — matches by href or onclick target rather
// than a specific element id, so it covers dashboard.html, nurse.html,
// receptionist.html, and doctor-slots.html's differing markup without
// per-page changes.
function gateAdmissionsNav() {
  if (!isFoundationTier()) return;
  document.querySelectorAll('a[href="admissions.html"], [onclick*="admissions.html"]').forEach((el) => {
    if (el.dataset.upgradeGated) return;
    el.dataset.upgradeGated = "1";
    el.removeAttribute("onclick");
    el.setAttribute("href", "javascript:void(0)");
    el.classList.add("nav-locked");
    el.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      openUpgradeModal();
    });
  });
}

document.addEventListener("DOMContentLoaded", gateAdmissionsNav);

let _gateAdmissionsNavDebounce = null;
new MutationObserver(() => {
  clearTimeout(_gateAdmissionsNavDebounce);
  _gateAdmissionsNavDebounce = setTimeout(gateAdmissionsNav, 150);
}).observe(document.documentElement, { childList: true, subtree: true });

setInterval(gateAdmissionsNav, 2000);