# ADR-0012: Production starts small, in the home lab

- Status: accepted
- Date: 2026-10-10
- Builds on: ADR-0009 (personal use, legal), ADR-0010 (staging), ADR-0011 (editor)

## Context

The app works end to end on staging (ADR-0010) and is ready for real users through Google
Play. There are no paying customers yet, so the owner wants the cheapest setup that is safe
for users' data, and to scale only once revenue justifies it. The home lab already runs
staging; it has about 2 vCPUs and 3.8 GB of RAM to spare.

Google Play requires, for a new personal developer account, a closed test with at least 12
testers opted in for 14 days before production access; a privacy policy; in-app and web
account deletion; a Data safety form; and a content rating.

## Decision

- **Production is a second, separate environment in the home lab**, built exactly like staging
  (Terraform module per environment, docker compose, Cloudflare Tunnel, nightly backups to
  R2) with nothing shared: its own VM (2 vCPU / 3 GB to start), database, R2 bucket
  (`riffscribe-prod`), tunnel, Clerk **production** instance and hostname
  `riffscribe.sumitgautam.tech`.
- **An external uptime check** emails the owner when production's `/readyz` stops answering.
- **Privacy and Play requirements before any public release:** uploaded audio is deleted once a
  job is over (done); account deletion in the app and on a web page; a privacy policy and
  terms of use at public URLs; an "I have the right to use this recording" confirmation before
  the first upload; an Acknowledgements screen for third-party licences (TD-28). A lawyer
  reviews the legal texts before the production release (ADR-0009).
- **Release path:** an EAS `production` build (an Android App Bundle, signed through Play App
  Signing), then Play's internal testing, then a closed test with 12+ testers for 14 days, then
  production.
- **Scale only with paying customers:** a bigger VM or a cloud host (CLAUDE.md's AWS path) is a
  decision for when revenue exists; TD-32 lists the triggers.

## Consequences

- Near-zero running cost: the lab's electricity, R2's free tier, free Cloudflare Tunnel.
- Real users depend on the home's power and internet, and their data lives in the lab (TD-32).
- A small VM: one transcription at a time, about twice as slow as staging.
- Staging stays the place to try changes first; production gets only tested commits.
