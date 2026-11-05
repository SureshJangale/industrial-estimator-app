# IndustriQuote v0.8.1-dev — Pallet creation workflow correction

**Developer build, not production-ready.** This patch is intentionally limited to the inconsistency between the seeded fabricated pallet and newly created fabricated-pallet projects.

## Fixed

- The built-in product family `fabricated_pallet` now **always starts with the original cost-plus estimator**: Documents → Requirements → BOM & materials → Operations → Cost & approvals.
- New Project shows a clear **Original cost-plus (same as the sample pallet)** message when that family is selected. It hides the commercial quotation workflow selector rather than presenting three choices that create different screens for the same pallet family.
- Switching product family within the form restores the existing quotation workflow selector for other product families.
- The backend enforces cost-plus for newly created `fabricated_pallet` projects, including submissions from a browser with a cached earlier interface. It records the requested and applied workflows in the project audit trail.
- Existing projects, both cost-plus and commercial, are **not converted or deleted**. Other product families and the three commercial quotation workflows remain unchanged.

## Known limitations retained (not fixed by this patch)

- Existing commercial pallet projects, such as your previous Pallet Mfg project, **remain on their original workflow**. This patch affects *new* pallet projects only.
- The original cost-plus path provides an **internal provisional PDF** and its older issuance flow. It does **not** currently support the Quote 73 PDF template, paired editable Word download or the customer-contact fields available in the separate commercial quotation workflow. The New Project dialog therefore hides those fields for cost-plus pallet creation rather than pretending to save them.
- No multi-company SaaS tenant isolation, production migration tooling, or complete interactive browser UAT is included.

## Check

1. Open the default **Fabricated pallet — sample** project and observe the **Cost & approvals** tab.
2. Create a new estimate with **Fabricated steel pallet/cage**. The dialog displays **Original cost-plus**, not the commercial workflow selector.
3. Confirm the new project has **Cost & approvals**, **BOM & materials**, and **Operations**, with no separate **Customer quotation** tab.
4. Select **Generic repair and field service** in another New Project dialog to confirm its commercial workflow dropdown remains available.

This release intentionally does not redesign extraction, BOM review, approvals, company settings or quotation exports.
