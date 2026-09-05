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

function isBelowScaleTier() {
  const doc = (typeof getDoctor === "function") ? getDoctor() : null;
  if (!doc) return true;
  return tierIndex(doc.hospital_tier || "growth") < tierIndex("scale");
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

    .upgrade-request-modal { max-width: 480px; }
    .upgrade-request-preview {
      border: 1.5px solid var(--border);
      border-radius: var(--radius-lg);
      padding: 18px 18px 16px;
      background: linear-gradient(180deg, var(--teal-subtle) 0%, var(--white) 70%);
      margin-top: 4px;
    }
    .upgrade-request-preview-head {
      display: flex; align-items: baseline; justify-content: space-between; gap: 10px;
      margin-bottom: 4px;
    }
    .upgrade-request-preview-label { font-size: 17px; font-weight: 800; color: var(--navy); }
    .upgrade-request-preview-price { font-size: 20px; font-weight: 800; color: var(--teal); white-space: nowrap; }
    .upgrade-request-preview-price span { font-size: 12px; font-weight: 500; color: var(--slate); }
    .upgrade-request-preview-scope { font-size: 12.5px; color: var(--slate); margin-bottom: 12px; }
    .upgrade-request-preview-features { display: flex; flex-direction: column; gap: 7px; }
    .upgrade-request-preview-feature {
      display: flex; align-items: flex-start; gap: 7px;
      font-size: 12.5px; color: var(--navy); line-height: 1.4;
    }
    .upgrade-request-preview-check { color: var(--teal); font-weight: 700; flex-shrink: 0; }
    .upgrade-request-actions {
      display: flex; align-items: center; justify-content: space-between; gap: 14px;
      margin-top: 20px;
    }
    .upgrade-request-confirm-btn {
      flex: 1;
      padding: 13px 18px !important;
      font-size: 15px !important;
      font-weight: 700 !important;
      box-shadow: 0 4px 14px rgba(15, 118, 110, 0.28);
    }
    .btn-text-back {
      background: none; border: none; color: var(--slate); font-size: 13px;
      font-weight: 600; cursor: pointer; padding: 8px 2px; flex-shrink: 0;
      text-decoration: underline; text-underline-offset: 2px; white-space: nowrap;
    }
    .btn-text-back:hover { color: var(--navy); }
  `;
  document.head.appendChild(style);
}

function _tierCardHtml(tier, currentTierKey) {
  const isCurrent = tier.key === currentTierKey;
  const doc = (typeof getDoctor === "function") ? getDoctor() : null;
  const isAdmin = !!doc && ["admin", "sub_admin"].includes(doc.role);
  let cta;
  if (isCurrent) {
    cta = `<span class="btn btn-outline btn-sm upgrade-tier-cta" style="pointer-events:none">Current Plan</span>`;
  } else if (tier.comingSoon) {
    cta = `<span class="btn btn-outline btn-sm upgrade-tier-cta" style="pointer-events:none">Coming Soon</span>`;
  } else if (isAdmin) {
    cta = `<button class="btn btn-primary btn-sm upgrade-tier-cta" onclick="openUpgradeRequestModal('${tier.key}')">Contact Us to Upgrade</button>`;
  } else {
    cta = `<button class="btn btn-primary btn-sm upgrade-tier-cta" onclick="sendUpgradeNudge('${tier.key}','${tier.label}', this)">Ask Admin to Upgrade</button>`;
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

async function sendUpgradeNudge(tierKey, tierLabel, btn) {
  if (btn) { btn.disabled = true; btn.textContent = "Sending…"; }
  try {
    await api("POST", "/billing/request-upgrade-nudge", { tier: tierKey });
    toast(`Sent — your admin has been notified you'd like the ${tierLabel} plan.`, "success");
    if (btn) { btn.textContent = "Sent ✓"; }
  } catch (e) {
    toast(e.message, "error");
    if (btn) { btn.disabled = false; btn.textContent = "Ask Admin to Upgrade"; }
  }
}

function _ensureUpgradeRequestModal() {
  _ensureUpgradeModalStyles();
  if (document.getElementById("modal-upgrade-request")) return;
  const wrap = document.createElement("div");
  wrap.innerHTML = `
    <div class="modal-overlay" id="modal-upgrade-request">
      <div class="modal upgrade-request-modal">
        <div class="modal-header">
          <h2>Request an Upgrade</h2>
          <button class="modal-close" onclick="closeUpgradeRequestModal()">&times;</button>
        </div>

        <div class="form-group">
          <label class="form-label">Which plan would you like?</label>
          <select class="form-control" id="upgrade-request-tier-select" onchange="renderUpgradeRequestTierPreview()"></select>
        </div>

        <div id="upgrade-request-tier-preview" class="upgrade-request-preview"></div>

        <div class="form-group" style="margin-top:16px">
          <label class="form-label">Anything you'd like us to know? <span style="font-weight:400;color:var(--slate)">(optional)</span></label>
          <textarea class="form-control" id="upgrade-request-message" rows="3" placeholder="e.g. best time to call, specific features you need"></textarea>
        </div>

        <div class="err-msg" id="upgrade-request-err"></div>

        <div class="upgrade-request-actions">
          <button type="button" class="btn-text-back" onclick="closeUpgradeRequestModal(); openUpgradeModal();">&larr; Back to plans</button>
          <button type="button" class="btn btn-primary upgrade-request-confirm-btn" id="upgrade-request-submit-btn" onclick="submitUpgradeRequest()">Confirm &amp; Send Request</button>
        </div>
      </div>
    </div>`;
  document.body.appendChild(wrap.firstElementChild);
}

function openUpgradeRequestModal(tierKey) {
  _ensureUpgradeRequestModal();
  const doc = (typeof getDoctor === "function") ? getDoctor() : null;
  const currentTierKey = (doc && doc.hospital_tier) || "growth";
  const currentIdx = tierIndex(currentTierKey);
  const higherTiers = TIER_CATALOG.filter((t, i) => i > currentIdx);
  const sel = document.getElementById("upgrade-request-tier-select");
  sel.innerHTML = higherTiers.map((t) =>
    `<option value="${t.key}"${t.key === tierKey ? " selected" : ""}>${t.label}</option>`
  ).join("");
  document.getElementById("upgrade-request-message").value = "";
  document.getElementById("upgrade-request-err").textContent = "";
  renderUpgradeRequestTierPreview();
  document.getElementById("modal-upgrade-request").classList.add("open");
}

function renderUpgradeRequestTierPreview() {
  const key = document.getElementById("upgrade-request-tier-select").value;
  const tier = TIER_CATALOG.find((t) => t.key === key);
  if (!tier) return;
  document.getElementById("upgrade-request-tier-preview").innerHTML = `
    <div class="upgrade-request-preview-head">
      <span class="upgrade-request-preview-label">${tier.label}</span>
      <span class="upgrade-request-preview-price">${tier.price}<span>${tier.period}</span></span>
    </div>
    <div class="upgrade-request-preview-scope">${tier.scope}</div>
    <div class="upgrade-request-preview-features">
      ${tier.features.map((f) =>
        `<div class="upgrade-request-preview-feature"><span class="upgrade-request-preview-check">\u2713</span><span>${f}</span></div>`
      ).join("")}
    </div>
  `;
}

function closeUpgradeRequestModal() {
  document.getElementById("modal-upgrade-request")?.classList.remove("open");
}

async function submitUpgradeRequest() {
  const btn = document.getElementById("upgrade-request-submit-btn");
  const err = document.getElementById("upgrade-request-err");
  const tierKey = document.getElementById("upgrade-request-tier-select").value;
  const message = document.getElementById("upgrade-request-message").value.trim();
  btn.disabled = true;
  btn.textContent = "Sending…";
  try {
    await api("POST", "/billing/request-upgrade", { tier: tierKey, message });
    closeUpgradeRequestModal();
    closeUpgradeModal();
    toast("Request sent — our team will reach out shortly.", "success");
  } catch (e) {
    err.textContent = e.message;
  } finally {
    btn.disabled = false;
    btn.textContent = "Confirm & Send Request";
  }
}

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