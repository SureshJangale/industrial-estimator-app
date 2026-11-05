# IndustriQuote v0.8.2-dev — Single workflow for all new projects

**Developer build. Not production-ready.** This is a narrow creation-path change to remove the confusing choice between cost-plus estimation and separate commercial quotation workflows.

## Changed

- **All new projects** use the original **cost-plus estimation** path regardless of product family: pallets, EOT cranes, conveyors, general fabrication, repair/service and custom product configurations.
- **New estimate** no longer offers a quotation-workflow selector. It displays one read-only workflow explanation: Documents → Requirements → BOM & materials → Operations → Cost & approvals.
- The backend enforces the single workflow. Cached old forms submitting `quote_workflow=equipment_supply`, `service_repair` or `general_sale` are ignored at creation and recorded in the audit trail; they cannot change the new project's path.
- Original costing, overhead, contingency, margin and release gates are unchanged. Product-specific requirements, permissible components and operation requirements remain determined by the product family.
- Source evidence review and BOM review persistence added in v0.8 are unchanged.

## Not changed / known limitations

- **Existing projects are not converted.** Previously created projects with a commercial profile retain that profile, their old tabs and recorded quotation data. Changing them safely to cost-plus requires a separate reviewed migration; simply deleting their profiles would lose access to prior pricing records.
- The old commercial profile endpoints and quotation-format gallery remain in the code for *existing legacy projects* and compatibility; they are not offered in **New estimate**. This release is not a database schema migration.
- The original cost-plus PDF preview and issue path are unchanged. It does **not yet integrate** the Quote 73 template or customer-facing editable Word export used in the other path. No claim to the contrary is made.
- The original cost-plus release checks still require approved BOM quantities/rates even for service jobs. Crane configurations may deliberately block firm release pending validated engineering rules. These existing policy constraints were not changed.
- Admin company settings remain configurable, but the cost-plus PDF still uses its existing renderer. No other workflows, menus or quotation engines were redesigned.
- Interactive browser acceptance, migrations, security hardening, backup-and-restore, and extraction benchmarks are still needed before production.

## Automated verification

- 60 backend regression tests passing across three isolated test batches (25 + 18 + 17).
- Frontend structural render and new-project modal checks passing.
- Clean package includes no developer/demo runtime database, temporary customer files or previous issue records.
