# IndustriQuote v0.7.0-dev - company configuration and quantity-unit hardening

This is a **local development release**, not a production certification.

### Fixed

- New **Company setup** page: admin can update seller name, office/works address, GSTIN, contact information, signatory, optional header line, quote-reference prefix and suggested units.
- Company configuration now persists in the database rather than being copied exclusively from Yash Engineering constants. Yash remains the **default for the current factory installation**. New company installs can use different data.
- Seller details are snapshotted per quotation; existing drafts can explicitly refresh with **Apply company defaults**. Issued PDF/DOCX snapshots are unaffected.
- Quote 73 A4 PDF keeps the original **right-side quotation number** position. The editable Word version has a corresponding right-aligned reference/date field.
- Customer pricing supports decimal quantities and per-line units (`Set`, `Pair`, `kg`, `m`, `m2`, `sq ft`, `hour`, `job`, custom labels). Quantity x rate is deterministic and remains associated with that unit.
- Fixed-price (lump sum) items cannot misleadingly claim a quantity greater than one; use `UNIT_RATE` instead.
- Internal price-book and BOM unit fields are editable; undefined unit conversions are rejected.
- Corrected DOCX pagination: repeating price rows shrink the blank item region in the **stock Quote 73 Word fallback**, preventing one-page samples from splitting off the signatory.
- Stock Quote 73 Word header is a configurable placeholder. Stock Word output now uses rupee-formatted item amounts and plain numeric tax/total cells, closer to the supplied original.
- More than 40 additional negative/positive checks from earlier versions retained; new tests cover admin-only settings, second company branding, unit arithmetic, invalid labels, reference alignment and safe price conversion failures.

### Compatibility

- New `company_settings` database table is additive. Yash settings are seeded only for an installation that has no company configuration.
- Existing commercial quote branding remains as a snapshot; a blank/missing Yash header from prior versions is migrated conservatively.
- Untouched built-in Word Quote 73 layouts can update to the new placeholder contract. Admin-replaced Word layouts are preserved.
- For safe local testing, extract this release into a **new directory** and run on a separate port. Backup old data before attempting any manual migration.

### Not yet completed

True SaaS tenant isolation, calibrated OCR/drawing-to-BOM accuracy, production schema migrations, secure public deployment hardening, formal GST review and a full interactive browser QA matrix. See `docs/COMPANY_CONFIG_AND_DEPLOYMENT.md`.
