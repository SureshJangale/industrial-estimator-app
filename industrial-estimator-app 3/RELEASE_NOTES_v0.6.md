# IndustriQuote v0.6 — Separate template/design uploads, pallet Word layout

## Done
- A separate **Quote formats** administrator screen for reusable DOCX quotation templates (plus existing JSON templates).
- A separate **Documents** second project tab for PDF/DOCX design files and extraction only.
- Downloadable five-page synthetic pallet quotation DOCX with source-backed specification placeholders, repeating BOM and price rows, operations, tax and terms.
- DOCX template validation, private storage, preview via free LibreOffice, customer-project assignment, workflow defaults, replacement/versioning, and issued-PDF immutability.
- API and frontend tests proving the document and template upload paths remain separate.
- Hardening of DOCX relationship validation against external links.

## Important limitations
- Word template imports require the uploaded Word document to **already contain valid `{{...}}` placeholders**. Arbitrary historical quotations are **not automatically converted** to placeholder templates without review.
- Drawings in the Documents tab are inputs for extraction; requirement match scores do not imply 100% certainty.
- This is local pilot software. Install LibreOffice for DOCX-to-PDF rendering; run only on a trusted network and use synthetic/demo data until approved.
- Material cutting lengths, fabrication hours, supplier prices and engineering approvals cannot be invented from the GLT-A reference drawing.
