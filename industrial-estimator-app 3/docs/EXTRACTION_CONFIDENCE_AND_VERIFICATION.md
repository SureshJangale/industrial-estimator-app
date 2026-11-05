# Extraction reliability, confidence and requirement verification

## Safety principle

A source extraction's `confidence_score` (0–99) is a heuristic match-strength score. It is **not calibrated probability**, **not an engineering approval**, and **not a guarantee that the document is correct**. We deliberately never label machine-extracted requirements 100% certain.

The release target is **100% human-review coverage of critical requirements with recorded evidence**, not 100% AI accuracy.

## Per-field data contract

For every candidate extraction:

- `kind`, `key`, `value`, `raw_value`, `raw_unit`, `unit`: normalized and original values.
- `document_id`, `page` / logical section, `evidence`, `source_location`: source provenance.
- `method`, `confidence_score`, `confidence_basis`, `confidence_kind`: extraction method and rationale.
- `review_status`: initially `UNVERIFIED`. User acceptance creates/updates a requirement in PENDING state; only an authorized engineer can mark it APPROVED.

When a requirement is entered manually or no candidate can be matched to the record, its extraction score is `null`, not a fabricated 100.

## High-consequence validation gates

1. Every configured mandatory technical requirement must be present and engineer-approved.
2. The relevant source and the evidence note must be available to the reviewer.
3. Conflicting normalized values from documents are held for resolution. The reviewer must choose an authoritative value, verify it as a requirement, and record why.
4. A new uploaded source invalidates prior source-conflict resolutions on affected fields.
5. The approved technical values must not conflict with values recognized in customer-facing selling-price line descriptions.
6. Commercial price lines, tax configuration, terms and role approvals must match the exact current fingerprint before firm issue.
7. The system must *not* invent unprovided measurements, material quantities, safety calculations or vendor prices.

## Current supported cases

- Text-based PDF extraction and Word DOCX paragraphs/tables.
- Explicit numeric field labels and unit normalization (`5000 kg` = `5 t`, `8.6 mtr` = `8.6 m`).
- Document reference duplication and recognized contradictions.
- Separate requirements for hoist headroom and minimum crane headroom, preventing a false conflict from 800 mm vs 450 mm.
- Source matching based on product configuration: product field names and controlled aliases; no executable user regex.
- Recognized material names from configured literal synonyms (never automatically derive cut lengths).

## Known limitations

- No image-to-geometry interpretation; scanned PDFs without selectable text need local OCR or manual review.
- PDF text extraction may reorder tables or omit text; a missing candidate is not evidence that a requirement is absent.
- DOCX does not encode stable physical page numbers, so provenance is logical section/text rather than a printed page.
- Heuristic extraction scores have not been calibrated against a labelled dataset.
- Text aliases can be ambiguous. Low confidence is flagged; high confidence is **not sufficient for automatic approval**.
- Conflict detection only works for fields that the extractor successfully recognizes and normalizes.

## Field evaluation programme before wider use

Build a private gold dataset of at least 50 varied examples per target product/document type, with engineer-labelled fields and expected source spans. Include source ambiguity, scans, unit variations, revised drawings, contradictory tables and missing fields. Measure per-field precision, recall, false-positive rate, normalization accuracy and time to human verification. Keep unseen test cases separate from tuning data.

For a controlled pilot, require no unresolved critical disagreements and full reviewer coverage; investigate every critical extraction defect. No finite test sample proves universal 100% accuracy. Do not distribute private source documents to third-party models or public repositories without permission.
