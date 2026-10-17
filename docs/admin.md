# Admin section: setup

The admin page is `https://<host>/admin` (ADR-0015). It needs two things per environment; until
both are done, nobody can use it.

## 1. Cloudflare Access (once per hostname)

1. Cloudflare dashboard → **Zero Trust** → **Access** → **Applications** → **Add an application**
   → **Self-hosted**.
2. Name: `Riffscribe admin (prod)`. Session duration: 24 hours.
3. Public hostname: domain `riffscribe.sumitgautam.tech`, path `admin` (this covers `/admin` and
   `/admin/api/...`). For staging, a second application on `riffscribe-staging.sumitgautam.tech`.
4. Add a policy: name `operator`, action **Allow**, include **Emails**: your email address.
5. Login method: **One-time PIN** (Cloudflare emails you a code). Save.

Check: a private browser window on `https://<host>/admin` shows Cloudflare's login, not the page.

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
