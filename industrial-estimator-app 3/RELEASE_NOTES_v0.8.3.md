# IndustriQuote v0.8.3-dev — Restore quotation features to cost-plus estimation

**Developer/test build. Not suitable for production or public exposure.**

## Scope agreed with the user

One consistent **cost-plus estimation workflow** for every new product project:

1. Create project and choose product family (no workflow selector).
2. Upload design documents and review extracted requirements with source evidence.
3. Review BOM quantities/material prices and manufacturing/service operations.
4. Review cost breakdown, overhead, contingency, margin, and approvals.
5. Configure and generate the customer quotation from the **same cost-plus selling price**.
6. Archive issued PDF and editable DOCX versions in History.

There is **no second customer-price-line calculation** for newly created projects. Quote format categories are output layouts, not project workflows.

## Restored in every new project and the seeded pallet

- **Quotation tab**, including company letterhead details, named customer contact, customer address, editable quoted-item description/quantity unit, payment and delivery terms, validity, exclusions, and tax confirmation.
- Template gallery / **Choose format**, with Quote 73 fixed-geometry one-page PDF and alternate reusable templates; editable DOCX export.
- Cost-plus BOM, internal rates, operations, overhead, contingency, and **Edit pricing rules** remain the source for selling prices. Changing template/terms does not create another price schedule.
- Both PDF and DOCX require a named customer contact. Drafts are marked provisional; firm issue requires cost-plus engineering/pricing/commercial sign-off plus reviewed tax, contact, terms and valid template.
- **History** archives both issued files. Changes to drafts invalidate applicable approvals, without rewriting previously issued files.
- **Company setup** remains admin-configurable, with Yash Engineering as the starter profile per installation. Existing project seller snapshots are not silently overwritten.
- The dashboard and issue controls use the complete release gate, not only the underlying cost-plus approvals.
- Document extraction, evidence verification and candidate-to-BOM review persistence from v0.8 are unchanged.

## Compatibility and data handling

- Existing **legacy cost-plus** projects gain the shared quotation settings when opened (a new additive settings table; legacy BOM, documents, rates, approvals and issued PDFs remain untouched). They may need a named contact and tax/terms confirmation before draft export or firm issue.
- Older projects *already created* with the deprecated commercial/customer-price-line model retain their historical UI and data. They are **not silently converted** or deleted. That historical model is no longer selectable when creating a new project.
- To use data from an older installation, back up both its database and private-file directory; running this ZIP in a new extracted folder starts a **separate database**. There is no automated cross-installation migration.
- For custom Word template output, layout may shift in a word processor. The built-in Quote 73 PDF uses fixed geometry and rejects content that does not fit its one-page layout.
- The internal calculated selling price is displayed before tax; unapproved taxes or contact prevent firm release. Do not interpret PDF/DOCX drafts as authorized offers.

## Verification

- 65 backend regression tests passed across three groups (29 + 19 + 17).
- Three frontend structural smoke suites passed, including single-workflow project creation and shared quotation controls.
- Rendered and visually checked a one-page Quote 73 PDF and one-page editable DOCX with synthetic project/customer details and configurable Yash Engineering seller profile.
- A clean ZIP extraction, seed/startup and API smoke test must pass before delivery.

## Known release blockers

Interactive end-user browser acceptance on the target Mac remains necessary. Accurate extraction of real design sets must be benchmarked and human verified; crane and service product-specific business rules require validation. Proper database migration/backup-restore, disaster recovery, access security and deployment hardening are not yet production-ready. Separate per-company installs are supported; **multi-tenant SaaS isolation is not**. This is not certified engineering or tax advice.
