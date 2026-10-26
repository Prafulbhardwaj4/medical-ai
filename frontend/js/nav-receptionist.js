// nav-receptionist.js
// Single source of truth for the receptionist sidebar, bottom tabs and mobile "More" menu.
// A page that needs them includes this file + api.js, keeps the containers
// (#app-sidebar or #sidebar-receptionist, #app-bottom-nav or #bottom-nav-receptionist,
// #app-mobile-menu-body) and calls renderReceptionistNav("KEY") once the user is known.
// To add, remove or reorder an item: edit RECEPTIONIST_NAV_ITEMS and the three key lists below only.

const RECEPTIONIST_NAV_ITEMS = {
  home: {
    href: "receptionist.html", label: "Home",
    icon: "M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6",
  },
  appointments: {
    href: "receptionist.html?tab=portal", label: "Appointments",
    icon: "M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z",
  },
  admissions: {
    href: "admissions.html", label: "Admissions",
    icon: "M19 14l-7 7m0 0l-7-7m7 7V3",
  },
  attendance: {
    href: "receptionist.html?tab=attendance", label: "Attendance",
    icon: "M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z",
  },
  availability: {
    href: "receptionist.html?tab=availability", label: "Manage Availability",
    icon: "M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z",
  },
  patients: {
    href: "receptionist.html?tab=patients", label: "Patients",
    icon: "M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0",
  },
  dayend: {
    href: "receptionist.html?dayend=1", label: "Day-End Summary",
    icon: "M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z",
  },
  refunds: {
    href: "refunds.html", label: "Refunds",
    icon: "M3 10h11a5 5 0 010 10H9m-6-10l4-4m-4 4l4 4",
  },
};

const RECEPTIONIST_SIDEBAR_KEYS = ["home", "appointments", "admissions", "availability", "patients"];
const RECEPTIONIST_QUICK_KEYS = ["dayend", "refunds"];
const RECEPTIONIST_BOTTOM_KEYS = ["home", "appointments", "admissions", "attendance"];
// "Appointments" is a bottom tab, so it is not repeated in More.
const RECEPTIONIST_MENU_KEYS = ["patients", "availability", "refunds"];

function _recSvg(path, sized) {
  const size = sized === false ? "" : ' width="20" height="20"';
  return `<svg${size} fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="${path}"/></svg>`;
}

function renderReceptionistNav(activeKey) {
  const sidebarEl = document.getElementById("sidebar-receptionist") || document.getElementById("app-sidebar");
  if (sidebarEl) {
    let html = '<div class="sidebar-section-label">Navigation</div>';
    RECEPTIONIST_SIDEBAR_KEYS.forEach((key) => {
      const it = RECEPTIONIST_NAV_ITEMS[key];
      html += `<a class="nav-item${key === activeKey ? " active" : ""}" href="${it.href}">${_recSvg(it.icon, false)}${it.label}</a>`;
    });
    html += '<div class="nav-divider"></div><div class="sidebar-section-label">Quick Actions</div>';
    RECEPTIONIST_QUICK_KEYS.forEach((key) => {
      const it = RECEPTIONIST_NAV_ITEMS[key];
      html += `<a class="nav-item${key === activeKey ? " active" : ""}" href="${it.href}">${_recSvg(it.icon, false)}${it.label}</a>`;
    });
    sidebarEl.innerHTML = html;
    sidebarEl.style.display = "";
  }

  const bottomEl = document.getElementById("bottom-nav-receptionist") || document.getElementById("app-bottom-nav");
  if (bottomEl) {
    let html = "";
    RECEPTIONIST_BOTTOM_KEYS.forEach((key) => {
      const it = RECEPTIONIST_NAV_ITEMS[key];
      html += `<a class="bottom-nav-item${key === activeKey ? " active" : ""}" href="${it.href}">${_recSvg(it.icon)}${it.label}</a>`;
    });
    html += `<button class="bottom-nav-item" onclick="openMobileMenu()">${_recSvg("M4 6h16M4 12h16M4 18h16")}Menu</button>`;
    bottomEl.innerHTML = html;
    bottomEl.style.display = "";
  }

  const menuEl = document.getElementById("app-mobile-menu-body");
  if (menuEl) {
    menuEl.innerHTML = RECEPTIONIST_MENU_KEYS.map((key) => {
      const it = RECEPTIONIST_NAV_ITEMS[key];
      return `<a class="mobile-menu-item${key === activeKey ? " active" : ""}" href="${it.href}">${_recSvg(it.icon)}${it.label}</a>`;
    }).join("");
  }
}