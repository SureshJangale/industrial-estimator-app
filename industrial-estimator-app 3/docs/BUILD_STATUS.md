# Release verification — IndustriQuote v0.5

- **Backend:** 28 isolated integration tests passed, covering baseline cost estimation, source provenance, DOCX upload and draft prefill, conflicting requirements, tax/pricing modes, approval fingerprints and issued-PDF immutability.
- **Frontend:** `node --check` and `node tests/frontend_render_smoke.cjs` pass. Quote format gallery and editor were also visually inspected using a mocked browser screenshot.
- **PDFs:** Synthetic traditional equipment and compact service PDFs generated, rendered, and all pages visually inspected. They preserve format structure but do not copy real customers' letterhead or logo.
- **Sample DOCX:** Purpose-built synthetic pallet document rendered and visually verified; API upload prefilled six labelled field values as pending and suggested four operations without numeric time/rate.
- **Not verified:** Integrated browser navigation on local Uvicorn was blocked by sandbox network policy, so a human must click through on Mac. Production multi-user security, factory data accuracy, scanned drawings, DWG/DXF and OCR remain future work.
- **Safety:** Extracted value is a proposal, not an authoritative design fact. A heuristic confidence score is *not* a 100% probability and never bypasses engineer review. Large-scale factory acceptance testing not done.
