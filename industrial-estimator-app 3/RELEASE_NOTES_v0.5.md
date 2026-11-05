# IndustriQuote v0.5 — Quote format gallery, traditional PDFs, design prefill

## Delivered

- Explicit **Quote formats** navigation for all signed-in users, with a gallery of three ready-to-use defaults. Only administrators may create, import, duplicate, edit, export or set a default.
- Equipment quotation output resembling the *structure* of the real historical multi-annexure offers: cover page, offer letter, technical specification, line-item commercial prices with certification list, commercial terms and signature. Annexure letters are generated consistently.
- Compact service/repair quotation output with work descriptions, qty/rate/amount, configured tax components and grand total.
- A template selector in the quotation header and selling-price workspace. Controlled JSON-based custom layouts can choose traditional or modern styles and specify text/section headings/colours. No template executes uploaded code.
- PDF and DOCX design file upload in the **Documents** tab. Labelled unambiguous fields are prefilled as **PENDING** (never approved). Evidence/source/match strength are preserved. Conflicting values remain unresolved and block firm issue.
- Operation keywords extracted into **suggestions only**. Staff must separately enter/verify labour time, rates and necessity of the operation.
- Included a purpose-built synthetic pallet DOCX for testing upload and prefill, plus sample quotation PDFs using fictional companies/customers.

## Verified locally

- 28 automated backend integration tests including PDF formats, DOCX prefill, ambiguity detection, tax arithmetic, permissions and issued-PDF immutability.
- JavaScript syntax check and frontend structural screen checks.
- Synthetic pallet DOCX upload through the application API: 1100 mm length, 550 mm width, 750 mm height were proposed as PENDING. Cutting/welding/painting/inspection proposed as unpriced operations.
- PDF rendering and visual QA of all pages of the multi-annexure equipment output and the one-page service output. Sample data only.
- Visual review of the template gallery using a mocked browser fixture. Full integrated local-browser navigation remained blocked by sandbox networking, and needs manual Mac QA.

## Remaining limitations

- This is a supervised local MVP, not production-certified engineering, CAD parsing or tax software.
- DOCX text and paragraphs in tables are parsed locally, but embedded drawings, raster photos, scanned PDF/image-only text and complex CAD geometry are **not** interpreted or OCR processed.
- Extraction scores are heuristic match strengths, not calibrated 100%-correctness probabilities. Human engineering verification is mandatory before firm issue.
- The built-in PDF layouts preserve structural business sections, but are **not pixel-perfect reproductions** of supplied letterhead/logo/product imagery. Administrators can customize headings/colours, but Word DOCX quotation layout upload and full graphical designer are not implemented.
- No quotation data or original proprietary sample quotes are included in the release. Samples use synthetic identities and values.
- Never expose demo accounts on a public server; production authentication, backup drills and a factory user acceptance pilot are still required.
