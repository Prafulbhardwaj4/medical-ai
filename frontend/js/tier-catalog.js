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
    yearlyPrice: "\u20B91,19,999",
    yearlyPeriod: "/year",
    yearlyBenefit: "Pay for 12 months, get 13 \u2014 one month of service free",
    yearlyPerks: ["Pay for 12 months, get 13 \u2014 one month of service free"],
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
    ],
  },
  {
    key: "growth",
    label: "Growth",
    price: "\u20B929,999",
    period: "/month",
    yearlyPrice: "\u20B93,49,999",
    yearlyPeriod: "/year",
    yearlyBenefit: "Extra 2,000 consultations across the year, plus free early access to the Radiology module when it launches (coming soon)",
    yearlyPerks: [
      "Extra 2,000 consultations across the year (62,000 AI Scribe consultations in total)",
      "Radiology module: free early access when it launches (coming soon)",
    ],
    scope: "5,000 consultations/month",
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
    // Real target pricing, decided but not shown until this tier is
    // actually sellable: \u20B944,999/month, \u20B95,25,000/year (+5,000 bonus
    // AI Scribe consultations across the year on top of the 120,000
    // baseline). Flip comingSoon to false and fill these back in when ready.
    price: "-",
    period: "/month",
    yearlyPrice: "-",
    yearlyPeriod: "/year",
    yearlyBenefit: "5,000 bonus AI Scribe consultations across the year, on top of the 120,000 you already get",
    scope: "10,000 consultations/month",
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
    price: "-",
    period: "/month",
    yearlyPrice: "-",
    yearlyPeriod: "/year",
    yearlyBenefit: "Custom quotation, priced around your hospital's actual consultation volume",
    scope: "Unlimited consultations",
    comingSoon: true,
    premium: true,
    features: [
      "Everything in Scale",
      "AI Scribe for admitted / IPD patients",
      "Radiology / Imaging (X-ray, CT, MRI, ultrasound ordering and reports)",
      "Blood Bank / transfusion management",
      "Specialty-specific tools (e.g. orthopaedic)",
      "White-glove onboarding \u2014 we set up every staff account, your full test catalog, and medicine list for you",
    ],
  },
];

function tierLabel(key) {
  const t = TIER_CATALOG.find((t) => t.key === key);
  return t ? t.label : "Unknown plan";
}

function tierIndex(key) {
  return TIER_CATALOG.findIndex((t) => t.key === key);
}