# ADR-0015: An admin section on the web

- Status: accepted (phase A: read-only dashboard)
- Date: 2026-10-17

## Context

The closed test (12+ testers for 14 days) has started. The operator needs sign-ups, activity,
retention and failures without SSH (`make stats` needs the LAN and prints counts only), and
soon wants to block users and send targeted notifications. Both need a place where only the
operator gets in.

## Decision

- **A web page at `/admin`** (`infra/site/admin.html`), served by Caddy like the legal pages. It
  is one static file: no build step and no framework. Charts are SVG it draws itself. Every value
  goes into the page with `textContent`, because emails and job names are user input.
- **Its API under `/admin/api`** (`services/api/src/api/admin.py`), in the same API service. The
  routes are read-only in phase A and left out of the OpenAPI document the app's types come from
  (TD-21).
- **Two locks:**
  1. Cloudflare Access on `/admin*` (Zero Trust, free up to 50 users): only the operator's email
     reaches the server at all.
  2. The API accepts only Clerk users listed in `ADMIN_USER_IDS` (the VM's `.env`). Anyone else
     signed in gets 403 with their own user ID, which is how the operator finds the ID to add.
- **Sign-in with Clerk's browser SDK**, the web version of the app's sign-in. It is loaded from
  the Clerk instance's own Frontend API, pinned to an exact version. The publishable key is
  derived from `JWT_ISSUER` (it is the base64 of the instance host), so nothing new needs
  configuring.
- **Accounts come from Clerk's Backend API** (who signed in, when, how, last active); usage comes
  from our database. Without `CLERK_SECRET_KEY` (local runs) the database's users are listed.
- **Later phases:** blocking users with an audit log (B), then targeted notifications sent by
  the worker (C). Each needs its own plan, a migration and a sentence in the legal pages.

## Update 2026-10-25: plans (phase B, first part)

The admin section can now change one thing: a user's **plan**. `PUT /admin/api/users/{id}/plan`
sets `free` or `unlimited` (migration 0008: `users.plan`, `plan_changed_at`, `plan_changed_by`).
Unlimited skips the monthly limit in `POST /jobs/{id}/submit`; the job is still counted, so usage
stays visible and counts against the free limit if the plan goes back mid-month. The 5-minute
clip limit, rate limits and queue priority are the same for both plans. Every change is written
to `admin_actions` (who, whom, when, from, to, an optional note), shown on the page; deleting an
account deletes the actions about it, as the privacy policy promises. The app shows "Unlimited
plan" from `/me`. Manual grants stand in for subscriptions until billing exists (TD-42).

## Consequences

- The operator sees the closed test's progress from any browser, with no server access.
- Production load is a handful of small queries and one Clerk API call per page load.
- Retention counts transcriptions only: opening the app to read a score isn't recorded (TD-37).
- One more surface to keep safe. A bug in `/admin/api` can't reach users' data without passing
  both locks, and phase A can't change anything.
