# Quote 73 — fixed-format quotation contract (v0.6.2)

This is the **default customer quotation PDF** for equipment/fabrication, repair/service, and general supply in local demo installations. It reproduces the **measured A4 page geometry** of the user-provided Quote 73, not a generic lookalike.

## Parts that remain in the same places

- 595.2 × 841.8 pt A4 portrait page; fixed border approximately `(72,103)` to `(462,663)` pt.
- `II Shri II`, `QUOTATION`, seller header, office and works-address rows.
- Quotation number/date block at upper-right and customer/subject/attention/salutation block below header.
- `Work as follows :-`, the same five item columns (`Sr.No.`, `Particulars`, `Qty`, `Rate per Qty`, `Amt. (Rs.)`) at their original coordinates.
- Original unusually large blank area for work items, payment line at bottom of the item area, then subtotal, two tax rows, total.
- Original validity band and split GSTIN/signatory/closing section.
- Original stock letter wording is preserved, including typos, to meet the user's exact-reference requirement. An admin can choose a different template if they want copyedited prose.

## Variable values that are never copied from the historical quote

`seller.name`, `seller.address`, `seller.works_address`, `seller.gstin`, `seller.signature_title`, `buyer.name`, `buyer.address`, `buyer.attention`, `quote.number`, `quote.date`, `product.name`, `price_lines.{description,qty_unit,rate,amount,tax_code}`, `commercial.payment`, `commercial.validity`, `tax_lines.{name,rate,amount}`, `pricing.subtotal`, `pricing.total`.

All price and tax values come from the current approved quotation's commercial data; **no historical rates or taxes are assumed**. Incomplete pricing displays PENDING; draft PDFs are visibly marked non-issuable.

## Exactness and limitations

The **page frame, grid coordinates, major row heights and section order** match the source. This is not a binary/typographic clone: text uses cross-platform PDF standard fonts instead of redistributing proprietary fonts from the supplied PDF. Longer variable text wraps or shrinks within defined bounds. If it cannot fit, the app returns an explicit 422 layout-overflow error rather than clipping or producing an extra page. The fixed form holds at most two tax rows. Use the multi-page equipment template for longer scopes.

The original historical quotation PDF is **not bundled** in the application. Template changes and uploads belong in **Quote Formats**; design drawing and technical requirement uploads belong only in the project's second-tab **Documents**.
