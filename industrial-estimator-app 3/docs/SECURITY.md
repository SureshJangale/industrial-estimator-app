# Security and safe deployment checklist

## For any factory pilot

1. **Replace demo credentials.** Demo mode is only for localhost testing; start a fresh database with a unique admin password.
2. Set `APP_SECRET` to a persistent, high-entropy value; production startup refuses to run without one.
3. Restrict access: localhost by default, or a trusted LAN behind a configured TLS reverse proxy. Never publicly expose database or private document directories.
4. Require permission to process customer or third-party drawings. The user-supplied third-party pallet PDF is excluded from this repository.
5. Keep documents and DB backups encrypted, protected by OS permissions, and outside any public web root.
6. Separate estimator, engineering, procurement and commercial responsibilities; commercial approval cannot reuse the engineering reviewer account.
7. Back up database and uploads together. Restore on a separate machine before trusting the backup strategy.
8. Block automatic external quotation sending; the system only generates a downloadable signed-off PDF.
9. Verify dependency versions and patch security issues before production; run security scanning and an application penetration test before internet exposure.
10. Treat extraction results and user-entered source text as untrusted. Never execute formulas, shell commands or scripts embedded in uploaded files.

## What the current MVP does

- Uses PBKDF2-HMAC-SHA256 with random salt for passwords.
- Uses signed, eight-hour bearer tokens. Client stores them in sessionStorage.
- Protects all business APIs and document download routes by authentication.
- Keeps uploads outside frontend public paths; filenames are randomized.
- Limits PDFs to 15 MB and 60 pages, BOM import to 1 MB and 300 rows.
- Computes pricing and release permissions server-side.
- Does not send uploads to external AI/cloud vendors.
- Uses a single-origin browser app; no third-party scripts or CDN assets.
- Logs product changes, price changes, approvals and quotation issue activity.

## Not yet done — production hardening work

- User account lockout, password resets, session revocation and MFA.
- Fine-grained organization scoping / multi-tenancy.
- File malware scanning and parser sandboxing; avoid processing untrusted PDFs at scale.
- Concurrent editor conflict resolution and cross-database transaction/race handling.
- Formal database migrations (Alembic), structured logging, monitoring and restore drills.
- Rate-source attachment verification beyond a human approval assertion.
- Controlled end-to-end approvals evidence for regulated equipment design.

**Never treat this MVP as a crane-design validation or certification system.**
