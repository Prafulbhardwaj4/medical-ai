// Shared guided-tutorial overlay. One engine, reused across every role and
// page — a page calls initTutorial(subjectType, role, page) once on load
// (auto-triggers only if this account hasn't completed/skipped this role's
// tutorial yet — see backend GET /tutorials/status/{subjectType} — so it
// naturally shows through a patient's first real session and never again
// after they finish or skip it, regardless of later reloads/logins/devices),
// and wires a "Tutorial" menu item to startTutorial(subjectType, role, page,
// true) for manual replay. subjectType is "patient" or "staff" — matches
// which status/complete endpoints to call; role/page select which
// TutorialStep rows to fetch and render, in step_order.
//
// Each step also carries a "device": "mobile" | "desktop" | "both" — mobile
// and desktop layouts differ enough (sidebar vs bottom-nav, stacked vs
// tabbed sections) that a step's target often only exists/is visible on one
// of the two. Steps are filtered client-side against window.innerWidth
// using the same 900px breakpoint the rest of the app's CSS already uses,
// so a desktop session only ever sees desktop(+both) steps and a mobile
// session only ever sees mobile(+both) steps.
//
// Highlights one real DOM element at a time (via the target's own
// data-tutorial-id attribute — never a class/ID that might get renamed
// later for unrelated reasons), with a card-style tooltip + pointer arrow
// positioned relative to it, and Back/Next/Finish controls.

(function () {
  const MOBILE_BREAKPOINT = 900;

  let _steps = [];
  let _stepIndex = 0;
  let _subjectType = null;
  let _role = null;
  let _overlayEl = null;
  let _tooltipEl = null;
  let _highlightEl = null;
  let _arrowEl = null;
  let _resizeHandler = null;
  let _wheelBlocker = null;
  let _localOptions = null; // set only by startLocalTour — marks "local" (non-backend) mode
  let _page = null; // which tab's tutorial is currently loaded — passed back on completion
  let _onDone = null; // optional callback for backend-driven tutorials — fires on Finish OR Skip, after the completion API call

  function _statusEndpoint(subjectType, page) {
    const base = subjectType === "patient" ? "/tutorials/status/patient" : "/tutorials/status/staff";
    return page ? `${base}?page=${encodeURIComponent(page)}` : base;
  }
  function _completeEndpoint(subjectType, page) {
    const base = subjectType === "patient" ? "/tutorials/status/patient/complete" : "/tutorials/status/staff/complete";
    return page ? `${base}?page=${encodeURIComponent(page)}` : base;
  }
  function _isMobile() {
    return window.innerWidth <= MOBILE_BREAKPOINT;
  }
  function _matchesDevice(step) {
    if (!step.device || step.device === "both") return true;
    return _isMobile() ? step.device === "mobile" : step.device === "desktop";
  }

  async function initTutorial(subjectType, role, page, onDone) {
    try {
      const status = await api("GET", _statusEndpoint(subjectType, page));
      if (status.completed) return; // already seen/skipped this tab — only manual replay from here on
      // Marked seen the moment it auto-shows, not only on Finish/Skip — a
      // reload or navigating away mid-tour must never bring it back
      // automatically. Manual replay (startTutorial with isReplay=true)
      // never goes through here, so it's unaffected.
      api("POST", _completeEndpoint(subjectType, page)).catch(() => {});
      startTutorial(subjectType, role, page, false, onDone);
    } catch (e) { /* silent — a broken tutorial fetch should never block the real page */ }
  }

  async function startTutorial(subjectType, role, page, isReplay, onDone) {
    try {
      const allSteps = await api("GET", `/tutorials/${role}/${page}`);
      const steps = allSteps.filter(_matchesDevice);
      if (!steps.length) {
        if (isReplay) toast("No tutorial is set up for this page yet.", "info");
        return;
      }
      _steps = steps;
      _stepIndex = 0;
      _subjectType = subjectType;
      _role = role;
      _page = page;
      _localOptions = null;
      _onDone = onDone || null;
      _buildOverlay();
      _renderStep();
    } catch (e) {
      if (isReplay) toast("Could not load the tutorial right now.", "error");
    }
  }

  // Local, non-backend-driven tour for flows that don't fit the per-role
  // TutorialStep/status-endpoint model — e.g. a scripted cross-page demo.
  // Steps are passed in directly (same shape as a TutorialStep row: title,
  // description, target_selector, placement, device) plus two optional
  // extras per step:
  //   - nextLabel: overrides the Next/Finish button text for this step.
  //   - onNext(): called when Next/Finish is pressed, before advancing.
  //               Returning false stops the tour from auto-advancing —
  //               use this when the step itself navigates away (e.g. to
  //               another page) instead of moving to the next step here.
  // options: { onSkip(), onFinish() } run instead of the normal
  // tutorial-complete API call, since a local tour has no subjectType.
  function startLocalTour(steps, options) {
    const filtered = steps.filter(_matchesDevice);
    if (!filtered.length) return;
    _steps = filtered;
    _stepIndex = 0;
    _subjectType = null;
    _localOptions = options || {};
    _buildOverlay();
    _renderStep();
  }

  function _buildOverlay() {
    if (_overlayEl) return;
    _lockScroll();
    _overlayEl = document.createElement("div");
    _overlayEl.id = "tutorial-overlay";
    _overlayEl.style.cssText = "position:fixed;inset:0;z-index:10500;pointer-events:none";
    document.body.appendChild(_overlayEl);

    _highlightEl = document.createElement("div");
    _highlightEl.id = "tutorial-highlight";
    _highlightEl.style.cssText = "position:absolute;border-radius:10px;box-shadow:0 0 0 3px var(--teal, #0d9488),0 0 0 9999px rgba(15,31,61,0.6);transition:all .25s ease;pointer-events:none";
    _overlayEl.appendChild(_highlightEl);

    _tooltipEl = document.createElement("div");
    _tooltipEl.id = "tutorial-tooltip";
    _tooltipEl.style.cssText = "position:absolute;background:#fff;border:1px solid var(--border,#e2e8f0);border-radius:var(--radius-lg,14px);box-shadow:var(--shadow-lg, 0 10px 40px rgba(15,31,61,0.18));padding:18px 18px 16px;pointer-events:auto;font-family:inherit;transition:top .25s ease,left .25s ease";
    _overlayEl.appendChild(_tooltipEl);

    _resizeHandler = () => _positionForCurrentStep();
    window.addEventListener("resize", _resizeHandler);
  }

  function _teardownOverlay() {
    if (_resizeHandler) window.removeEventListener("resize", _resizeHandler);
    if (_overlayEl) _overlayEl.remove();
    _unlockScroll();
    _overlayEl = null; _tooltipEl = null; _highlightEl = null; _arrowEl = null; _resizeHandler = null;
  }

  function _lockScroll() {
    if (_wheelBlocker) return;
    _wheelBlocker = (e) => e.preventDefault();
    window.addEventListener("wheel", _wheelBlocker, { passive: false });
    window.addEventListener("touchmove", _wheelBlocker, { passive: false });
  }

  function _unlockScroll() {
    if (!_wheelBlocker) return;
    window.removeEventListener("wheel", _wheelBlocker, { passive: false });
    window.removeEventListener("touchmove", _wheelBlocker, { passive: false });
    _wheelBlocker = null;
  }

  function _renderStep() {
    const step = _steps[_stepIndex];
    const isLast = _stepIndex === _steps.length - 1;
    const dots = _steps.map((s, i) => `<span style="width:6px;height:6px;border-radius:50%;flex-shrink:0;background:${i === _stepIndex ? 'var(--teal,#0d9488)' : 'var(--border,#e2e8f0)'};display:inline-block;transition:background .2s"></span>`).join('');
    _tooltipEl.innerHTML = `
      <div id="tutorial-arrow" style="position:absolute;width:14px;height:14px;background:#fff;pointer-events:none"></div>
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px">
        <div style="font-size:11px;letter-spacing:.04em;color:var(--slate-light,#94a3b8);font-weight:700;text-transform:uppercase;padding-top:3px">Step ${_stepIndex + 1} of ${_steps.length}</div>
        <button id="tutorial-skip-btn" style="background:none;border:none;color:var(--slate-light,#94a3b8);font-size:12.5px;font-weight:600;cursor:pointer;padding:2px 0 0" aria-label="Skip tutorial">Skip</button>
      </div>
      <div style="font-size:16px;font-weight:700;color:var(--navy,#0f1f3d);margin:4px 0 6px">${_escape(step.title)}</div>
      <div style="font-size:13.5px;color:var(--slate,#475569);line-height:1.55;margin-bottom:16px">${_escape(step.description)}</div>
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px">
        <div style="display:flex;gap:5px;align-items:center">${dots}</div>
        <div style="display:flex;gap:8px">
          ${_stepIndex > 0 ? `<button id="tutorial-back-btn" class="btn btn-outline btn-sm">Back</button>` : ''}
          <button id="tutorial-next-btn" class="btn btn-primary btn-sm">${step.nextLabel || (isLast ? 'Finish' : 'Next')}</button>
        </div>
      </div>
    `;
    _arrowEl = document.getElementById("tutorial-arrow");
    document.getElementById("tutorial-skip-btn").addEventListener("click", () => {
      if (_localOptions) { _teardownOverlay(); if (_localOptions.onSkip) _localOptions.onSkip(); }
      else { _finish(); }
    });
    document.getElementById("tutorial-next-btn").addEventListener("click", () => {
      if (step.onNext) {
        const shouldAdvance = step.onNext();
        if (shouldAdvance === false) return; // step itself is handling the transition (e.g. navigating away)
      }
      if (isLast) { _finish(); } else { _stepIndex++; _renderStep(); }
    });
    const backBtn = document.getElementById("tutorial-back-btn");
    if (backBtn) backBtn.addEventListener("click", () => { _stepIndex--; _renderStep(); });

    _positionForCurrentStep();
  }

  function _positionForCurrentStep() {
    const step = _steps[_stepIndex];
    if (step.click_before) {
      // Switches to the tab/section this step's target lives in before
      // measuring it — e.g. a mobile bottom-nav tab whose content is
      // display:none until tapped. Idempotent (re-clicking an already-active
      // tab is harmless), so it's safe to run again on window resize too.
      const trigger = document.querySelector(step.click_before);
      if (trigger) trigger.click();
    }
    const target = document.querySelector(step.target_selector);
    const preRect = target ? target.getBoundingClientRect() : null;
    if (!target || (preRect.width === 0 && preRect.height === 0)) {
      // Missing, OR present but currently invisible (e.g. a different
      // tab's content that isn't the active one right now) — skip past it
      // rather than draw a box over nothing.
      if (_stepIndex < _steps.length - 1) { _stepIndex++; _renderStep(); }
      else _finish();
      return;
    }
    // Scroll BEFORE measuring, not after — scrollIntoView's smooth-scroll
    // animation used to run *after* the highlight/tooltip were already
    // placed from the pre-scroll position, so the box ended up floating
    // wherever the target used to be once the animation finished. Instant
    // scroll removes that race entirely; positioning is always measured
    // post-scroll now.
    target.scrollIntoView({ block: "center", behavior: "instant" });
    const rect = target.getBoundingClientRect();
    const pad = 6;
    _highlightEl.style.top = `${rect.top - pad}px`;
    _highlightEl.style.left = `${rect.left - pad}px`;
    _highlightEl.style.width = `${rect.width + pad * 2}px`;
    _highlightEl.style.height = `${rect.height + pad * 2}px`;

    const placement = step.placement || "bottom";
    const gap = 16;
    const tw = Math.min(300, window.innerWidth - 24);
    _tooltipEl.style.width = `${tw}px`;
    const th = _tooltipEl.offsetHeight;

    let top, left;
    if (placement === "top") { top = rect.top - gap - th; left = rect.left; }
    else if (placement === "left") { top = rect.top; left = rect.left - tw - gap; }
    else if (placement === "right") { top = rect.top; left = rect.right + gap; }
    else { top = rect.bottom + gap; left = rect.left; }

    left = Math.max(12, Math.min(left, window.innerWidth - tw - 12));
    top = Math.max(12, Math.min(top, window.innerHeight - th - 12));
    _tooltipEl.style.top = `${top}px`;
    _tooltipEl.style.left = `${left}px`;

    // Pointer arrow: a small rotated square, half tucked behind the
    // tooltip's edge closest to the target, nudged along that edge to line
    // up with the target's own center (clamped so it stays clear of the
    // card's rounded corners).
    const targetCenterX = rect.left + rect.width / 2;
    const targetCenterY = rect.top + rect.height / 2;
    const border = "1px solid var(--border,#e2e8f0)";
    const base = "position:absolute;width:14px;height:14px;background:#fff;pointer-events:none;transform:rotate(45deg);";
    if (placement === "top") {
      const x = Math.max(14, Math.min(targetCenterX - left - 7, tw - 28));
      _arrowEl.style.cssText = `${base}bottom:-8px;left:${x}px;border-right:${border};border-bottom:${border};border-top:none;border-left:none;`;
    } else if (placement === "left") {
      const y = Math.max(14, Math.min(targetCenterY - top - 7, th - 28));
      _arrowEl.style.cssText = `${base}right:-8px;top:${y}px;border-top:${border};border-right:${border};border-bottom:none;border-left:none;`;
    } else if (placement === "right") {
      const y = Math.max(14, Math.min(targetCenterY - top - 7, th - 28));
      _arrowEl.style.cssText = `${base}left:-8px;top:${y}px;border-bottom:${border};border-left:${border};border-top:none;border-right:none;`;
    } else {
      const x = Math.max(14, Math.min(targetCenterX - left - 7, tw - 28));
      _arrowEl.style.cssText = `${base}top:-8px;left:${x}px;border-top:${border};border-left:${border};border-bottom:none;border-right:none;`;
    }
  }

  async function _finish() {
    _teardownOverlay();
    if (_localOptions) {
      if (_localOptions.onFinish) _localOptions.onFinish();
      return;
    }
    try { await api("POST", _completeEndpoint(_subjectType, _page)); } catch (e) { /* best-effort — don't block the user on this */ }
    if (_onDone) _onDone();
  }

  function _escape(s) {
    const d = document.createElement("div");
    d.textContent = s || "";
    return d.innerHTML;
  }

  window.initTutorial = initTutorial;
  window.startTutorial = startTutorial;
  window.startLocalTour = startLocalTour;
})();