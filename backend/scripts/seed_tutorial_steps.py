"""Idempotent staff-tutorial content seeder — run directly, no migration
needed. Content-only data (the tutorial_steps table itself, and its
device column, were real schema changes and stayed as Alembic
migrations — this script never touches schema).

step_order is a SINGLE continuous sequence per (role, page) — the
backend returns every active step for a page in one step_order-sorted
list regardless of which "section" it belongs to (see GET
/tutorials/{role}/{page} in routers/tutorials.py), and the frontend
just filters that list by device. It does NOT restart per section —
sections below are grouped with comments for readability only; the
numbers must stay continuous within each role+page.

Safe to rerun any time: each STEPS entry is upserted by its natural key
(role, page, device, target_selector) — matched rows get their
title/description/placement/step_order updated in place, new rows are
inserted, and any row that used to exist for a role+page but is no
longer listed here gets soft-disabled (is_active=False) rather than
deleted, consistent with how tutorial_steps already uses is_active.

Usage:
    cd backend && python -m scripts.seed_tutorial_steps
"""
import sys
import os

# Only needed for standalone `python -m scripts.seed_tutorial_steps` use —
# when this module is instead imported from app.main at startup, app.main
# has already put the backend dir on sys.path and fully initialized the
# model registry (Hospital, Doctor, etc.), so this import is a no-op then.
if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import app.main  # noqa: F401 — registers every model's mapper before we touch the DB

from app.database import SessionLocal
from app.models.tutorial_step import TutorialStep

STEPS = [
    # ═══ lab / lab.html — continuous 1-9 ═══
    # Queue
    {"role": "lab", "page": "lab", "device": "desktop", "step_order": 1,
     "target_selector": "#sidebar-tab-queue", "title": "Waiting Queue",
     "description": "Patients waiting for lab tests show up here as soon as they're checked in.",
     "placement": "right"},
    {"role": "lab", "page": "lab", "device": "mobile", "step_order": 1,
     "target_selector": "#tab-btn-queue", "title": "Home",
     "description": "Patients waiting for lab tests show up here as soon as they're checked in.",
     "placement": "top"},
    {"role": "lab", "page": "lab", "device": "both", "step_order": 2,
     "target_selector": "#lab-queue-search", "title": "Find a Patient",
     "description": "Search by name or token, or use the filter next to it to narrow by status.",
     "placement": "bottom"},
    {"role": "lab", "page": "lab", "device": "both", "step_order": 3,
     "target_selector": "#lab-queue-list", "title": "Enter Results",
     "description": "Tap a patient's card to see their ordered tests and enter results.",
     "placement": "top"},
    # Pending Tasks
    {"role": "lab", "page": "lab", "device": "desktop", "step_order": 4,
     "target_selector": "#sidebar-tab-pending", "title": "Pending Tasks",
     "description": "Paid tests that need to be requeued — a missed sample, a redo, etc. — land here.",
     "placement": "right"},
    {"role": "lab", "page": "lab", "device": "mobile", "step_order": 4,
     "target_selector": "#tab-btn-pending", "title": "Pending Tasks",
     "description": "Paid tests that need to be requeued — a missed sample, a redo, etc. — land here.",
     "placement": "top"},
    {"role": "lab", "page": "lab", "device": "both", "step_order": 5,
     "target_selector": "#lab-pending-search", "title": "Search or Browse",
     "description": "Search a patient by name, or leave it blank to see everything pending.",
     "placement": "bottom"},
    {"role": "lab", "page": "lab", "device": "both", "step_order": 6,
     "target_selector": "#lab-pending-results", "title": "Requeue a Test",
     "description": "Tap Requeue on a patient's card to send their test back to the waiting queue.",
     "placement": "top"},
    # Reports
    {"role": "lab", "page": "lab", "device": "desktop", "step_order": 7,
     "target_selector": "#sidebar-tab-reports", "title": "Reports",
     "description": "Completed lab reports for every patient live here, organized by patient.",
     "placement": "right"},
    {"role": "lab", "page": "lab", "device": "mobile", "step_order": 7,
     "target_selector": "#tab-btn-reports", "title": "Reports",
     "description": "Completed lab reports for every patient live here, organized by patient.",
     "placement": "top"},
    {"role": "lab", "page": "lab", "device": "both", "step_order": 8,
     "target_selector": "#lab-reports-search", "title": "Find a Report",
     "description": "Search by patient name or UID to jump straight to their reports.",
     "placement": "bottom"},
    {"role": "lab", "page": "lab", "device": "both", "step_order": 9,
     "target_selector": "#lab-reports-list", "title": "View & Share",
     "description": "Tap Report on a patient's card to download or send their results on WhatsApp.",
     "placement": "top"},

    # ═══ receptionist / receptionist.html — "receptionist-attendance" page ═══
    # Mobile-only: this section has no desktop equivalent anywhere on the
    # page (pre-existing gap — desktop receptionists have no attendance UI
    # here at all).
    {"role": "receptionist", "page": "receptionist-attendance", "device": "mobile", "step_order": 1,
     "target_selector": "#rec-attendance-card", "title": "Today's Status",
     "description": "Mark yourself Present, On Break, or Off Duty for the day here.",
     "placement": "bottom"},

    # ═══ receptionist / receptionist.html — "receptionist-home" page ═══
    {"role": "receptionist", "page": "receptionist-home", "device": "both", "step_order": 2,
     "target_selector": "#s-name", "title": "Check In a Patient",
     "description": "Start typing a patient's name to find them, or use the buttons below for something else.",
     "placement": "bottom"},
    {"role": "receptionist", "page": "receptionist-home", "device": "both", "step_order": 3,
     "target_selector": "[onclick=\"openNewPatient()\"]", "title": "New Patient",
     "description": "No match in search? Add them as a new patient from here.",
     "placement": "top"},
    {"role": "receptionist", "page": "receptionist-home", "device": "both", "step_order": 4,
     "target_selector": "[onclick=\"openPhoneBookingModal()\"]", "title": "Book Appointment",
     "description": "Book a future appointment for a patient who isn't here right now.",
     "placement": "top"},
    {"role": "receptionist", "page": "receptionist-home", "device": "both", "step_order": 5,
     "target_selector": "#btn-emergency-intake", "title": "Emergency Intake",
     "description": "For urgent cases — skips the usual queue and checks the patient in immediately.",
     "placement": "top"},
    {"role": "receptionist", "page": "receptionist-home", "device": "both", "step_order": 6,
     "target_selector": "#pending-payments-card", "title": "Pending Payments",
     "description": "Today's unpaid bills across all patients — search, review, and collect payment from here.",
     "placement": "top"},
    {"role": "receptionist", "page": "receptionist-home", "device": "desktop", "step_order": 7,
     "target_selector": "#sidebar-nav-portal", "title": "Appointments",
     "description": "Today's expected patients and upcoming online bookings live here.",
     "placement": "right"},
    {"role": "receptionist", "page": "receptionist-home", "device": "mobile", "step_order": 7,
     "target_selector": "#tab-btn-portal", "title": "Appointments",
     "description": "Today's expected patients and upcoming online bookings live here.",
     "placement": "top"},
    {"role": "receptionist", "page": "receptionist-home", "device": "desktop", "step_order": 8,
     "target_selector": "a.nav-item[href=\"admissions.html\"]", "title": "Admissions",
     "description": "Manage patients currently admitted to the hospital from here.",
     "placement": "right"},
    {"role": "receptionist", "page": "receptionist-home", "device": "mobile", "step_order": 8,
     "target_selector": "a.bottom-nav-item[href=\"admissions.html\"]", "title": "Admissions",
     "description": "Manage patients currently admitted to the hospital from here.",
     "placement": "top"},
    {"role": "receptionist", "page": "receptionist-home", "device": "desktop", "step_order": 9,
     "target_selector": "#sidebar-nav-availability", "title": "Manage Availability",
     "description": "Set which doctors are available, and when, for booking.",
     "placement": "right"},
    {"role": "receptionist", "page": "receptionist-home", "device": "mobile", "step_order": 9,
     "target_selector": "[data-tutorial-id='rec-mobile-menu-btn']", "title": "More",
     "description": "Manage Availability lives here on mobile.",
     "placement": "top"},
    {"role": "receptionist", "page": "receptionist-home", "device": "desktop", "step_order": 10,
     "target_selector": "#sidebar-nav-patients", "title": "Patients",
     "description": "Every patient ever registered at your hospital, searchable from here.",
     "placement": "right"},
    {"role": "receptionist", "page": "receptionist-home", "device": "both", "step_order": 11,
     "target_selector": "#bills-header-btn", "title": "Bills",
     "description": "A quick look at today's bills across all patients.",
     "placement": "bottom"},
    {"role": "receptionist", "page": "receptionist-home", "device": "both", "step_order": 12,
     "target_selector": "#suggestion-header-btn", "title": "Suggest",
     "description": "Have an idea to improve MedScribe? Send it here.",
     "placement": "bottom"},
    {"role": "receptionist", "page": "receptionist-home", "device": "both", "step_order": 13,
     "target_selector": "#chat-header-btn", "title": "Chat",
     "description": "Message your hospital admin directly from here.",
     "placement": "bottom"},
    {"role": "receptionist", "page": "receptionist-home", "device": "both", "step_order": 14,
     "target_selector": ".topbar-profile-btn", "title": "Profile",
     "description": "Your account settings — and you can replay any tab's tutorial from here any time.",
     "placement": "bottom"},

    # ═══ nurse / nurse.html — continuous 1-2 (Vitals module only, first slice) ═══
    # Desktop's "Home" sidebar tab shows Vitals Queue and Post-Consultation
    # Tasks stacked together (no separate desktop tab for each, unlike
    # mobile's bottom-nav) — this module covers Vitals only; Tasks is a
    # separate later seed reusing the same #sidebar-nav-home nav step.
    {"role": "nurse", "page": "nurse", "device": "desktop", "step_order": 1,
     "target_selector": "#sidebar-nav-home", "title": "Home",
     "description": "Vitals Queue and Post-Consultation Tasks are both here.",
     "placement": "right"},
    {"role": "nurse", "page": "nurse", "device": "mobile", "step_order": 1,
     "target_selector": "#tab-btn-vitals", "title": "Vitals Queue",
     "description": "Patients waiting for vitals to be recorded, or a doctor-requested recheck, show up here.",
     "placement": "top"},
    {"role": "nurse", "page": "nurse", "device": "both", "step_order": 2,
     "target_selector": "#vitals-list", "title": "Record Vitals",
     "description": "Mark yourself Present first, then tap Record Vitals (or Recheck) on a patient's card.",
     "placement": "top"},
    # Post-Consultation Tasks — mobile has its own bottom-nav tab for this
    # (desktop already showed it under Home in step 1, so desktop just
    # gets the content step; mobile needs its nav step first, one order
    # position later than desktop's equivalent content step).
    {"role": "nurse", "page": "nurse", "device": "mobile", "step_order": 3,
     "target_selector": "#tab-btn-tasks", "title": "Post-Consultation Tasks",
     "description": "Tasks a doctor left for after the consultation — a follow-up measurement, a note to check on — land here.",
     "placement": "top"},
    {"role": "nurse", "page": "nurse", "device": "desktop", "step_order": 3,
     "target_selector": "#postconsult-list", "title": "Mark Tasks Done",
     "description": "Mark yourself Present first, then tap Mark Done once you've completed a task.",
     "placement": "top"},
    {"role": "nurse", "page": "nurse", "device": "mobile", "step_order": 4,
     "target_selector": "#postconsult-list", "title": "Mark Tasks Done",
     "description": "Mark yourself Present first, then tap Mark Done once you've completed a task.",
     "placement": "top"},
    # History — has its own dedicated nav on both devices, but lands one
    # position later on mobile (5) than desktop (4) because mobile needed
    # an extra Tasks-nav step desktop didn't. The two content steps below
    # it are split by device rather than "both" for the same reason —
    # a single shared step_order can't be correct for both device sequences
    # at once here.
    {"role": "nurse", "page": "nurse", "device": "desktop", "step_order": 4,
     "target_selector": "#sidebar-nav-history", "title": "History",
     "description": "Everything you've recorded today — vitals and post-consult tasks together — for a quick recheck.",
     "placement": "right"},
    {"role": "nurse", "page": "nurse", "device": "mobile", "step_order": 5,
     "target_selector": "#tab-btn-history", "title": "History",
     "description": "Everything you've recorded today — vitals and post-consult tasks together — for a quick recheck.",
     "placement": "top"},
    {"role": "nurse", "page": "nurse", "device": "desktop", "step_order": 5,
     "target_selector": "#nurse-history-search", "title": "Search",
     "description": "Search by patient name, ID, or token to find a specific record.",
     "placement": "bottom"},
    {"role": "nurse", "page": "nurse", "device": "mobile", "step_order": 6,
     "target_selector": "#nurse-history-search", "title": "Search",
     "description": "Search by patient name, ID, or token to find a specific record.",
     "placement": "bottom"},
    {"role": "nurse", "page": "nurse", "device": "desktop", "step_order": 6,
     "target_selector": "#history-list", "title": "Edit a Record",
     "description": "Tap Edit on any entry to correct a recorded vitals or task value.",
     "placement": "top"},
    {"role": "nurse", "page": "nurse", "device": "mobile", "step_order": 7,
     "target_selector": "#history-list", "title": "Edit a Record",
     "description": "Tap Edit on any entry to correct a recorded vitals or task value.",
     "placement": "top"},

    # ═══ assistant / assistant.html — continuous 1-3 (Home module: Up Next + Walk-ins) ═══
    # #up-next-card is set to display:'' unconditionally inside renderQueues()
    # (called via loadQueues -> refreshAll before initTutorial fires), so
    # it's reliably visible by the time the tutorial runs despite its
    # display:none default in the raw HTML. Online Appointments and the
    # Doctors tab are separate, later modules.
    {"role": "assistant", "page": "assistant", "device": "desktop", "step_order": 1,
     "target_selector": "#sidebar-nav-home", "title": "Home",
     "description": "Your Up Next patient and both queues live here.",
     "placement": "right"},
    {"role": "assistant", "page": "assistant", "device": "mobile", "step_order": 1,
     "target_selector": "#tab-btn-home", "title": "Home",
     "description": "Your Up Next patient and both queues live here.",
     "placement": "top"},
    {"role": "assistant", "page": "assistant", "device": "both", "step_order": 2,
     "target_selector": "#up-next-card", "title": "Up Next",
     "description": "The next patient in line, across both walk-in and online queues, always shows here.",
     "placement": "bottom"},
    {"role": "assistant", "page": "assistant", "device": "both", "step_order": 3,
     "target_selector": "#queue-card-walkin", "title": "Walk-ins",
     "description": "Patients who walked in today — check their status and vitals, and track their progress here.",
     "placement": "top"},
    {"role": "assistant", "page": "assistant", "device": "both", "step_order": 4,
     "target_selector": "#queue-card-online", "title": "Online Appointments",
     "description": "Patients who booked online — same queue, same actions, just a different source.",
     "placement": "top"},
    # Doctors — its own nav on both devices, staying in sync since
    # assistant's desktop/mobile step counts haven't diverged so far.
    {"role": "assistant", "page": "assistant", "device": "desktop", "step_order": 5,
     "target_selector": "#sidebar-nav-doctors", "title": "Doctors",
     "description": "See who's available for consultation right now, and who you're currently assisting.",
     "placement": "right"},
    {"role": "assistant", "page": "assistant", "device": "mobile", "step_order": 5,
     "target_selector": "#tab-btn-doctors", "title": "Doctors",
     "description": "See who's available for consultation right now, and who you're currently assisting.",
     "placement": "top"},
    {"role": "assistant", "page": "assistant", "device": "both", "step_order": 6,
     "target_selector": "#doctor-roster-list", "title": "Doctor Roster",
     "description": "Each doctor's current status, and a badge marking who you're assisting today.",
     "placement": "top"},

    # ═══ pharmacy / pharmacy.html — continuous 1-12 (desktop), 1-7 (mobile) ═══
    # Home / Waiting Queue
    {"role": "pharmacy", "page": "pharmacy", "device": "desktop", "step_order": 1,
     "target_selector": "#nav-home-tab", "title": "Home",
     "description": "Patients waiting for medicines to be dispensed show up here.",
     "placement": "right"},
    {"role": "pharmacy", "page": "pharmacy", "device": "mobile", "step_order": 1,
     "target_selector": "#tab-btn-home", "title": "Home",
     "description": "Patients waiting for medicines to be dispensed show up here.",
     "placement": "top"},
    {"role": "pharmacy", "page": "pharmacy", "device": "both", "step_order": 2,
     "target_selector": "#pharm-search", "title": "Find a Patient",
     "description": "Search by token or patient name, or use the filter next to it to narrow by status.",
     "placement": "bottom"},
    {"role": "pharmacy", "page": "pharmacy", "device": "both", "step_order": 3,
     "target_selector": "#pharmacy-queue-list", "title": "Dispense Medicines",
     "description": "Tap a patient's card here to see their prescribed medicines and dispense them.",
     "placement": "top"},
    # Pending Dispenses
    {"role": "pharmacy", "page": "pharmacy", "device": "desktop", "step_order": 4,
     "target_selector": "#nav-pending-tab", "title": "Pending Dispenses",
     "description": "Prescriptions that still need medicines dispensed sit here.",
     "placement": "right"},
    {"role": "pharmacy", "page": "pharmacy", "device": "mobile", "step_order": 4,
     "target_selector": "#tab-btn-pending", "title": "Pending Dispenses",
     "description": "Prescriptions that still need medicines dispensed sit here.",
     "placement": "top"},
    {"role": "pharmacy", "page": "pharmacy", "device": "both", "step_order": 5,
     "target_selector": "#pharm-pending-search", "title": "Find a Patient",
     "description": "Search by patient name or ID to jump to their pending items.",
     "placement": "bottom"},
    {"role": "pharmacy", "page": "pharmacy", "device": "both", "step_order": 6,
     "target_selector": "#pharm-pending-results", "title": "Requeue Pending Items",
     "description": "Tap Requeue All on a patient's card to send their pending medicines back to today's list.",
     "placement": "top"},
    # Patients + Stock (mobile: both reached via the same "More" overflow
    # sheet, whose items are hidden until tapped — one combined mobile
    # step points at the Menu button itself; desktop gets full walkthroughs
    # for each since both are direct, always-visible sidebar tabs there)
    {"role": "pharmacy", "page": "pharmacy", "device": "desktop", "step_order": 7,
     "target_selector": "#nav-patients-tab", "title": "Patients",
     "description": "Look up any patient's documents or today's prescription from here.",
     "placement": "right"},
    {"role": "pharmacy", "page": "pharmacy", "device": "mobile", "step_order": 7,
     "target_selector": "[data-tutorial-id='pharm-mobile-menu-btn']", "title": "More",
     "description": "Tap here to find Patients and Meds (stock).",
     "placement": "top"},
    {"role": "pharmacy", "page": "pharmacy", "device": "desktop", "step_order": 8,
     "target_selector": "#pharm-patients-search", "title": "Find a Patient",
     "description": "Search by name, phone, or patient ID.",
     "placement": "bottom"},
    {"role": "pharmacy", "page": "pharmacy", "device": "desktop", "step_order": 9,
     "target_selector": "#pharm-patients-list", "title": "Docs & Medicine",
     "description": "Each patient's Docs button and today's Medicine link (if they have an active order) are right here.",
     "placement": "top"},
    {"role": "pharmacy", "page": "pharmacy", "device": "desktop", "step_order": 10,
     "target_selector": "#nav-stock-tab", "title": "Medicine Catalog",
     "description": "Every medicine you stock — pricing, batches, and quantities — lives here.",
     "placement": "right"},
    {"role": "pharmacy", "page": "pharmacy", "device": "desktop", "step_order": 11,
     "target_selector": "#stock-search", "title": "Find a Medicine",
     "description": "Search by medicine name to jump straight to it.",
     "placement": "bottom"},
    {"role": "pharmacy", "page": "pharmacy", "device": "desktop", "step_order": 12,
     "target_selector": "#stock-medicines-list", "title": "Manage Stock",
     "description": "Add stock, edit pricing, or add a new medicine to the catalog from here.",
     "placement": "top"},
]


def run():
    db = SessionLocal()
    try:
        seen_role_pages = set()
        seen_keys = set()
        for s in STEPS:
            key = (s["role"], s["page"], s["device"], s["target_selector"])
            seen_keys.add(key)
            seen_role_pages.add((s["role"], s["page"]))
            row = db.query(TutorialStep).filter_by(
                role=s["role"], page=s["page"], device=s["device"], target_selector=s["target_selector"]
            ).first()
            if row:
                row.step_order = s["step_order"]
                row.title = s["title"]
                row.description = s["description"]
                row.placement = s["placement"]
                row.is_active = True
            else:
                db.add(TutorialStep(
                    role=s["role"], page=s["page"], device=s["device"],
                    target_selector=s["target_selector"], step_order=s["step_order"],
                    title=s["title"], description=s["description"],
                    placement=s["placement"], is_active=True,
                ))
        for role, page in seen_role_pages:
            existing = db.query(TutorialStep).filter_by(role=role, page=page, is_active=True).all()
            for row in existing:
                if (row.role, row.page, row.device, row.target_selector) not in seen_keys:
                    row.is_active = False
        db.commit()
        print(f"Seeded/updated {len(STEPS)} tutorial steps across {len(seen_role_pages)} role/page(s).")
    finally:
        db.close()


if __name__ == "__main__":
    run()