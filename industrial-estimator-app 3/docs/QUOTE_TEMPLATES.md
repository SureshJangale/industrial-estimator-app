# Quotation formats and administrator-defined layouts (v0.6.1)

Open the always-visible **Quote formats** sidebar item to browse the **Quote 73-inspired one-page Word quotation (default for all three workflows)** and the three legacy standard layouts:

| Built-in default | Workflow | Output |
| --- | --- | --- |
| Classic equipment / multi-annexure | Equipment or fabricated product | Cover → letter → technical annexure → pricing and certificates → commercial terms |
| Classic service / itemized | Repair or service | Compact work description → quantity/rate/amount → taxes/total → terms and signature |
| General quotation | Other sales/services | Simplified modern price and terms |

Select **Preview sample PDF** on any card; samples are synthetic. In a quotation, choose **Choose format** at the top or **Change template** in the customer quotation tab.

## Custom format (administrator only)

1. Click **Duplicate** next to the closest layout (recommended). Alternatively click **+ Create custom format**.
2. Choose a unique code, name and compatible workflow, then edit **Document format**: `classic_equipment`, `classic_service` or `modern`.
3. Edit the document title, intro, closing text, colours, footer and visible section labels and order.
4. Save, then click **Preview sample PDF**. Use **Set default** for new quotations in that workflow.
5. **Export JSON** creates a portable definition; **Import JSON layout** can upload a reviewed JSON configuration. Original built-in layouts cannot be changed in place.

A sample file is `data/example_custom_quote_template.json`.

## JSON structure

```json
{
  "code": "my_company_eot_offer",
  "name": "Equipment quotation",
  "workflow": "equipment_supply",
  "layout": {
    "format_style": "classic_equipment",
    "title": "TECHNO-COMMERCIAL OFFER",
    "primary_color": "#17344C",
    "accent_color": "#087E75",
    "intro": "We submit our offer for {project} to {customer}.",
    "closing": "We welcome your enquiry.",
    "footer": "Quotation {quote_number}",
    "sections": [
      {"key":"technical","title":"Technical specification","enabled":true},
      {"key":"pricing","title":"Price schedule","enabled":true},
      {"key":"certifications","title":"Certificates","enabled":true},
      {"key":"terms","title":"Commercial terms","enabled":true}
    ]
  }
}
```

The allowed section keys are `technical`, `pricing`, `certifications`, `terms`; pricing and terms remain required. Classic equipment uses technical/pricing/terms as major annexures, and certifications display under the pricing section. Annexure lettering is regenerated from visible section order so A/B/C labels stay consistent. Supported text placeholders: `{customer}`, `{project}`, `{quote_number}`, `{company_name}`, `{date}`; any replacement is limited to these literal strings and HTML/JS is not executed.

**Two separate uploads:**

- **Sidebar → Quote formats → Upload quotation template (.docx)** is **administrator only**. It stores a reusable **quotation layout**, available for future quotations, not a project source document. The uploaded Word file must already use reviewed `{{field.name}}` placeholders. The application validates allowed/required fields; unsupported tokens and external links are rejected. Select the saved template from **Customer quotation → Change template**. Sample file: `data/Pallet_Quotation_Reusable_Template.docx`. Free LibreOffice on the server is required for Word-to-PDF conversion; no paid API is needed.
- **Project → Documents (second tab) → Upload design / specification** accepts `.pdf` and `.docx` engineering source material for **requirement extraction**. These documents are attached only to that project and are never inserted into the reusable template library. Scanned/image-only drawings need manual review.

**Automatic template discovery limitation:** Uploading an ordinary historical quotation does not yet automatically identify every variable and rebuild its layout as a safe reusable template. First edit that quotation in Word, replace variable text with supported tokens, and have an administrator approve it. That is deliberately different from extracting dimensions from customer design documents.

## Pallet Word placeholder example

Download the synthetic pallet layout directly from **Quote formats → Download pallet example**, or open `data/Pallet_Quotation_Reusable_Template.docx`. It has a cover letter plus technical, material, price and commercial annexures. The repeating row collections are `material_lines.*`, `price_lines.*`, `operations.*`, and `certifications.*`. The document must not be sent to a customer with PENDING REVIEW values left unresolved. All template uploads and PDF generation stay on the local backend.

## Versioning and approvals

- Editing the selected custom template increments its version and invalidates stale in-progress commercial approval fingerprints.
- Each issued PDF is frozen and unaffected by later template edits. The selected template snapshot is retained alongside the issued quotation.
- Admin actions are restricted by the API (not merely hidden in the frontend).
- Sample company details are synthetic. Configure company letterhead information, quote number, commercial terms and approved taxes under the quotation workspace.

## Visual fidelity

These outputs use the business organization of supplied historical quotations, not their precise typeface, pagination, logos, images, or stationery. Incorporating branding assets and arbitrary DOCX quotation templates will require a separate, tested graphical renderer/import pipeline.


## Quote 73 default: latest user-supplied quotation

The latest uploaded pallet lifting-chain quotation, **Quote No. 73/YE**, is the reference for the **default visual format**. On new installs and first boot after this upgrade, the app creates `quote73_equipment`, `quote73_service`, and `quote73_general`, all using `data/Quote73_One_Page_Reusable_Template.docx`. Admins can select another default anytime; restarting will not reverse their choice.

The original 15,500 INR sale and 9% + 9% GST are **only reference figures for the synthetic preview**, not preset selling prices or approved tax rates. The original recipient and quotation number never appear as fixed values in the template. Existing quotation projects keep their previous explicitly selected template, but any new project automatically picks the new workflow default.


## Quote 73: fixed-layout default (v0.6.2)

The installed `quote73_equipment`, `quote73_service` and `quote73_general` templates are the defaults. Their generated PDF preserves the layout geometry of the supplied one-page quotation: A4 frame x=72..462 pt, header divider y=162 pt, item table columns at x=101/307/350/402 pt, tax rows anchored at y=542..568 pt, and footer at y=586..663 pt. These are page coordinates; admin-custom Word layouts are not constrained to them. The original sample PDF is *not* stored in the app or Git repository.

**Admin**: Quote formats → select the default template → Preview sample PDF. For a new custom look, upload a DOCX in Quote formats. Replacing the downloaded Word fallback changes the rendering mode and can change the original pattern. **Estimator**: use the project's second-tab Documents upload solely for design drawings and engineering requirement extraction.
