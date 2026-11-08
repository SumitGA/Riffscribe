# Billing: store subscriptions through RevenueCat

Pro is sold as an App Store and Google Play subscription (ADR-0016). RevenueCat sits between
the stores and the API: it checks purchases with Apple and Google, and tells the API when
something changes. The API keeps a copy in two tables:

- `subscriptions`: what each user owns, as RevenueCat last reported it (one row per product).
- `billing_events`: every webhook RevenueCat sent, as received.

A user's plan is Pro while a subscription is paid up or in the store's grace period after a
failed payment. An admin grant of unlimited outranks it. When a subscription ends, the user keeps
every score; only new uploads go back to the free limits.

## How an event is handled

1. RevenueCat calls `POST /billing/revenuecat` with `Authorization: Bearer <webhook secret>`.
   A wrong secret gets 401.
2. The event is stored by its ID. A repeated delivery answers `duplicate` and does nothing.
3. Events from the other environment are stored and ignored (`other_environment`): staging
   only counts the stores' test purchases, production only real ones.
4. The API reads each affected customer back from RevenueCat and replaces their
   `subscriptions` rows. The event only says whom to re-read, so events that arrive late or out
   of order can't leave a wrong state.
5. If RevenueCat can't be reached, the API answers 503 and RevenueCat delivers the event again
   later.

After a purchase or Restore Purchases, the app calls `POST /me/billing/sync`, which re-reads
the caller straight away, so Pro doesn't wait for the webhook. It is also how a user who bought
before the API knew them gets their row (the webhook skips unknown users: `unknown_user`).

Deleting an account removes the user's subscription rows, their billing events and their
RevenueCat customer. The store subscription keeps billing until the user cancels it in the
store; the app says so before deleting.

## Setup, per environment

Menu names as of RevenueCat's November 2026 dashboard.

1. **Secret API key**: RevenueCat > **Project settings > API keys > + New secret API key**,
   name `riffscribe-api-staging` (or `-prod`), API version v1. Copy the `sk_...` key.
2. **Webhook secret**: on your Mac, `openssl rand -hex 32`. Use a different one for staging and
   production.
3. **On the VM**, add to `/srv/riffscribe/stack/.env`:
   ```
   REVENUECAT_SECRET_API_KEY=sk_...
   REVENUECAT_WEBHOOK_SECRET=<the hex string>
   BILLING_ENVIRONMENT=sandbox        # production on the production VM
   ```
   then `cd /srv/riffscribe/stack && docker compose up -d api`.
4. **The webhook**: RevenueCat > **Integrations > Webhooks > + Add webhook**:
   - Name `riffscribe-staging` (or `riffscribe-prod`).
   - URL `https://riffscribe-staging.sumitgautam.tech/billing/revenuecat` (production:
     `https://riffscribe.sumitgautam.tech/billing/revenuecat`).
   - Authorization header value: `Bearer <the hex string>`.
   - Environment: **Sandbox** for staging, **Production** for production. If only one webhook
     is possible, point it at production: the API ignores the other environment's events
     anyway.
5. **Check**: **Send test event** on the webhook. The API answers `{"outcome": "test"}` and the
   event appears in `billing_events`.

Never put either secret in the repo, the app or a chat.

## Checking what happened

On the VM:

```
docker compose exec postgres psql -U riffscribe -c \
  "SELECT received_at, type, environment, outcome, error FROM billing_events ORDER BY received_at DESC LIMIT 20"
```

| Outcome | Meaning |
|---|---|
| `synced` | The user's subscriptions were re-read. |
| `test` | RevenueCat's test button. |
| `other_environment` | A sandbox event on production, or a real one on staging. Ignored. |
| `unknown_user` | No such user here (not used the app yet, or deleted). The app's sync covers it. |
| `failed` | RevenueCat couldn't be reached (`error` says why). RevenueCat retries. |

## Testing with sandbox purchases (staging)

- **iOS**: App Store Connect > **Users and Access > Sandbox > Testers**, then sign in with
  the tester on the phone under **Settings > Developer > Sandbox Apple Account**. Renewals are
  fast: a month lasts minutes (the tester's renewal rate is set in App Store Connect), and a
  subscription stops renewing after a set number of renewals.
- **Android**: Play Console > **Settings > License testing**, add the Google account on the
  phone. A month lasts 5 minutes, and the test payment methods include one that always
  declines.

Cases to try on both: buying, renewing, cancelling, a declined payment, a refund, switching
monthly to yearly, Restore Purchases on another phone, a second account on the same phone,
and deleting an account that has an active subscription.
