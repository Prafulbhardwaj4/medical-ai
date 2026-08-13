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

    // List view — the primary screen: navy header, "+ Suggest" top-right,
    // suggestions listed in sequence below. Same visual language as the
    // Super Admin suggestion detail modal (navy header bar, teal accents).
    const listModal = document.createElement("div");
    listModal.className = "modal-overlay";
    listModal.id = "suggestion-list-modal";
    listModal.innerHTML = `
      <div class="modal" style="max-width:600px;max-height:85vh;padding:0;overflow:hidden;display:flex;flex-direction:column">
        <div style="background:var(--navy);color:#fff;padding:18px 22px;display:flex;justify-content:space-between;align-items:center">
          <h2 style="margin:0;font-size:17px">Suggestions</h2>
          <div style="display:flex;align-items:center;gap:10px">
            <button id="suggestion-new-btn" style="background:var(--teal);border:none;color:#fff;padding:6px 12px;border-radius:6px;font-size:13px;font-weight:600;cursor:pointer">+ Suggest</button>
            <button id="suggestion-list-close-btn" style="background:rgba(255,255,255,0.12);border:none;color:#fff;width:26px;height:26px;border-radius:50%;font-size:16px;line-height:1;cursor:pointer">×</button>
          </div>
        </div>
        <div style="padding:16px 22px;overflow-y:auto;flex:1">
          <div style="display:flex;justify-content:flex-end;margin-bottom:10px">
            <select id="suggestion-mine-filter" class="form-control" style="width:auto;font-size:12px;padding:3px 6px" onchange="window.__suggestionWidget.filter(this.value)">
              <option value="">All</option>
              <option value="sent">Sent</option>
              <option value="seen">Seen</option>
              <option value="in_progress">In Progress</option>
              <option value="rejected">Rejected</option>
              <option value="completed">Completed</option>
            </select>
          </div>
          <div id="suggestion-mine-list"></div>
        </div>
      </div>
    `;

    // Compose view — a separate modal reached via "+ Suggest", with its own
    // Back button rather than living inline in the list.
    const composeModal = document.createElement("div");
    composeModal.className = "modal-overlay";
    composeModal.id = "suggestion-compose-modal";
    composeModal.innerHTML = `
      <div class="modal" style="max-width:520px;padding:0;overflow:hidden">
        <div style="background:var(--navy);color:#fff;padding:18px 22px;display:flex;align-items:center;gap:12px">
          <button id="suggestion-back-btn" style="background:rgba(255,255,255,0.12);border:none;color:#fff;width:28px;height:28px;border-radius:50%;font-size:16px;cursor:pointer">←</button>
          <h2 style="margin:0;font-size:17px" id="suggestion-compose-title">New Suggestion</h2>
        </div>
        <div style="padding:20px 22px">
          <textarea id="suggestion-text" class="form-control" rows="5"
            placeholder="What would make this easier to use?" style="resize:vertical;margin-bottom:14px"></textarea>
          <button class="btn btn-primary" id="suggestion-send-btn" style="width:100%;background:var(--teal);border-color:var(--teal)">Send</button>
        </div>
      </div>
    `;

    document.body.appendChild(listModal);
    document.body.appendChild(composeModal);

    trigger.addEventListener("click", open);
    listModal.addEventListener("click", (e) => { if (e.target === listModal) close(); });
    composeModal.addEventListener("click", (e) => { if (e.target === composeModal) closeCompose(); });
    document.getElementById("suggestion-list-close-btn").addEventListener("click", close);
    document.getElementById("suggestion-new-btn").addEventListener("click", () => openCompose());
    document.getElementById("suggestion-back-btn").addEventListener("click", closeCompose);
    document.getElementById("suggestion-send-btn").addEventListener("click", send);

    window.__suggestionWidget = { open, close, edit, followUp, toggleThread, sendThreadReply, filter };
  }

  function open() {
    document.getElementById("suggestion-list-modal").classList.add("open");
    loadMine();
  }

  function close() {
    document.getElementById("suggestion-list-modal").classList.remove("open");
  }

  function openCompose(editingId) {
    const textarea = document.getElementById("suggestion-text");
    const btn = document.getElementById("suggestion-send-btn");
    const title = document.getElementById("suggestion-compose-title");
    if (editingId) {
      const row = mineCache.find(s => s.id === editingId);
      textarea.value = row ? row.message : "";
      btn.textContent = "Save Edit";
      btn.dataset.editingId = editingId;
      title.textContent = "Edit Suggestion";
    } else {
      textarea.value = "";
      btn.textContent = "Send";
      delete btn.dataset.editingId;
      title.textContent = "New Suggestion";
    }
    document.getElementById("suggestion-list-modal").classList.remove("open");
    document.getElementById("suggestion-compose-modal").classList.add("open");
    textarea.focus();
  }

  function closeCompose() {
    document.getElementById("suggestion-compose-modal").classList.remove("open");
    document.getElementById("suggestion-list-modal").classList.add("open");
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
      closeCompose();
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
  let mineFilter = "";

  function filter(status) {
    mineFilter = status;
    renderMine();
  }

  async function loadMine() {
    const el = document.getElementById("suggestion-mine-list");
    el.innerHTML = '<p style="color:var(--slate-light);font-size:13px">Loading…</p>';
    try {
      mineCache = await api("GET", "/suggestions/mine");
      renderMine();
    } catch (e) {
      el.innerHTML = `<p style="color:var(--red,#c0392b);font-size:13px">${e.message}</p>`;
    }
  }

  function renderMine() {
    const el = document.getElementById("suggestion-mine-list");
    const rows = mineFilter ? mineCache.filter(s => s.status === mineFilter) : mineCache;
    if (!mineCache.length) {
      el.innerHTML = '<p style="color:var(--slate-light);font-size:13px">Nothing submitted yet.</p>';
      return;
    }
    if (!rows.length) {
      el.innerHTML = '<p style="color:var(--slate-light);font-size:13px">Nothing with this status.</p>';
      return;
    }
    const isTerminal = s => s.status === "completed" || s.status === "rejected";
    const pillBtnStyle = "font-size:12px;padding:4px 10px;border-radius:20px;border:1px solid var(--teal);color:var(--teal);background:#fff;cursor:pointer";
    el.innerHTML = rows.map(s => `
      <div style="padding:12px;margin-bottom:10px;border:1px solid var(--border);border-radius:var(--radius-lg,10px)" id="sugg-row-${s.id}">
        <div style="display:flex;justify-content:space-between;align-items:start;gap:8px">
          <span style="font-size:13px" id="sugg-text-${s.id}">${sanitize(s.message)}</span>
          <span class="badge ${STATUS_CLASS[s.status] || 'badge-grey'}" style="flex-shrink:0">${STATUS_LABEL[s.status] || s.status}</span>
        </div>
        ${s.status === 'rejected' && s.rejection_reason ? `<div style="font-size:12px;color:var(--slate-light);margin-top:4px;background:#fef2f2;border-radius:6px;padding:6px 8px">${sanitize(s.rejection_reason)}</div>` : ''}
        ${isTerminal(s) ? '' : `
          <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap">
            <button style="${pillBtnStyle}" onclick="window.__suggestionWidget.edit(${s.id})">Edit</button>
            <button style="${pillBtnStyle}" onclick="window.__suggestionWidget.toggleThread(${s.id})">💬 Conversation</button>
            ${s.can_follow_up ? `<button style="${pillBtnStyle}" onclick="window.__suggestionWidget.followUp(${s.id})">${s.follow_up_requested_at ? 'Follow up again' : 'Follow Up'}</button>` : ''}
            ${s.follow_up_requested_at ? `<span style="font-size:12px;color:var(--slate-light);align-self:center">Followed up ✓</span>` : ''}
          </div>
          <div id="sugg-thread-${s.id}" style="display:none;margin-top:8px"></div>
        `}
      </div>
    `).join('');
  }

  function edit(id) {
    const row = mineCache.find(s => s.id === id);
    if (!row) return;
    if (!row.can_edit) {
      toast("This one is already in progress and cannot be changed — you can send another suggestion.", "error");
      return;
    }
    openCompose(id);
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
              <div style="display:inline-block;max-width:85%;padding:5px 9px;border-radius:10px;font-size:12.5px;background:${r.sender === 'staff' ? 'var(--teal)' : 'var(--white)'};color:${r.sender === 'staff' ? '#fff' : 'var(--navy)'};border:${r.sender === 'staff' ? 'none' : '1px solid var(--border)'}">
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