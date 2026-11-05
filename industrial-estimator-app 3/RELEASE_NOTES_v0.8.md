# IndustriQuote v0.8.0-dev — Review Workflow Repair

**Development build only. Do not use it to issue unattended customer quotations.**

## Changes

- Requirements: source-backed engineer review form, corrected values, explicit verification note, audit record and no one-click approval of raw extracted text.
- Documents: persistent candidate review journal; shows saved and verified requirements, material quantities, operation estimates, source locations, and not-applicable decisions after reopening or editing.
- BOM: linked design candidate and live quantity; evidence-backed engineering quantity approval; editing resets approval; removals remove stale active links.
- Operations: saved hours and rate linked to the source keyword; the source never supplies unverified time or pricing.
- Technical specs: shared requirement keys stay aligned between project Requirements and customer-facing specifications; changing a technical value resets its approval.
- Customer quotation: "Add price line" renamed "Add customer charge" with plain-English pricing mode explanations, explicitly separated from internal BOM costs.
- No additional paid dependencies or cloud providers.

## Compatibility

Includes two additive tables: `document_candidate_reviews` and `bom_verifications`. Existing v0.7 SQLite tables remain in place. A fresh local development installation is the safest initial test. For a true production migration, back up the old DB and use a reviewed migration tool instead of `create_all`.

**Version in health endpoint:** `0.8.0-dev`.

## Verification

- Backend and frontend tests, including new source-review regression tests.
- A live browser click-through was attempted but blocked by environment policy (`net::ERR_BLOCKED_BY_ADMINISTRATOR`); it was **not completed**.
- Production certification: **not achieved**. See `docs/PERSISTENT_DOCUMENT_REVIEW_v0.8.md` for remaining blockers.
