# IndustriQuote v0.8.4 — Account management update

**This release adds account management to the existing v0.8.3 app, without changing its single Cost-Plus quotation workflow.** Every signed-in user can open My Profile, edit contact details, change their password, revoke sessions, and generate six offline recovery codes. The sign-in screen includes recovery-code password reset. Administrators can create accounts, edit roles/status, and reset another user's password to a temporary password requiring change on next sign-in. Existing SQLite installations use additive, non-destructive account column migrations. A Windows-ready installer kit is distributed separately; a compiled Windows EXE is not included in the source ZIP.

# IndustriQuote v0.8.3-dev — One cost-plus workflow + all quotation controls

**Developer build, not production-ready.** Every new project, regardless of product family, uses the original **Documents → Requirements → BOM → Operations → Cost & approvals** estimation flow. The **Quotation** tab is available in that same project with configurable seller/company details, named recipient, taxes/terms, templates, Quote 73 PDF, editable DOCX, and issued-file history. No separate customer-price-line workflow is created for new projects.

**Start with:** `START_HERE_MAC.md` and `RELEASE_NOTES_v0.8.3.md`. The cost-plus estimate is the sole selling-price calculation; approved tax is added separately. Historical projects from previous workflows remain accessible without automatic conversion. Unzip in a new folder to keep your old database safe.

The rest of this README is *historical*, including descriptions of retired commercial workflows; the v0.8.3 notes above take precedence.

---


# Historical v0.7 notes (current v0.8 instructions above take priority)


**Start here:** `START_HERE_MAC.md` for Mac installation.

**New in this version:** an Admin **Company setup** area (Yash is the factory default, but not hardcoded), editable units per customer line and internal price item, exact Quote 73 right-side reference placement, and corrected one-page editable Word fallback. Full information and remaining production blockers: `docs/COMPANY_CONFIG_AND_DEPLOYMENT.md`.

**Important:** company configuration is one-company-per-isolated-installation, not a safe shared-database multi-tenant model. This release is not production-certified.

---

# Previous v0.6.3 usage notes (historical; v0.7 configuration takes precedence)

**A free, self-hosted, browser-based MVP for manufacturing, equipment-sales, repair and service quotations.** One codebase serves multiple product configurations; the company controls its own drawings, pricing, service descriptions, taxes and approval process.

> **Pilot software, not certified engineering or tax software.** No extractor can guarantee 100% factual accuracy. All high-consequence requirements must be verified against original documents by qualified staff. No paid model/API is required; no uploaded source is transmitted to an external service.

## Start on Mac or Linux

From the extracted top-level application folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
bash scripts/start_demo.sh
```

Open **http://127.0.0.1:8000**. Use `demo` / `demo-pass-123` (local demonstration only). Other demo accounts: `estimator`, `engineer`, `procurement`, `commercial` with the same local demonstration password.

**If you see `requirements.txt not found`, you are not in the extracted application folder.** Run `pwd` and `ls` first. Never expose the demo server to the public internet.

## Yash Engineering is the seller; contact person is required

New commercial quotations use the official **YASH ENGINEERING** details provided in the historical quotations: its office and works addresses, GSTIN `27JILPS1079H1ZL`, email, phone numbers and proprietor sign-off. An administrator can edit the current company configuration under **Company setup**; an estimator can edit the draft seller snapshot in **Customer quotation > Edit contact, terms, GST & letterhead**. The original source document's spelling is retained; verify company details before any external issue.

The **customer contact person (Kind Attendance)** must be an actual named person. The customer name alone does not meet the requirement, nor does a department label like "Purchase Team". Enter the contact when creating a project or under **Customer quotation > Set / edit contact person**; the interface will prompt before PDF preview, Word download, or issue if absent. The backend independently enforces this; the contact is part of the approval fingerprint so edits invalidate prior approvals.

The **same approved quote data** can be exported as two files from a project's Customer quotation area:

- **View quotation PDF**: faithful fixed-layout Quote 73 page, suitable for reviewed customer delivery.
- **Download editable Word (.docx)**: editable counterpart containing the current customer, named contact, prices, taxes and terms. It is visually similar but not guaranteed to be pixel-identical after editing in Word/LibreOffice.

When an approved quote is **issued**, the app archives immutable PDF **and** DOCX snapshots accessible under **History**. Editing a downloaded Word document does not alter the database, audit history, or original issued PDF. Make corrections **inside the application**, renew any affected approvals, then issue a new revision if needed. Do not assume manually edited Word content has been revalidated by the app.

See `RELEASE_NOTES_v0.6.3.md` and `docs/YASH_CONTACT_AND_DUAL_EXPORT.md`.

## Latest quotation style is the default

The uploaded **Quote No. 73/YE (Pallet Lifting Chain)** is now the default **layout style** for all three new quotation workflows. The original customer details, quotation number, rates, tax treatment and terms are *not* copied into future quotes; they are placeholders filled from the project's approved commercial data. See `data/Quote73_One_Page_Reusable_Template.docx` and `RELEASE_NOTES_v0.6.2.md`. In **Quote formats**, you can preview, download, or replace this Word layout. The traditional multi-page equipment format remains selectable when required.

## Finding default templates and creating a custom layout

Open **Quote formats** in the sidebar. The gallery is visible to every signed-in user; sign in as **demo** (administrator) to create, edit, import or set defaults.

- Three legacy built-in formats are included, plus a preinstalled Quote 73 fixed-geometry one-page PDF format (with an editable Word fallback) that is now the default for equipment, repair/service, and general sales: **Traditional equipment technical-commercial** (cover, letter, grouped technical annexure, price schedule, terms); **Traditional service/repair** (one-page labour/repair itemization, taxes and signature); **General quotation** (modern adaptable layout). These follow the STRUCTURE of supplied examples but do not reproduce their customer names, logo, exact visual assets or pagination pixel-for-pixel.
- Preview each with **synthetic example data** (not your customers' documents).
- Click **Duplicate** to create a custom layout from a built-in option, or **+ Create custom format** at the top right.
- Admins can edit document format (traditional equipment, traditional service, modern), headings, introduction/closing text, colours, footer and section order. Each edit increments the template version and retains the previous definition in history.
- Admins can **Export JSON**, edit it outside the app, or **Import JSON layout** to create a custom format. Layout imports are intentionally not executable.
- **Set default** chooses the layout for new quotations of the matching workflow. Each quotation also has **Choose format** in the header and **Change template** under **Customer quotation**.
- Updating a selected layout changes the quotation's approval fingerprint, so pricing/commercial approvals must be renewed before issuing a fresh quote. **Issued PDFs remain frozen.**

JSON layouts are declarative data, not executable HTML, code or CSS. Word layout imports must be non-macro `.docx` files and contain reviewed supported placeholders. **Important distinction:** **Quote formats** (sidebar) is for **reusable customer-facing quotation templates**: import `.docx` with approved `{{placeholders}}`, preview PDFs, set defaults and retain versions. **Documents** (second tab within a project) is strictly for **technical drawings, RFQs and design specifications** to extract requirements, never for quotation formats. DOCX quotation template rendering requires the free LibreOffice application to be installed on the server. See `docs/QUOTE_TEMPLATES.md` and `data/Pallet_Quotation_Reusable_Template.docx`.

## How to try the revised features

1. Log in; choose **New estimate**. Select a product family independently from the quotation workflow:
   - **Equipment / fabricated product sale** — technical specifications, cost model, independent customer price schedule, annexures.
   - **Repair and service** — no mandatory drawing or BOM; service scope, labour line items and taxes.
   - **General goods/services** — generic quote lines and terms.
2. Open **Documents** and choose **Upload technical design**. Select `.pdf` or `.docx`, then press **Upload, extract & prefill draft**. The app extracts *candidates* with normalized values, source location/evidence, method and a heuristic match-strength score. A score is **not** a probability of correctness. If an empty requirement has exactly one distinct labelled value, it is autofilled as **PENDING**; conflicting fields are never auto-selected.
3. Open **Requirements**. Check the prefilled dimensions and source evidence against the original document. Correct them and have an engineer verify critical parameters. In **Documents**, operation candidates such as cutting, welding, painting, inspection, erection or commissioning offer **Set hours & rate**; this opens a proposed operation entry with **empty** hours/rate fields. Do not assume a suggested keyword proves the operation is required. Missing information and conflicts require explicit resolution.
4. For equipment, use **BOM & materials** and **Operations** to calculate the private internal estimate, with review and source pricing.
5. Open **Customer quotation**. Select a compatible quotation template and create fixed-price, unit-rate, included, excluded, at-actual and descriptive-only lines. This selling-price schedule is independent of private cost calculations.
6. Edit **Commercial terms, taxes & letterhead**. Tax rates are configuration inputs; authorize them only after the responsible staff have checked the specific transaction.
7. Preview the customer quotation. **Review & issue** requires workflow-appropriate approvals on the exact current version. An issued PDF remains byte-for-byte frozen.

**Important:** An unresolved conflict (e.g. technical span 40 m vs 25 m in a price schedule) blocks firm issue. A DOCX lacks reliable physical page numbers: it reports a logical section with original evidence instead.

## What's supported

| Area | Status |
|---|---|
| Product families + custom fields/aliases/recognition hints | Working, configuration driven |
| Independent equipment, service and general quotation workflows | Working |
| Private cost estimate and customer selling-price schedule | Working |
| Fixed/quantity-rate/included/excluded/at-actual/note pricing | Working |
| Decimal money arithmetic and configured tax components | Working; tax approval mandatory |
| PDF and DOCX text extraction | Working locally for readable text and Word table paragraphs; source-linked candidates |
| Unique labelled dimension/requirement autofill | Working; PENDING/unverified only |
| Source-keyword operation suggestions | Working; hours and rates always require human input |
| Confidence score + method + source evidence + reviewer status | Working; heuristic, never assured correctness |
| Source-versus-source conflict detection | Working for recognized normalized fields |
| Approved requirement versus quote-line description check | Working for recognized numeric fields |
| Manual engineering review and conflict resolutions | Working |
| Traditional equipment cover/letter/annexures and compact repair PDF | Working; structural match, not pixel-perfect |
| Admin-managed custom quotation templates: edit/import/export/default/version | Working for JSON-based layouts |
| DOCX quotation layout upload (admin only) | **Supported for validated placeholders; preview/defaults/versioning; requires LibreOffice for PDF** |
| Automatic conversion of arbitrary historical quotations to reviewed placeholders | **Not yet: a human must first replace variable content in Word** |
| Free SQLite single-PC or PostgreSQL via Compose | Working |
| Scanned-PDF OCR and arbitrary DWG/DXF geometry extraction | **Not yet** |
| Automatic verified fabrication BOM or structural design | **Not yet** |
| Fully self-service public multi-tenant SaaS, enterprise SSO | **Not yet** |

A PDF/Word parser cannot infer requirements that were never specified or are only present in unsupported images. Unsupported content must be handled by manual review rather than guessed.

## Sensitive source files

All user-supplied documents are stored in `runtime/files/` outside the public frontend directory. Do not commit `runtime/`, database files, customer prices or proprietary drawings to GitHub. The real customer quotations used to shape acceptance tests are **not bundled**. Test fixtures are generated and use synthetic identities.

For factory use, create a separate clean database, replace demo credentials with individual accounts, configure a persistent `APP_SECRET`, restrict access to a trusted LAN and backup files plus database. See `docs/SECURITY.md`.

## Upgrading from v0.1

The v0.3-v0.6 model changes are additive. Do **not** overwrite a live v0.1 database or `runtime/files` without taking and verifying backups. Existing product configurations are not silently rewritten; the richer matching aliases in the v0.3 JSON product packs are used on fresh demonstration databases. New quotations can be created with the v0.5 commercial workflow, while legacy cost-plus projects retain their old behavior.

For a real factory data migration, perform a rehearsal on a copy of the database and review source matching, product-version semantics, and PDF snapshots before switching over. This release is not a fully audited production migration tool.

## Tests

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
node --check frontend/assets/app.js
node tests/frontend_render_smoke.cjs
```

The Python tests cover login, roles, document extraction, source confidence, ambiguous values, conflicting spans, billable item modes, tax arithmetic, approvals, and immutable issued PDFs. UI structural checks run without external JavaScript packages. A screenshot of the template gallery was visually checked using browser fixtures. Full interactive browser navigation to a local server is blocked by this execution sandbox; manually exercise actual actions in the browser on your Mac before factory use.

## Check which version you opened

For **v0.7**, use `PORT=8008 bash scripts/start_demo.sh`; open `http://127.0.0.1:8008/api/health` and confirm **`version: "0.7.0-dev"`**. Stop the older server with `Ctrl+C` to free RAM and hard-refresh the browser with **Cmd+Shift+R** on a Mac.

**A separate download/extraction folder is recommended.** The demo launcher has a deliberate guard against overwriting non-demo records. On a fresh extraction it seeds a new demo database. For local reset only, stop the server and delete the development SQLite database `runtime/estimator.db` before starting again, but back up anything worth retaining first.

## Synthetic test inputs supplied in `data/`

- `SYNTHETIC_DESIGN_REQUIREMENTS.docx`: labelled pallet dimensions, material notes, welding/painting/inspection scope. Upload this to a new **fabricated pallet** project and inspect unverified prefilled dimensions and operation suggestions.
- `SYNTHETIC_PALLET_DEMO.pdf`: a separate textual PDF demonstration.
- `example_custom_quote_template.json`: administrator-importable custom template definition.
- `examples/` contains synthetic equipment and service quotation previews (once installed).

## Deployment

The free demo launcher uses SQLite and localhost. For a private installation, use `scripts/start_private.sh` after creating a fresh database and a persistent secret; see the original private-deployment instructions in `docs/SECURITY.md`. `compose.yaml` is included for a self-managed PostgreSQL deployment.

**Costs:** No software license or paid AI API is needed. Hosting hardware, electricity, storage, security administration, backup media and your time are not necessarily free.

## Exact Quote 73 layout (v0.6.3)

By default, short new quotations use the **same fixed A4 page frame, column boundaries, row heights, tax rows and footer positions as supplied Quote No. 73/YE**. The app generates this with the bundled free ReportLab PDF renderer. Customer details, reference number, prices, taxes, dates and terms come from the current project's fields and **never** from the old quotation. The layout preview uses synthetic details. The original customer PDF is **not** bundled.

- Open **Quote formats** to preview the one-page original-pattern layout (installed default across Equipment, Service and General Sale).
- In **Customer quotation**, fill all prices and terms; missing or unverified amounts are marked PENDING. The original page pattern has space for only two separate tax rows and a bounded number of item descriptions; the app refuses overflow instead of clipping it.
- To switch to a longer offer, choose the built-in **Classic equipment | multi-annexure** template.
- To customize text or layout, administrators may download/replace the Word fallback or upload a separate custom DOCX. **Replaced Word layouts will use Word's own rendering**, which may change the exact original grid. The fixed default cannot preserve arbitrary Word edits pixel for pixel.
- The **Documents** tab is strictly for engineering/drawing inputs, not quote templates.
