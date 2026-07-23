// Shared Admin <-> Staff chat widget.
// Include this on any authenticated staff page after js/api.js.
// Mounts its trigger button in the topbar, between the doctor name
// block and the profile icon. Auto-detects the current user's role:
//   - a single-thread "Chat with Admin" view (doctor/receptionist/nurse/lab/pharmacy)
//   - a "Staff Chats" thread-list view (admin/sub_admin)

(function () {
  const ADMIN_ROLES = ["admin", "sub_admin"];
  const STAFF_ROLES = ["doctor", "receptionist", "nurse", "lab", "pharmacy"];

  let currentThreadStaffId = null; // admin-side: which staff thread is open

  function mount() {
    const doctor = getDoctor();
    if (!doctor || !getToken()) return;
    if (!ADMIN_ROLES.includes(doctor.role) && !STAFF_ROLES.includes(doctor.role)) return;

    const profileBtn = document.querySelector(".topbar-profile-btn");

    const trigger = document.createElement("button");
    trigger.className = "chat-header-btn";
    trigger.id = "chat-header-btn";
    trigger.title = "Chat";
    trigger.innerHTML = `
      <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path>
      </svg>
      <span class="chat-header-badge" id="chat-header-badge">0</span>
    `;

    if (profileBtn && profileBtn.parentNode) {
      profileBtn.parentNode.insertBefore(trigger, profileBtn);
    } else {
      document.body.appendChild(trigger); // fallback if a page's topbar markup differs
    }

    const backdrop = document.createElement("div");
    backdrop.className = "chat-backdrop";
    backdrop.id = "chat-backdrop";

    const panel = document.createElement("div");
    panel.className = "chat-panel";
    panel.id = "chat-panel";
    panel.innerHTML = `
      <div class="chat-panel-header">
        <div style="display:flex;align-items:center;gap:6px">
          <button class="chat-back-btn" id="chat-back-btn" style="display:none">&larr;</button>
          <strong id="chat-panel-title">${ADMIN_ROLES.includes(doctor.role) ? "Staff Chats" : "Chat with Admin"}</strong>
        </div>
        <button class="chat-back-btn" onclick="window.__chatWidget.close()">&times;</button>
      </div>
      <div class="chat-panel-body" id="chat-panel-body"></div>
    `;

    document.body.appendChild(backdrop);
    document.body.appendChild(panel);

    trigger.addEventListener("click", open);
    backdrop.addEventListener("click", close);
    document.getElementById("chat-back-btn").addEventListener("click", () => {
      if (ADMIN_ROLES.includes(doctor.role) && currentThreadStaffId !== null) {
        currentThreadStaffId = null;
        renderAdminThreadList();
      }
    });

    refreshUnreadBadge();
    setInterval(refreshUnreadBadge, 20000);

    window.__chatWidget = { open, close };
  }

  function open() {
    document.getElementById("chat-panel").classList.add("open");
    document.getElementById("chat-backdrop").classList.add("open");
    const doctor = getDoctor();
    if (ADMIN_ROLES.includes(doctor.role)) {
      renderAdminThreadList();
    } else {
      renderStaffThread();
    }
  }

  function close() {
    document.getElementById("chat-panel").classList.remove("open");
    document.getElementById("chat-backdrop").classList.remove("open");
  }

  async function refreshUnreadBadge() {
    try {
      const data = await api("GET", "/chat/unread-count", null, false, true);
      const badge = document.getElementById("chat-header-badge");
      if (!badge || !data) return;
      if (data.unread_count > 0) {
        badge.textContent = data.unread_count > 9 ? "9+" : data.unread_count;
        badge.style.display = "flex";
      } else {
        badge.style.display = "none";
      }
    } catch (e) { /* silent */ }
  }

  function fmtTime(iso) {
    if (!iso) return "";
    return new Date(iso).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", day: "2-digit", month: "short" });
  }

  // ---------- Staff side: single thread with Admin ----------
  async function renderStaffThread() {
    document.getElementById("chat-back-btn").style.display = "none";
    const body = document.getElementById("chat-panel-body");
    body.innerHTML = `
      <div class="chat-messages-wrap" id="chat-messages-wrap"><p style="padding:20px;text-align:center;color:var(--slate);font-size:13px">Loading…</p></div>
      <div class="chat-compose">
        <input type="text" id="chat-input" placeholder="Message admin..." maxlength="2000" />
        <button id="chat-send-btn">Send</button>
      </div>
    `;
    document.getElementById("chat-send-btn").addEventListener("click", sendStaffMessage);
    document.getElementById("chat-input").addEventListener("keydown", (e) => { if (e.key === "Enter") sendStaffMessage(); });

    try {
      const data = await api("GET", "/chat/messages");
      renderMessages(data.messages);
      refreshUnreadBadge();
    } catch (e) {
      document.getElementById("chat-messages-wrap").innerHTML = `<p style="color:var(--danger);text-align:center;font-size:13px">Could not load chat.</p>`;
    }
  }

  async function sendStaffMessage() {
    const input = document.getElementById("chat-input");
    const msg = input.value.trim();
    if (!msg) return;
    input.value = "";
    try {
      await api("POST", "/chat/messages", { message: msg });
      const data = await api("GET", "/chat/messages");
      renderMessages(data.messages);
    } catch (e) {
      toast(e.message || "Could not send message.", "error");
    }
  }

  // ---------- Admin side: thread list + individual thread ----------
  async function renderAdminThreadList() {
    document.getElementById("chat-panel-title").textContent = "Staff Chats";
    document.getElementById("chat-back-btn").style.display = "none";
    const body = document.getElementById("chat-panel-body");
    body.innerHTML = `<p style="padding:20px;text-align:center;color:var(--slate);font-size:13px">Loading…</p>`;
    try {
      const threads = await api("GET", "/chat/threads");
      if (!threads.length) {
        body.innerHTML = `<p style="padding:20px;text-align:center;color:var(--slate);font-size:13px">No staff to chat with yet.</p>`;
        return;
      }
      body.innerHTML = threads.map(t => `
        <div class="chat-thread-item ${t.unread_count > 0 ? 'unread' : ''}" onclick="window.__chatWidgetOpenThread(${t.staff_id})">
          <div>
            <div class="chat-thread-name">${sanitize(t.name)}</div>
            <div class="chat-thread-role">${sanitize(t.role)}</div>
            ${t.last_message ? `<div class="chat-thread-preview">${sanitize(t.last_message)}</div>` : ''}
          </div>
          ${t.unread_count > 0 ? `<span class="chat-thread-unread-dot">${t.unread_count}</span>` : ''}
        </div>
      `).join("");
      refreshUnreadBadge();
    } catch (e) {
      body.innerHTML = `<p style="color:var(--danger);text-align:center;font-size:13px;padding:20px">Could not load chats.</p>`;
    }
  }

  window.__chatWidgetOpenThread = async function (staffId) {
    currentThreadStaffId = staffId;
    document.getElementById("chat-back-btn").style.display = "";
    const body = document.getElementById("chat-panel-body");
    body.innerHTML = `
      <div class="chat-messages-wrap" id="chat-messages-wrap"><p style="padding:20px;text-align:center;color:var(--slate);font-size:13px">Loading…</p></div>
      <div class="chat-compose">
        <input type="text" id="chat-input" placeholder="Type a message..." maxlength="2000" />
        <button id="chat-send-btn">Send</button>
      </div>
    `;
    document.getElementById("chat-send-btn").addEventListener("click", sendAdminMessage);
    document.getElementById("chat-input").addEventListener("keydown", (e) => { if (e.key === "Enter") sendAdminMessage(); });
    try {
      const data = await api("GET", `/chat/threads/${staffId}/messages`);
      document.getElementById("chat-panel-title").textContent = data.staff_name;
      renderMessages(data.messages);
      refreshUnreadBadge();
    } catch (e) {
      document.getElementById("chat-messages-wrap").innerHTML = `<p style="color:var(--danger);text-align:center;font-size:13px">Could not load chat.</p>`;
    }
  };

  async function sendAdminMessage() {
    const input = document.getElementById("chat-input");
    const msg = input.value.trim();
    if (!msg || currentThreadStaffId === null) return;
    input.value = "";
    try {
      await api("POST", `/chat/threads/${currentThreadStaffId}/messages`, { message: msg });
      const data = await api("GET", `/chat/threads/${currentThreadStaffId}/messages`);
      renderMessages(data.messages);
    } catch (e) {
      toast(e.message || "Could not send message.", "error");
    }
  }

  function renderMessages(messages) {
    const wrap = document.getElementById("chat-messages-wrap");
    if (!wrap) return;
    if (!messages.length) {
      wrap.innerHTML = `<p style="text-align:center;color:var(--slate);font-size:13px">No messages yet — say hello.</p>`;
      return;
    }
    wrap.innerHTML = messages.map(m => `
      <div class="chat-bubble ${m.is_mine ? 'mine' : 'theirs'}">
        ${sanitize(m.body)}
        <span class="chat-bubble-time">${fmtTime(m.created_at)}</span>
      </div>
    `).join("");
    wrap.scrollTop = wrap.scrollHeight;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount);
  } else {
    mount();
  }
})();