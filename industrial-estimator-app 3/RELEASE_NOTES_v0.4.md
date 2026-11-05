# IndustriQuote v0.4 — Release notes

## Included in this release

- Product-independent equipment supply, repair/service, and general quotation flows from v0.3.
- Source-linked, local PDF/DOCX text extraction with heuristic confidence, explicit engineer confirmation, and conflict resolution. Confidence is NOT a calibrated probability of truth.
- Separate cost model and selling-price schedule, unit-rate/fixed/at-actual/description pricing, configured taxes, and immutable issued PDFs.
- New **Quotation templates** admin page: three built-in defaults, custom template creation/duplication/editing, safe JSON upload/export, synthetic preview PDF, version history and defaults by workflow.
- Template choice per quotation, with compatibility checks. Changes in a selected template's layout invalidate stale quote approvals but not previously issued PDF bytes.
- Template rendering is based on safe, validated section definitions and text only: no script execution or untrusted HTML.

## Validation

- 21 backend integration tests passed including template library permissions, imports, layouts, default switching, approval invalidation and frozen issued PDFs.
- Frontend JavaScript syntax and structural render checks passed.
- Generated example PDF was rendered and visually inspected after adjusting pagination.
- A true interactive Chromium test was attempted but the sandbox prohibits localhost navigation (ERR_BLOCKED_BY_ADMINISTRATOR). Run `tests/browser_smoke.py` locally.

## Unfinished and intentionally excluded

- Arbitrary Word DOCX template upload/visual editing: only JSON-configured PDF templates are supported.
- Scanned image OCR, arbitrary DWG/DXF geometry understanding, automatic validated fabrication quantities, or guaranteed extraction accuracy.
- Enterprise-grade authentication/rate limiting, schema migration against real customer databases, production backups and penetration/security assessment.
- Public multi-tenant SaaS deployment. No private drawings are included in the distributable.

## Deployment

Use localhost with test accounts for a synthetic-data demo. For factory use, create individual accounts, change secrets, restrict to a trusted network, perform off-server backups, and conduct supervised engineering/financial verification. No paid AI or cloud subscription is required for this software.
