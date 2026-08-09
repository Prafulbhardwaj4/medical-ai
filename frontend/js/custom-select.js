// custom-select.js
// Progressive enhancement: turns every <select class="form-control"> into a
// themed dropdown (styled trigger + styled options list), with a live
// type-to-filter search box for any select with more than 7 options. The
// native <select> stays in the DOM (hidden) so existing code that reads/sets
// .value or listens for "change" keeps working unmodified. Works on selects
// added dynamically (e.g. wizard steps that rebuild innerHTML) via a
// MutationObserver.

(function () {
  function syncVisibility(select, wrapper) {
    wrapper.style.display = window.getComputedStyle(select).display === "none" ? "none" : "";
  }

  function enhanceSelect(select) {
    if (!select || select.dataset.csEnhanced || select.multiple) return;
    select.dataset.csEnhanced = "1";

    const wrapper = document.createElement("div");
    wrapper.className = "cs-wrapper";
    if (select.style.width) wrapper.style.width = select.style.width;
    if (select.style.maxWidth) wrapper.style.maxWidth = select.style.maxWidth;
    if (select.style.minWidth) wrapper.style.minWidth = select.style.minWidth;
    if (select.style.margin) wrapper.style.margin = select.style.margin;
    if (select.style.marginBottom) wrapper.style.marginBottom = select.style.marginBottom;
    if (select.style.marginTop) wrapper.style.marginTop = select.style.marginTop;
    if (select.style.flexShrink) wrapper.style.flexShrink = select.style.flexShrink;
    select.parentNode.insertBefore(wrapper, select);
    wrapper.appendChild(select);
    select.classList.add("cs-native");
    select.setAttribute("tabindex", "-1");
    select.setAttribute("aria-hidden", "true");
    syncVisibility(select, wrapper);
    window.addEventListener("resize", () => syncVisibility(select, wrapper));

    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "cs-trigger";
    trigger.setAttribute("aria-haspopup", "listbox");
    trigger.setAttribute("aria-expanded", "false");
    const triggerLabel = document.createElement("span");
    triggerLabel.className = "cs-trigger-label";
    trigger.appendChild(triggerLabel);
    wrapper.appendChild(trigger);

    const menu = document.createElement("div");
    menu.className = "cs-menu";
    menu.setAttribute("role", "listbox");
    wrapper.appendChild(menu);

    // Every enhanced select gets a type-to-filter box now — not just long
    // lists — so typing "i" always jumps the list to matching items,
    // regardless of how many options a given dropdown happens to have.
    // Opt out per-select with data-no-search when a plain list is wanted
    // instead (e.g. a short, physical-location picker like room selection).
    const searchable = !select.hasAttribute("data-no-search");
    let searchInput = null;
    if (searchable) {
      const searchWrap = document.createElement("div");
      searchWrap.className = "cs-search-wrap";
      searchInput = document.createElement("input");
      searchInput.type = "text";
      searchInput.className = "cs-search-input";
      searchInput.placeholder = "Type to search...";
      searchInput.addEventListener("click", (e) => e.stopPropagation());
      searchInput.addEventListener("input", () => renderOptions(searchInput.value));
      searchWrap.appendChild(searchInput);
      menu.appendChild(searchWrap);
    }

    const optionsList = document.createElement("div");
    optionsList.className = "cs-options-list";
    menu.appendChild(optionsList);

    let optionEls = [];

    function renderOptions(filterText) {
      const q = (filterText || "").trim().toLowerCase();
      optionsList.innerHTML = "";
      optionEls = [];
      Array.from(select.options).forEach((opt, i) => {
        if (q && !opt.textContent.toLowerCase().includes(q)) return;
        const item = document.createElement("div");
        item.className = "cs-option";
        item.setAttribute("role", "option");
        item.textContent = opt.textContent;
        if (opt.disabled) item.classList.add("cs-option-disabled");
        if (i === select.selectedIndex) {
          item.classList.add("cs-option-selected");
          item.setAttribute("aria-selected", "true");
        }
        if (!opt.disabled) {
          item.addEventListener("click", () => {
            select.selectedIndex = i;
            select.dispatchEvent(new Event("change", { bubbles: true }));
            closeMenu();
            trigger.focus();
          });
        }
        optionsList.appendChild(item);
        optionEls.push(item);
      });
      if (!optionEls.length) {
        const none = document.createElement("div");
        none.className = "cs-no-results";
        none.textContent = "No matches";
        optionsList.appendChild(none);
      }
    }

    function syncTrigger() {
      const opt = select.options[select.selectedIndex];
      triggerLabel.textContent = opt ? opt.textContent : "";
      trigger.classList.toggle("cs-placeholder", !opt || !opt.value);
      trigger.disabled = select.disabled;
      wrapper.classList.toggle("cs-disabled", select.disabled);
    }

    function positionMenu() {
      menu.classList.remove("cs-menu-up");
      const rect = trigger.getBoundingClientRect();
      const spaceBelow = window.innerHeight - rect.bottom;
      if (spaceBelow < 240 && rect.top > spaceBelow) menu.classList.add("cs-menu-up");
    }

    function closeOthers() {
      document.querySelectorAll(".cs-wrapper.cs-open").forEach((w) => {
        if (w !== wrapper) {
          w.classList.remove("cs-open");
          const t = w.querySelector(".cs-trigger");
          if (t) t.setAttribute("aria-expanded", "false");
        }
      });
    }

    function openMenu() {
      if (select.disabled || !select.options.length) return;
      closeOthers();
      if (searchInput) searchInput.value = "";
      renderOptions(searchInput ? searchInput.value : "");
      wrapper.classList.add("cs-open");
      trigger.setAttribute("aria-expanded", "true");
      positionMenu();
      document.addEventListener("click", onOutsideClick, true);
      document.addEventListener("keydown", onKeydown, true);
      if (searchInput) setTimeout(() => searchInput.focus(), 0);
    }

    function closeMenu() {
      wrapper.classList.remove("cs-open");
      trigger.setAttribute("aria-expanded", "false");
      document.removeEventListener("click", onOutsideClick, true);
      document.removeEventListener("keydown", onKeydown, true);
    }

    function onOutsideClick(e) {
      if (!wrapper.contains(e.target)) closeMenu();
    }

    function onKeydown(e) {
      if (e.key === "Escape") { closeMenu(); trigger.focus(); return; }
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        const enabled = optionEls.filter((o) => !o.classList.contains("cs-option-disabled"));
        let idx = enabled.findIndex((o) => o.classList.contains("cs-option-selected"));
        idx = e.key === "ArrowDown" ? Math.min(idx + 1, enabled.length - 1) : Math.max(idx - 1, 0);
        enabled.forEach((o) => o.classList.remove("cs-option-selected"));
        if (enabled[idx]) {
          enabled[idx].classList.add("cs-option-selected");
          enabled[idx].scrollIntoView({ block: "nearest" });
        }
      }
      if (e.key === "Enter") {
        const sel = optionsList.querySelector(".cs-option-selected");
        if (sel) sel.click();
      }
    }

    trigger.addEventListener("click", (e) => {
      e.stopPropagation();
      wrapper.classList.contains("cs-open") ? closeMenu() : openMenu();
    });

    select.addEventListener("change", syncTrigger);

    // Picks up dynamic changes made by existing app code, e.g.
    // citySel.innerHTML = "..."; citySel.disabled = false;
    const mo = new MutationObserver(() => {
      syncTrigger();
      syncVisibility(select, wrapper);
      if (wrapper.classList.contains("cs-open")) renderOptions(searchInput ? searchInput.value : "");
    });
    mo.observe(select, { childList: true, attributes: true, attributeFilter: ["disabled", "style", "class"] });

    syncTrigger();
  }

  function scan(root) {
    if (!root || !root.querySelectorAll) return;
    root.querySelectorAll("select.form-control").forEach(enhanceSelect);
  }

  document.addEventListener("DOMContentLoaded", () => scan(document));

  new MutationObserver((mutations) => {
    for (const m of mutations) {
      m.addedNodes.forEach((node) => {
        if (node.nodeType !== 1) return;
        if (node.matches && node.matches("select.form-control")) enhanceSelect(node);
        scan(node);
      });
    }
  }).observe(document.documentElement, { childList: true, subtree: true });
})();