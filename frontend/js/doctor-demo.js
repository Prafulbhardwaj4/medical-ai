// Guided "demo patient" walkthrough for doctor/sub_admin onboarding.
// Spans three real pages (dashboard.html -> patient.html ->
// consultation.html) with a fake patient that never touches a real API
// call and is never registered anywhere — the ?demo=1 query param is the
// single source of truth carried from page to page (no sessionStorage,
// so there's nothing that can go stale into a later real session).
//
// Currently a manually-triggered "Tutorial" item from the profile menu
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
  // For the one demo entry shown in Visit History on patient.html — a past,
  // already-confirmed visit, distinct from today's in-progress one above.
  pastVisit: {
    token: "T-0917",
    date: "10 Sep 2026",
    complaint: "Seasonal cold and mild cough",
    doctor: "Dr. Sandeep Dabas",
    diagnosis: "Common cold",
    vitals: { BP: "118/76", Pulse: "72" },
    medicines: [{ name: "Cetirizine", dosage: "10mg", frequency: "0-0-1", duration: "5 days" }],
  },
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
    { target_selector: "#attendance-card", placement: "bottom", device: "desktop",
      title: "Today's Status", description: "Mark yourself present, on break, or off duty for the day — right from here." },
    { target_selector: "#attendance-card", click_before: "#bn-attendance", placement: "bottom", device: "mobile",
      title: "Today's Status", description: "Mark yourself present, on break, or off duty for the day — right from here." },
    { target_selector: "#up-next-card-doctor", placement: "bottom", device: "both",
      title: "Up Next", description: "The next patient in line for you shows up here." },
    { target_selector: "#queue-card-walkin", placement: "bottom", device: "both",
      title: "Walk-ins", description: "Patients who walked in today and checked in at reception show up here, in order." },
    { target_selector: "#queue-card-online", placement: "top", device: "both",
      title: "Online Appointments", description: "Patients who booked an appointment online land in this second queue." },
    { target_selector: "#nav-patients-tab", placement: "right", device: "desktop",
      title: "Patients", description: "Every patient you've ever seen, searchable from here." },
    { target_selector: "a.nav-item[href='admissions.html']", placement: "right", device: "desktop",
      title: "Admissions", description: "Ward vacancy and every currently admitted patient live here." },
    { target_selector: "a.bottom-nav-item[href='admissions.html']", placement: "top", device: "mobile",
      title: "Admissions", description: "Ward vacancy and every currently admitted patient live here." },
    { target_selector: "a.nav-item[href='doctor-slots.html']", placement: "right", device: "desktop",
      title: "My Availability", description: "Set which days and times you're open for booking." },
    { target_selector: "[data-tutorial-id='doctor-mobile-menu-btn']", placement: "top", device: "mobile",
      title: "More", description: "Patients and My Availability live here on mobile." },
    { target_selector: "#suggestion-header-btn", placement: "bottom", device: "both",
      title: "Suggest", description: "Have an idea to improve MedScribe? Send it here." },
    { target_selector: "#chat-header-btn", placement: "bottom", device: "both",
      title: "Chat", description: "Message your hospital admin directly from here." },
    { target_selector: ".topbar-profile-btn", placement: "bottom", device: "both",
      title: "Profile", description: "Your account settings — and you can replay this tutorial from here any time." },
    { target_selector: "#demo-tour-card", placement: "bottom", offsetY: 12, device: "both",
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

  // Real onclicks stay neutralized in demo mode — these would otherwise
  // fire real API calls against a patient id that doesn't exist. Only
  // "+ New Consultation" actually navigates anywhere.
  document.getElementById("btn-send-admit")?.setAttribute("onclick", "toast('Just for the tutorial — nothing to open here.','info')");
  document.querySelector('[onclick="openReportsModal(patientId)"]')?.setAttribute("onclick", "toast('Just for the tutorial — nothing to open here.','info')");
  document.querySelectorAll('[onclick*="openEditPatient"]').forEach(el => { el.style.display = "none"; });

  const continueBtn = document.getElementById("btn-continue-consult");
  if (continueBtn) {
    continueBtn.style.display = "";
    continueBtn.setAttribute("onclick", "toast('Shown for same-day return patients — nothing to open here.','info')");
  }

  const newConsultBtn = document.getElementById("btn-new-consult");
  if (newConsultBtn) newConsultBtn.setAttribute("onclick", "window.location.href='/pages/consultation.html?demo=1'");

  // Vitals (Recorded by Nurse) — normally hidden until a nurse actually
  // records something for this visit.
  const vitalsCard = document.getElementById("vitals-card");
  if (vitalsCard) {
    vitalsCard.style.display = "";
    document.getElementById("vitals-rows").innerHTML = Object.entries(DEMO_PATIENT.vitals).map(([k, v]) =>
      `<div><div style="font-size:12px;color:var(--slate)">${k.toUpperCase()}</div><div style="font-weight:700;color:var(--navy)">${v}</div></div>`
    ).join("");
  }

  // One past visit, same shape as loadHistory()'s real template, so the
  // demo looks exactly like a real Visit History card — just static.
  document.getElementById("visit-count").textContent = "1 visit";
  const pv = DEMO_PATIENT.pastVisit;
  document.getElementById("visit-list").innerHTML = `
    <div class="visit-card">
      <div class="visit-header">
        <div style="display:flex;align-items:center;flex-wrap:wrap;gap:8px 12px;min-width:0">
          <span class="badge badge-navy">${pv.token}</span>
          <span style="font-size:0.875rem;font-weight:600;color:var(--navy)">${pv.date}</span>
          <span style="font-size:0.82rem;color:var(--slate)">${pv.complaint}</span>
          <span style="font-size:0.82rem;color:var(--teal);font-weight:500">${pv.doctor}</span>
        </div>
        <div style="display:flex;align-items:center;flex-wrap:wrap;gap:8px 10px">
          <span class="badge badge-green">WhatsApp: sent</span>
        </div>
      </div>
      <div class="visit-body" style="display:block">
        <div class="visit-detail-grid" style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:14px">
          <div class="detail-section">
            <div class="detail-label">Chief Complaint</div>
            <div class="detail-value">${pv.complaint}</div>
          </div>
          <div class="detail-section">
            <div class="detail-label">Diagnosis</div>
            <div class="detail-value">${pv.diagnosis}</div>
          </div>
        </div>
        <div class="detail-section">
          <div class="detail-label">Vitals</div>
          <div style="display:flex;flex-wrap:wrap;gap:8px">
            ${Object.entries(pv.vitals).map(([k, v]) => `<span style="background:var(--smoke);padding:3px 10px;border-radius:6px;font-size:0.82rem"><strong>${k}:</strong> ${v}</span>`).join("")}
          </div>
        </div>
        <div class="detail-section">
          <div class="detail-label">Medicines</div>
          <div>${pv.medicines.map(m => `<span class="med-pill">${m.name} ${m.dosage} — ${m.frequency} × ${m.duration}</span>`).join("")}</div>
        </div>
      </div>
    </div>`;

  const banner = document.createElement("div");
  banner.style.cssText = "background:#f0fdfa;border:1px solid var(--teal);border-radius:var(--radius);padding:10px 14px;margin-bottom:16px;font-size:13px;color:var(--navy);display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap";
  banner.innerHTML = `<span>🧪 Demo mode — this is a made-up patient. Nothing here is saved.</span>
    <button class="btn btn-outline btn-sm" onclick="exitDoctorDemo()">Exit Demo</button>`;
  document.querySelector("main")?.prepend(banner);
}

function runDoctorDemoPatientTour() {
  const steps = [
    { target_selector: "#patient-header", placement: "bottom", device: "both",
      title: "Patient Overview", description: "Every patient's details and quick actions live at the top of their own page like this." },
    { target_selector: "#vitals-card", placement: "top", device: "both",
      title: "Vitals Recorded", description: "Once a nurse records vitals for this visit, they show up here." },
    { target_selector: "#visit-history-card", placement: "top", device: "both",
      title: "Visit History", description: "Every past visit for this patient, expandable for the full details of each one." },
    { target_selector: "#btn-send-admit", placement: "bottom", device: "both",
      title: "Send Admit", description: "Admit this patient to a ward directly from their own page." },
    { target_selector: "[onclick*=\"toast('Just for the tutorial\"]", placement: "bottom", device: "both",
      title: "Reports", description: "Lab and radiology reports for this patient, all in one place." },
    { target_selector: "#btn-continue-consult", placement: "top", device: "both",
      title: "Continue Consultation", description: "If a patient returns the same day, pick up their consultation right where it was left off instead of starting fresh." },
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
  document.querySelector('#patient-context-card [onclick="openReportsModal(patientId)"]')
    ?.setAttribute("onclick", "toast('Just for the tutorial — nothing to open here.','info')");

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
    _runDemoTopTour();
  }
}

function _runDemoTopTour() {
  const steps = [
    { target_selector: "#nurse-vitals-wrap", placement: "bottom", device: "both",
      title: "Vitals", description: "Vitals a nurse recorded for this visit, before the consultation even starts." },
    { target_selector: "#patient-context-card [onclick*=\"toast('Just for the tutorial\"]", placement: "bottom", device: "both",
      title: "Reports", description: "Lab and radiology reports for this patient, right from the consultation screen." },
    { target_selector: "#panel-1", placement: "bottom", device: "both",
      title: "Record Consultation", description: "This is where a real consultation gets recorded and transcribed automatically." },
    { target_selector: "#transcript", placement: "top", device: "both",
      title: "The Transcript", nextLabel: "Analyse with AI →",
      description: "We've filled in a sample transcript here so you can see what comes next — in a real consultation this fills in automatically as you record.",
      onNext: () => {
        document.getElementById("recorder-wrap").style.display = "none";
        document.getElementById("transcript").value = DEMO_PATIENT.transcript;
        document.getElementById("btn-structure").disabled = false;
        _runDemoStructureTour();
        return false;
      } },
  ];
  startLocalTour(steps, { onSkip: exitDoctorDemo });
}

function _runDemoStructureTour() {
  const steps = [
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
  // The real button under this tooltip calls doConfirm(), which hits the
  // live API — in demo mode there's no real patientId, so that call would
  // 422. Neutralizing it here (the moment the panel renders, not only via
  // the tour's own Next) means clicking the real button directly, not the
  // tour's button, is safe too.
  document.getElementById("confirm-btn")?.setAttribute("onclick", "_showDemoConfirmedPanel()");
}

function _runDemoReviewTour(cameFromRecording) {
  const introDescription = cameFromRecording
    ? "MedScribe just structured the whole consultation from that transcript — vitals, complaint, diagnosis, and medicines, all filled in automatically."
    : "On the Foundation plan, AI Scribe isn't included, so consultations are entered directly here instead of via recording — same fields, just typed in by hand.";
  const steps = [
    { target_selector: "#vitals-section", placement: "bottom", device: "both",
      title: "Vitals", description: introDescription },
    { target_selector: "#diagnosis-section", placement: "bottom", device: "both",
      title: "Diagnosis", description: "Chief complaint and diagnosis — edit freely, this is a normal text field either way." },
    { target_selector: "#medicines-section", placement: "top", device: "both",
      title: "Medicines", description: "Add, edit, or remove medicines here. Search the box above to add from your hospital's medicine list." },
    { target_selector: "#test-catalog-block", placement: "top", device: "both",
      title: "Tests / Investigations", description: "Order lab tests for this patient the same way — search and add from your hospital's test list." },
    { target_selector: "#advice-section", placement: "top", device: "both",
      title: "Doctor's Advice", description: "General advice for the patient to follow after this visit." },
    { target_selector: "#followup-section", placement: "top", device: "both",
      title: "Follow-up Instructions", description: "When the patient should come back, if at all." },
    { target_selector: "#nurse-instructions-section", placement: "top", device: "both",
      title: "Post-Consultation Nurse Instructions", description: "Optional — a dressing, an injection, anything a nurse should do right after this consultation." },
    { target_selector: "#confirm-btn", placement: "top", device: "both",
      title: "Generate the Prescription", nextLabel: "Confirm & Generate PDF →",
      description: "This is the last step — confirming generates a token and a PDF prescription for the patient. For this demo, nothing is actually saved or sent.",
      onNext: () => { _showDemoConfirmedPanel(); return false; } },
  ];
  startLocalTour(steps, { onSkip: exitDoctorDemo });
}

function _showDemoConfirmedPanel() {
  document.getElementById("token-display").textContent = "DEMO-0001";
  document.getElementById("patient-context-card").style.display = "none"; // the raw vitals summary above is redundant once the prescription's already generated
  goStep(3);
  const viewPdfBtn = document.querySelector('#panel-3 [onclick="viewPdf()"]');
  if (viewPdfBtn) viewPdfBtn.setAttribute("onclick", "toast('This is a demo — no real PDF is generated.', 'info')");
  document.querySelectorAll('#panel-3 [onclick="goBack()"]').forEach(btn => {
    btn.setAttribute("onclick", "exitDoctorDemo()");
  });
  const steps = [
    { target_selector: '#panel-3 [onclick="exitDoctorDemo()"]', placement: "right", device: "both",
      title: "Done", nextLabel: "Done",
      description: "That's the full flow, start to finish. Done takes you back to your dashboard.",
      onNext: () => { exitDoctorDemo(); return false; } },
  ];
  startLocalTour(steps, { onSkip: exitDoctorDemo });
}