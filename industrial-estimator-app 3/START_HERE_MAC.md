# IndustriQuote v0.8.3-dev — Mac installation

**Developer build only.** v0.8.3 restores standard quotation features to the one original cost-plus workflow; it does not bring back multiple project workflows.

## Install in a new folder (do not overwrite older data)

Stop the old terminal server with Ctrl+C. Put `IndustriQuote_v0.8.3_CostPlus_With_Quotations.zip` in Downloads, then:

```bash
cd ~/Downloads
unzip IndustriQuote_v0.8.3_CostPlus_With_Quotations.zip -d IndustriQuote-v083
cd IndustriQuote-v083/industrial-estimator-app
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
unset DATABASE_URL PRIVATE_DIR
PORT=8012 bash scripts/start_demo.sh
```

Open <http://127.0.0.1:8012>. Log in with `demo` / `demo-pass-123` **for private localhost testing only**. Do not expose demo credentials to the internet.

If port 8012 is occupied, select another port. Check `http://127.0.0.1:8012/api/health` to confirm `0.8.3-dev`. Each extracted folder has its own SQLite database under `runtime/estimator.db`.

## What to test

1. Open built-in **Fabricated pallet — sample**, then create a **new pallet** and an **EOT crane** project. All display *Documents*, *Requirements*, *BOM & materials*, *Operations*, *Cost & approvals*, *Quotation*, and *History*. There is **no workflow selection**.
2. Open **Cost & approvals**. Confirm the original *Edit pricing rules* and cost breakdown still exist.
3. Open **Quotation** in each project. Enter a real named **customer contact person**, optional customer address, scope/payment/delivery, tax components and tax review; select a format and preview **PDF** / download editable **Word**.
4. Confirm the quotation's selling price comes from **Cost & approvals**, with a configurable quantity unit (e.g. Set/Pair); it is not a separate manually entered price line.
5. Confirm drafts remain *not for issue* until technical verification, BOM/rates approvals, contact, tax and commercial approvals are complete. **History** retains issued PDF + Word files after subsequent draft changes.
6. Open **Company setup** as admin; verify company information can be configured. Yash Engineering is the starter company, not a hardcoded product restriction.

## Preserve previous work

Unzipping into a new directory does **not** carry old projects forward; use the older installation to access its data. Do **not** delete old `runtime/estimator.db` or private uploaded/issued files. To upgrade an existing installation, back up the database **and** private-file directory first; migration and restore require separate validation. Previously created projects using retired customer-price-line models are intentionally left as historical projects, without automatic conversion or data loss.

## Production disclaimer

This version is not production-ready. Real-world extraction validation, target-browser user acceptance, deployment security, and backup/migration tests remain outstanding. See `RELEASE_NOTES_v0.8.3.md`.
