// Shared Suggestion Box widget.
// Include this on any authenticated staff page after js/api.js (and after
// js/chat-widget.js if present, so it reuses the same topbar-right-group).
// Mounts a teal-green header button for every staff role except super_admin
// (who instead reviews everything from their own dashboard tab). Opens a
// panel with a free-text box to submit a new suggestion, and a read-only
// list of the staff member's own past submissions with status badges —
// staff can see status, they can never set it.

(function () {
  const EXCLUDED_ROLES = ["super_admin"];

  function mount() {
    const doctor = getDoctor();
    if (!doctor || !getToken()) return;
    if (EXCLUDED_ROLES.includes(doctor.role)) return;

    const profileBtn = document.querySelector(".topbar-profile-btn");
    if (!profileBtn || !profileBtn.parentNode) return;

    const trigger = document.createElement("button");
    trigger.className = "suggestion-header-btn";
    trigger.id = "suggestion-header-btn";
    trigger.title = "Suggest something";
    trigger.innerHTML = `
      <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M9 18h6M10 22h4M12 2a7 7 0 00-4 12.7c.5.4.8 1 .8 1.6v.7h6.4v-.7c0-.6.3-1.2.8-1.6A7 7 0 0012 2z"></path>
      </svg>
      <span>Suggest</span>
    `;

    let rightGroup = document.querySelector(".topbar-right-group");
    if (!rightGroup) {
      rightGroup = document.createElement("div");
      rightGroup.className = "topbar-right-group";
      profileBtn.parentNode.insertBefore(rightGroup, profileBtn);
      rightGroup.appendChild(profileBtn);
    }
    rightGroup.insertBefore(trigger, rightGroup.firstChild);

    const backdrop = document.createElement("div");
    backdrop.className = "suggestion-backdrop";
    backdrop.id = "suggestion-backdrop";

    const panel = document.createElement("div");
    panel.className = "suggestion-panel";
    panel.id = "suggestion-panel";
    panel.innerHTML = `
      <div class="chat-panel-header">
        <strong>Suggest something</strong>
        <button class="chat-back-btn" onclick="window.__suggestionWidget.close()">&times;</button>
      </div>
      <div class="chat-panel-body" style="padding:16px">
        <textarea id="suggestion-text" class="form-control" rows="4"
          placeholder="What would make this easier to use?" style="resize:vertical;margin-bottom:10px"></textarea>
        <button class="btn btn-primary" id="suggestion-send-btn" style="width:100%;margin-bottom:18px">Send</button>
        <div style="font-size:12px;font-weight:600;color:var(--slate);text-transform:uppercase;letter-spacing:.03em;margin-bottom:8px">Your suggestions</div>
        <div id="suggestion-mine-list"></div>
      </div>
    `;

    document.body.appendChild(backdrop);
    document.body.appendChild(panel);

    trigger.addEventListener("click", open);
    backdrop.addEventListener("click", close);
    document.getElementById("suggestion-send-btn").addEventListener("click", send);

    window.__suggestionWidget = { open, close };
  }

  function open() {
    document.getElementById("suggestion-panel").classList.add("open");
    document.getElementById("suggestion-backdrop").classList.add("open");
    loadMine();
  }

  function close() {
    document.getElementById("suggestion-panel").classList.remove("open");
    document.getElementById("suggestion-backdrop").classList.remove("open");
  }

  async function send() {
    const textarea = document.getElementById("suggestion-text");
    const btn = document.getElementById("suggestion-send-btn");
    const message = textarea.value.trim();
    if (!message) { textarea.focus(); return; }
    btn.disabled = true;
    btn.textContent = "Sending…";
    try {
      await api("POST", "/suggestions", { message });
      textarea.value = "";
      toast("Suggestion sent", "success");
      loadMine();
    } catch (e) {
      toast(e.message, "error");
    } finally {
      btn.disabled = false;
      btn.textContent = "Send";
    }
  }

  const STATUS_LABEL = {
    sent: "Sent", seen: "Seen", in_progress: "In Progress",
    rejected: "Rejected", completed: "Completed",
  };
  const STATUS_CLASS = {
    sent: "badge-grey", seen: "badge-teal", in_progress: "badge-amber",
    rejected: "badge-red", completed: "badge-green",
  };

  async function loadMine() {
    const el = document.getElementById("suggestion-mine-list");
    el.innerHTML = '<p style="color:var(--slate-light);font-size:13px">Loading…</p>';
    try {
      const rows = await api("GET", "/suggestions/mine");
      if (!rows.length) {
        el.innerHTML = '<p style="color:var(--slate-light);font-size:13px">Nothing submitted yet.</p>';
        return;
      }
      el.innerHTML = rows.map(s => `
        <div style="padding:10px 0;border-bottom:1px solid var(--border)">
          <div style="display:flex;justify-content:space-between;align-items:start;gap:8px">
            <span style="font-size:13px">${sanitize(s.message)}</span>
            <span class="badge ${STATUS_CLASS[s.status] || 'badge-grey'}" style="flex-shrink:0">${STATUS_LABEL[s.status] || s.status}</span>
          </div>
          ${s.status === 'rejected' && s.rejection_reason ? `<div style="font-size:12px;color:var(--slate-light);margin-top:4px">${sanitize(s.rejection_reason)}</div>` : ''}
        </div>
      `).join('');
    } catch (e) {
      el.innerHTML = `<p style="color:var(--red,#c0392b);font-size:13px">${e.message}</p>`;
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount);
  } else {
    mount();
  }
})();