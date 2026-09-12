// Guided "demo patient" walkthrough for doctor/sub_admin onboarding.
// Spans three real pages (dashboard.html -> patient.html ->
// consultation.html) with a fake patient that never touches a real API
// call and is never registered anywhere — the ?demo=1 query param is the
// single source of truth carried from page to page (no sessionStorage,
// so there's nothing that can go stale into a later real session).
//
// Currently a manually-triggered "Product Tour" from the profile menu
// (dashboard.html only) — wiring it to auto-fire on first login is a
// follow-up once this has been reviewed.

const DEMO_PATIENT = {
  name: "Rina Kumari (Demo)",
  uid: "DEMO-0001",
  age: 34,
  gender: "Female",
  phone: "98765 43210",
  address: "123 MG Road, Ambala (demo address)",
  vitalsSummary: "BP 122/80 · Pulse 78 · Temp 98.4°F · SpO2 98%",
  transcript:
    "Doctor: What brings you in today?\n" +
    "Patient: I've had fever and body ache for the last three days, it's worse at night.\n" +
    "Doctor: Any cough, cold, or breathing difficulty?\n" +
    "Patient: No cough, just tiredness and a mild headache.\n" +
    "Doctor: Alright, let's check your vitals and start you on some medicines for the fever.",
  chiefComplaint: "Fever and body ache for the last 3 days, worse at night",
  diagnosis: "Viral fever (suspected)",
  advice: "Plenty of fluids, rest, and light home-cooked food. Return immediately if fever crosses 102°F or breathing becomes difficult.",
  followup: "Review after 3 days if fever persists",
  vitals: { bp: "122/80", temperature: "98.4°F", pulse: "78", spo2: "98%" },
  medicines: [
    { name: "Paracetamol", brand_name: "Crocin", dosage: "650mg", frequency: "1-0-1", duration: "3 days", times_per_day: 2, duration_days: 3, schedule: "otc" },
    { name: "Cetirizine", brand_name: "", dosage: "10mg", frequency: "0-0-1", duration: "3 days", times_per_day: 1, duration_days: 3, schedule: "otc" },
  ],
};

function isDoctorDemoMode() {
  return location.search === "?demo=1";
}

function exitDoctorDemo() {
  window.location.href = "/pages/dashboard.html";
}

// ── dashboard.html ──────────────────────────────────────────────
function startDoctorProductTour() {
  const card = document.getElementById("demo-tour-card");
  if (card) card.style.display = "";

  const steps = [
    { target_selector: "#nav-home", placement: "right", device: "both",
      title: "Welcome", description: "This is your Home tab — everything for today's patients lives here. Let's take a quick look, then try a full demo consultation." },
    { target_selector: "#queue-card-walkin", placement: "top", device: "both",
      title: "Walk-ins", description: "Patients who walked in today and checked in at reception show up here, in order." },
    { target_selector: "#queue-card-online", placement: "top", device: "both",
      title: "Online Appointments", description: "Patients who booked an appointment online land in this second queue." },
    { target_selector: "#demo-tour-card", placement: "bottom", device: "both",
      title: "Try a Demo Patient", nextLabel: "Consult →",
      description: "We've added a demo patient below so you can walk through a full consultation end to end. Nothing you do here is saved or sent to your hospital's records — it's just for you to learn the flow.",
      onNext: () => { window.location.href = "/pages/patient.html?demo=1"; return false; } },
  ];

  startLocalTour(steps, {
    onSkip: () => { if (card) card.style.display = "none"; },
  });
}

// ── patient.html ────────────────────────────────────────────────
function renderDoctorDemoPatientPage() {
  document.title = "MedScribe — Rina Kumari (Demo)";
  document.getElementById("p-name").textContent = DEMO_PATIENT.name;
  document.getElementById("p-uid").textContent = DEMO_PATIENT.uid;
  document.getElementById("p-age").textContent = DEMO_PATIENT.age + " yrs";
  document.getElementById("p-gender").textContent = DEMO_PATIENT.gender;
  document.getElementById("p-phone").textContent = DEMO_PATIENT.phone;
  document.getElementById("p-address").textContent = DEMO_PATIENT.address;

  // Hide every action that would otherwise fire a real API call against a
  // patient id that doesn't exist — only "+ New Consultation" is wired for
  // the demo, and even that never leaves this page for real.
  ["btn-continue-consult"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = "none";
  });
  document.querySelectorAll('[onclick*="openReportsModal"], [onclick*="openEditPatient"]').forEach(el => {
    el.style.display = "none";
  });

  const newConsultBtn = document.getElementById("btn-new-consult");
  if (newConsultBtn) newConsultBtn.setAttribute("onclick", "window.location.href='/pages/consultation.html?demo=1'");

  const banner = document.createElement("div");
  banner.style.cssText = "background:#f0fdfa;border:1px solid var(--teal);border-radius:var(--radius);padding:10px 14px;margin-bottom:16px;font-size:13px;color:var(--navy);display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap";
  banner.innerHTML = `<span>🧪 Demo mode — this is a made-up patient. Nothing here is saved.</span>
    <button class="btn btn-outline btn-sm" onclick="exitDoctorDemo()">Exit Demo</button>`;
  document.querySelector("main")?.prepend(banner);
}

function runDoctorDemoPatientTour() {
  const steps = [
    { target_selector: "#p-name", placement: "bottom", device: "both",
      title: "Patient Overview", description: "This is what a patient's page looks like — their details, vitals, and visit history all in one place." },
    { target_selector: "#btn-new-consult", placement: "top", device: "both",
      title: "Start the Consultation", nextLabel: "New Consultation →",
      description: "This is where a real consultation begins. Click New Consultation to see how MedScribe helps you record and structure a visit.",
      onNext: () => { window.location.href = "/pages/consultation.html?demo=1"; return false; } },
  ];
  startLocalTour(steps, { onSkip: exitDoctorDemo });
}

// ── consultation.html ───────────────────────────────────────────
function runDoctorDemoConsultation() {
  document.getElementById("patient-label").textContent = `Patient: ${DEMO_PATIENT.name} · ${DEMO_PATIENT.uid}`;
  const vitalsSummaryEl = document.getElementById("nurse-vitals-summary");
  if (vitalsSummaryEl) vitalsSummaryEl.textContent = DEMO_PATIENT.vitalsSummary;

  const banner = document.createElement("div");
  banner.style.cssText = "background:#f0fdfa;border:1px solid var(--teal);border-radius:var(--radius);padding:10px 14px;margin-bottom:16px;font-size:13px;color:var(--navy);display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap";
  banner.innerHTML = `<span>🧪 Demo mode — nothing here is saved or sent anywhere.</span>
    <button class="btn btn-outline btn-sm" onclick="exitDoctorDemo()">Exit Demo</button>`;
  document.querySelector(".steps")?.before(banner);

  const foundation = typeof isFoundationTier === "function" && isFoundationTier();

  if (foundation) {
    document.getElementById("steps").style.display = "none";
    document.getElementById("panel-2-title").textContent = "Consultation Details";
    document.getElementById("panel-2-ai-badge").style.display = "none";
    _fillDemoReviewPanel();
    goStep(2);
    _runDemoReviewTour(/* cameFromRecording */ false);
  } else {
    document.getElementById("recorder-wrap").style.display = "none";
    document.getElementById("transcript").value = DEMO_PATIENT.transcript;
    document.getElementById("btn-structure").disabled = false;
    _runDemoRecordTour();
  }
}

function _runDemoRecordTour() {
  const steps = [
    { target_selector: "#transcript", placement: "top", device: "both",
      title: "The Transcript", description: "In a real consultation, MedScribe records and transcribes the conversation automatically. We've filled in a sample transcript here so you can see what comes next." },
    { target_selector: "#btn-structure", placement: "top", device: "both",
      title: "Analyse with AI", nextLabel: "Analyse with AI →",
      description: "This is the core of MedScribe — click here and AI turns the raw transcript into a structured prescription: complaint, diagnosis, medicines, and advice.",
      onNext: () => {
        toast("Analysing transcript…", "info");
        setTimeout(() => {
          document.getElementById("panel-2-title").textContent = "Review & Edit Prescription";
          _fillDemoReviewPanel();
          goStep(2);
          _runDemoReviewTour(true);
        }, 900);
        return false;
      } },
  ];
  startLocalTour(steps, { onSkip: exitDoctorDemo });
}

function _fillDemoReviewPanel() {
  window._lastEditedData = {
    chief_complaint: DEMO_PATIENT.chiefComplaint,
    diagnosis: DEMO_PATIENT.diagnosis,
    advice: DEMO_PATIENT.advice,
    followup: DEMO_PATIENT.followup,
    nurse_instructions: "",
    medicines: DEMO_PATIENT.medicines,
    vitals: DEMO_PATIENT.vitals,
  };
}

function _runDemoReviewTour(cameFromRecording) {
  const introDescription = cameFromRecording
    ? "MedScribe just structured the whole consultation from that transcript — vitals, complaint, diagnosis, and medicines, all filled in automatically."
    : "On the Foundation plan, AI Scribe isn't included, so consultations are entered directly here instead of via recording — same fields, just typed in by hand.";
  const steps = [
    { target_selector: "#vitals-review-fields", placement: "bottom", device: "both",
      title: "Vitals", description: introDescription },
    { target_selector: "#f-diagnosis", placement: "bottom", device: "both",
      title: "Diagnosis", description: "Chief complaint and diagnosis — edit freely, this is a normal text field either way." },
    { target_selector: "#med-rows", placement: "top", device: "both",
      title: "Medicines", description: "Add, edit, or remove medicines here. Search the box above to add from your hospital's medicine list." },
    { target_selector: "#confirm-btn", placement: "top", device: "both",
      title: "Generate the Prescription", nextLabel: "Confirm & Generate PDF →",
      description: "This is the last step — confirming generates a token and a PDF prescription for the patient. For this demo, nothing is actually saved or sent.",
      onNext: () => { _showDemoConfirmedPanel(); return false; } },
  ];
  startLocalTour(steps, { onSkip: exitDoctorDemo });
}

function _showDemoConfirmedPanel() {
  document.getElementById("token-display").textContent = "DEMO-0001";
  goStep(3);
  const viewPdfBtn = document.querySelector('#panel-3 [onclick="viewPdf()"]');
  if (viewPdfBtn) viewPdfBtn.setAttribute("onclick", "toast('This is a demo — no real PDF is generated.', 'info')");
  document.querySelectorAll('#panel-3 [onclick="goBack()"]').forEach(btn => {
    btn.textContent = "Finish Demo";
    btn.setAttribute("onclick", "exitDoctorDemo()");
  });
}