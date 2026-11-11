# ADR-0016: Billing: plans, limits and store subscriptions

- Status: accepted (plans and limits, 2026-11-07; the webhook and subscription tables,
  2026-11-07; the app's paywall, 2026-11-08; terms v2 and the privacy policy, 2026-11-11); the
  admin billing area is built in a later step
- Date: 2026-11-07

## Context

Riffscribe is live on Google Play and the App Store with one free plan (10 transcriptions a
month, clips up to 5 minutes) and a hand-granted unlimited plan (TD-42). The next step is a paid
subscription. Both stores require their own billing for digital features unlocked in an app
(Apple guideline 3.1.1, Google Play's Payments policy), so a card form or Stripe inside the app
is not an option.

Decisions taken with the operator on 2026-11-07:

- Pro unlocks more transcriptions (100 a month), longer clips (up to 15 minutes) and the
  priority queue. Song mode (step B) is not reserved for Pro.
- Prices are set later. Products are built and tested as placeholders.
- Refunds follow the stores' processes and the Australian Consumer Law, with goodwill from the
  admin section: a refund on Android, free Pro time on either platform.
- When a subscription ends, the user keeps everything they made. Only new uploads go back to
  the free limits.

## Decision

### Plans and limits (built first)

- **Three plans** (`users.plan`, migration 0009): `free` (the default), `pro` (the paid plan)
  and `unlimited` (granted in the admin section only, never sold: Pro's limits without a
  monthly cap).
- **Limits are API settings**, one set per plan (`api/plans.py`, `api/settings.py`):

  | | Free | Pro | Unlimited |
  |---|---|---|---|
  | Transcriptions a month | 10 | 100 | no limit |
  | Longest clip | 5 min | 15 min | 15 min |
  | Largest upload | 64 MiB | 192 MiB | 192 MiB |
  | Queue | normal | high priority | high priority |

  Changing a limit is a deploy, not an app update: the app reads them from `GET /me`.
- **`GET /me`** returns the plan, where it came from (`plan_source`: `default` or `admin`, later
  the stores) and its `limits`. It keeps `jobs_per_month` for app builds from before `limits`.
- **A job's clip limit is fixed when it is submitted** (`jobs.max_duration_s`). The worker gives
  it to the normalize stage, which already enforces the limit. It is not part of the job's
  config, so it stays out of the dedup cache key: a limit doesn't change the result.
- **Priority** comes from the plan when the job is queued, and the worker keeps it for every
  stage after the first.
- **Admin:** the plan picker in Users sets any of the three plans, audited as before.

### Subscriptions (next steps, each its own PR)

- **RevenueCat** between the stores and the API: one SDK in the app for StoreKit and Play
  Billing, purchase checks with the stores, and one webhook format for both. Its user ID is the
  Clerk user ID, so purchases follow the account, not the phone. The SDK is a native module, so
  it ships as new store builds for both apps with one version (TD-43).
- **Server** (built, `api/billing.py`, `docs/billing.md`): a `subscriptions` table (store,
  product, entitlement, period dates, trial, billing issue, cancelled, refunded, sandbox or
  production; migration 0010) and a `billing_events` table (every webhook, raw, deduplicated by
  event ID). The webhook (`POST /billing/revenuecat`) checks a shared secret and re-reads the
  customer from RevenueCat (`GET /v1/subscribers`) before it changes anything, so events that
  arrive late or twice can't leave a wrong state; if RevenueCat is down it answers 503 and
  RevenueCat retries. Each server counts only its own environment's purchases
  (`BILLING_ENVIRONMENT`: staging sandbox, production by default), so a test purchase can never
  unlock Pro in production. The plan then comes from an active subscription or an admin grant,
  whichever gives more (a tie is the subscription: `plan_source: store`); Pro lasts through the
  store's grace period after a failed payment and ends on a refund. `GET /me` adds the latest
  subscription (renewal date, will it renew, trial, billing issue, refunded). The app calls
  `POST /me/billing/sync` after a purchase or a restore so Pro doesn't wait for the webhook;
  the webhook skips users the API doesn't know yet. Deleting an account removes its
  subscription rows, billing events and RevenueCat customer.
- **Store review:** reviewers and TestFlight buy with test accounts on the production app.
  Production counts test purchases only for the accounts in `BILLING_SANDBOX_USER_IDS` (the
  review account), so a review purchase unlocks Pro and nobody else's test purchase does.
- **App** (built, `src/app/pro.tsx`, `src/billing/`; RevenueCat's SDK 10.16, MIT): a paywall in the app's own design (store price, period, auto-renewal wording, Terms
  and Privacy links, Restore Purchases), shown from the Account screen and when a free limit is
  reached; subscription status and a link to the store's subscription settings on the Account
  screen; account deletion warns that the store subscription must be cancelled in the store.
- **Admin billing area:** subscribers, trials, revenue, churn, refunds and billing problems;
  each user's subscription history; audited actions: grant Pro for a number of days (a
  RevenueCat promotional entitlement), refund an Android purchase, re-sync a user. Apple
  purchases can only be refunded by Apple; the admin records the request and Apple's refund
  event removes Pro.
- **Legal:** terms v2 (subscriptions, auto-renewal, cancelling, refunds, the Australian Consumer
  Law), the privacy policy (purchase history, RevenueCat as a processor), the App Store privacy
  label (Purchases) and Google Play's Data safety form (Purchase history).
  Built: `infra/site/terms.html` (version 2026-11-11, so every user accepts it again before their
  next upload) and `infra/site/privacy.html`. Prices at launch: A$4.99 a month, A$39.99 a year,
  the same in both stores. Android was released after unit tests only: Google Play's sandbox
  purchases weren't run (the iOS sandbox flow was, on staging, 2026-11-08).
- **Testing:** webhook fixtures in the API tests; sandbox purchases (Apple sandbox testers,
  Google Play license testers) against staging, covering buying, renewing, cancelling, a failing
  card, refunds, switching monthly to yearly, restoring on a new phone, a second account on one
  phone, and deleting an account with an active subscription.

## Consequences

- Pro can be granted and tested before any payment exists, which is what the store builds and
  the paywall will be tested against.
- 15-minute clips take about 3 minutes of transcription on the production VM (compute is about
  0.2 s per second of audio). Stages keep their queue messages alive with a heartbeat, so long
  stages are not retried by mistake. Memory for a 15-minute clip is to be measured on staging
  before Pro is sold.
- App builds from before this change show Pro users as "Free plan" with the right count; the
  app update that adds the paywall shows the plan's name and limits.
- The stores take 15% (Apple's Small Business Program, which needs applying for, and Google's
  rate for subscriptions) and handle sales tax. RevenueCat is free below about US$2,500 of
  monthly revenue.
- TD-45 records the monthly cap on Pro; TD-46 records limits being fixed at submission.
- TD-47 records relying on RevenueCat and keeping a copy of its data.
- TD-48 records Pro's benefits being written into the app as well as the server's settings.
