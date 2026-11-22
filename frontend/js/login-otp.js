// ScribeKare OTP boxes: one box per digit, used by the login 2FA modal and the forgot-password modal.
// Design notes:
// - Typing moves to the next box; Backspace on an empty box goes back; arrows, Home and End move around.
// - Paste (or a phone's SMS autofill into the first box) spreads the digits across all boxes.
// - The first box has autocomplete="one-time-code" so phones can offer the code.
// - Digits only. Nothing is stored. All text is set through properties, never innerHTML.
// - State is shown with data-state on the container: "", "error" (shakes), "verifying", "success".
// Usage: var otp = OtpBoxes.create(el, { length: 6, groupLabel, onChange(v), onComplete(v) });
//        otp.value(), otp.clear(), otp.focus(), otp.setState("error")
(function () {
  "use strict";

  function create(root, opts) {
    opts = opts || {};
    var len = opts.length || 6;
    var cells = [];
    var api = {};

    root.textContent = "";
    root.classList.add("otp");
    root.setAttribute("role", "group");
    root.setAttribute("aria-label", opts.groupLabel || len + "-digit code");
    root.dataset.state = "";

    function value() {
      var v = "";
      for (var k = 0; k < cells.length; k++) v += cells[k].value;
      return v;
    }

    function sync() {
      for (var k = 0; k < cells.length; k++) cells[k].classList.toggle("is-filled", cells[k].value !== "");
      var v = value();
      root.classList.toggle("is-complete", v.length === len);
      if (opts.onChange) opts.onChange(v);
      if (v.length === len && opts.onComplete) opts.onComplete(v);
    }

    function fill(from, digits) {
      var i = from;
      for (var k = 0; k < digits.length && i < len; k++, i++) cells[i].value = digits[k];
      cells[Math.min(i, len - 1)].focus();
    }

    function leaveError() {
      if (root.dataset.state === "error") root.dataset.state = "";
    }

    function build(i) {
      var inp = document.createElement("input");
      inp.type = "text";
      inp.inputMode = "numeric";
      inp.pattern = "[0-9]*";
      inp.autocomplete = i === 0 ? "one-time-code" : "off";
      inp.maxLength = i === 0 ? len : 1;
      inp.spellcheck = false;
      inp.setAttribute("autocapitalize", "off");
      inp.setAttribute("aria-label", "Digit " + (i + 1) + " of " + len);
      inp.style.setProperty("--i", i);

      inp.addEventListener("focus", function () { inp.select(); });
      inp.addEventListener("click", function () { inp.select(); });

      inp.addEventListener("input", function () {
        var d = inp.value.replace(/\D/g, "");
        leaveError();
        if (!d) { inp.value = ""; sync(); return; }
        if (d.length === 1) {
          inp.value = d;
          if (i < len - 1) cells[i + 1].focus();
        } else {
          inp.value = "";
          fill(i, d.slice(0, len));
        }
        sync();
      });

      inp.addEventListener("keydown", function (e) {
        if (e.key === "Backspace" && inp.value === "" && i > 0) {
          e.preventDefault();
          cells[i - 1].value = "";
          cells[i - 1].focus();
          sync();
        } else if (e.key === "ArrowLeft" && i > 0) {
          e.preventDefault();
          cells[i - 1].focus();
        } else if (e.key === "ArrowRight" && i < len - 1) {
          e.preventDefault();
          cells[i + 1].focus();
        } else if (e.key === "Home") {
          e.preventDefault();
          cells[0].focus();
        } else if (e.key === "End") {
          e.preventDefault();
          cells[len - 1].focus();
        }
      });

      inp.addEventListener("paste", function (e) {
        var text = (e.clipboardData || window.clipboardData).getData("text") || "";
        var d = text.replace(/\D/g, "");
        if (!d) return;
        e.preventDefault();
        leaveError();
        fill(d.length >= len ? 0 : i, d.slice(0, len));
        sync();
      });

      return inp;
    }

    for (var i = 0; i < len; i++) {
      var c = build(i);
      cells.push(c);
      root.appendChild(c);
    }

    api.el = root;
    api.value = value;
    api.clear = function () {
      for (var k = 0; k < cells.length; k++) cells[k].value = "";
      sync();
    };
    api.focus = function () {
      var idx = 0;
      while (idx < len && cells[idx].value !== "") idx++;
      cells[Math.min(idx, len - 1)].focus();
    };
    api.setState = function (s) {
      root.dataset.state = s || "";
      var lock = s === "verifying" || s === "success";
      for (var k = 0; k < cells.length; k++) cells[k].readOnly = lock;
      if (s === "error") {
        root.classList.remove("shake");
        void root.offsetWidth;
        root.classList.add("shake");
      }
    };
    return api;
  }

  window.OtpBoxes = { create: create };
})();