// Shared "Forgot password?" component — works for BOTH staff (Doctor-model,
// email-based, /auth/*) and patients (PatientAccount, phone-based,
// /portal/auth/*). Identifier type is auto-detected (isEmail/isPhone, from
// login.html's inline script — loaded before this deferred script runs).
// Self-contained: injects its own modal markup, reuses the site's
// .modal-overlay/.modal CSS, and reuses renderPasswordStrength() /
// togglePwVisibility() from api.js. Include this script on any page that
// needs a "Forgot password?" entry point and call openForgotPasswordModal().

(function () {
  let fpCaptchaToken = null;
  let fpIdentifier = null;   // the raw email or phone the user typed
  let fpIsEmail = null;      // true = staff/email path, false = patient/phone path
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

          <div id="fp-step-identifier">
            <div class="form-group">
              <label class="form-label">Email or Phone Number</label>
              <input class="form-control" id="fp-identifier" type="text" placeholder="you@hospital.com or 10-digit phone" />
            </div>
            <div class="form-group" id="fp-captcha-group">
              <label class="form-label">Enter the code shown below</label>
              <div id="fp-captcha-image-box" style="margin-bottom:8px;line-height:0">Loading captcha…</div>
              <div style="display:flex;gap:8px;align-items:center">
                <input class="form-control" id="fp-captcha-answer" type="text" autocapitalize="characters" placeholder="Type the code" />
                <span onclick="fpLoadCaptcha()" style="cursor:pointer;font-size:20px;padding:0 4px" title="Get a new code">🔄</span>
              </div>
            </div>
            <div class="err-msg" id="fp-identifier-err"></div>
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
              <div style="position:relative">
                <input class="form-control" id="fp-new-password" type="password" placeholder="At least 8 characters"
                  style="padding-right:40px" oninput="renderPasswordStrength(this.value, 'fp-pw')" />
                <span onclick="togglePwVisibility('fp-new-password', 'fp-pw-eye-icon')"
                  style="position:absolute;right:12px;top:50%;transform:translateY(-50%);cursor:pointer;color:var(--slate-light);font-size:14px"
                  id="fp-pw-eye-icon">👁</span>
              </div>
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
    document.getElementById("fp-step-identifier").style.display = "block";
    document.getElementById("fp-step-otp").style.display = "none";
    document.getElementById("fp-step-newpw").style.display = "none";
    document.getElementById("fp-identifier").value = "";
    document.getElementById("fp-identifier-err").textContent = "";
    fpLoadCaptcha();
  };

  window.closeForgotPasswordModal = function () {
    const overlay = document.getElementById("fp-modal-overlay");
    if (overlay) overlay.classList.remove("open");
    fpCaptchaToken = null; fpIdentifier = null; fpIsEmail = null; fpResetToken = null;
  };

  window.fpLoadCaptcha = async function () {
    const box = document.getElementById("fp-captcha-image-box");
    const answerInput = document.getElementById("fp-captcha-answer");
    box.innerHTML = "Loading captcha…";
    answerInput.value = "";
    try {
      const res = await fetch(`${BASE}/auth/captcha`);
      const json = await res.json();
      box.innerHTML = json.svg;
      fpCaptchaToken = json.token;
    } catch (e) {
      box.innerHTML = "Couldn't load captcha — tap 🔄 to retry";
      fpCaptchaToken = null;
    }
  };

  window.fpRequestOtp = async function () {
    const err = document.getElementById("fp-identifier-err");
    const btn = document.getElementById("fp-btn-send");
    err.textContent = "";

    const rawIdentifier = document.getElementById("fp-identifier").value.trim();
    const isEmailId = isEmail(rawIdentifier);
    const isPhoneId = isPhone(rawIdentifier);
    const identifier = isEmailId ? rawIdentifier.toLowerCase() : rawIdentifier;
    const captchaAnswer = document.getElementById("fp-captcha-answer").value.trim();
    if (!isEmailId && !isPhoneId) { err.textContent = "Enter a valid email or 10-digit phone number."; return; }
    if (!fpCaptchaToken || !captchaAnswer) { err.textContent = "Please answer the captcha question."; return; }

    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span>';
    try {
      const url = isEmailId ? `${BASE}/auth/forgot-password/request` : `${BASE}/portal/auth/forgot-password/request`;
      const body = isEmailId
        ? { email: identifier, captcha_token: fpCaptchaToken, captcha_answer: captchaAnswer }
        : { phone: identifier, captcha_token: fpCaptchaToken, captcha_answer: captchaAnswer };
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
      const json = await res.json();
      if (!res.ok) {
        if (json.detail && json.detail.toLowerCase().includes("captcha")) fpLoadCaptcha();
        throw new Error(json.detail || "Could not send OTP");
      }
      fpIdentifier = identifier;
      fpIsEmail = isEmailId;
      document.getElementById("fp-step-identifier").style.display = "none";
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
      const url = fpIsEmail ? `${BASE}/auth/forgot-password/verify` : `${BASE}/portal/auth/forgot-password/verify`;
      const body = fpIsEmail ? { email: fpIdentifier, otp } : { phone: fpIdentifier, otp };
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
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
      const url = fpIsEmail ? `${BASE}/auth/reset-password` : `${BASE}/portal/auth/reset-password`;
      const res = await fetch(url, {
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