# Validation plan

## A. Functional testing

Automated API tests run with `python -m pytest -q tests/test_end_to_end.py` and use a temporary database. Structural frontend smoke tests run via `node tests/frontend_render_smoke.cjs`.

| Scenario | Expected result |
| --- | --- |
| Login with bad credentials | 401 |
| Access a private drawing without token | 401 |
| Upload valid PDF | Extract text and unapproved candidate fields |
| Upload invalid content as `.pdf` | 422 |
| Add BOM line with incompatible `each` → `kg` conversion | 422 and no persisted invalid row |
| Attempt to forge APPROVED BOM quantity | 403 |
| Import spreadsheet BOM | Rows stay ASSUMED |
| Attempt to issue while gates pending | 409 |
| Engineering and pricing reviews complete | Commercial approver can sign current fingerprint |
| Change rate after approval | Previous approvals no longer current |
| Retrieve issued PDF after changing live price | PDF bytes/checksum unchanged |
| Create new product family config | Existing costing engine can use it without new backend code |

## B. Factory acceptance testing

Use 5–10 *approved-to-share* real historical estimates and a separate unseen pilot batch. Compare:

1. Extracted fields versus engineer-authenticated source drawings, separating labelled from ambiguous dimensions.
2. Line-by-line material quantities versus approved cutting lists.
3. Cost calculations versus an independently checked quotation worksheet using the **same inputs and policy**, not merely the historical quote total.
4. Missing data, stale rates, unit conversions, tax exclusions and revision controls.
5. Hands-on estimator minutes and total turnaround time before and after the system.
6. User comprehension of price provenance, assumption warnings, and difference between budgetary and firm output.

Do not enable firm release for new product families merely because the application can calculate a price; engineering validation and documented control procedures remain necessary.

## C. Open questions for your relative's factory

- How do their drawing, design and cutting-list files arrive? PDF only, or native DWG/DXF/STEP and Excel?
- Who signs off material quantities? Is structural mass obtained from CAD, approved cut lists, or estimators' historical rules?
- Are fabrication rates costed per hour, per kilogram or by process? Which overheads are already embedded?
- How often do supplier rates change, and what proof counts as an approved rate?
- Which quote terms and taxes are product- or customer-specific?
- How many users will review or issue quotations, and on which network?

## D. Release decision

The MVP is suitable for **supervised local trials**. Before external use on live customer transactions, close the safety gaps, confirm the organization has rights to process documents, check final quote wording, and validate numerical and engineering inputs against approved references.

## v0.3 test coverage

Run `python -m pytest -q tests/test_end_to_end.py tests/test_commercial_extraction.py` to verify source-conflict detection, confidence fields, DOCX parsing, service GST math, selling-line pricing modes, requirement-vs-price-line conflicts, stale approvals and immutable issued PDFs. The synthetic cases derive from public patterns and user-supplied document formats; no real customer names or files are committed.

**Confidence** is a heuristic match strength, not a calibrated probability. 100% mandatory-field review coverage and zero known critical contradictions are release goals; a universal 100% automatic extraction accuracy claim is neither tested nor supportable.
