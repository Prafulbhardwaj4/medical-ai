// Shared "Forgot password?" component for staff (Doctor-model) accounts —
// works identically for every role (doctor, nurse, receptionist, admin,
// lab, pharmacy, sub_admin, etc.) since they all authenticate through the
// same /auth endpoints. Self-contained: injects its own modal markup,
// reuses the site's .modal-overlay/.modal CSS, and reuses the shared
// renderPasswordStrength() from api.js. Include this script on any page
// that needs a "Forgot password?" entry point (currently just login.html)
// and call openForgotPasswordModal() from a link/button.

(function () {
  let fpCaptchaToken = null;
  let fpEmail = null;
  let fpResetToken = null;

  function injectModal() {
    if (document.getElementById("fp-modal-overlay")) return;
    const div = document.createElement("div");
    div.innerHTML = `
      <div class="modal-overlay" id="fp-modal-overlay">
        <div class="modal">
          <div class="modal-header">
            <div style="font-weight:600;font-size:1.05rem">Reset your password</div>
            <div class="modal-close" onclick="closeForgotPasswordModal()">✕</div>
          </div>

          <div id="fp-step-email">
            <div class="form-group">
              <label class="form-label">Email</label>
              <input class="form-control" id="fp-email" type="email" placeholder="you@hospital.com" />
            </div>
            <div class="form-group" id="fp-captcha-group">
              <label class="form-label" id="fp-captcha-question">Loading captcha…</label>
              <div style="display:flex;gap:8px;align-items:center">
                <input class="form-control" id="fp-captcha-answer" type="text" inputmode="numeric" placeholder="Your answer" />
                <span onclick="fpLoadCaptcha()" style="cursor:pointer;font-size:20px;padding:0 4px" title="Get a new question">🔄</span>
              </div>
            </div>
            <div class="err-msg" id="fp-email-err"></div>
            <button class="btn btn-primary btn-lg" style="width:100%;margin-top:8px" id="fp-btn-send" onclick="fpRequestOtp()">
              Send OTP on WhatsApp
            </button>
          </div>

          <div id="fp-step-otp" style="display:none">
            <p style="color:var(--slate);font-size:13px;margin-bottom:16px">Enter the OTP sent to the phone number on this account.</p>
            <div class="form-group">
              <label class="form-label">OTP</label>
              <input class="form-control" id="fp-otp" type="text" inputmode="numeric" placeholder="4-digit code" />
            </div>
            <div class="err-msg" id="fp-otp-err"></div>
            <button class="btn btn-primary btn-lg" style="width:100%;margin-top:8px" id="fp-btn-verify" onclick="fpVerifyOtp()">
              Verify OTP
            </button>
          </div>

          <div id="fp-step-newpw" style="display:none">
            <div class="form-group">
              <label class="form-label">New Password</label>
              <input class="form-control" id="fp-new-password" type="password" placeholder="At least 8 characters"
                oninput="renderPasswordStrength(this.value, 'fp-pw')" />
              <ul style="list-style:none;padding:0;margin:8px 0 0;font-size:12.5px">
                <li id="fp-pw-check-length" style="color:var(--slate-light)">○ At least 8 characters</li>
                <li id="fp-pw-check-number" style="color:var(--slate-light)">○ At least 1 number</li>
                <li id="fp-pw-check-upper" style="color:var(--slate-light)">○ At least 1 capital letter</li>
              </ul>
            </div>
            <div class="form-group">
              <label class="form-label">Confirm Password</label>
              <input class="form-control" id="fp-new-password-confirm" type="password" placeholder="Re-enter password" />
            </div>
            <div class="err-msg" id="fp-newpw-err"></div>
            <button class="btn btn-primary btn-lg" style="width:100%;margin-top:8px" id="fp-btn-setpw" onclick="fpSetNewPassword()">
              Set Password &amp; Sign In
            </button>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(div.firstElementChild);
  }

  window.openForgotPasswordModal = function () {
    injectModal();
    document.getElementById("fp-modal-overlay").classList.add("open");
    document.getElementById("fp-step-email").style.display = "block";
    document.getElementById("fp-step-otp").style.display = "none";
    document.getElementById("fp-step-newpw").style.display = "none";
    document.getElementById("fp-email").value = "";
    document.getElementById("fp-email-err").textContent = "";
    fpLoadCaptcha();
  };

  window.closeForgotPasswordModal = function () {
    const overlay = document.getElementById("fp-modal-overlay");
    if (overlay) overlay.classList.remove("open");
    fpCaptchaToken = null; fpEmail = null; fpResetToken = null;
  };

  window.fpLoadCaptcha = async function () {
    const q = document.getElementById("fp-captcha-question");
    const answerInput = document.getElementById("fp-captcha-answer");
    q.textContent = "Loading captcha…";
    answerInput.value = "";
    try {
      const res = await fetch(`${BASE}/auth/captcha`);
      const json = await res.json();
      q.textContent = json.question;
      fpCaptchaToken = json.token;
    } catch (e) {
      q.textContent = "Couldn't load captcha — tap 🔄 to retry";
      fpCaptchaToken = null;
    }
  };

  window.fpRequestOtp = async function () {
    const err = document.getElementById("fp-email-err");
    const btn = document.getElementById("fp-btn-send");
    err.textContent = "";

    const email = document.getElementById("fp-email").value.trim();
    const captchaAnswer = document.getElementById("fp-captcha-answer").value.trim();
    if (!email) { err.textContent = "Enter your email."; return; }
    if (!fpCaptchaToken || !captchaAnswer) { err.textContent = "Please answer the captcha question."; return; }

    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span>';
    try {
      const res = await fetch(`${BASE}/auth/forgot-password/request`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, captcha_token: fpCaptchaToken, captcha_answer: captchaAnswer })
      });
      const json = await res.json();
      if (!res.ok) {
        if (json.detail && json.detail.toLowerCase().includes("captcha")) fpLoadCaptcha();
        throw new Error(json.detail || "Could not send OTP");
      }
      fpEmail = email;
      document.getElementById("fp-step-email").style.display = "none";
      document.getElementById("fp-step-otp").style.display = "block";
      document.getElementById("fp-otp").value = "";
      document.getElementById("fp-otp-err").textContent = "";
    } catch (e) {
      err.textContent = e.message;
    } finally {
      btn.disabled = false;
      btn.textContent = "Send OTP on WhatsApp";
    }
  };

  window.fpVerifyOtp = async function () {
    const err = document.getElementById("fp-otp-err");
    const btn = document.getElementById("fp-btn-verify");
    err.textContent = "";

    const otp = document.getElementById("fp-otp").value.trim();
    if (!otp) { err.textContent = "Enter the OTP."; return; }

    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span>';
    try {
      const res = await fetch(`${BASE}/auth/forgot-password/verify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: fpEmail, otp })
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail || "Incorrect OTP");
      fpResetToken = json.reset_token;
      document.getElementById("fp-step-otp").style.display = "none";
      document.getElementById("fp-step-newpw").style.display = "block";
    } catch (e) {
      err.textContent = e.message;
    } finally {
      btn.disabled = false;
      btn.textContent = "Verify OTP";
    }
  };

  window.fpSetNewPassword = async function () {
    const err = document.getElementById("fp-newpw-err");
    const btn = document.getElementById("fp-btn-setpw");
    err.textContent = "";

    const pw = document.getElementById("fp-new-password").value;
    const cpw = document.getElementById("fp-new-password-confirm").value;
    if (pw.length < 8 || !/\d/.test(pw) || !/[A-Z]/.test(pw)) {
      err.textContent = "Password must be at least 8 characters, with 1 number and 1 capital letter.";
      return;
    }
    if (pw !== cpw) { err.textContent = "Passwords do not match."; return; }

    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span>';
    try {
      const res = await fetch(`${BASE}/auth/reset-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reset_token: fpResetToken, new_password: pw })
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail || "Could not reset password");
      closeForgotPasswordModal();
      saveSession(json.access_token, json.doctor);
      redirectByRole(json.doctor.role);
    } catch (e) {
      err.textContent = e.message;
      btn.disabled = false;
      btn.textContent = "Set Password & Sign In";
    }
  };
})();