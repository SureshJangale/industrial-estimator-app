# IndustriQuote v0.8.4 — Account and access management

Built on the user's working v0.8.3 package. No modifications to pricing formulas, BOM rules, quotation generation, templates, document review, existing company setups, or the single Cost-Plus project workflow.

## Added operations
- My Profile visible to every signed-in user: view username/role, edit display name, optional email and phone.
- Change password with the current password (12–128 characters). Revoke all existing sessions, including other devices.
- Generate six one-time offline recovery codes, displayed once, stored only as cryptographic hashes, invalidating earlier codes; password reset from sign-in without requiring an email service.
- Administrator: create users (temporary password changed at first sign-in), edit roles/contact/status, deactivate or reactivate users, reset another user's password to a random temporary password (shown once).
- Administrator actions require administrator password confirmation. Self role/status edits and self admin reset are disallowed; cannot remove last active administrator. No user deletion: preserve quotation approvals and audit history.
- Audit events for profile update, password changes/recovery, recovery code regeneration, user updates and admin password reset.
- Additive migration for existing SQLite or PostgreSQL `users` tables; no project/quotation table changes. Existing sessions remain valid until a password change, recovery, admin role/status change or explicit signout-all.

## Important recovery design
No automated password-reset email is sent: the desktop app is offline by design. Users must save the generated codes in a secure offline location, or ask an active administrator to reset their password. The first-run Windows administrator wizard displays recovery codes immediately upon account creation. Do not share the codes with support.

## Verification performed in the Linux build environment
- Backend auth/profile/recovery tests and previous costing, BOM, quotation and export regression tests.
- Verified non-destructive migration from a legacy pre-account-management SQLite user table.
- Frontend Node smoke tests and Chromium-based static visual check for new account pages/modals.
- Packaging and AppData secret/backup tests are included in the Windows build project.

## Limitations
The final Windows `.exe` still requires compilation on Windows and a clean Windows installation/upgrade test. A developer/pilot build is not a security-reviewed public SaaS; keep the embedded backend bound to localhost.
