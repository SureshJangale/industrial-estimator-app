# IndustriQuote v0.6.2 - Quote 73 fixed-layout quotation format

The latest uploaded quotation (No. 73/YE, pallet lifting chain) is the **default visual quotation pattern** for new Equipment, Service, and General Sale projects. The layout is rendered in a fixed one-page A4 PDF using the same overall page frame, five column widths, unusually tall item table, bottom tax rows, validity band, and two-column GSTIN/signature area as the supplied reference. This corrects the v0.6.1 Word draft, which had a generic top-aligned table and did not accurately match the original.

## Dynamic placeholders

The customer, quote number/date, seller, seller office and works address, attention, subject, item descriptions, HSN/SAC, quantities, unit rates, amounts, payment terms, tax components, total, GSTIN, validity, and signature title are all sourced from the current quotation. Historical customer data is not hardcoded. Admins enter separate Office and Works addresses in Customer quotation > Edit terms.

## Important limitations

- This is a precise **page/grid geometry recreation**, not a bit-for-bit copy of the original: some fonts will differ (the reference includes Times New Roman and Baskerville), and dynamic text lengths affect wrapping. The original reference PDF is not redistributed.
- The short form supports up to two tax rows; more detailed or lengthy scopes require a multi-page template. A layout overflow causes an explicit validation error, never invisible text clipping.
- Quote 73's historical price, GST, client, and quote number are **not defaults for new real quotes**. The example preview is synthetic and clearly marked as non-issuable. GST amounts require current accounting approval.
- Admin-replaced Word templates are rendered according to the newly uploaded Word file; their geometry may differ. Project design documents remain a separate upload area.
