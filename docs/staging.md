# Staging runbook

Staging (ADR-0010) is one VM in the home-lab OpenStack running the backend with docker compose,
reachable from the internet at `https://api-staging.riffscribe.sumitgautam.tech` through a
Cloudflare Tunnel, with Cloudflare R2 for audio and scores and an installable Android APK built
by EAS. This page goes from nothing to a working phone, then covers deploys, backups and
restores. Terraform and deploys run from a machine on the home LAN.

Secrets never go in the repo or in chat: they live in `~/.config/openstack/clouds.yaml` on your
machine and in `/srv/riffscribe/stack/.env` on the VM. Both are outside git.

## 1. One-time setup

### Cloudflare R2

1. In the Cloudflare dashboard, open **R2** and create a bucket `riffscribe-staging`
   (storage class *Standard*: the free tier only covers Standard).
2. **R2 > Manage API tokens > Create API token**: permission *Object Read & Write*, scoped
   to that bucket only. Keep the *Access Key ID*, the *Secret Access Key* and the S3 endpoint
   (`https://<account id>.r2.cloudflarestorage.com`) for the VM's `.env`.
3. **Billing > Billable Usage > Create budget alert** at $1 and $5. R2 has no spending cap;
   the alerts email you so a runaway bug is noticed.

No CORS rule is needed: the app uploads from native code, not from a browser.

### OpenStack access from your machine

The lab's public API endpoints (`dashboard.sumitgautam.tech:<port>`) sit behind Cloudflare's
proxy, which doesn't forward OpenStack's ports, so everything uses the internal endpoints over
the LAN. `~/.config/openstack/clouds.yaml` (mode 600) holds an application credential (Horizon:
*Identity > Application Credentials > Create*, then *Download clouds.yaml*) under two entries:
`openstack` as downloaded, and `homelab-lan`, the same credential with
`auth_url: http://192.168.0.250:5000` and `interface: internal`. Terraform uses `homelab-lan`.

```sh
uv tool install python-openstackclient          # once
openstack --os-cloud homelab-lan token issue    # works only from the LAN
```

### The VM (Terraform)

The defaults in `infra/terraform/staging/variables.tf` match the lab (image `ubuntu-24.04`,
4 vCPU / 6 GB / 40 GB, floating IPs from `public1`, SSH from `192.168.0.0/24`); copy
`terraform.tfvars.example` to `terraform.tfvars` only to change one.

```sh
cd infra/terraform/staging
terraform init
terraform plan     # 13 to add: flavor, keypair, network, subnet, router, security group, VM, floating IP...
terraform apply
```

The outputs give the VM's LAN address and the SSH command. Keep `terraform.tfstate`: it's how
Terraform knows what it created (TD-30). Wait for cloud-init (2-4 minutes), then check:

```sh
ssh ubuntu@<lan ip> 'cloud-init status --wait && docker --version'
```

### Cloudflare Tunnel (public HTTPS)

1. Cloudflare dashboard > **Zero Trust > Networks > Tunnels > Create a tunnel**, type
   *Cloudflared*, name `riffscribe-staging`.
2. On the install step, copy the token: the long string after `--token` in the shown command.
   It goes in the VM's `.env` as `TUNNEL_TOKEN`. Don't run the install command; the stack
   runs `cloudflared` itself.
3. **Public hostname:** subdomain `api-staging.riffscribe`, domain `sumitgautam.tech`; service
   type **HTTP**, URL **`caddy:80`**. Cloudflare creates the DNS record itself.

The tunnel shows *Healthy* once the first deploy starts `cloudflared`.

### The VM's `.env`

```sh
scp infra/staging/.env.example ubuntu@<lan ip>:/srv/riffscribe/stack/.env
ssh ubuntu@<lan ip>
nano /srv/riffscribe/stack/.env      # fill in every value; POSTGRES_PASSWORD: openssl rand -hex 24
chmod 600 /srv/riffscribe/stack/.env
```

### Container images

CI publishes `ghcr.io/sumitga/riffscribe-api` and `-worker` after every green push to `main`;
they are public, so the VM pulls them without logging in. (New GHCR packages can start out
private: *Your profile > Packages >* the package *> Package settings > Change visibility*.)

## 2. Deploy

```sh
make deploy-staging STAGING_SSH=ubuntu@<lan ip>             # the latest green commit on main
make deploy-staging STAGING_SSH=ubuntu@<lan ip> TAG=<sha>   # a specific commit (or a rollback)
```

It checks the VM's `.env`, copies the stack files, pulls that commit's images, runs
migrations, restarts the services (waiting for health checks), installs the nightly backup
job, and finally checks `https://<STAGING_HOST>/readyz` through the tunnel.

Useful on the VM (`cd /srv/riffscribe/stack`):

```sh
docker compose ps                     # what's running, and its health
docker compose logs -f api worker     # JSON logs, each line carrying job_id where relevant
docker compose exec api python -c "import urllib.request as u; print(u.urlopen('http://localhost:8000/metrics').read().decode())" | grep queue   # queue depth
```

## 3. The app

### Google sign-in for EAS builds

EAS signs the APK with its own key, and Google and Clerk only let sign-in through for keys they
know. The debug key you use locally is already registered; the EAS key needs the same:

1. `cd apps/mobile && npx eas-cli@latest credentials -p android`, choose the `staging`
   profile, and note the keystore's **SHA-1** and **SHA-256** fingerprints. (The first
   `eas build` creates the keystore if there isn't one yet.)
2. Google Cloud Console > *APIs & Services > Credentials*: create an **Android** OAuth client
   with package `com.sumitga.riffscribe` and the **SHA-1**.
3. Clerk dashboard > *Configure > Native applications* > Android: add the **SHA-256** next to
   the debug one.
4. The Google consent screen is in *Testing* mode: add every staging tester's Google account
   under *Audience > Test users*.

### Build-time values (EAS environment `preview`)

```sh
cd apps/mobile
npx eas-cli@latest env:create --environment preview --visibility plaintext \
  --name EXPO_PUBLIC_API_URL --value https://api-staging.<your domain>
npx eas-cli@latest env:create --environment preview --visibility plaintext \
  --name EXPO_PUBLIC_CLERK_PUBLISHABLE_KEY --value <pk_test_... from apps/mobile/.env.local>
```

Then upload `google-services.json` in the dashboard: expo.dev > the project > *Environment
variables* > *Add* > name `GOOGLE_SERVICES_JSON`, type **file**, visibility **secret**,
environment **preview**. Both `EXPO_PUBLIC_*` values end up inside the app; neither is secret.

### Build and install

```sh
npx eas-cli@latest build -p android --profile staging
```

EAS prints a link and a QR code when the build finishes. Open it on the phone and install
(allow installs from the browser once). JavaScript-only changes can then skip the rebuild:

```sh
npx eas-cli@latest update --channel staging --environment preview --message "what changed"
```

Native changes (new native modules, app.json changes) need a new build. The `fingerprint`
runtime version makes sure an update only reaches builds it is compatible with.

## 4. Check it works

The end-to-end check runs the app's flow against staging. It needs real Clerk tokens for two
different test users, valid long enough for the run (session tokens last 60 seconds):

1. Clerk dashboard > *JWT templates* > *New template*, named `e2e`, lifetime 900 seconds.
2. Create two test users in the dashboard (*Users > Create user*). For each, start a session
   and get a token from Clerk's Backend API (creating sessions this way works on development
   instances, which staging uses), with your secret key in your shell only, never in a file
   in this repo:

   ```sh
   export CLERK_SECRET_KEY=sk_test_...        # from the Clerk dashboard; don't save it
   sid=$(curl -s -X POST https://api.clerk.com/v1/sessions \
     -H "Authorization: Bearer $CLERK_SECRET_KEY" -H "Content-Type: application/json" \
     -d '{"user_id": "<user id>"}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
   curl -s -X POST "https://api.clerk.com/v1/sessions/$sid/tokens/e2e" \
     -H "Authorization: Bearer $CLERK_SECRET_KEY" | python3 -c 'import json,sys; print(json.load(sys.stdin)["jwt"])'
   ```

3. Run it:

   ```sh
   make e2e-staging STAGING_URL=https://api-staging.<your domain> \
     E2E_TOKEN=<first user's jwt> E2E_OTHER_TOKEN=<second user's jwt>
   ```

The real acceptance test is the phone: sign in, record a take, get the push notification,
open the score, play your recording and the guitar sound, export a PDF.

## 5. Backups and restore

Every night at 03:17 (VM time) `backup.sh` dumps Postgres in custom format to the VM's disk
and, only if that succeeded, uploads it to `r2://riffscribe-staging/backups/<UTC time>.dump`,
then deletes backups older than 14 days (never the newest). Its log is
`/srv/riffscribe/stack/backup.log`. Run it by hand with
`/srv/riffscribe/stack/backup.sh`.

To restore (on the VM, `cd /srv/riffscribe/stack`):

```sh
r2() { docker compose run --rm -T --no-deps -v "$PWD/backup_to_r2.py:/backup_to_r2.py:ro" api python /backup_to_r2.py "$@"; }
export TAG=$(cat TAG)
r2 list                                              # pick a key, newest last
docker compose stop api worker                       # nothing writes during the restore
r2 download backups/<time>.dump > /srv/riffscribe/stack/restore.dump
docker compose exec -T postgres pg_restore -U riffscribe -d riffscribe --clean --if-exists < /srv/riffscribe/stack/restore.dump
docker compose start api worker && rm /srv/riffscribe/stack/restore.dump
```

Audio and scores live in R2, not in the database, so a restore brings back jobs, users and
score versions. The objects they point at are already there.

## 6. Replacing the VM

The lab has no block storage, so Postgres lives on the VM's disk: R2 holds the audio, scores
and nightly database dumps. To rebuild the VM:

1. If the old VM still runs, take a fresh backup first: `ssh ubuntu@<lan ip> /srv/riffscribe/stack/backup.sh`.
2. `terraform apply -replace=openstack_compute_instance_v2.vm` (the floating IP stays the same).
3. Copy `.env` back, `make deploy-staging`, then restore the latest dump (section 5).

Changes since the last dump are lost (TD-29).
