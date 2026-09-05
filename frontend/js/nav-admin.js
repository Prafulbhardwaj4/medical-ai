// nav-admin.js
// Single source of truth for the admin-role sidebar, bottom-nav, and mobile "More" menu.
// Any admin page that needs nav just includes this file + api.js + auth.js, keeps three
// empty containers in its HTML (#app-sidebar, #app-bottom-nav, #app-mobile-menu-body),
// and calls renderAdminNav('KEY') once `doc` is available.
//
// To add/remove/reorder an admin nav item in the future: edit ADMIN_NAV_ITEMS below only.
// Every admin page picks it up automatically -- no per-page HTML edits needed.
//
// Items that also exist as an in-page tab on analytics.html carry a `section` field
// (matching analytics.html's SECTIONS array + its nav-<section> ids). analytics.html calls
// renderAdminNav('overview', { inPage: true }) so those items render as showSection(...)
// calls instead of page navigations; every other admin page renders them as normal links
// to analytics.html?section=<section>.

const ADMIN_NAV_ITEMS = [
  {
    key: "overview",
    section: "overview",
    href: "analytics.html",
    label: "Overview",
    icon: 'M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6',
    inBottomNav: true,
  },
  {
    key: "patients",
    section: "patients",
    href: "analytics.html?section=patients",
    label: "Patients",
    icon: 'M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z',
    inMobileMenu: true,
  },
  {
    key: "consultations",
    section: "consultations",
    href: "analytics.html?section=consultations",
    label: "Consultations",
    icon: 'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2',
    inMobileMenu: true,
  },
  {
    key: "medicines-analytics",
    section: "medicines",
    href: "analytics.html?section=medicines",
    label: "Medicines",
    icon: 'M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z',
    inMobileMenu: true,
  },
  {
    key: "tests-analytics",
    section: "tests",
    href: "analytics.html?section=tests",
    label: "Tests & Diagnoses",
    icon: 'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01',
    inMobileMenu: true,
  },
  {
    key: "demographics",
    section: "demographics",
    href: "analytics.html?section=demographics",
    label: "Demographics",
    icon: 'M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z',
    inMobileMenu: true,
  },
  {
    key: "billing",
    section: "billing",
    href: "analytics.html?section=billing",
    label: "Billing",
    icon: 'M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z',
    requiresBilling: true,
    inMobileMenu: true,
  },
  {
    key: "appointments",
    section: "appointments",
    href: "analytics.html?section=appointments",
    label: "Appointments",
    icon: 'M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z',
    inMobileMenu: true,
  },
  {
    key: "staff",
    href: "doctors.html",
    label: "Manage Staff",
    icon: 'M18 9v3m0 0v3m0-3h3m-3 0h-3m-2-5a4 4 0 11-8 0 4 4 0 018 0zM3 20a6 6 0 0112 0v1H3v-1z',
    inBottomNav: true,
    bottomNavLabel: "Staff",
  },
  {
    key: "admissions",
    href: "admissions.html",
    label: "Admissions",
    icon: 'M19 14l-7 7m0 0l-7-7m7 7V3',
    inMobileMenu: true,
  },
  {
    key: "medicine-catalog",
    href: "medicines.html",
    label: "Medicine Catalog",
    icon: 'M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4',
    inMobileMenu: true,
  },
  {
    key: "test-catalog",
    href: "tests-catalog.html",
    label: "Test Catalog",
    icon: 'M9 3h6m-6 0v5.586a1 1 0 01-.293.707L4.293 13.707A1 1 0 004 14.414V19a2 2 0 002 2h12a2 2 0 002-2v-4.586a1 1 0 00-.293-.707l-4.414-4.414A1 1 0 0115 8.586V3',
    inMobileMenu: true,
  },
  {
    key: "radiology-templates",
    href: "#",
    label: "Radiology Templates",
    icon: 'M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2V9z M9 22V12h6v10',
    onclick: "toast('Radiology Templates -- Coming Soon','info');return false;",
    inMobileMenu: true,
  },
  {
    key: "hiv-results",
    href: "#",
    label: "HIV Results",
    icon: 'M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z',
    onclick: "toast('HIV Results -- Coming Soon','info');return false;",
    inMobileMenu: true,
  },
  {
    key: "complaints",
    href: "#",
    label: "Complaints",
    icon: 'M7 8h10M7 12h4m1 8l-4-4H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-3l-4 4z',
    onclick: "toast('Complaints & Suggestions -- Coming Soon','info');return false;",
    inMobileMenu: true,
  },
  {
    key: "attendance",
    href: "attendance.html",
    label: "Attendance",
    icon: 'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4',
    inMobileMenu: true,
  },
  {
    key: "rooms",
    href: "rooms.html",
    label: "Rooms",
    icon: 'M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2M19 21H5m0 0H3m9-9h.01',
    inBottomNav: true,
  },
  {
    key: "reports",
    href: "#",
    label: "Reports",
    icon: 'M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z',
    onclick: "toast('Reports -- Coming Soon','info');return false;",
    inMobileMenu: true,
  },
  {
    key: "audit",
    href: "audit.html",
    label: "Audit Log",
    icon: 'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4',
    inMobileMenu: true,
  },
];

function _adminSvg(pathD, size) {
  const s = size || 20;
  return `<svg width="${s}" height="${s}" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="${pathD}" /></svg>`;
}

// Resolve {id, href, onclick} for a nav item depending on whether we're rendering
// in-page (analytics.html driving its own tabs) or as a cross-page link.
function _adminItemNav(item, opts, forMobile) {
  const prefix = forMobile ? "closeMobileMenu();" : "";
  if (opts.inPage && item.section) {
    return {
      id: `nav-${item.section}`,
      href: "#",
      onclick: `${prefix}showSection('${item.section}');return false;`,
    };
  }
  if (item.onclick) {
    return { id: "", href: "#", onclick: `${prefix}${item.onclick}` };
  }
  return { id: "", href: item.href, onclick: "" };
}

function renderAdminNav(activeKey, opts) {
  opts = opts || {};
  const doc = (typeof getDoctor === "function") ? getDoctor() : null;
  const billingOn = !!(doc && doc.billing_enabled);
  const visibleItems = ADMIN_NAV_ITEMS.filter((it) => !it.requiresBilling || billingOn);

  // ---- Sidebar ----
  const sidebarEl = document.getElementById("app-sidebar");
  if (sidebarEl) {
    let html = '<div class="sidebar-section-label">Hospital Admin</div>';
    visibleItems.forEach((item) => {
      const active = item.key === activeKey ? " active" : "";
      const nav = _adminItemNav(item, opts, false);
      const idAttr = nav.id ? ` id="${nav.id}"` : "";
      const onclickAttr = nav.onclick ? ` onclick="${nav.onclick}"` : "";
      html += `<a class="nav-item${active}"${idAttr} href="${nav.href}"${onclickAttr}>${_adminSvg(item.icon)}${item.label}</a>`;
    });
    sidebarEl.innerHTML = html;
  }

  // ---- Bottom nav (Home / Rooms / Staff / Menu) ----
  const bottomNavEl = document.getElementById("app-bottom-nav");
  if (bottomNavEl) {
    let html = "";
    ADMIN_NAV_ITEMS.filter((it) => it.inBottomNav).forEach((item) => {
      const active = item.key === activeKey ? " active" : "";
      const nav = _adminItemNav(item, opts, false);
      const idAttr = nav.id ? ` id="bn-${nav.id}"` : "";
      const onclickAttr = nav.onclick ? ` onclick="${nav.onclick}"` : "";
      html += `<a class="bottom-nav-item${active}"${idAttr} href="${nav.href}"${onclickAttr}>${_adminSvg(item.icon)}${item.bottomNavLabel || item.label}</a>`;
    });
    html += `<button class="bottom-nav-item" onclick="openMobileMenu()">${_adminSvg("M4 6h16M4 12h16M4 18h16")}Menu</button>`;
    bottomNavEl.innerHTML = html;
  }

  // ---- Mobile "More" menu ----
  const mobileMenuEl = document.getElementById("app-mobile-menu-body");
  if (mobileMenuEl) {
    let html = "";
    visibleItems.filter((it) => it.inMobileMenu).forEach((item) => {
      const nav = _adminItemNav(item, opts, true);
      const idAttr = nav.id ? ` id="mnav-${nav.id}"` : "";
      const onclickAttr = nav.onclick ? ` onclick="${nav.onclick}"` : "";
      html += `<a class="mobile-menu-item"${idAttr} href="${nav.href}"${onclickAttr}>${_adminSvg(item.icon)}${item.label}</a>`;
    });
    html += `<a class="mobile-menu-item" href="#" onclick="closeMobileMenu();logout();return false;" style="color:var(--danger)">${_adminSvg("M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1")}Sign out</a>`;
    mobileMenuEl.innerHTML = html;
  }
}