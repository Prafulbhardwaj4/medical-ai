// Shared Admin <-> Staff chat widget.
// Include this on any authenticated staff page after js/api.js.
// Mounts its trigger button in the topbar, between the doctor name
// block and the profile icon. Auto-detects the current user's role:
//   - a single-thread "Chat with Admin" view (doctor/receptionist/nurse/lab/pharmacy)
//   - a "Staff Chats" thread-list view (admin/sub_admin)

(function () {
  const ADMIN_ROLES = ["admin", "sub_admin"];
  const STAFF_ROLES = ["doctor", "receptionist", "nurse", "assistant", "lab", "pharmacy"];

  let currentThreadStaffId = null; // admin-side: which staff thread is open
  let staffChatTab = "admin"; // staff-side: "admin" or "colleagues"
  let currentPeerId = null;   // staff-side: which colleague thread is open

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
      const rightGroup = document.createElement("div");
      rightGroup.className = "topbar-right-group";
      profileBtn.parentNode.insertBefore(rightGroup, profileBtn);
      rightGroup.appendChild(trigger);
      rightGroup.appendChild(profileBtn);
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
          <strong id="chat-panel-title">${ADMIN_ROLES.includes(doctor.role) ? "Staff Chats" : "Chat"}</strong>
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
      } else if (STAFF_ROLES.includes(doctor.role) && currentPeerId !== null) {
        currentPeerId = null;
        document.getElementById("chat-back-btn").style.display = "none";
        document.getElementById("chat-panel-title").textContent = "Chat";
        renderStaffColleaguesList();
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

  function fmtThreadTime(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    const now = new Date();
    const sameDay = d.toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata" }) === now.toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata" });
    return sameDay
      ? d.toLocaleString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit" })
      : d.toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short" });
  }

  function iconAttach() {
    return `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"></path></svg>`;
  }

  async function pickAndSendAttachment(sendFn) {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/*,.pdf,.doc,.docx";
    input.style.display = "none";
    document.body.appendChild(input);
    input.addEventListener("change", async () => {
      const file = input.files[0];
      document.body.removeChild(input);
      if (!file) return;
      if (file.size > 10 * 1024 * 1024) { toast("File is too large (10MB max)", "error"); return; }
      try {
        const fd = new FormData();
        fd.append("file", file);
        const uploaded = await api("POST", "/chat/upload", fd, true);
        await sendFn(uploaded);
      } catch (e) {
        toast(e.message || "Could not upload file.", "error");
      }
    });
    input.click();
  }

  async function loadAuthImage(url, imgEl) {
    try {
      const res = await fetch(BASE + url, { headers: { Authorization: `Bearer ${getToken()}` } });
      if (!res.ok) return;
      const blob = await res.blob();
      imgEl.src = window.URL.createObjectURL(blob);
    } catch (e) { /* silent */ }
  }

  // ---------- Staff side: "Admin" tab + "Colleagues" tab ----------
  function renderStaffThread() {
    currentPeerId = null;
    document.getElementById("chat-back-btn").style.display = "none";
    document.getElementById("chat-panel-title").textContent = "Chat";
    const body = document.getElementById("chat-panel-body");
    body.innerHTML = `
      <div class="chat-filter-tabs">
        <button class="chat-filter-tab ${staffChatTab === 'admin' ? 'active' : ''}" data-tab="admin">Admin</button>
        <button class="chat-filter-tab ${staffChatTab === 'colleagues' ? 'active' : ''}" data-tab="colleagues">Colleagues</button>
      </div>
      <div id="chat-staff-tab-body"></div>
    `;
    body.querySelectorAll(".chat-filter-tab").forEach(btn => {
      btn.addEventListener("click", () => {
        staffChatTab = btn.dataset.tab;
        body.querySelectorAll(".chat-filter-tab").forEach(b => b.classList.toggle("active", b === btn));
        renderStaffTabBody();
      });
    });
    renderStaffTabBody();
  }

  function renderStaffTabBody() {
    if (staffChatTab === "admin") renderStaffAdminSubTab();
    else renderStaffColleaguesList();
  }

  async function renderStaffAdminSubTab() {
    const tabBody = document.getElementById("chat-staff-tab-body");
    tabBody.innerHTML = `
      <div class="chat-messages-wrap" id="chat-messages-wrap"><p style="padding:20px;text-align:center;color:var(--slate);font-size:13px">Loading…</p></div>
      <div class="chat-compose">
        <button class="chat-compose-file-btn" id="chat-file-btn" type="button" title="Attach file">${iconAttach()}</button>
        <input type="text" id="chat-input" placeholder="Message admin..." maxlength="2000" />
        <button id="chat-send-btn">Send</button>
      </div>
    `;
    document.getElementById("chat-send-btn").addEventListener("click", sendStaffMessage);
    document.getElementById("chat-input").addEventListener("keydown", (e) => { if (e.key === "Enter") sendStaffMessage(); });
    document.getElementById("chat-file-btn").addEventListener("click", () => pickAndSendAttachment(sendStaffAttachment));

    try {
      const data = await api("GET", "/chat/messages");
      renderMessages(data.messages);
      refreshUnreadBadge();
    } catch (e) {
      document.getElementById("chat-messages-wrap").innerHTML = `<p style="color:var(--danger);text-align:center;font-size:13px">Could not load chat.</p>`;
    }
  }

  async function renderStaffColleaguesList() {
    const tabBody = document.getElementById("chat-staff-tab-body");
    tabBody.innerHTML = `<div class="chat-thread-list" id="chat-thread-list"><p style="padding:20px;text-align:center;color:var(--slate);font-size:13px">Loading…</p></div>`;
    try {
      threadsCache = await api("GET", "/chat/staff-directory");
      const list = document.getElementById("chat-thread-list");
      if (!threadsCache.length) {
        list.innerHTML = `<p style="padding:20px;text-align:center;color:var(--slate);font-size:13px">No other staff to chat with yet.</p>`;
        return;
      }
      list.innerHTML = threadsCache.map(t => `
        <div class="chat-thread-item ${t.unread_count > 0 ? 'unread' : ''}" onclick="window.__chatWidgetOpenPeer(${t.staff_id})">
          <div class="chat-thread-avatar">${threadInitials(t.name)}</div>
          <div class="chat-thread-info">
            <div class="chat-thread-name">${sanitize(t.name)} <span class="chat-thread-role">${sanitize(t.role)}</span></div>
            ${t.last_message ? `<div class="chat-thread-preview">${sanitize(t.last_message)}</div>` : ''}
          </div>
          <div class="chat-thread-side">
            ${t.last_message_at ? `<span class="chat-thread-time">${fmtThreadTime(t.last_message_at)}</span>` : ''}
            ${t.unread_count > 0 ? `<span class="chat-thread-unread-dot">${t.unread_count}</span>` : ''}
          </div>
        </div>
      `).join("");
      refreshUnreadBadge();
    } catch (e) {
      document.getElementById("chat-thread-list").innerHTML = `<p style="color:var(--danger);text-align:center;font-size:13px;padding:20px">Could not load colleagues.</p>`;
    }
  }

  window.__chatWidgetOpenPeer = async function (peerId) {
    currentPeerId = peerId;
    document.getElementById("chat-back-btn").style.display = "";
    const tabBody = document.getElementById("chat-staff-tab-body");
    tabBody.innerHTML = `
      <div class="chat-messages-wrap" id="chat-messages-wrap"><p style="padding:20px;text-align:center;color:var(--slate);font-size:13px">Loading…</p></div>
      <div class="chat-compose">
        <button class="chat-compose-file-btn" id="chat-file-btn" type="button" title="Attach file">${iconAttach()}</button>
        <input type="text" id="chat-input" placeholder="Type a message..." maxlength="2000" />
        <button id="chat-send-btn">Send</button>
      </div>
    `;
    document.getElementById("chat-send-btn").addEventListener("click", sendPeerMessage);
    document.getElementById("chat-input").addEventListener("keydown", (e) => { if (e.key === "Enter") sendPeerMessage(); });
    document.getElementById("chat-file-btn").addEventListener("click", () => pickAndSendAttachment(sendPeerAttachment));
    try {
      const data = await api("GET", `/chat/peer/${peerId}/messages`);
      document.getElementById("chat-panel-title").textContent = data.staff_name;
      renderMessages(data.messages);
      refreshUnreadBadge();
    } catch (e) {
      document.getElementById("chat-messages-wrap").innerHTML = `<p style="color:var(--danger);text-align:center;font-size:13px">Could not load chat.</p>`;
    }
  };

  async function sendPeerMessage() {
    const input = document.getElementById("chat-input");
    const msg = input.value.trim();
    if (!msg || currentPeerId === null) return;
    input.value = "";
    try {
      await api("POST", `/chat/peer/${currentPeerId}/messages`, { message: msg });
      const data = await api("GET", `/chat/peer/${currentPeerId}/messages`);
      renderMessages(data.messages);
    } catch (e) {
      toast(e.message || "Could not send message.", "error");
    }
  }

  async function sendPeerAttachment(uploaded) {
    if (currentPeerId === null) return;
    try {
      await api("POST", `/chat/peer/${currentPeerId}/messages`, { message: "", attachment_filename: uploaded.attachment_filename, attachment_name: uploaded.attachment_name, attachment_type: uploaded.attachment_type });
      const data = await api("GET", `/chat/peer/${currentPeerId}/messages`);
      renderMessages(data.messages);
    } catch (e) {
      toast(e.message || "Could not send file.", "error");
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

  async function sendStaffAttachment(uploaded) {
    try {
      await api("POST", "/chat/messages", { message: "", attachment_filename: uploaded.attachment_filename, attachment_name: uploaded.attachment_name, attachment_type: uploaded.attachment_type });
      const data = await api("GET", "/chat/messages");
      renderMessages(data.messages);
    } catch (e) {
      toast(e.message || "Could not send file.", "error");
    }
  }

  // ---------- Admin side: thread list + individual thread ----------
  let threadsCache = [];
  let threadFilter = "all";
  let threadSearchTerm = "";

  function threadInitials(name) {
    return (name || "").trim().split(/\s+/).slice(0, 2).map(w => w[0]?.toUpperCase() || "").join("");
  }

  async function renderAdminThreadList() {
    document.getElementById("chat-panel-title").textContent = "Staff Chats";
    document.getElementById("chat-back-btn").style.display = "none";
    const body = document.getElementById("chat-panel-body");
    body.innerHTML = `
      <div class="chat-search-bar"><input type="text" id="chat-thread-search" placeholder="Search staff..." /></div>
      <div class="chat-filter-tabs">
        <button class="chat-filter-tab active" data-filter="all">All</button>
        <button class="chat-filter-tab" data-filter="unread">Unread</button>
      </div>
      <div class="chat-thread-list" id="chat-thread-list"><p style="padding:20px;text-align:center;color:var(--slate);font-size:13px">Loading…</p></div>
    `;
    document.getElementById("chat-thread-search").addEventListener("input", (e) => {
      threadSearchTerm = e.target.value.trim().toLowerCase();
      renderThreadListFiltered();
    });
    body.querySelectorAll(".chat-filter-tab").forEach(btn => {
      btn.addEventListener("click", () => {
        threadFilter = btn.dataset.filter;
        body.querySelectorAll(".chat-filter-tab").forEach(b => b.classList.toggle("active", b === btn));
        renderThreadListFiltered();
      });
    });
    try {
      threadsCache = await api("GET", "/chat/threads");
      renderThreadListFiltered();
      refreshUnreadBadge();
    } catch (e) {
      document.getElementById("chat-thread-list").innerHTML = `<p style="color:var(--danger);text-align:center;font-size:13px;padding:20px">Could not load chats.</p>`;
    }
  }

  function renderThreadListFiltered() {
    const list = document.getElementById("chat-thread-list");
    if (!list) return;
    let threads = threadsCache;
    if (threadFilter === "unread") threads = threads.filter(t => t.unread_count > 0);
    if (threadSearchTerm) threads = threads.filter(t => t.name.toLowerCase().includes(threadSearchTerm) || t.role.toLowerCase().includes(threadSearchTerm));
    if (!threads.length) {
      list.innerHTML = `<p style="padding:20px;text-align:center;color:var(--slate);font-size:13px">${threadsCache.length ? 'No matching staff.' : 'No staff to chat with yet.'}</p>`;
      return;
    }
    list.innerHTML = threads.map(t => `
      <div class="chat-thread-item ${t.unread_count > 0 ? 'unread' : ''}" onclick="window.__chatWidgetOpenThread(${t.staff_id})">
        <div class="chat-thread-avatar">${threadInitials(t.name)}</div>
        <div class="chat-thread-info">
          <div class="chat-thread-name">${sanitize(t.name)} <span class="chat-thread-role">${sanitize(t.role)}</span></div>
          ${t.last_message ? `<div class="chat-thread-preview">${sanitize(t.last_message)}</div>` : ''}
        </div>
        <div class="chat-thread-side">
          ${t.last_message_at ? `<span class="chat-thread-time">${fmtThreadTime(t.last_message_at)}</span>` : ''}
          ${t.unread_count > 0 ? `<span class="chat-thread-unread-dot">${t.unread_count}</span>` : ''}
        </div>
      </div>
    `).join("");
  }

  window.__chatWidgetOpenThread = async function (staffId) {
    currentThreadStaffId = staffId;
    document.getElementById("chat-back-btn").style.display = "";
    const body = document.getElementById("chat-panel-body");
    body.innerHTML = `
      <div class="chat-messages-wrap" id="chat-messages-wrap"><p style="padding:20px;text-align:center;color:var(--slate);font-size:13px">Loading…</p></div>
      <div class="chat-compose">
        <button class="chat-compose-file-btn" id="chat-file-btn" type="button" title="Attach file">${iconAttach()}</button>
        <input type="text" id="chat-input" placeholder="Type a message..." maxlength="2000" />
        <button id="chat-send-btn">Send</button>
      </div>
    `;
    document.getElementById("chat-send-btn").addEventListener("click", sendAdminMessage);
    document.getElementById("chat-input").addEventListener("keydown", (e) => { if (e.key === "Enter") sendAdminMessage(); });
    document.getElementById("chat-file-btn").addEventListener("click", () => pickAndSendAttachment(sendAdminAttachment));
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

  async function sendAdminAttachment(uploaded) {
    if (currentThreadStaffId === null) return;
    try {
      await api("POST", `/chat/threads/${currentThreadStaffId}/messages`, { message: "", attachment_filename: uploaded.attachment_filename, attachment_name: uploaded.attachment_name, attachment_type: uploaded.attachment_type });
      const data = await api("GET", `/chat/threads/${currentThreadStaffId}/messages`);
      renderMessages(data.messages);
    } catch (e) {
      toast(e.message || "Could not send file.", "error");
    }
  }

  function renderAttachment(m) {
    if (!m.attachment_url) return "";
    if (m.attachment_type === "image") {
      return `<img class="chat-attachment-img" data-attach-url="${m.attachment_url}" alt="${sanitize(m.attachment_name || 'attachment')}" />`;
    }
    return `<a class="chat-attachment" href="#" onclick="downloadFile('${m.attachment_url}', '${(m.attachment_name || 'file').replace(/'/g, "\\'")}');return false;">📎 ${sanitize(m.attachment_name || 'file')}</a>`;
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
        ${renderAttachment(m)}
        ${m.body ? sanitize(m.body) : ""}
        <span class="chat-bubble-time">${fmtTime(m.created_at)}</span>
      </div>
    `).join("");
    wrap.scrollTop = wrap.scrollHeight;
    wrap.querySelectorAll("img[data-attach-url]").forEach(img => loadAuthImage(img.dataset.attachUrl, img));
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount);
  } else {
    mount();
  }
})();