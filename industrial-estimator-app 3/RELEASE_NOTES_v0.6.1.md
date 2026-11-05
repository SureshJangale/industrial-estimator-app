# IndustriQuote v0.6.1 - Quote 73 default style correction

## Why this update

The uploaded historical **Quote No.73/YE - Pallet Lifting Chain** is the intended default visual quotation style. Version 0.6 incorrectly treated a separate GLT-A fabricated-pallet quote as the primary example. This release supplies a **one-page, Quote-73-style Word template** as the real default for each of the three quote workflows.

## New default selection

- New equipment/fabrication quotes: `quote73_equipment`
- New repair/service quotes: `quote73_service`
- New general sales quotes: `quote73_general`
- The previous Classic Equipment (multi-annexure), Classic Service and General layouts remain available in **Quote formats** as optional alternatives.
- Existing projects retain their saved template selection. The upgrade installs the new defaults once; future changes an administrator makes through **Set default** are preserved on restart.
- The historical quotation's customer, number and price are NOT embedded in the reusable DOCX. The sample preview uses clearly marked synthetic business identities. Its example price and GST calculations are for layout testing only; real tax and prices require review.

## Template fields and behaviour

The built-in Word layout includes `{{seller.name}}`, `{{seller.address}}`, `{{seller.contact}}`, `{{seller.gstin}}`, `{{quote.number}}`, `{{quote.date}}`, `{{buyer.name}}`, `{{buyer.address}}`, `{{buyer.attention}}`, `{{product.name}}`, repeating `{{price_lines.*}}`, repeating `{{tax_lines.*}}`, `{{pricing.subtotal}}`, `{{pricing.total}}`, `{{commercial.payment}}`, `{{commercial.validity}}` and seller signature fields.

The commercial editor adds **GSTIN** and **validity days**, and preserves existing hidden terms while saving. Documents in the project second tab remain design inputs only; template Word files live solely in **Quote formats**.

## Constraints

This is a structural adaptation of the real one-page quotation, not a pixel-perfect scan reproduction. It may paginate when used with long quotations. The default one-page format does not automatically include all detailed equipment engineering annexures; users should select the multi-annexure option when those details need to be contractually included. Source extraction is still reviewable, not guaranteed 100% correct. Real customer documents remain excluded from the distributed ZIP.
