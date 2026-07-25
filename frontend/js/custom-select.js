// custom-select.js
// Progressive enhancement: turns every <select class="form-control"> into a
// themed dropdown (styled trigger + styled options list). The native <select>
// stays in the DOM (hidden) so existing code that reads/sets .value or listens
// for "change" keeps working unmodified. Works on selects added dynamically
// (e.g. wizard steps that rebuild innerHTML) via a MutationObserver.

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
    wrapper.appendChild(trigger);

    const menu = document.createElement("div");
    menu.className = "cs-menu";
    menu.setAttribute("role", "listbox");
    wrapper.appendChild(menu);

    let optionEls = [];

    function renderOptions() {
      menu.innerHTML = "";
      optionEls = Array.from(select.options).map((opt, i) => {
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
        menu.appendChild(item);
        return item;
      });
    }

    function syncTrigger() {
      const opt = select.options[select.selectedIndex];
      trigger.textContent = opt ? opt.textContent : "";
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
      renderOptions();
      wrapper.classList.add("cs-open");
      trigger.setAttribute("aria-expanded", "true");
      positionMenu();
      document.addEventListener("click", onOutsideClick, true);
      document.addEventListener("keydown", onKeydown, true);
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
        enabled[idx].classList.add("cs-option-selected");
        enabled[idx].scrollIntoView({ block: "nearest" });
      }
      if (e.key === "Enter") {
        const sel = menu.querySelector(".cs-option-selected");
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
      if (wrapper.classList.contains("cs-open")) renderOptions();
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