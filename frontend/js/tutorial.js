// Shared guided-tutorial overlay. One engine, reused across every role and
// page — a page just calls initTutorial(subjectType, role, page) once on
// load (auto-triggers only if this account hasn't completed/skipped this
// role's tutorial yet — see backend GET /tutorials/status/{subjectType}),
// and wires a "Tutorial" menu item to startTutorial(subjectType, role, page,
// true) for manual replay. subjectType is "patient" or "staff" — matches
// which status/complete endpoints to call; role/page select which
// TutorialStep rows to fetch and render, in step_order.
//
// Highlights one real DOM element at a time (via the target's own
// data-tutorial-id attribute — never a class/ID that might get renamed
// later for unrelated reasons), with a tooltip positioned relative to it,
// and Back/Next/Skip controls. Steps for the current page only are shown;
// steps belonging to other pages in the same role's tutorial are fetched
// but just not rendered here (a future page navigation, e.g. from
// my-health.html to my-appointments.html, re-inits and picks up that
// page's own steps — this file doesn't try to survive a page navigation
// mid-tutorial).

(function () {
  let _steps = [];
  let _stepIndex = 0;
  let _subjectType = null;
  let _role = null;
  let _overlayEl = null;
  let _tooltipEl = null;
  let _highlightEl = null;
  let _resizeHandler = null;

  function _statusEndpoint(subjectType) {
    return subjectType === "patient" ? "/tutorials/status/patient" : "/tutorials/status/staff";
  }
  function _completeEndpoint(subjectType) {
    return subjectType === "patient" ? "/tutorials/status/patient/complete" : "/tutorials/status/staff/complete";
  }

  async function initTutorial(subjectType, role, page) {
    try {
      const status = await api("GET", _statusEndpoint(subjectType));
      if (status.completed) return; // already seen/skipped — only manual replay from here on
      startTutorial(subjectType, role, page, false);
    } catch (e) { /* silent — a broken tutorial fetch should never block the real page */ }
  }

  async function startTutorial(subjectType, role, page, isReplay) {
    try {
      const steps = await api("GET", `/tutorials/${role}/${page}`);
      if (!steps.length) {
        if (isReplay) toast("No tutorial is set up for this page yet.", "info");
        return;
      }
      _steps = steps;
      _stepIndex = 0;
      _subjectType = subjectType;
      _role = role;
      _buildOverlay();
      _renderStep();
    } catch (e) {
      if (isReplay) toast("Could not load the tutorial right now.", "error");
    }
  }

  function _buildOverlay() {
    if (_overlayEl) return;
    _overlayEl = document.createElement("div");
    _overlayEl.id = "tutorial-overlay";
    _overlayEl.style.cssText = "position:fixed;inset:0;z-index:10500;pointer-events:none";
    document.body.appendChild(_overlayEl);

    _highlightEl = document.createElement("div");
    _highlightEl.id = "tutorial-highlight";
    _highlightEl.style.cssText = "position:absolute;border-radius:10px;box-shadow:0 0 0 4px var(--teal, #0d9488),0 0 0 9999px rgba(15,31,61,0.55);transition:all .2s ease;pointer-events:none";
    _overlayEl.appendChild(_highlightEl);

    _tooltipEl = document.createElement("div");
    _tooltipEl.id = "tutorial-tooltip";
    _tooltipEl.style.cssText = "position:absolute;max-width:300px;background:#fff;border-radius:12px;box-shadow:0 8px 30px rgba(15,31,61,0.25);padding:16px;pointer-events:auto;font-family:inherit";
    _overlayEl.appendChild(_tooltipEl);

    _resizeHandler = () => _positionForCurrentStep();
    window.addEventListener("resize", _resizeHandler);
  }

  function _teardownOverlay() {
    if (_resizeHandler) window.removeEventListener("resize", _resizeHandler);
    if (_overlayEl) _overlayEl.remove();
    _overlayEl = null; _tooltipEl = null; _highlightEl = null; _resizeHandler = null;
  }

  function _renderStep() {
    const step = _steps[_stepIndex];
    const isLast = _stepIndex === _steps.length - 1;
    _tooltipEl.innerHTML = `
      <div style="font-size:12px;color:var(--slate-light,#94a3b8);font-weight:600;margin-bottom:6px">STEP ${_stepIndex + 1} OF ${_steps.length}</div>
      <div style="font-size:16px;font-weight:700;color:var(--navy,#0f1f3d);margin-bottom:6px">${_escape(step.title)}</div>
      <div style="font-size:13.5px;color:var(--slate,#475569);line-height:1.5;margin-bottom:14px">${_escape(step.description)}</div>
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px">
        <button id="tutorial-skip-btn" style="background:none;border:none;color:var(--slate-light,#94a3b8);font-size:13px;cursor:pointer;padding:0">Skip</button>
        <div style="display:flex;gap:8px">
          ${_stepIndex > 0 ? `<button id="tutorial-back-btn" class="btn btn-outline btn-sm">Back</button>` : ''}
          <button id="tutorial-next-btn" class="btn btn-primary btn-sm">${isLast ? 'Finish' : 'Next'}</button>
        </div>
      </div>
    `;
    document.getElementById("tutorial-skip-btn").addEventListener("click", _finish);
    document.getElementById("tutorial-next-btn").addEventListener("click", () => {
      if (isLast) { _finish(); } else { _stepIndex++; _renderStep(); }
    });
    const backBtn = document.getElementById("tutorial-back-btn");
    if (backBtn) backBtn.addEventListener("click", () => { _stepIndex--; _renderStep(); });

    _positionForCurrentStep();
  }

  function _positionForCurrentStep() {
    const step = _steps[_stepIndex];
    const target = document.querySelector(step.target_selector);
    if (!target) {
      // Target isn't on this page/viewport right now (e.g. a mobile-only
      // nav item while on desktop) — skip straight past it rather than
      // stall the whole tutorial on a missing element.
      if (_stepIndex < _steps.length - 1) { _stepIndex++; _renderStep(); }
      else _finish();
      return;
    }
    const rect = target.getBoundingClientRect();
    const pad = 6;
    _highlightEl.style.top = `${rect.top - pad}px`;
    _highlightEl.style.left = `${rect.left - pad}px`;
    _highlightEl.style.width = `${rect.width + pad * 2}px`;
    _highlightEl.style.height = `${rect.height + pad * 2}px`;
    target.scrollIntoView({ block: "center", behavior: "smooth" });

    const placement = step.placement || "bottom";
    const tw = 300, gap = 14;
    let top, left;
    if (placement === "top") { top = rect.top - gap; left = rect.left; _tooltipEl.style.transform = "translateY(-100%)"; }
    else if (placement === "left") { top = rect.top; left = rect.left - tw - gap; _tooltipEl.style.transform = "none"; }
    else if (placement === "right") { top = rect.top; left = rect.right + gap; _tooltipEl.style.transform = "none"; }
    else { top = rect.bottom + gap; left = rect.left; _tooltipEl.style.transform = "none"; }

    left = Math.max(12, Math.min(left, window.innerWidth - tw - 12));
    top = Math.max(12, Math.min(top, window.innerHeight - 12));
    _tooltipEl.style.top = `${top}px`;
    _tooltipEl.style.left = `${left}px`;
    _tooltipEl.style.width = `${tw}px`;
  }

  async function _finish() {
    _teardownOverlay();
    try { await api("POST", _completeEndpoint(_subjectType)); } catch (e) { /* best-effort — don't block the user on this */ }
  }

  function _escape(s) {
    const d = document.createElement("div");
    d.textContent = s || "";
    return d.innerHTML;
  }

  window.initTutorial = initTutorial;
  window.startTutorial = startTutorial;
})();