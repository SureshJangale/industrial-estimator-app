# IndustriQuote v0.6.3 — Yash Engineering, named contact & dual-format export

## What's new

1. **Official seller identity by default** — YASH ENGINEERING, office + works address, GSTIN, email/phones, proprietor sign-off, transcribed from the supplied quotations. No fictional sellers on newly created quotations. The demo's buyer remains deliberately synthetic.
2. **Customer contact person (Kind Attendance)** — explicit user input. The application prompts before previewing a quote, downloading Word, or issuing. Missing or department-only names (e.g., `Purchase Team`) are refused in both UI and backend. Contact edits invalidate previous approval checks.
3. **DOCX for every commercial quotation** — draft editable Word download beside PDF preview. Built-in Quote 73 PDFs retain original fixed-page geometry, with an editable close-format Word counterpart. The generic and admin-uploaded Word formats also offer a Word download.
4. **Issued Word snapshot** — when the commercial approver issues a quotation, both Word and PDF are stored under immutable issue history. Word downloads from history use the snapshot associated with that numbered issue, not the latest draft.
5. **Old placeholder branding** — development databases with untouched `Your Company` seller names are migrated to Yash Engineering on startup; manually customized other seller profiles are not changed.
6. **Existing commercial workflows retained** — independent pricing, configurable tax components, extraction confidence/evidence, engineering verification, template library, design inputs, review and versioning.

## Important limits

- The **PDF** is the authoritative rendering for matching the provided Quote 73 page. **Editable DOCX** is not pixel-identical, particularly after a user edits it; Word page flow depends on fonts and software.
- A Word edit is a standalone file change: it does **not** update the app, approval states, or PDF. For audited corrections, edit the project and re-issue a new revision.
- Extractions remain unverified candidates until engineering approval; do not infer material quantities or certify cranes automatically.
- Demo credentials must never be exposed on public networks. Keep the factory pilot on localhost/trusted LAN and secure backups.

## Verification

- 44 backend tests covering current and regression workflows, including contact guards, seller defaults, PDF/DOCX outputs, frozen issue history and safe placeholder migration.
- Frontend JavaScript syntax and structural UI checks passed.
- Synthetic Quote 73 PDF and editable Word rendered and visually inspected (one page each). The original customer's contact/price is not included in test artifacts.

## Installation

See `START_HERE_MAC.md`. Use a fresh extracted folder; if using the existing local v0.6.2 database, back it up before trying a migration.
