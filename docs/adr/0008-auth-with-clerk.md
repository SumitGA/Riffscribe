# ADR-0008: Sign-in with Clerk

- Status: accepted
- Date: 2026-10-06
- Replaces: the AWS Cognito default in CLAUDE.md's tech stack

## Context

Phase 3 adds sign-in to the mobile app: email + password and Google on both platforms, and Sign
in with Apple on iOS (App Store guideline 4.8 requires it when Google is offered). CLAUDE.md
defaulted to AWS Cognito, but the MVP runs on OpenStack VMs, not AWS (ADR-0004), and Cognito has
no Expo SDK: its sign-in screens would be ours to build, or a hosted web page.

## Decision

- **Clerk** is the auth provider. The app uses `@clerk/expo` and Clerk's native sign-in screen
  (`AuthView`, TD-22); sessions are stored in the Keychain / Keystore.
- **The API stays provider-neutral.** It validates RS256 JWTs against the issuer's JWKS
  (`JWT_ISSUER`, `JWT_JWKS_URL`) and uses `sub` as the user ID (Clerk's `user_...` IDs fit the
  object-key rules). It never calls Clerk's Backend API and doesn't hold Clerk's secret key.
- Dev tokens (TD-17) stay for backend tests and `make e2e`. `make api CLERK_ISSUER=...` makes the
  local API accept the app's Clerk sessions instead.
- The app ID is `com.sumitga.riffscribe` on both platforms, and the app is named Riffscribe.

## Consequences

- Clerk's free tier covers development and early users; pricing is per monthly active user after
  that. Moving providers means a new sign-in screen in the app and user migration, but no API
  code change.
- Session tokens live about a minute; the app asks Clerk for a fresh one per request (cached by
  the SDK), so revoking a session takes effect within a minute without the API calling Clerk.
- Clerk's native screen needs a development build and iOS 17 or later (TD-22).
- Production needs a Clerk production instance with its own domain, and the native apps
  registered in the Clerk dashboard (iOS Team ID + bundle ID, Android package + signing SHA-256).
