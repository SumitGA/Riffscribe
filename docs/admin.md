# Admin section: setup

The admin page is `https://<host>/admin` (ADR-0015). It needs two things per environment; until
both are done, nobody can use it.

## 1. Cloudflare Access

Menu names as of Cloudflare's April 2026 dashboard.

Once per account:
1. **Zero Trust → Integrations → Identity providers → Add new identity provider → One-time
   PIN → Save** (new accounts no longer have it on).
2. **Zero Trust → Access controls → Policies → Add a policy**: name `operator`, action
   **Allow**, session 24 hours, rule **Include → Emails →** your email. **Save**. Never use an
   Include rule of "Login Methods → One-time PIN": that lets anyone with an email in.

Once per hostname (staging and production each):
1. **Zero Trust → Access controls → Applications → Create new application → Self-hosted and
   private**.
2. **Add public hostname**: subdomain `riffscribe` (staging: `riffscribe-staging`), domain
   `sumitgautam.tech`, path `admin`. Use `admin`, not `admin/*`: the wildcard form doesn't cover
   `/admin` itself; `admin` covers `/admin` and everything under it, `/admin/api/...` included.
3. Name `Riffscribe admin (prod)` / `(staging)`; access policy `operator`; identity provider
   **One-time PIN** (optionally **Apply instant authentication**). **Create**.

Check from outside: `curl -s -o /dev/null -w "%{http_code}" https://<host>/admin/api/config`
gives 302 (to `*.cloudflareaccess.com`), while `/readyz` still gives 200.

## 2. Who is an admin

1. Open `https://<host>/admin`, pass Cloudflare, and sign in with your Riffscribe account.
2. The page says "This account isn't an admin" and shows your user ID (`user_...`).
3. On the VM, add it to `/srv/riffscribe/stack/.env`:
   ```
   ADMIN_USER_IDS=user_...
   ```
   (several IDs: comma-separated), then restart the API:
   `cd /srv/riffscribe/stack && docker compose up -d api`.
4. Reload the page.

Staging and production have different Clerk instances, so your user ID differs between them.

## 3. Plans: unlimited transcriptions

In **Users**, each person has a plan badge, **Free** (the monthly limit, 10 transcriptions) or
**Unlimited** (no monthly limit), and a button to switch it:

- **Grant unlimited** asks for confirmation and an optional note for the audit log (e.g. "paid
  for October"). It works for someone who signed up but never transcribed.
- **Back to free** takes it away. Transcriptions they made this month count towards the free
  limit, so they may be blocked until next month.

Clips stay limited to 5 minutes on both plans. **Admin actions** lists every change, newest first.
The app shows "Unlimited plan" in the Library and Account tabs.

