# IndustriQuote v0.3 — Release notes

## Implemented

- Independent commercial selling-price schedules; no assumption that sales price equals cost-plus margin.
- Equipment / service / general quote workflow choice, independent of product family.
- Fixed, unit-rate, at-actual, excluded, included and explanatory price lines.
- Configurable tax components and required tax authorization; work-item tax codes.
- Service PDF and equipment annexure PDF templates; quote-specific terms, letterhead and certifications.
- Source-linked PDF + DOCX extraction with heuristic confidence score, evidence, unit normalization and review state.
- Same-field source conflicts and recognized price-description/approved-technical conflicts, which block release.
- Engineer conflict-resolution record invalidated by changes to source data.
- Generic product creation with field aliases and optional material recognition/catalog hints.
- Distinct release gates per commercial workflow, role separation and immutable issued PDFs.

## Validated with synthetic test scenarios informed by three real-world quotations

- Motor repair: 39,500 + 6,000 = 45,500 before tax; separate 9% + 9% yields 53,690 without double-counting a 21,500/16,000/2,000 work breakdown.
- New equipment: fixed 850,000 plus 25,000 commissioning = 875,000 known subtotal; transport at actual remains explicitly additional, not zero.
- Complex equipment: known fixed components plus two unpriced per-metre rates remain a *partial* amount; conflicting 40 m and 25 m span sources are flagged.
- Different headroom descriptions are handled as distinct configurable fields rather than automatically treating them as contradictory.

## Open before factory production

- Independent document reading against the full actual dataset, including scanned drawings.
- Formal schema migration tests against a copy of the factory database; safe product-config version snapshots.
- Browsing/visual UI QA on a real Mac; accessibility/usability review.
- Comprehensive security hardening and tested restore; customer-specific branding and print validation.
- Calibrated extraction quality metrics; engineer-signed definition of critical fields.
- Any standards compliance, safety analysis, tax applicability and firm quotation approval remain accountable human decisions.
