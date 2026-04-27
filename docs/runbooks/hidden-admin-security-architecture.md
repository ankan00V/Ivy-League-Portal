# Hidden Admin Security Architecture (Vidyaverse)

## Objective
Implement a non-public admin control plane with strict single-identity ownership, TOTP MFA, and auditable privileged actions across backend and frontend.

## Scope
- Dedicated hidden admin authentication flow.
- Dedicated hidden admin dashboard for platform controls.
- Full privileged operations for jobs, opportunities, moderation, and platform governance.
- Single reserved admin identity enforced at runtime.
- TOTP required for admin login.

## Non-Goals
- Publicly advertised admin UX.
- Multi-admin tenancy.
- Weak shared credentials stored in source code.

## Identity and Access Model
- **Reserved admin email** is fixed via env: `ADMIN_BOOTSTRAP_EMAIL` (default intended for one owner).
- **Admin bootstrap password** must come from env secret: `ADMIN_BOOTSTRAP_PASSWORD`.
- **Admin TOTP seed** must come from env secret: `ADMIN_TOTP_SECRET`.
- Admin privilege is granted only when both are true:
  - `user.is_admin == true`
  - `user.email == ADMIN_BOOTSTRAP_EMAIL` (normalized lowercase)
- All admin API access depends on this strict check.

## Hidden Surface Strategy
- Admin frontend routes are intentionally unlinked from normal UI and navigation.
- Admin backend endpoints use dedicated paths and are excluded from standard API schema where possible.
- Normal user discovery paths (`/`, `/login`, `/register`, `/dashboard`) remain unchanged.

## Authentication Flow
1. Admin submits email + password + TOTP on hidden login route.
2. Backend validates:
   - reserved email match
   - password hash
   - TOTP code window
   - lockout/rate-limit state
3. On success, issue regular signed auth session/JWT with admin scopes.
4. On failure, record audit event and enforce progressive lockout.

## Bootstrap and Migration Strategy
At API startup (post-DB init):
1. Normalize reserved admin email.
2. Locate existing account for reserved email.
3. If account exists but is regular-user shaped, safely remove linked user artifacts and replace with admin account.
4. Ensure a single admin account exists for reserved email with:
   - `is_admin=true`
   - password hash from env secret
   - TOTP enabled and encrypted seed persisted
5. Demote all other `is_admin=true` users.

## Admin Audit Model
- Record admin auth events in existing auth audit stream.
- Record privileged admin actions (CRUD/moderation/governance) as structured audit events.
- Expose admin-only audit listing endpoint.

## Threat Model (STRIDE)
### Spoofing
- Threat: attacker logs in as admin with stolen password.
- Control: mandatory TOTP + lockout + strong password hashing.

### Tampering
- Threat: unauthorized modification of opportunities/content.
- Control: strict admin dependency on all privileged endpoints + action audit logs.

### Repudiation
- Threat: admin actions denied after-the-fact.
- Control: append-only audit events with actor, action, target, timestamp.

### Information Disclosure
- Threat: admin endpoints and identity leaked in UI/docs.
- Control: hidden routes, no nav links, reduced schema exposure, secret-driven credentials.

### Denial of Service
- Threat: brute-force admin endpoint.
- Control: abuse lockouts + existing rate-limiting middleware + per-action failure tracking.

### Elevation of Privilege
- Threat: non-admin user toggles into admin path.
- Control: backend gate verifies both `is_admin` and reserved identity email.

## Security Controls Checklist
- Passwords hashed (`bcrypt` via existing security module).
- TOTP seed encrypted at rest using app secret-derived key.
- No admin credentials hardcoded in source.
- CSRF protections remain enabled for cookie session mode.
- CORS/host restrictions preserved.
- Admin auth and actions both logged.

## Rollout Phases
1. Foundation: settings, model fields, crypto/totp utilities, bootstrap migration.
2. Auth: dedicated admin login endpoint, reserved-identity flow blocking in public auth paths.
3. RBAC + APIs: strict admin dependency and admin control endpoints.
4. Frontend: hidden admin login and dashboard routes (unlinked).
5. Validation: tests, cso-style security review, final review, README update.
