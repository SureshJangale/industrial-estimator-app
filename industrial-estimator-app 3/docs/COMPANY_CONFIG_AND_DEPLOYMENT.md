# Company profiles, units and safe deployments (v0.7 developer preview)

## What changed

- **Company setup** is an Admin-only screen. It persists the company's legal/display name, office address, works address, GSTIN/tax identifier, email/phone contact, signature title, optional header line, quotation-reference prefix and suggested quantity units.
- **One installation = one company's data**. v0.7 is configurable and repeatable, but **not a multi-tenant SaaS**. Run a separate database, private file directory and administrator account for each customer. Do not share a database or document directory between companies.
- Yash Engineering is the **first-install configuration only**. It is not hardcoded into the main quotation renderer, customer-price engine or company settings UI. The initial form uses the actual Yash details shown in the customer-provided quotations.
- **New quotes snapshot seller information** when created. Editing Company setup affects NEW quotations; it does not mutate previous issued PDF/DOCX files or existing drafts. In a draft, use **Apply company defaults** to explicitly refresh seller details. Any such refresh makes existing quote approvals stale because the quote fingerprint changes.
- Internal project IDs remain unique and stable. New project references use the configured company prefix plus date and random suffix (e.g. `YE-261102-1A2B3C`). The customer-facing quotation number can be overridden per project using **External quote number**, e.g. `73/YE`.

## Quantity and pricing units

- Every customer price line has an **independent text unit**, editable with suggestions: `Nos.`, `Set`, `Pair`, `kg`, `tonne`, `m`, `mm`, `m2`, `m3`, `sqft`, `sq ft`, `hour`, `day`, `job`, `lot`, `roll`, etc.
- `UNIT_RATE` calculates quantity x price using decimal arithmetic and the exact unit entered on that line. `2.5 m2 x 123.40 = 308.50` and `3 Set x 100 = 300.00` both work.
- `FIXED` means **one total lump sum**. Quantity other than `1` must use `UNIT_RATE`; this blocks ambiguous customer-facing rates.
- `AT_ACTUAL`, `EXCLUDED`, `INCLUDED` and `NOTE` are not silently assigned numerical prices.
- Internal price-book and BOM units are editable too. The internal calculation engine will accept a same-unit match but **reject unsupported conversions**, rather than guessing that `ml` can be costed from `litre` or that an arbitrary steel section has a certified weight.
- The present commercial costing/display is **INR only**. There is no foreign-exchange conversion, multi-currency settlement, or tax-jurisdiction engine. Supporting additional currencies needs a separate, tested extension.

## Template behavior

- **Quote 73** remains the default one-page PDF layout, matching the original measured A4 borders and right-side quotation reference position (right edge ~390.9 PDF pt, as in the source).
- The Word `.docx` export is editable and displays the reference in a right-aligned tab in the customer block. For a normal short quote, it shrinks the blank work area when rows are repeated, keeping tax totals and signatory on the same page.
- An admin-uploaded Word quotation design uses **its own layout**; do not force Quote 73 geometry onto another company's template.
- Data fields for buyer and price lines remain dynamic; the source quotation's historical customer/amount is never seeded into new customer quotes.
- A quote with too much content for the one-page PDF throws a readable error instead of clipping. Select a multi-page template.

## Starting another company's installation

1. Create a **new installation directory** and new `DATABASE_URL` and `PRIVATE_DIR`; do not copy Yash's production database or uploaded documents.
2. Install and start the application with that separate environment. Create the administrator using `scripts/start_private.sh` and a strong unique secret; do not use demo credentials for real work.
3. Go to **Company setup** as admin, enter verified seller details and your company's quotation-prefix/unit suggestions.
4. In **Quote formats**, choose a default document layout or upload a reviewed `.docx` with supported placeholders.
5. Configure product families, price catalogue, tax treatment, and approvers independently. Review a synthetic document and then real documents only with written authorization.
6. Test all role, approval, export, backup/restore and PDF-layout flows before allowing use for actual customers.

## Production blockers — not yet release-ready

1. No tenant-aware authorization/storage isolation for serving multiple companies through a shared database.
2. No versioned schema migration framework for incremental production upgrades (the existing `create_all` initialization is a dev convenience).
3. No complete automated browser interaction + cross-platform layout suite; manual Mac review still required.
4. No calibrated extraction accuracy benchmark against a consented corpus of drawings; source matches still need engineering verification.
5. No hardened public-hosting configuration, rate limits, security assessment, disaster recovery/restore drills, or operational monitoring.
6. Currency and tax rules are not universal; they must be independently verified by the company's commercial/accounting team.

**Release recommendation:** treat v0.7 as a **local developer/pilot build**, not a production or multi-tenant SaaS release.
