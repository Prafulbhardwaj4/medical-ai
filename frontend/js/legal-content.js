/* ScribeKare legal documents. ONE source for privacy.html, terms.html, the first sign-in acceptance dialog
   and the in-app reader (profile menu > Settings). Edit the wording here and everything updates.
   When the wording changes in a way people must accept again, change `version` below and set the same value
   as CONSENT_NOTICE_VERSION in backend/app/config.py (or the CONSENT_NOTICE_VERSION environment variable).
   Tokens: {{company}} = registered company name (js/brand.js), {{brand}} = product name. Text is rendered with textContent only. */
window.LEGAL_DOCS = {
  version: "2026-12-01",
  effective: "1 December 2026",
  updated: "20 November 2026",
  audiences: {
    hospitals: { label: "Hospitals & staff", short: "For hospitals, nursing homes, clinics and the staff who use ScribeKare" },
    patients: { label: "Patients & portal users", short: "For patients and everyone who uses the ScribeKare patient portal" }
  },

  /* ======================================================================== TERMS OF SERVICE */
  terms: {
    hospitals: {
      lead: "These Terms of Service are the agreement between {{company}} and each hospital, nursing home or clinic that uses {{brand}}. They also apply to every staff member who signs in.",
      summary: [
        "{{brand}} is software. Your hospital provides the medical care. We provide the system that runs it.",
        "Your hospital owns its data. We process it only to run the service for you.",
        "The AI scribe drafts notes. The doctor reviews and confirms every note.",
        "Plans and prices are published and flat. You can export your data.",
        "Indian law applies."
      ],
      sections: [
        { title: "Agreement and definitions", blocks: [
          "These Terms are an agreement between {{company}} (“{{brand}}”, “we”, “us”) and the hospital, nursing home or clinic that subscribes to the Service (the “Hospital”). The Hospital accepts these Terms by signing an order or inquiry form, or by using the Service. The person who accepts for the Hospital confirms that they are authorised to do so.",
          "Every staff member who signs in (an “Authorised User”) must also accept these Terms and the Privacy Policy when they first sign in.",
          { h: "Meanings" },
          { ul: [
            "“Service” means the {{brand}} hospital management system: its modules, the patient portal, the AI scribe, public verification pages, and related onboarding and support.",
            "“Hospital Data” means all information the Hospital or its Authorised Users enter into, or create through, the Service, including Patient Data.",
            "“Patient Data” means information about patients, including health information.",
            "“Plan” means the subscription tier the Hospital has chosen, as shown on our Plans page or in its order."
          ] },
          "Clicking to accept, signing in or using the Service is a valid way to agree to these Terms under the Information Technology Act, 2000."
        ] },
        { title: "The Service", blocks: [
          "{{brand}} is cloud software for hospital operations: OPD registration, token queue and display, vitals, consultations and prescriptions with QR verification, pharmacy, pathology laboratory, billing with GST invoices, online appointments, a patient portal, attendance, an audit trail and role-based access. Higher Plans add the AI scribe, IPD and admissions, and staff chat.",
          "What is included depends on the Plan. Features described as “coming soon” or “planned” are not part of the Service until we release them, and they are not a promise about delivery or timing.",
          "We may improve, add or change features. If a change removes a material feature of the Hospital’s Plan, we will give at least 30 days’ notice."
        ] },
        { title: "Onboarding and set-up", blocks: [
          "We set the Hospital up. We create the first accounts and load the master lists of tests and medicines that the Hospital chooses to offer. The Hospital is responsible for the accuracy and completeness of what it gives us, including its test catalog, medicine list, prices, tax settings, licences and staff details, and for checking its set-up before it goes live.",
          "Files that the Hospital uploads or imports must be files it has the right to use."
        ] },
        { title: "Accounts, roles and access", blocks: [
          { ul: [
            "The Hospital’s administrator decides who gets an account and which role each person has (admin, doctor, nurse, receptionist, pharmacy or lab). Give each person only the access they need.",
            "Every Authorised User must use their own account. Sharing logins is not allowed.",
            "Credentials must be kept confidential. The Hospital must remove access promptly when someone leaves or changes role.",
            "The Hospital is responsible for everything done through its accounts, except where it is caused by our breach of these Terms.",
            "Tell us without delay if you suspect an account has been misused. We may lock or reset an account to protect the Service or its data."
          ] }
        ] },
        { title: "The Hospital’s responsibilities", blocks: [
          "{{brand}} is a software service. It is not a healthcare provider and does not practise medicine. The Hospital and its clinicians remain solely responsible for patient care, clinical judgement, prescriptions, test results and reports, and for the accuracy of what they record.",
          "The Hospital must:",
          { ul: [
            "hold and keep valid every registration and licence it needs (for example clinical establishment registration, pharmacy and laboratory licences) and follow the laws that apply to its work, including rules on Schedule H1 and Schedule X drugs, price controls, medical records and tax;",
            "give patients the notices, and obtain the consents, that the law requires before it collects or uses their information, including before any consultation is recorded for the AI scribe;",
            "use the Service only for lawful healthcare and hospital administration;",
            "check that prescriptions, reports, invoices and other documents produced by the Service are correct before they are issued;",
            "keep its own devices, networks and passwords secure; and",
            "keep a way to continue essential work (for example a paper fallback) if the Service is unavailable."
          ] },
          { note: "Warnings in the Service, such as price-ceiling alerts, expiry blocks and critical-result flags, are aids for the Hospital’s staff. They do not replace professional judgement or the Hospital’s own checks." }
        ] },
        { title: "AI scribe", blocks: [
          "The AI scribe, available on Growth and higher Plans, listens to a consultation in Hindi, English or a mix of both and drafts a consultation note. The doctor reviews, edits and confirms the note. The AI never finalises anything on its own.",
          { ul: [
            "AI output can contain mistakes or leave things out. The doctor must check every draft before confirming it, and is responsible for the final note and prescription.",
            "The AI scribe does not diagnose, treat or give medical advice. It must not be used in place of clinical judgement.",
            "Before recording, the Hospital must tell the patient and obtain the patient’s agreement. The Service records that agreement. A consultation can go ahead without the AI scribe if the patient says no.",
            "Use is subject to the consultation limits of the Plan and any extra packs the Hospital buys.",
            "How patient information is handled for the AI scribe is explained in the Privacy Policy. We do not use Patient Data to train AI models."
          ] }
        ] },
        { title: "Fees, billing and renewal", blocks: [
          "Fees are the flat monthly or yearly Plan fees published on our Plans page or stated in the Hospital’s order, plus any taxes, including GST, shown on the invoice. Enterprise fees are as quoted in writing.",
          { ul: [
            "Fees are payable in advance for each billing cycle. A yearly Plan is paid for the year. If the offer includes an extra period, it is stated when the Plan is sold.",
            "A billing cycle continues when the Hospital renews it with us. If a cycle ends without renewal, access continues for a short grace period that we tell the Hospital about. When the grace period ends, the account is deactivated until the Hospital renews. Deactivation does not delete data.",
            "Extra AI scribe consultation packs are charged at the price shown when they are bought and are valid for the period stated.",
            "A move to a higher Plan takes effect when we confirm it. We will tell the Hospital what is payable before the change.",
            "We may change prices for a future billing cycle by giving at least 30 days’ notice. A price change never applies to a cycle that has already been paid.",
            "Fees already paid are not refundable, except where these Terms or the law say otherwise, or where we agree in writing.",
            "Evaluation or pilot access, if we offer it, runs for the period and within the limits we tell the Hospital, and ends automatically unless the Hospital moves to a paid Plan."
          ] },
          "If the Hospital disputes an invoice, it must tell us within 15 days of the invoice date so that we can look into it."
        ] },
        { title: "Hospital Data and Patient Data", blocks: [
          "The Hospital owns the Hospital Data. We do not claim ownership of it. The Hospital gives us a limited licence to host, process, back up, display and transmit Hospital Data only as needed to provide, secure, support and improve the Service for the Hospital.",
          "For Patient Data, the Hospital decides why and how the data is used (it is the “Data Fiduciary” under the Digital Personal Data Protection Act, 2023) and {{brand}} acts on its behalf as its processor. We will:",
          { ul: [
            "process Patient Data only to provide the Service and on the Hospital’s documented instructions (these Terms and the Hospital’s use of the Service are those instructions);",
            "keep it confidential and make sure that everyone with access is bound by confidentiality;",
            "apply the security measures described in these Terms and in the Privacy Policy;",
            "use sub-processors (such as hosting, speech and language, messaging and payment providers) only under written terms that protect the data, and tell the Hospital which categories we use when it asks;",
            "help the Hospital respond to patient requests and to its legal obligations, within what the Service allows;",
            "tell the Hospital without undue delay, and where possible within 72 hours, after we become aware of a personal data breach affecting its data; and",
            "on request, give the information reasonably needed to show that we comply with this section."
          ] },
          "Each hospital’s data is kept separate from every other hospital’s data. We do not sell Hospital Data and we do not use it for advertising.",
          "We may use information that cannot identify any person or hospital to measure usage, keep the Service reliable and improve it. We will not try to re-identify it.",
          "Our own records about how the Hospital is set up and billed (account, contact, billing and usage information) are handled as described in the Privacy Policy."
        ] },
        { title: "Security", blocks: [
          "We protect the Service with role-based access, separation of each hospital’s data, encrypted connections (HTTPS), encryption of sensitive fields, hashed passwords, temporary lock-out after repeated failed sign-ins, and an audit trail of important actions. We follow reasonable security practices and procedures as required by Indian law.",
          "Security is shared. The Hospital must manage its users, keep its devices secure and not try to bypass the Service’s controls. No system is completely secure, and we do not promise that it is.",
          "The audit trail records who did important things and when. It exists for the Hospital’s protection and accountability."
        ] },
        { title: "Acceptable use", blocks: [
          "The Hospital and its Authorised Users must not:",
          { ul: [
            "use the Service for anything unlawful, or in a way that harms patients, other hospitals or us;",
            "try to access another hospital’s data, or bypass or test the Service’s security or access controls;",
            "copy, modify, reverse engineer, resell or build a competing product from the Service;",
            "upload malicious code, or overload or disrupt the Service;",
            "use automated tools to extract data from the Service, other than features we provide;",
            "enter false identities or false clinical information; or",
            "use patient information for any purpose other than care, administration and legal duties."
          ] }
        ] },
        { title: "Availability and support", blocks: [
          "We work to keep the Service available. We try to schedule maintenance at quiet times and to tell the Hospital in advance about planned downtime. The Service may sometimes be unavailable or slow because of maintenance, faults, internet or power failures, or outages at third parties that we do not control. We do not promise uninterrupted service.",
          "Support is available through the contact details on our website. Onboarding and set-up assistance is part of the Plan unless we tell the Hospital otherwise in writing."
        ] },
        { title: "Third-party services", blocks: [
          "The Service relies on third parties such as cloud hosting, speech-to-text and language-model providers, payment processors and messaging platforms (for example WhatsApp). Their availability and terms are outside our control. Where a messaging platform is used to send reminders or tokens to patients, the Hospital is responsible for having the right to contact those patients."
        ] },
        { title: "Intellectual property", blocks: [
          "{{company}} and its licensors own the Service, including the software, design, text, graphics and the {{brand}} name and logo. During its subscription, the Hospital receives a non-exclusive, non-transferable, revocable right to use the Service for its own hospital operations. No ownership passes to the Hospital.",
          "If the Hospital gives us feedback or ideas about the Service, we may use them without obligation to the Hospital."
        ] },
        { title: "Confidentiality", blocks: [
          "Each party will keep the other’s non-public business, pricing and technical information confidential, use it only for the purposes of these Terms, and share it only with people who need to know it and are bound to keep it confidential. This does not apply to information that is public through no fault of the receiving party, that it already knew or received lawfully from someone else, or that it must disclose by law (in which case it will tell the other party first where it lawfully can). This section continues for three years after the Service ends. Patient Data stays protected for as long as we hold it."
        ] },
        { title: "Warranties and disclaimers", blocks: [
          "We provide the Service with reasonable skill and care. Except as stated in these Terms, and to the extent the law allows, the Service is provided “as is”, and we give no other warranty, including that it will be error-free or fit for a particular purpose. We give no warranty about clinical outcomes or about AI-generated output."
        ] },
        { title: "Limitation of liability", blocks: [
          { ul: [
            "To the extent the law allows, neither party is liable to the other for indirect, special or consequential loss, or for loss of profit or goodwill.",
            "Our total liability for all claims arising out of or relating to these Terms in any 12-month period is limited to the fees the Hospital paid us for the Service in the 12 months before the event that gave rise to the claim.",
            "We are not responsible for clinical decisions, diagnosis, treatment or outcomes, which are the Hospital’s responsibility, or for claims by patients against the Hospital, except to the extent caused by our breach of these Terms.",
            "Nothing in these Terms limits any liability that cannot be limited by law, including liability for fraud or wilful misconduct."
          ] }
        ] },
        { title: "Indemnity", blocks: [
          "The Hospital will defend and compensate us against third-party claims arising from (a) the clinical and other services the Hospital provides, (b) the Hospital’s or its Authorised Users’ breach of the law or of these Terms, or (c) Hospital Data that the Hospital had no right to use.",
          "We will defend and compensate the Hospital against third-party claims that the Service, as we provide it, infringes Indian intellectual property rights, subject to the limit in the section on limitation of liability.",
          "The party seeking protection must tell the other promptly, allow it to control the defence, and cooperate reasonably."
        ] },
        { title: "Suspension and termination", blocks: [
          { ul: [
            "The Hospital may stop using the Service at the end of a paid cycle by telling us in writing. We do not refund the unused part of a paid cycle unless the law requires it or we agree.",
            "We may suspend or end access if the Hospital does not pay after the grace period, seriously or repeatedly breaches these Terms, uses the Service unlawfully, or puts the security of the Service or of other hospitals at risk. Where practicable, we will tell the Hospital first and allow a reasonable time to put things right.",
            "If we end the Service for a reason other than the Hospital’s breach, we will refund the unused part of the paid cycle.",
            "Export and deletion. We will not delete Hospital Data during the 90 days after the Service ends, so that the Hospital can export it or come back. After that, we delete or anonymise it when the Hospital asks in writing, or after giving the Hospital 30 days’ notice, except where the law requires us to keep it. Backups are overwritten in the normal course. The Hospital’s legal duty to keep medical records stays with the Hospital, so it should export its records before it leaves.",
            "Sections that by their nature should continue after the Service ends (including payment, confidentiality, intellectual property, liability, indemnity and governing law) do continue."
          ] }
        ] },
        { title: "Changes to these Terms", blocks: [
          "We may update these Terms. For material changes we will give at least 30 days’ notice in the Service or by email, and we may ask Authorised Users to accept the updated Terms when they next sign in. If the Hospital does not agree, it may end its subscription before the change takes effect. Using the Service after the effective date means the Hospital accepts the change. We will remind users of these Terms at least once a year."
        ] },
        { title: "Notices", blocks: [
          "Notices to us go through the contact details on our website. Notices to the Hospital go to the contact details it gave us or appear in the Service. Electronic notices are valid."
        ] },
        { title: "Governing law and disputes", blocks: [
          "These Terms are governed by the laws of India. The parties will first try to settle any dispute by good-faith discussion for 30 days after one party gives the other written notice of it. If the dispute is not settled, it will be finally resolved by arbitration under the Arbitration and Conciliation Act, 1996, by a sole arbitrator appointed by agreement or, failing agreement, as the Act provides. The seat and venue of arbitration are the city in India where {{company}}’s registered office is situated, and the language is English. Subject to this, the courts at that city have exclusive jurisdiction. Either party may ask a competent court for urgent interim relief."
        ] },
        { title: "General", blocks: [
          { ul: [
            "These Terms, the Privacy Policy and the Hospital’s order are the whole agreement about the Service. If they conflict on commercial terms, the order prevails.",
            "If part of these Terms cannot be enforced, the rest continues to apply.",
            "A delay in enforcing a right is not a waiver of it.",
            "The Hospital may not transfer these Terms without our written consent. We may transfer them to a successor to our business, and we will tell the Hospital if we do.",
            "Neither party is liable for delay or failure caused by events beyond its reasonable control, other than a duty to pay.",
            "The parties are independent. These Terms do not create a partnership, employment or agency, and give no rights to anyone who is not a party."
          ] }
        ] },
        { title: "Contact and grievances", blocks: [
          "Questions about these Terms, and complaints, can be sent to our Grievance Officer. We acknowledge a complaint within 48 hours and aim to resolve it within 15 days.",
          { contact: true }
        ] }
      ]
    },

    patients: {
      lead: "These Terms explain how you may use the {{brand}} patient portal, which is run by {{company}}. They are between you and {{company}}. Your treatment is provided by the hospitals and doctors you visit, not by {{company}}.",
      summary: [
        "The portal shows your records and lets you book appointments. It is not medical advice.",
        "In an emergency, do not use the portal. Go to the nearest hospital or call 108 or 112.",
        "You keep your password private. You can add family members with their permission.",
        "The rules for cancelling and refunds are shown before you pay.",
        "We do not sell your information."
      ],
      sections: [
        { title: "About the portal and these Terms", blocks: [
          "The patient portal is a service from {{company}} that lets you see your visits, prescriptions, test reports and bills from the hospitals you have visited, and book appointments with them. By creating an account, signing in or tapping accept, you agree to these Terms and to the Privacy Policy. If you do not agree, please do not use the portal.",
          "Accepting on screen is a valid way to agree under the Information Technology Act, 2000."
        ] },
        { title: "Who can use the portal", blocks: [
          "You must be 18 or older to hold your own account. A profile for a child is managed by the child’s parent or legal guardian, who accepts these Terms for the child and is responsible for that profile. Do not pretend to be someone else."
        ] },
        { title: "Your account", blocks: [
          { ul: [
            "Give correct details and keep them up to date.",
            "Keep your password private and do not share your login. You are responsible for what happens through your account.",
            "Add a family member’s profile only with their permission, or as their parent or guardian.",
            "Tell us at once if you think someone else has used your account. We may ask you to verify yourself again, or lock the account, to protect it."
          ] }
        ] },
        { title: "What the portal does", blocks: [
          { ul: [
            "Shows your visits, prescriptions, test and scan reports, admissions and bills, from every hospital you have visited, in one place.",
            "Lets you book, view, reschedule where the hospital allows it, and cancel appointments.",
            "Lets you check that a prescription or report is genuine by scanning its QR code."
          ] },
          "The portal shows what hospitals have recorded. It may be incomplete or not yet up to date, because a hospital may take time to add a record. If something looks wrong, tell the hospital."
        ] },
        { title: "Medical care and emergencies", blocks: [
          "{{company}} is not a hospital or a doctor. We do not give medical advice, and using the portal does not create a doctor–patient relationship with us. Always follow your doctor’s advice. The portal does not replace it.",
          { note: "The portal is not for emergencies. In an emergency, go to the nearest hospital or call 108 or 112." },
          "Your doctor may use an AI scribe to draft the note of your consultation. Your doctor must tell you first, and you can say no. The doctor checks the note and is responsible for it."
        ] },
        { title: "Appointments", blocks: [
          { ul: [
            "The fee for a consultation is set by the hospital. It is shown before you confirm.",
            "A booking holds your slot. If a booking is not paid in time, the hospital may release the slot. We limit how many unpaid holds one account can have at a time.",
            "Please reach the hospital by your slot time. If you arrive late, you will be moved to the next available slot with the same doctor that day instead of losing your booking.",
            "If you cancel, the refund depends on how early you cancel. The rules that apply are shown before you pay and again when you cancel. Close to the consultation time, cancelling may not be possible.",
            "If the hospital or doctor cancels or cannot see you, you will be refunded in full or offered a new slot.",
            "The hospital provides the consultation. If something goes wrong with a visit, please raise it with the hospital first."
          ] }
        ] },
        { title: "Payments and refunds", blocks: [
          "Online payments are handled by payment partners. We do not store your card number or UPI PIN. Amounts, and any taxes, are shown before you pay, and you receive a receipt.",
          "A refund goes back to the way you paid. How long it takes to reach you depends on your bank or payment provider. If you think you were charged wrongly, contact us or the hospital and we will look into it."
        ] },
        { title: "Your information", blocks: [
          "How we and the hospitals handle your information is explained in the Privacy Policy. If you share a document or screen with someone, they can see what you show them, so share only with people you trust."
        ] },
        { title: "Fair use", blocks: [
          "Please do not:",
          { ul: [
            "make false or repeated bookings you do not intend to use;",
            "share your login, or try to see anyone else’s information;",
            "collect information from the portal by automated means;",
            "misuse QR verification, or tamper with a prescription, report or bill;",
            "upload anything unlawful, harmful or abusive, or try to disrupt the portal."
          ] }
        ] },
        { title: "Availability and changes", blocks: [
          "We work to keep the portal running, but it may sometimes be unavailable for maintenance or for reasons outside our control. Download or keep a copy of anything important. We may improve or change the portal over time."
        ] },
        { title: "Third-party services", blocks: [
          "The portal uses third parties, for example payment partners and messaging platforms such as WhatsApp for reminders and tokens. Their own terms apply to their services."
        ] },
        { title: "Intellectual property", blocks: [
          "The portal, including its software, design and the {{brand}} name and logo, belongs to {{company}} and its licensors. You may use it for your own personal, non-commercial purposes while your account is open. You may not copy it, reverse engineer it or use it to build another service."
        ] },
        { title: "Suspending or closing your account", blocks: [
          "You can ask to close your account at any time through “Data & privacy requests” in the portal’s profile menu. We may suspend or close an account that breaks these Terms or puts the portal or other people at risk. Closing your account does not erase records that hospitals must keep by law. Those stay with the hospitals."
        ] },
        { title: "Our responsibility", blocks: [
          "We provide the portal with reasonable care. To the extent the law allows, we are not responsible for medical decisions, treatment or the acts of hospitals and doctors, for indirect losses, or for the portal being unavailable. Where we are responsible to you, our total liability is limited to the amount you paid us for the portal in the previous 12 months, if any.",
          "Nothing in these Terms takes away any right you have under Indian law, including the Consumer Protection Act, 2019, or limits any liability that cannot be limited by law."
        ] },
        { title: "Changes to these Terms", blocks: [
          "We may update these Terms. If a change is important, we will tell you in the portal and ask you to accept again. We will remind you of these Terms at least once a year."
        ] },
        { title: "Complaints", blocks: [
          "If you have a complaint about the portal, send it to our Grievance Officer, or use “Data & privacy requests” in the portal’s profile menu. We acknowledge a complaint within 48 hours and aim to resolve it within 15 days of receiving it.",
          { contact: true }
        ] },
        { title: "Governing law", blocks: [
          "These Terms are governed by the laws of India. Subject to your rights as a consumer, including your right to approach a consumer commission where you live, the courts at the city in India where {{company}}’s registered office is situated have jurisdiction over disputes about the portal."
        ] }
      ]
    }
  },

  /* ======================================================================== PRIVACY POLICY */
  privacy: {
    hospitals: {
      lead: "This Privacy Policy explains how {{company}} handles information when hospitals use {{brand}}. It covers information about the hospital and its staff, which we decide how to use, and patient information that hospitals enter, which we handle on the hospital’s behalf. It follows the Information Technology Act, 2000, the Information Technology (Reasonable Security Practices and Procedures and Sensitive Personal Data or Information) Rules, 2011, and the Digital Personal Data Protection Act, 2023 and the rules made under it, as they come into force.",
      summary: [
        "Hospitals decide how patient information is used. We handle it only to run the service for them.",
        "We do not sell personal information and we do not use it for advertising.",
        "Each hospital’s data is kept separate. Access is by role, and important actions are logged.",
        "The AI scribe turns speech into text. We do not keep the audio recording, and the doctor confirms every note.",
        "You can ask us about your information at any time."
      ],
      sections: [
        { title: "Who we are and our roles", blocks: [
          "{{company}} provides {{brand}}. Our role depends on the kind of information:",
          { table: { head: ["Information", "Who decides how it is used", "Our role"], rows: [
            ["Patient records and other data that a hospital enters", "The hospital", "We are the hospital’s processor. We act on its instructions."],
            ["Hospital account, billing and usage information; staff account information", "We do", "We are the Data Fiduciary."],
            ["Website enquiries and demo requests", "We do", "We are the Data Fiduciary."],
            ["Patient portal accounts", "We do (see the patient part of this Policy)", "We are the Data Fiduciary for portal account data."]
          ] } }
        ] },
        { title: "Information we collect", blocks: [
          { table: { head: ["Category", "Examples", "Where it comes from"], rows: [
            ["Hospital and business details", "Name, registration and licence details, address, GST number, contact people, Plan, invoices and payment records", "The hospital, and our onboarding"],
            ["Staff account details", "Name, role, email, phone, professional registration where entered, password (stored only in hashed form), attendance and sign-in records, staff chat messages", "The hospital’s administrator and staff"],
            ["Patient and clinical data (health information)", "Identity and contact details, age, gender, address, visits, vitals, consultation notes, prescriptions, test orders and results, reports, pharmacy dispensing, admissions and discharge records, bills and payments, referrals, consent records", "Hospital staff, and patients through the portal"],
            ["AI scribe data", "Live audio during a consultation that is recorded for the scribe, its text transcript and the drafted note", "The consultation"],
            ["Audit and security data", "A record of important actions (who, what, when), IP address, device and browser type, error diagnostics", "Collected automatically"],
            ["Enquiries", "Name, phone, email, hospital, city and message", "The person who contacts us"]
          ] } }
        ] },
        { title: "How and why we use information", blocks: [
          "We use information to:",
          { ul: [
            "provide, run, secure and support the Service, including onboarding and training;",
            "bill for the Service and keep accounting and tax records;",
            "reply to enquiries, requests and complaints;",
            "keep the Service safe, prevent misuse and investigate incidents;",
            "measure usage and improve the Service, using information that cannot identify a person or hospital where possible;",
            "send service messages, such as renewals, changes and security notices; and",
            "meet our legal duties."
          ] },
          "We use patient information only to provide the Service to the hospital that entered it, and only as that hospital instructs. We do not sell personal information, and we do not use it for advertising or for marketing profiles.",
          "We rely on the consent of the person concerned, which the hospital obtains for patient information, or on another ground that the law allows, such as performing a contract or meeting a legal duty."
        ] },
        { title: "Sensitive personal data", blocks: [
          "Health information is sensitive personal data. We collect, use and disclose it only for the purposes of the Service, only as the hospital instructs, and only with the consent the hospital obtains from its patients or as the law otherwise permits. A patient who wishes to withdraw consent should contact the hospital, and we will help the hospital act on it."
        ] },
        { title: "AI processing of consultations", blocks: [
          "When a doctor records a consultation for the AI scribe:",
          { ol: [
            "the hospital has told the patient and obtained the patient’s agreement, and the Service records that agreement;",
            "the audio is streamed to a speech-to-text provider, which returns a text transcript. We do not keep the audio as a recording;",
            "the transcript is stored in encrypted form with the consultation;",
            "before the text is sent to a language-model provider to organise it into a note, we remove the patient’s name and phone number from it;",
            "the model returns a draft note, which the doctor reviews, edits and confirms."
          ] },
          "These providers may process the information only to give us the service, under written terms, and we do not use patient information to train AI models. The AI does not make decisions about a patient. It drafts, and the doctor decides."
        ] },
        { title: "Who we share information with", blocks: [
          "Inside a hospital, access depends on role, so each person sees what they need for their work. Hospitals do not see each other’s data. In the patient portal, a patient sees their own records from every hospital they have visited.",
          "We share information only with:",
          { ul: [
            "cloud hosting, database and storage providers that run the Service;",
            "speech-to-text and language-model providers used for the AI scribe;",
            "payment processors and messaging providers (such as WhatsApp) that deliver payments, reminders and tokens;",
            "error-monitoring and similar tools that help us find and fix faults. We limit what these tools receive;",
            "professional advisers, such as lawyers and auditors, under confidentiality;",
            "authorities, courts and regulators, where the law requires or a lawful order is made; and",
            "a successor to our business, if we are sold or merge, who must keep to this Policy."
          ] },
          { note: "Prescriptions, invoices and reports carry a QR code. Anyone who scans it can see the details needed to check that the document is genuine, such as the hospital, the doctor, the patient’s name and the items listed. Hospitals should tell patients this." }
        ] },
        { title: "Storage and transfers", blocks: [
          "We store information with reputable cloud providers under written contracts. Some providers, for example for AI or messaging, may process information outside India. We choose providers that give protections consistent with this Policy, and we follow the rules of Indian law on transfers."
        ] },
        { title: "Security", blocks: [
          "We follow reasonable security practices and procedures. They include encrypted connections (HTTPS), encryption of sensitive fields such as consultation transcripts, hashed passwords, role-based access, separation of each hospital’s data, temporary lock-out after repeated failed sign-ins, an audit trail of important actions, backups, and confidentiality duties for our people.",
          "If a personal data breach occurs, we will tell the affected hospital without undue delay, and where possible within 72 hours, and we will help it meet its duty to inform the Data Protection Board of India and affected people. We report incidents to CERT-In as the law requires."
        ] },
        { title: "How long we keep information", blocks: [
          { table: { head: ["Information", "How long"], rows: [
            ["Patient and clinical records", "For the life of the hospital’s subscription, and afterwards as the hospital instructs and the law requires. We do not delete medical records automatically."],
            ["Audit trail", "Kept with the hospital’s records. It is not deleted automatically."],
            ["Consultation transcripts", "Kept as part of the consultation record, unless the hospital’s retention setting provides for earlier deletion. The audio is not kept."],
            ["Hospital account, billing and tax records", "While the account is active, and afterwards for the period that tax and company law require."],
            ["Staff messages and uploaded files", "While the hospital’s account is active, unless users or the hospital delete them sooner."],
            ["Message delivery records", "About 180 days."],
            ["Enquiries", "Up to 24 months after the last contact, unless the hospital becomes a customer."],
            ["After the Service ends", "As set out in the Terms of Service: 90 days for export, then deletion or anonymisation as described there."]
          ] } },
          "Backups are overwritten in the normal course."
        ] },
        { title: "Rights and choices", blocks: [
          "Under the Digital Personal Data Protection Act, 2023, every person whose information we hold may ask to:",
          { ul: [
            "see a summary of their information and how it is used;",
            "correct or complete it;",
            "have it erased, unless the law requires us or the hospital to keep it;",
            "withdraw consent;",
            "nominate another person to exercise these rights if they die or become unable to; and",
            "have a grievance resolved."
          ] },
          "Staff and hospital contacts can make a request to us directly. If a patient contacts us about treatment records, we pass the request to the hospital, which is responsible for answering it, and we help the hospital do so. We may need to confirm who you are first. We aim to reply within 30 days."
        ] },
        { title: "What hospitals must do", blocks: [
          "As the Data Fiduciary for patient information, each hospital must:",
          { ul: [
            "give patients clear notice when it collects their information, and obtain consent where the law requires it, including before AI recording, and for tests or procedures that need specific consent;",
            "collect only what it needs, and keep it accurate;",
            "answer patients’ requests, and keep medical records for as long as the law requires;",
            "obtain the verifiable consent of a parent or guardian for a child’s information;",
            "report a personal data breach to the Data Protection Board of India and to the people affected, as the law requires;",
            "keep staff accounts secure and make sure its staff understand their confidentiality duties."
          ] }
        ] },
        { title: "Children", blocks: [
          "Records of patients under 18 are handled with the consent of a parent or guardian. We do not allow children to open patient portal accounts, and we do not track children or aim advertising at them."
        ] },
        { title: "Cookies and similar technologies", blocks: [
          "We use only what is needed to run the Service: browser storage that keeps you signed in, remembers settings and protects your session. We do not use advertising or analytics cookies, and we do not track you across other websites."
        ] },
        { title: "Changes to this Policy", blocks: [
          "We may update this Policy. If a change is important, we will tell you in the Service or by email, and we may ask you to accept it again. The date at the top shows when it last changed."
        ] },
        { title: "Grievance Officer and contact", blocks: [
          "If you have a question or complaint about your information, contact our Grievance Officer. We acknowledge a complaint within 48 hours and aim to resolve it within 15 days. If you are not satisfied, you may approach the Data Protection Board of India as the Digital Personal Data Protection Act, 2023 provides.",
          { contact: true }
        ] }
      ]
    },

    patients: {
      lead: "This part of our Privacy Policy is for patients and everyone who uses the {{brand}} patient portal. It explains what information is held about you, why, who can see it, and how you can control it. It follows the Information Technology Act, 2000, the Information Technology (Reasonable Security Practices and Procedures and Sensitive Personal Data or Information) Rules, 2011, and the Digital Personal Data Protection Act, 2023 and the rules made under it, as they come into force.",
      summary: [
        "Hospitals hold your treatment records. {{company}} runs the portal that shows them to you.",
        "Your records are visible to you and to the hospital staff involved in your care. They are not sold and are not used for advertising.",
        "If your doctor records a consultation for the AI note, they must tell you first. You can say no.",
        "You can ask for a copy, a correction or deletion. Some medical records must be kept by law.",
        "Questions or complaints go to our Grievance Officer."
      ],
      sections: [
        { title: "Who is responsible for your information", blocks: [
          "Two kinds of organisation handle your information:",
          { ul: [
            "The hospitals you visit hold your treatment records. Each hospital decides why and how its records about you are used (it is the “Data Fiduciary”). {{company}} handles those records on the hospital’s behalf. The hospital’s own privacy notice also applies.",
            "{{company}} is responsible for your portal account: your sign-in, your profiles, your bookings and the combined view of your records."
          ] }
        ] },
        { title: "Information about you", blocks: [
          { table: { head: ["Category", "Examples", "Where it comes from"], rows: [
            ["Portal account", "Name, mobile number, password (stored only in hashed form), details you add such as age, gender and address, saved addresses", "You"],
            ["Family profiles", "Details of family members you add, with their permission or as their parent or guardian", "You"],
            ["Records from hospitals", "Visits, vitals, prescriptions, test and scan reports, admissions, referral details, bills and payments", "The hospitals you visit"],
            ["Bookings and payments", "Appointment details, payment status and refunds. Our payment partners handle your card or UPI details. We do not store card numbers or PINs", "You and our payment partners"],
            ["AI note-taking", "If your doctor records the consultation: the audio is processed live and is not kept as a recording. The transcript and the note become part of your hospital record", "The consultation"],
            ["Requests you send us", "Data and privacy requests, and suggestions to add a hospital that is not listed (the hospital name or place, and your mobile number)", "You"],
            ["Technical data", "Device, browser, IP address and security logs", "Collected automatically"]
          ] } }
        ] },
        { title: "Why we use your information", blocks: [
          { ul: [
            "to show you your records and to let you book and manage appointments;",
            "to take payments and make refunds;",
            "to send reminders and tokens for your appointments;",
            "to keep your account and records secure and to prevent misuse;",
            "to answer your questions, requests and complaints;",
            "to improve the portal, using information that cannot identify you where possible; and",
            "to meet legal duties."
          ] },
          "We do not sell your information. We do not use it for advertising."
        ] },
        { title: "Your consent", blocks: [
          "By creating a portal account and accepting this Policy, you agree that we may collect and use your information as described here, including health information, which is sensitive personal data. You may withdraw your consent at any time through “Data & privacy requests” in the portal’s profile menu. If you do, some portal features will stop working. Records that hospitals must keep by law stay with the hospitals."
        ] },
        { title: "AI note-taking", blocks: [
          "Your doctor may use an AI scribe to draft the note of your consultation. Your doctor must tell you first and ask for your agreement, and you can say no. The consultation will go ahead without it.",
          "If you agree, your voice is converted into text while you speak. We do not keep the audio as a recording. Before the text is organised into a note by an AI language model, your name and phone number are removed from it. The doctor checks the note and is responsible for the final version. The AI does not diagnose you or make decisions about your care. We do not use your information to train AI models."
        ] },
        { title: "Who can see your information", blocks: [
          { ul: [
            "You, and the people whose profiles you manage.",
            "The staff of a hospital involved in your care, and only according to their role. A hospital sees its own records about you. It does not see your records from other hospitals.",
            "People at {{company}} only when needed to run and support the portal, and bound by confidentiality.",
            "Service providers that help us run the portal (for example hosting, payment and messaging providers), under written terms.",
            "Authorities and courts, when the law requires it."
          ] },
          { note: "Prescriptions, invoices and reports carry a QR code. Anyone who scans it can see the details needed to check that the document is genuine, such as the hospital, the doctor, your name and the items listed. Show a printed or shared copy only to people who need to check it." }
        ] },
        { title: "Storage and transfers", blocks: [
          "Your information is stored with reputable cloud providers under written contracts. Some providers, for example for AI or messaging, may process information outside India. We choose providers that give protections consistent with this Policy, and we follow the rules of Indian law on transfers."
        ] },
        { title: "Security", blocks: [
          "We follow reasonable security practices and procedures. They include encrypted connections (HTTPS), encryption of sensitive fields, hashed passwords, role-based access, temporary lock-out after repeated failed sign-ins, a log of who opened or changed records, and confidentiality duties for our people. Please keep your password private. If you think your account has been misused, tell us at once.",
          "If a personal data breach affects you, we and the hospital will inform you and the Data Protection Board of India as the law requires."
        ] },
        { title: "How long we keep your information", blocks: [
          { ul: [
            "Medical records are kept by the hospital for as long as the law and medical practice require it to keep them.",
            "Your portal account is kept while it is open. When you close it, we delete or anonymise your account details within 30 days, except what we must keep for legal reasons, such as payment records and the record of your consents and requests.",
            "Message delivery records are kept for about 180 days."
          ] }
        ] },
        { title: "Your rights", blocks: [
          "Under the Digital Personal Data Protection Act, 2023, you may:",
          { ul: [
            "ask for a summary of your information and how it is used;",
            "ask for it to be corrected or completed;",
            "ask for it to be erased, unless the law requires it to be kept;",
            "withdraw your consent;",
            "nominate another person to exercise these rights if you die or become unable to; and",
            "have a complaint resolved."
          ] },
          "To use these rights, open “Data & privacy requests” in the portal’s profile menu and choose a copy of your data, a correction, or deletion. We may need to confirm who you are. We reply within 15 days. For treatment records, the hospital decides what can be corrected or erased, and we pass your request to it. Some medical records must be kept by law and cannot be erased."
        ] },
        { title: "Children", blocks: [
          "A child’s profile is created and managed by a parent or guardian, who gives consent for the child. We do not allow children to open their own portal accounts, and we do not track children or aim advertising at them."
        ] },
        { title: "Cookies and similar technologies", blocks: [
          "We use only what is needed to run the portal: browser storage that keeps you signed in and protects your session. We do not use advertising or analytics cookies, and we do not track you across other websites."
        ] },
        { title: "Changes to this Policy", blocks: [
          "We may update this Policy. If a change is important, we will tell you in the portal and ask you to accept it again. The date at the top shows when it last changed."
        ] },
        { title: "Grievance Officer and contact", blocks: [
          "If you have a question or complaint about your information, contact our Grievance Officer or use “Data & privacy requests” in the portal. We acknowledge a complaint within 48 hours and aim to resolve it within 15 days. If you are not satisfied, you may approach the Data Protection Board of India as the Digital Personal Data Protection Act, 2023 provides.",
          { contact: true }
        ] }
      ]
    }
  }
};