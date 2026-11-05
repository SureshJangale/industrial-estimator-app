# IndustriQuote v0.8: Evidence-backed review workflow

**Status: developer/pilot build. Not approved for production quotations.**

## Why this change was necessary

Previously a material extraction candidate could be sent to the BOM editor, but the Documents tab forgot which BOM line had been created and showed no actual quantity after reopening. Requirement verification could also be attempted without being guided to enter source evidence. Finally, the **Add price line** label made it look like another internal BOM operation, rather than a customer selling charge.

## The two separate review concepts

1. **Source candidate review**: a PDF/DOCX parser recognizes a possible dimension, material type or process word. This is not an approved requirement, quantity or operation. The Documents tab now shows: *Not reviewed*, *Prefilled; not verified*, *Saved; approval pending*, *Verified*, or *Marked not applicable*.
2. **Accountable verification**: a qualified reviewer checks the actual source and enters a source reference and verification note. This is distinct from the extraction match score (0-99 heuristic). For an issued firm quotation, product and commercial release gates still apply.

## How to use the Documents tab

1. Create a project and upload a **design PDF or DOCX** in the project's **Documents** tab. This is not the separate **Quote Formats** template uploader.
2. For labelled dimensions, click **Review value**. The engineer reviews the original source and confirms/corrects the value, enters drawing revision/page/reference and a verification note; click **Record verified requirement**. Estimator-role users can save a *pending* draft, while an engineer completes verification in **Requirements**.
3. For extracted materials, click **Enter BOM quantity**. Fill the actual quantity, UOM, waste allowance, and takeoff/reference note. This saves an **ASSUMED** BOM record. The Documents tab now displays the saved quantity and has an **Edit saved BOM** button. Revisiting the tab or reopening the project retrieves the live saved quantity.
4. In **BOM & materials**, an engineer uses **Verify** and records the approved cutting-list or calculation reference, plus a verification note. Both Documents and BOM & materials then show the verified status. Editing the quantity resets the status to **ASSUMED** and requires renewed approval.
5. For an operation keyword, click **Enter hours & rate**. The system suggests *only the operation name*, never labour hours/rate. Saved hours and rate are linked to the original document candidate. Procurement approval of operation rates is **not** engineering design certification.
6. If a candidate is irrelevant, choose **Not applicable**, provide a reason and save the decision. The decision remains visible and can be restored.

### Approval error addressed

The previous **"Record verified source evidence before approving requirement"** was a backend-only validation message. The new engineer form asks for:

- confirmed value (editable),
- source reference (document revision/page or independently approved engineering basis), and
- a note explaining the verification performed.

The API rejects empty/unreviewed evidence. Machine-prefilled evidence alone cannot use the old quick-approve route. The review is recorded in the audit trail.

### What "Add customer charge" actually means

The **Customer quotation** tab's **Add customer charge** button adds a row to the **selling-price schedule**, not the material BOM.

For the historical Pallet Lifting Chain quotation, the seller might enter: `Supply of pallet lifting chain; Qty 1; Unit SET; Unit Rate INR 15,500` (historical example, not a current approved price). It will appear on the customer quotation PDF/DOCX. The internal BOM is a separate calculation of steel, purchased components, manufacturing labour and true cost; it must not automatically be copied as another sales charge.

Modes:

- `FIXED`: one lump-sum charge, quantity must be 1.
- `UNIT_RATE`: quantity multiplied by the commercial rate, using the user-selected UOM.
- `AT_ACTUAL`: explicitly extra; no invented amount.
- `INCLUDED`: included in a different selling price.
- `EXCLUDED`: outside seller's scope.
- `NOTE`: descriptive only; prevents double-counting a component breakdown.

The UI now labels the button **Add customer charge**, includes this explanation next to the price table, and retains a separate **Price book** for internal material rates.

## Technical details

Two additive SQLite/PostgreSQL tables are introduced:

- `document_candidate_reviews` stores source document and candidate index, reviewer decision, linked requirement/BOM/operation record, reason and timestamp. Values are read from the **current linked record** when a project is reopened; they are not stale copies.
- `bom_verifications` stores quantity/unit, verified source reference, reviewer note, user and timestamp. Editing a BOM resets its approval, while the old verification record remains in history.

The existing requirement approval path is retained for compatibility with manually supplied evidence, but **will not approve auto-prefilled evidence without explicit reviewer input**. A new `/requirements/{key}/verify` endpoint records the value, source and engineer note atomically. Existing project schema is extended with new tables when the application starts. A **real production migration mechanism is still required** before deployment beyond supervised development.

## Tests and limitations

Automated tests cover: original source retained, extracted candidate prefill, evidence-required approval, stale approval invalidation, BOM save/reopen/edit/verify/delete, operation save/verify, not-applicable/restore decision, multi-role access controls, and customer technical specification syncing. Synthetic fixtures only; confidential customer drawings are not bundled. Frontend DOM structural checks cover review statuses and customer-charge wording.

Not done: calibrated extraction confidence, scanned/PDF image OCR, CAD takeoff, drawing-based BOM quantity derivation, comprehensive role/security audits, backup restoration drills, robust multi-tenancy, and successful graphical browser interaction tests (the execution environment blocks Chromium navigation). These remain production blockers.
