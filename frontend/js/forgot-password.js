// "Forgot password?" for admins, staff and patients (not super admins).
// Step 1: email (admins/staff) or 10-digit mobile number (patients) + captcha. The server always gives the
//         same answer, whether or not the account exists, and prepares a 6-digit code that the hospital
//         sends on WhatsApp. The code is valid for 10 minutes.
// Step 2: the 6-digit code + a new password, then the person is signed in.
//         A patient who never signed in before (or whose first verification code expired) leaves the
//         password boxes empty and gets a new verification code (valid 7 days) instead.
// Self-contained: injects its own modal and reuses .modal-overlay/.modal CSS plus
// renderPasswordStrength() / togglePwVisibility() / saveSession() / redirectByRole() from api.js.
// Include on login.html and call openForgotPasswordModal().

(function () {
  let fpCaptchaToken = null;
  let fpId = null;
  let fpIsStaff = false;

  const isEmail = (v) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v);
  const isPhone = (v) => /^\d{10}$/.test(v);
  const $ = (id) => document.getElementById(id);

  function injectModal() {
    if ($("fp-modal-overlay")) return;
    const wrap = document.createElement("div");
    wrap.innerHTML = `
      <div class="modal-overlay" id="fp-modal-overlay">
        <div class="modal">
          <div class="modal-header">
            <div style="font-weight:600;font-size:1.05rem">Reset your password</div>
            <div class="modal-close" id="fp-close" style="cursor:pointer">&#10005;</div>
          </div>

          <div id="fp-step-id">
            <p style="color:var(--slate);font-size:13px;margin-bottom:14px">Enter your email (admins and staff) or your mobile number (patients). We will prepare a 6-digit code, which the hospital sends to your WhatsApp.</p>
            <div class="form-group">
              <label class="form-label">Email / Mobile number</label>
              <input class="form-control" id="fp-id" type="text" autocomplete="username" placeholder="Email / Mobile number" />
            </div>
            <div class="form-group">
              <label class="form-label">Enter the code shown below</label>
              <div id="fp-captcha-image-box" style="margin-bottom:8px;line-height:0">Loading captcha...</div>
              <div style="display:flex;gap:8px;align-items:center">
                <input class="form-control" id="fp-captcha-answer" type="text" autocapitalize="characters" placeholder="Type the code" />
                <a href="#" id="fp-captcha-refresh" style="font-size:13px;white-space:nowrap;color:var(--teal, #0d9488)">New code</a>
              </div>
            </div>
            <div class="err-msg" id="fp-id-err"></div>
            <button class="btn btn-primary btn-lg" style="width:100%;margin-top:8px" id="fp-btn-send">Get code</button>
          </div>

          <div id="fp-step-reset" style="display:none">
            <p style="color:var(--slate);font-size:13px;margin-bottom:14px" id="fp-sent-note"></p>
            <div class="form-group">
              <label class="form-label">6-digit code</label>
              <input class="form-control" id="fp-code" type="text" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="6-digit code" />
            </div>
            <p id="fp-patient-note" style="display:none;color:var(--slate);font-size:12.5px;margin-bottom:12px">First time here, or your first verification code expired? Leave both password boxes empty and you will get a new verification code (valid 7 days) instead.</p>
            <div class="form-group">
              <label class="form-label">New Password</label>
              <div style="position:relative">
                <input class="form-control" id="fp-new-password" type="password" placeholder="At least 8 characters" style="padding-right:40px" />
                <span id="fp-pw-eye-icon" style="position:absolute;right:12px;top:50%;transform:translateY(-50%);cursor:pointer;color:var(--slate-light);font-size:14px">&#128065;</span>
              </div>
              <ul style="list-style:none;padding:0;margin:8px 0 0;font-size:12.5px">
                <li id="fp-pw-check-length" style="color:var(--slate-light)">&#9675; At least 8 characters</li>
                <li id="fp-pw-check-number" style="color:var(--slate-light)">&#9675; At least 1 number</li>
                <li id="fp-pw-check-upper" style="color:var(--slate-light)">&#9675; At least 1 capital letter</li>
              </ul>
            </div>
            <div class="form-group">
              <label class="form-label">Confirm Password</label>
              <input class="form-control" id="fp-new-password-confirm" type="password" placeholder="Re-enter password" />
            </div>
            <div class="err-msg" id="fp-reset-err"></div>
            <button class="btn btn-primary btn-lg" style="width:100%;margin-top:8px" id="fp-btn-reset">Continue</button>
            <div style="text-align:center;margin-top:12px"><a href="#" id="fp-back" style="font-size:13px;color:var(--teal, #0d9488)">Did not get a code? Ask for a new one</a></div>
          </div>

          <div id="fp-step-done" style="display:none">
            <p style="color:var(--slate);font-size:13px;margin-bottom:14px" id="fp-done-note"></p>
            <button class="btn btn-primary btn-lg" style="width:100%" id="fp-btn-done">Back to sign in</button>
          </div>
        </div>
      </div>`;
    document.body.appendChild(wrap.firstElementChild);

    $("fp-close").addEventListener("click", window.closeForgotPasswordModal);
    $("fp-btn-done").addEventListener("click", window.closeForgotPasswordModal);
    $("fp-captcha-refresh").addEventListener("click", (e) => { e.preventDefault(); loadCaptcha(); });
    $("fp-btn-send").addEventListener("click", requestCode);
    $("fp-btn-reset").addEventListener("click", resetPassword);
    $("fp-back").addEventListener("click", (e) => { e.preventDefault(); showStep("id"); loadCaptcha(); });
    $("fp-new-password").addEventListener("input", (e) => renderPasswordStrength(e.target.value, "fp-pw"));
    $("fp-pw-eye-icon").addEventListener("click", () => togglePwVisibility("fp-new-password", "fp-pw-eye-icon"));
    $("fp-code").addEventListener("input", (e) => { e.target.value = e.target.value.replace(/\D/g, "").slice(0, 6); });
  }

  function showStep(name) {
    ["id", "reset", "done"].forEach((s) => { $("fp-step-" + s).style.display = s === name ? "block" : "none"; });
  }

  window.openForgotPasswordModal = function () {
    injectModal();
    $("fp-modal-overlay").classList.add("open");
    const typed = (($("login-id") || {}).value || "").trim();
    $("fp-id").value = isEmail(typed) || isPhone(typed) ? typed : "";
    $("fp-id-err").textContent = "";
    showStep("id");
    loadCaptcha();
  };

  window.closeForgotPasswordModal = function () {
    const overlay = $("fp-modal-overlay");
    if (overlay) overlay.classList.remove("open");
    fpCaptchaToken = null;
    fpId = null;
  };

  async function loadCaptcha() {
    const box = $("fp-captcha-image-box");
    box.textContent = "Loading captcha...";
    $("fp-captcha-answer").value = "";
    try {
      const res = await fetch(`${BASE}/auth/captcha`);
      const json = await res.json();
      const img = document.createElement("img");
      img.alt = "captcha";
      img.draggable = false;
      img.style.cssText = "display:block;user-select:none;-webkit-user-select:none;pointer-events:none";
      img.src = "data:image/svg+xml;utf8," + encodeURIComponent(json.svg);
      box.textContent = "";
      box.appendChild(img);
      fpCaptchaToken = json.token;
    } catch (e) {
      box.textContent = "Could not load the captcha. Tap New code to retry.";
      fpCaptchaToken = null;
    }
  }

  async function requestCode() {
    const err = $("fp-id-err");
    const btn = $("fp-btn-send");
    err.textContent = "";
    const id = $("fp-id").value.trim();
    const answer = $("fp-captcha-answer").value.trim();
    if (!isEmail(id) && !isPhone(id)) { err.textContent = "Enter a valid email address or a 10-digit mobile number."; return; }
    if (!fpCaptchaToken || !answer) { err.textContent = "Please answer the captcha question."; return; }
    const staff = isEmail(id);
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span>';
    try {
      const res = await fetch(`${BASE}${staff ? "/auth" : "/portal/auth"}/forgot-password/request`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(staff
          ? { email: id, captcha_token: fpCaptchaToken, captcha_answer: answer }
          : { phone: id, captcha_token: fpCaptchaToken, captcha_answer: answer }),
      });
      const json = await res.json();
      if (!res.ok) {
        loadCaptcha();  // a captcha works once
        throw new Error(typeof json.detail === "string" ? json.detail : "Could not prepare the code");
      }
      fpId = id;
      fpIsStaff = staff;
      $("fp-sent-note").textContent =
        (json.message || "If this account exists, a code has been prepared.") +
        " It is valid for 10 minutes. Ask the hospital to send it to your WhatsApp, then enter it below.";
      $("fp-patient-note").style.display = staff ? "none" : "block";
      ["fp-code", "fp-new-password", "fp-new-password-confirm"].forEach((i) => { $(i).value = ""; });
      renderPasswordStrength("", "fp-pw");
      $("fp-reset-err").textContent = "";
      showStep("reset");
    } catch (e) {
      err.textContent = e.message;
    } finally {
      btn.disabled = false;
      btn.textContent = "Get code";
    }
  }

  async function resetPassword() {
    const err = $("fp-reset-err");
    const btn = $("fp-btn-reset");
    err.textContent = "";
    const code = $("fp-code").value.trim();
    const pw = $("fp-new-password").value;
    const cpw = $("fp-new-password-confirm").value;
    if (!/^\d{6}$/.test(code)) { err.textContent = "Enter the 6-digit code."; return; }
    const skipPassword = !fpIsStaff && pw === "" && cpw === "";
    if (!skipPassword) {
      if (pw.length < 8 || !/\d/.test(pw) || !/[A-Z]/.test(pw)) {
        err.textContent = "Password must be at least 8 characters, with 1 number and 1 capital letter.";
        return;
      }
      if (pw !== cpw) { err.textContent = "Passwords do not match."; return; }
    }
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span>';
    try {
      const body = fpIsStaff
        ? { email: fpId, otp: code, new_password: pw }
        : { phone: fpId, otp: code, new_password: skipPassword ? null : pw };
      const res = await fetch(`${BASE}${fpIsStaff ? "/auth" : "/portal/auth"}/forgot-password/reset`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const json = await res.json();
      if (!res.ok) throw new Error(typeof json.detail === "string" ? json.detail : "Could not reset the password");
      if (json.status === "verification_code_prepared") {
        $("fp-done-note").textContent = json.message ||
          "A new verification code has been prepared. The hospital will send it to your WhatsApp shortly. Use it as your password on the sign-in page.";
        showStep("done");
        return;
      }
      closeForgotPasswordModal();
      saveSession(json.access_token, json.doctor);
      redirectByRole(json.doctor.role);
    } catch (e) {
      err.textContent = e.message;
    } finally {
      btn.disabled = false;
      btn.textContent = "Continue";
    }
  }
})();