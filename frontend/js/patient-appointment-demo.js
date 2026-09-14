// Guided demo booking walkthrough for the patient portal's Appointments
// tab. Mostly rides on REAL, harmless data — states/cities are public
// reference data, and the "who is this for" profile list is the
// patient's own real (read-only) profiles — so only two things are
// actually faked: a demo hospital/doctor card (guarantees the tour
// always has something to point at regardless of what's actually
// seeded for a given test hospital) and the final booking confirmation,
// which never calls the real create-booking endpoint.
//
// Every in-page transition below follows one rule: the tour's onNext
// renders the new content and lets the engine advance itself (no
// `return false` — that's only for a real page navigation, which
// destroys the tour's whole JS context anyway). Every real element that
// can also be clicked directly (bypassing the tour's own button) calls
// the same render function *and* advanceLocalTour(), so a direct click
// and the tour's own Next always end up in the same place.

const DEMO_APPOINTMENT = {
  hospitalName: "City Care Hospital (Demo)",
  hospitalAddress: "MG Road, Ambala",
  doctorName: "Dr. Sandeep Dabas (Demo)",
  specialization: "General Medicine",
  fee: 500,
  dateLabel: "Mon, 15 Sep",
  slotTime: "10:30 AM",
};

let _demoProfiles = []; // pre-fetched once, up front, so the profile step is fully synchronous like every other step

async function runAppointmentDemoTour(isReplay) {
  if (isReplay) {
    // Reset the REAL wizard back to its first step so #pick-state/#pick-city
    // definitely exist before the tour tries to point at them, regardless
    // of wherever the person currently is in a real booking attempt.
    await setStep("location", false);
  }
  try { _demoProfiles = await api("GET", "/portal/dashboard/profiles"); } catch (e) { _demoProfiles = []; }

  const steps = [
    { target_selector: "[data-tutorial-id='my-appointments-list-btn']", placement: "left", device: "both",
      title: "My Appointments", description: "See all your booked appointments, past and upcoming, here." },
    { target_selector: "#state-city-row", placement: "bottom", device: "both",
      title: "Select State & City", description: "Pick your state and city to find nearby hospitals." },
    { target_selector: "#pick-state", placement: "bottom", device: "both",
      title: "State", description: "Choose the state you're looking for a hospital in." },
    { target_selector: "#pick-city", placement: "bottom", device: "both", nextLabel: "Next",
      title: "City", description: "Then the city — this narrows down the hospital list.",
      onNext: () => { _renderDemoHospitalStep(); } },
    { target_selector: "#wizard-hospital-lead-btn", placement: "bottom", device: "both",
      title: "Can't Find Your Hospital?", description: "Tell us which hospital you'd like to see on MedScribe, and we'll reach out to them." },
    { target_selector: "[data-tutorial-id='demo-hospital-card']", placement: "top", device: "both", nextLabel: "Next",
      title: "Hospital", description: "Pick a hospital from the list — we've added a demo one here so you can see what comes next.",
      onNext: () => { _renderDemoDoctorStep(); } },
    { target_selector: "[data-tutorial-id='demo-doctor-card']", placement: "top", device: "both", nextLabel: "Next",
      title: "Doctor", description: "Pick the doctor you'd like to see, along with their consultation fee.",
      onNext: () => { _renderDemoProfileStep(); } },
    { target_selector: "#demo-profile-list", placement: "top", device: "both",
      title: "Your Linked Accounts", description: "Accounts already linked to you show up here — pick one to book for them." },
    { target_selector: "#family-account-card", placement: "top", device: "both",
      title: "Someone With Their Own Account", description: "Booking for a family member who already has a separate portal login? Add them here." },
    { target_selector: "#new-patient-card", placement: "top", device: "both", nextLabel: "Next",
      title: "First Time at This Hospital", description: "Never been to this hospital before? Book as a new patient here.",
      onNext: () => { _renderDemoDatetimeStep(); } },
    { target_selector: "#demo-datetime-area", placement: "top", device: "both", nextLabel: "Next",
      title: "Date & Time", description: "Pick a date, then an open time slot. Green means plenty of slots left, yellow means filling up, red means full.",
      onNext: () => { _openDemoConfirmModal(); } },
    { target_selector: "#btn-pay-book", placement: "top", device: "both", nextLabel: "Confirm Booking →",
      title: "Confirm Booking", description: "Check the details, then confirm — you pay at the hospital when you arrive, nothing is charged online.",
      onNext: () => { _renderDemoConfirmedStep(); } },
    { target_selector: "#demo-confirmed-card", placement: "right", device: "both", nextLabel: "Finish",
      title: "Booking Confirmed", description: "That's it — your appointment is booked. This is what you'll see once it's confirmed." },
  ];
  startLocalTour(steps, { onSkip: () => {} });
}

function _renderDemoHospitalStep() {
  document.getElementById("wizard-title").textContent = "Select Hospital";
  document.getElementById("wizard-sub").textContent = `${document.getElementById("pick-city")?.value || "your city"}`;
  document.getElementById("wizard-back").style.display = "flex";
  document.getElementById("wizard-hospital-lead-btn").style.display = "inline-flex";
  const area = document.getElementById("wizard-area");
  area.innerHTML = `
    <div class="select-row-card" data-tutorial-id="demo-hospital-card" style="border:1px dashed var(--teal);cursor:pointer" onclick="_renderDemoDoctorStep(); advanceLocalTour();">
      <div><div class="src-name">🧪 ${DEMO_APPOINTMENT.hospitalName}</div><div class="src-sub">${DEMO_APPOINTMENT.hospitalAddress} — for the tutorial only</div></div>
    </div>`;
}

function _renderDemoDoctorStep() {
  document.getElementById("wizard-title").textContent = "Select Doctor";
  document.getElementById("wizard-sub").textContent = DEMO_APPOINTMENT.hospitalName;
  const area = document.getElementById("wizard-area");
  area.innerHTML = `
    <div class="select-row-card" data-tutorial-id="demo-doctor-card" style="border:1px dashed var(--teal);cursor:pointer" onclick="_renderDemoProfileStep(); advanceLocalTour();">
      <div><div class="src-name">🧪 ${DEMO_APPOINTMENT.doctorName}</div><div class="src-sub">${DEMO_APPOINTMENT.specialization}</div></div>
      <span class="badge badge-teal">₹${DEMO_APPOINTMENT.fee}</span>
    </div>`;
}

function _renderDemoProfileStep() {
  document.getElementById("wizard-title").textContent = "Who is this for?";
  document.getElementById("wizard-sub").textContent = DEMO_APPOINTMENT.doctorName;
  document.getElementById("wizard-hospital-lead-btn").style.display = "none";
  const area = document.getElementById("wizard-area");
  area.innerHTML = `<div id="demo-profile-list"></div>`;

  const familyAccountCard = `
    <div class="select-row-card" id="family-account-card" style="border:1px dashed var(--slate)" onclick="toast('Just for the tutorial — nothing to add here.','info')">
      <div><div class="src-name">+ Someone with their own account</div><div class="src-sub">Book for a family member who already has a separate portal login</div></div>
    </div>`;
  const newPatientCard = `
    <div class="select-row-card" id="new-patient-card" style="border:1px dashed var(--teal);cursor:pointer" onclick="_renderDemoDatetimeStep(); advanceLocalTour();">
      <div><div class="src-name">+ First time at this hospital</div><div class="src-sub">Book as a new patient here</div></div>
    </div>`;

  const listEl = document.getElementById("demo-profile-list");
  if (!_demoProfiles.length) {
    listEl.innerHTML = `<p style="color:var(--slate-light);font-size:13px;margin-bottom:12px">No linked accounts yet — book as yourself below, or add a new patient.</p>`;
  } else {
    searchableFullWidthList(
      listEl, _demoProfiles,
      (p) => `<div class="select-row-card" style="cursor:pointer" onclick="_renderDemoDatetimeStep(); advanceLocalTour();">
                <div><div class="src-name">${p.display_name}</div><div class="src-sub">${p.relation === 'self' ? 'You' : 'Family member'}</div></div>
              </div>`,
      (p, q) => p.display_name.toLowerCase().includes(q),
      "Search profiles..."
    );
  }
  area.insertAdjacentHTML("beforeend", familyAccountCard + newPatientCard);
}

function _renderDemoDatetimeStep() {
  document.getElementById("wizard-title").textContent = "Select Date and Time";
  document.getElementById("wizard-sub").textContent = DEMO_APPOINTMENT.doctorName;
  const area = document.getElementById("wizard-area");
  const today = new Date();
  const days = Array.from({ length: 5 }, (_, i) => {
    const d = new Date(today); d.setDate(today.getDate() + i);
    return { dayNum: d.getDate(), abbr: d.toLocaleDateString('en-IN', { weekday: 'short' }) };
  });
  const slotRow = (times) => `<div class="slot-grid">${times.map(([t, level]) =>
    `<div class="slot-chip ${level}" onclick="_openDemoConfirmModal(); advanceLocalTour();"><span class="dot"></span>${t}</div>`).join('')}</div>`;

  area.innerHTML = `
    <div id="demo-datetime-area">
      <div class="date-scroll-wrap">
        <div class="date-month-label">${today.toLocaleDateString('en-IN', { month: 'long', year: 'numeric' })}</div>
        <div class="date-scroll">
          ${days.map((d, i) => `<div class="date-pill${i === 0 ? ' selected' : ''}"><div class="dnum">${d.dayNum}</div><div class="dabbr">${d.abbr}</div></div>`).join('')}
        </div>
      </div>
      <div class="slot-period-title">Morning</div>
      ${slotRow([["9:00 AM", "green"], ["9:30 AM", "green"], ["10:00 AM", "yellow"]])}
      <div class="slot-period-title">Afternoon</div>
      ${slotRow([["1:00 PM", "yellow"], ["1:30 PM", "red"], ["2:00 PM", "green"]])}
      <div class="slot-period-title">Evening</div>
      ${slotRow([["6:00 PM", "green"], ["6:30 PM", "red"], ["7:00 PM", "yellow"]])}
    </div>`;
}

function _openDemoConfirmModal() {
  document.getElementById("confirm-body").innerHTML = `
    <div class="pay-summary-row"><span>Patient</span><strong>You</strong></div>
    <div class="pay-summary-row"><span>Doctor</span><strong>${DEMO_APPOINTMENT.doctorName}</strong></div>
    <div class="pay-summary-row"><span>Hospital</span><strong>${DEMO_APPOINTMENT.hospitalName}</strong></div>
    <div class="pay-summary-row"><span>Date &amp; Time</span><strong>${DEMO_APPOINTMENT.dateLabel}, ${DEMO_APPOINTMENT.slotTime}</strong></div>`;
  // The real button here calls confirmBooking(), which would create a real
  // appointment — neutralized the moment this modal opens, not only via
  // the tour's own Next, so clicking it directly is safe too.
  document.getElementById("btn-pay-book").setAttribute("onclick", "_renderDemoConfirmedStep(); advanceLocalTour();");
  document.getElementById("modal-confirm").classList.add("open");
}

function _renderDemoConfirmedStep() {
  document.getElementById("modal-confirm").classList.remove("open");
  document.getElementById("wizard-title").textContent = "Booking Confirmed";
  document.getElementById("wizard-sub").textContent = "Pay at the hospital when you arrive";
  document.getElementById("wizard-back").style.display = "none";
  const area = document.getElementById("wizard-area");
  area.innerHTML = `
    <div id="demo-confirmed-card">
      <div style="text-align:center;padding:8px 0 4px">
        <div style="width:52px;height:52px;border-radius:50%;background:var(--teal-subtle);color:var(--teal);display:flex;align-items:center;justify-content:center;margin:0 auto 14px;font-size:26px">✓</div>
        <div style="font-weight:700;font-size:1.05rem;color:var(--navy)">Confirmed — Pay at Hospital</div>
        <div style="font-size:13px;color:var(--slate);margin-top:4px">Bring payment with you and pay at reception when you arrive.</div>
      </div>
      <div class="pay-summary-row"><span>Doctor</span><strong>${DEMO_APPOINTMENT.doctorName}</strong></div>
      <div class="pay-summary-row"><span>Hospital</span><strong>${DEMO_APPOINTMENT.hospitalName}</strong></div>
      <div class="pay-summary-row"><span>Your Slot</span><strong>${DEMO_APPOINTMENT.dateLabel}, ${DEMO_APPOINTMENT.slotTime}</strong></div>
      <div class="pay-summary-row" style="font-size:16px"><span>Amount Due at Hospital</span><strong style="color:var(--teal)">₹${DEMO_APPOINTMENT.fee}</strong></div>
      <p style="font-size:12px;color:var(--slate-light);margin:14px 0 16px">Please reach the hospital by your slot time.</p>
      <div style="display:flex;gap:10px">
        <button class="btn btn-teal" style="flex:1" onclick="location.reload()">Done</button>
      </div>
    </div>`;
}