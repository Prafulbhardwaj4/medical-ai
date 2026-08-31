// tier-catalog.js
// Single source of truth for MedScribe's tier/feature list.
// Mirrors frontend/pages/home.html's #pricing section exactly — home.html
// renders its pricing cards FROM this file (see the render script at the
// bottom of home.html), and the shared Upgrade Modal (upgrade-gate.js)
// also reads from here. If pricing or the feature list changes, edit
// ONLY this file — never hardcode a second copy anywhere else.

const TIER_CATALOG = [
  {
    key: "foundation",
    label: "Foundation",
    price: "\u20B99,999",
    period: "/month",
    scope: "Unlimited staff logins, every role",
    comingSoon: false,
    premium: false,
    features: [
      "OPD: registration, token queue, consultation, prescriptions",
      "Lab orders, pharmacy dispense, billing & GST",
      "Pathology / Lab module",
      "Pharmacy module",
      "Online appointment booking",
      "Patient Portal",
      "Radiology / Imaging",
    ],
  },
  {
    key: "growth",
    label: "Growth",
    price: "\u20B929,999",
    period: "/month",
    scope: "Up to 5,000 consultations/month",
    comingSoon: false,
    premium: false,
    features: [
      "Everything in Foundation",
      "IPD / Admissions & ward management unlocked",
      "AI Medical Scribe for OPD (voice-to-prescription)",
      "Staff chat (staff \u2194 admin)",
    ],
  },
  {
    key: "scale",
    label: "Scale",
    price: "\u20B949,999",
    period: "/month",
    scope: "Up to 10,000 consultations/month",
    comingSoon: true,
    premium: false,
    features: [
      "Everything in Growth",
      "Higher AI Scribe consultation volume",
      "Pregnancy / Maternity management",
      "OT / Surgery clinical documentation",
      "Referrals to other onboarded hospitals",
    ],
  },
  {
    key: "enterprise",
    label: "Enterprise",
    price: "\u20B966,999",
    period: "/month",
    scope: "Unlimited consultations",
    comingSoon: true,
    premium: true,
    features: [
      "Everything in Scale",
      "AI Scribe for admitted / IPD patients",
      "Blood Bank / transfusion management",
      "Specialty-specific tools (e.g. orthopaedic)",
      "White-glove onboarding \u2014 we set up every staff account, your full test catalog, and medicine list for you",
    ],
  },
];

function tierLabel(key) {
  const t = TIER_CATALOG.find((t) => t.key === key);
  return t ? t.label : key;
}

function tierIndex(key) {
  return TIER_CATALOG.findIndex((t) => t.key === key);
}