# Staging runbook

Staging (ADR-0010) is one OpenStack VM running the backend with docker compose behind
`https://api-staging.<your domain>`, Cloudflare R2 for audio and scores, and an installable
Android APK built by EAS. This page goes from nothing to a working phone, then covers deploys,
backups and restores.

Secrets never go in the repo or in chat: they live in `~/.config/openstack/clouds.yaml` and
`infra/terraform/staging/terraform.tfvars` on your machine, and in `/srv/riffscribe/stack/.env`
on the VM. All three are git-ignored.

## 1. One-time setup

### Cloudflare R2

1. In the Cloudflare dashboard, open **R2** and create a bucket `riffscribe-staging`.
2. **R2 > Manage API tokens > Create API token**: permission *Object Read & Write*, scoped
   to that bucket only. Keep the *Access Key ID*, the *Secret Access Key* and the S3 endpoint
   (`https://<account id>.r2.cloudflarestorage.com`) for the VM's `.env`.
3. Optional but recommended: a lifecycle rule on the bucket deleting `backups/` objects after
   30 days, as a safety net behind the backup job's own 14-day pruning.

No CORS rule is needed: the app uploads from native code, not from a browser.

### The VM (Terraform)

1. Put your cloud's `clouds.yaml` at `~/.config/openstack/clouds.yaml` (Horizon: *API Access >
   Download OpenStack RC File > clouds.yaml*). Note the entry name; the default is `openstack`.
2. `cp infra/terraform/staging/terraform.tfvars.example infra/terraform/staging/terraform.tfvars`
   and fill it in. The names come from `openstack image list`, `openstack flavor list` (4
   vCPU / 8 GB) and `openstack network list`. `admin_cidr` is your public IP as a `/32`
   (`curl -s https://ifconfig.me`).
3. Create everything:

   ```sh
   cd infra/terraform/staging
   terraform init
   terraform plan    # check: 1 instance, 1 volume, 1 floating IP, 1 security group + rules
   terraform apply
   ```

   The outputs give the public IP and the SSH command. Keep `terraform.tfstate`: it's how
   Terraform knows what it created (TD-30).
4. Wait for cloud-init to finish (2-4 minutes), then check:

   ```sh
   ssh ubuntu@<ip> 'cloud-init status --wait && docker --version && df -h /srv/riffscribe'
   ```

### DNS

Add an **A record** `api-staging.<your domain>` pointing to the public IP. If your DNS is on
Cloudflare, set it to **DNS only** (grey cloud), so Caddy can get its certificate directly.
Check with `dig +short api-staging.<your domain>`.

### The VM's `.env`

```sh
scp infra/staging/.env.example ubuntu@<ip>:/srv/riffscribe/stack/.env
ssh ubuntu@<ip>
nano /srv/riffscribe/stack/.env      # fill in every value; POSTGRES_PASSWORD: openssl rand -hex 24
chmod 600 /srv/riffscribe/stack/.env
```

### Container images

CI publishes `ghcr.io/sumitga/riffscribe-api` and `-worker` after every green push to `main`.
New GHCR packages start out **private**: on GitHub, open each package (your profile >
*Packages*) > *Package settings* > *Change visibility* > **Public**, once. (The alternative is
`docker login ghcr.io` on the VM with a token that only has `read:packages`.)

## 2. Deploy

```sh
make deploy-staging STAGING_SSH=ubuntu@<ip>             # the latest green commit on main
make deploy-staging STAGING_SSH=ubuntu@<ip> TAG=<sha>   # a specific commit (or a rollback)
```

It checks the VM's `.env`, copies the stack files, pulls that commit's images, runs
migrations, restarts the services (waiting for health checks), installs the nightly backup
job, and finally checks `https://<STAGING_HOST>/readyz`. The first deploy also gets the HTTPS
certificate, which takes a few seconds.

Useful on the VM (`cd /srv/riffscribe/stack`):

```sh
docker compose ps                     # what's running, and its health
docker compose logs -f api worker     # JSON logs, each line carrying job_id where relevant
docker compose exec api curl -s localhost:8000/metrics | grep queue   # queue depth
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

Every night at 03:17 (VM time) `backup.sh` dumps Postgres in custom format to the data volume
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
r2 download backups/<time>.dump > /srv/riffscribe/restore.dump
docker compose exec -T postgres pg_restore -U riffscribe -d riffscribe --clean --if-exists < /srv/riffscribe/restore.dump
docker compose start api worker && rm /srv/riffscribe/restore.dump
```

Audio and scores live in R2, not in the database, so a restore brings back jobs, users and
score versions. The objects they point at are already there.

## 6. Replacing the VM

The data volume (`prevent_destroy`) and R2 hold everything. To rebuild the VM:
`terraform apply -replace=openstack_compute_instance_v2.vm`, copy `.env` back, and deploy.
cloud-init mounts the existing volume without reformatting it. The floating IP and DNS stay
the same.
