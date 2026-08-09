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

    window.__suggestionWidget = { open, close, edit, followUp, toggleThread, sendThreadReply };
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
    const editingId = btn.dataset.editingId;
    btn.disabled = true;
    btn.textContent = editingId ? "Saving…" : "Sending…";
    try {
      if (editingId) {
        await api("PATCH", `/suggestions/${editingId}`, { message });
        toast("Suggestion updated", "success");
        delete btn.dataset.editingId;
      } else {
        await api("POST", "/suggestions", { message });
        toast("Suggestion sent", "success");
      }
      textarea.value = "";
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

  let mineCache = [];

  async function loadMine() {
    const el = document.getElementById("suggestion-mine-list");
    el.innerHTML = '<p style="color:var(--slate-light);font-size:13px">Loading…</p>';
    try {
      const rows = await api("GET", "/suggestions/mine");
      mineCache = rows;
      if (!rows.length) {
        el.innerHTML = '<p style="color:var(--slate-light);font-size:13px">Nothing submitted yet.</p>';
        return;
      }
      el.innerHTML = rows.map(s => `
        <div style="padding:10px 0;border-bottom:1px solid var(--border)" id="sugg-row-${s.id}">
          <div style="display:flex;justify-content:space-between;align-items:start;gap:8px">
            <span style="font-size:13px" id="sugg-text-${s.id}">${sanitize(s.message)}</span>
            <span class="badge ${STATUS_CLASS[s.status] || 'badge-grey'}" style="flex-shrink:0">${STATUS_LABEL[s.status] || s.status}</span>
          </div>
          ${s.status === 'rejected' && s.rejection_reason ? `<div style="font-size:12px;color:var(--slate-light);margin-top:4px">${sanitize(s.rejection_reason)}</div>` : ''}
          <div style="margin-top:6px;display:flex;gap:12px">
            <a href="javascript:void(0)" style="font-size:12px" onclick="window.__suggestionWidget.edit(${s.id})">Edit</a>
            <a href="javascript:void(0)" style="font-size:12px" onclick="window.__suggestionWidget.toggleThread(${s.id})">💬 Conversation</a>
            ${s.can_follow_up ? `<a href="javascript:void(0)" style="font-size:12px" onclick="window.__suggestionWidget.followUp(${s.id})">${s.follow_up_requested_at ? 'Follow up again' : 'Follow Up'}</a>` : ''}
            ${s.follow_up_requested_at ? `<span style="font-size:12px;color:var(--slate-light)">Followed up ✓</span>` : ''}
          </div>
          <div id="sugg-thread-${s.id}" style="display:none;margin-top:8px"></div>
        </div>
      `).join('');
    } catch (e) {
      el.innerHTML = `<p style="color:var(--red,#c0392b);font-size:13px">${e.message}</p>`;
    }
  }

  function edit(id) {
    const row = mineCache.find(s => s.id === id);
    if (!row) return;
    if (!row.can_edit) {
      toast("This one is already in progress and cannot be changed — you can send another suggestion.", "error");
      return;
    }
    const textarea = document.getElementById("suggestion-text");
    const btn = document.getElementById("suggestion-send-btn");
    textarea.value = row.message;
    textarea.focus();
    btn.textContent = "Save Edit";
    btn.dataset.editingId = id;
    document.getElementById("suggestion-panel").scrollTop = 0;
  }

  async function followUp(id) {
    try {
      await api("POST", `/suggestions/${id}/follow-up`);
      toast("Follow-up sent", "success");
      loadMine();
    } catch (e) { toast(e.message, "error"); }
  }

  const openThreads = new Set();

  async function toggleThread(id) {
    const box = document.getElementById(`sugg-thread-${id}`);
    if (!box) return;
    if (openThreads.has(id)) {
      openThreads.delete(id);
      box.style.display = "none";
      return;
    }
    openThreads.add(id);
    box.style.display = "block";
    await loadThread(id);
  }

  async function loadThread(id) {
    const box = document.getElementById(`sugg-thread-${id}`);
    if (!box) return;
    box.innerHTML = '<p style="color:var(--slate-light);font-size:12px">Loading…</p>';
    try {
      const rows = await api("GET", `/suggestions/${id}/replies`);
      const listHtml = rows.length
        ? rows.map(r => `
            <div style="margin-bottom:6px;text-align:${r.sender === 'staff' ? 'right' : 'left'}">
              <div style="display:inline-block;max-width:85%;padding:5px 9px;border-radius:8px;font-size:12.5px;background:${r.sender === 'staff' ? 'var(--primary,#0f766e)' : 'var(--bg-light,#f1f5f9)'};color:${r.sender === 'staff' ? '#fff' : 'inherit'}">
                ${sanitize(r.message)}
              </div>
              <div style="font-size:10px;color:var(--slate-light)">${r.sender === 'staff' ? 'You' : 'Super Admin'}</div>
            </div>
          `).join('')
        : '<p style="color:var(--slate-light);font-size:12px">No questions yet.</p>';
      box.innerHTML = `
        <div style="max-height:160px;overflow-y:auto;border:1px solid var(--border);border-radius:6px;padding:8px;margin-bottom:6px">${listHtml}</div>
        <div style="display:flex;gap:6px">
          <input class="form-control" id="sugg-thread-input-${id}" placeholder="Reply…" style="font-size:12.5px;padding:6px 8px" />
          <button class="btn btn-primary btn-sm" onclick="window.__suggestionWidget.sendThreadReply(${id})">Send</button>
        </div>
      `;
    } catch (e) {
      box.innerHTML = `<p style="color:var(--red,#c0392b);font-size:12px">${e.message}</p>`;
    }
  }

  async function sendThreadReply(id) {
    const input = document.getElementById(`sugg-thread-input-${id}`);
    const message = input.value.trim();
    if (!message) return;
    try {
      await api("POST", `/suggestions/${id}/replies`, { message });
      input.value = "";
      loadThread(id);
    } catch (e) { toast(e.message, "error"); }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount);
  } else {
    mount();
  }
})();