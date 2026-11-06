# Releasing

How a change gets from `main` to the server and the apps. Riffscribe is on Google Play and the
App Store, and **app releases always go to Android and iOS together** (TD-43): the same app
code and the same version number on both.

## Which kind of release

| What changed | How it ships | Store review |
|---|---|---|
| Server (API, worker, pipeline, website in `infra/site`) | GitHub release, then `make deploy ENV=prod TAG=vX.Y.Z` | None |
| App, JavaScript only (screens, logic, assets) | Over-the-air update to both apps: `make mobile-update MESSAGE="..."` | None |
| App, native (a native package, a config plugin, anything in `app.json`, an Expo upgrade) | New store builds for both: `make mobile-release VERSION=x.y.z`, then submit to both stores | Google and Apple |

`make mobile-check` (and CI) tells the last two apart. It fails when the code's native
fingerprint for either platform no longer matches the build in its store
(`apps/mobile/store-runtimes.txt`, TD-38). Green means JavaScript only: an over-the-air update
reaches everyone. Red means a native change: it needs new store builds.

If a release needs both the server and the app, the server goes first: the apps call the new
API as soon as they update.

## Server release

1. Merge to `main` and wait for CI (it builds the images).
2. `make deploy ENV=staging` and check it.
3. Create the GitHub release `vX.Y.Z` on that commit (notes below).
4. `make deploy ENV=prod TAG=vX.Y.Z`. Production only deploys GitHub releases.

## Over-the-air update (JavaScript only)

1. Merge to `main`; CI must be green (the fingerprint check passes).
2. From a Mac with `apps/mobile/google-services.json`:
   ```sh
   make mobile-update MESSAGE="what changed, in a few words"
   ```
   It checks the fingerprints again and publishes one update for Android and iOS to the
   `production` channel. Apps download it on launch and apply it on the next launch.
3. Check it on both phones: open the app, close it fully, open it again.
4. Add the update ID to the next GitHub release's notes.

Rolling back: `npx eas-cli update:republish` the previous update group (both platforms).

## Native release (new store builds)

1. Bump `expo.version` in `apps/mobile/app.json` in the PR with the native change (1.0.0 to
   1.1.0 for features, 1.0.1 for fixes). Build numbers go up by themselves (EAS, remote).
2. Merge; CI fails the fingerprint check on purpose until the new builds are live.
3. `make mobile-release VERSION=x.y.z`: one EAS build for Android (AAB) and one for iOS.
4. Submit both: `npx eas-cli submit --platform all --latest` from `apps/mobile`, or upload
   by hand (Play Console: production release with notes; App Store Connect: new version,
   then submit for review). Use the same release notes for both.
5. Once both are live, put the new fingerprints in `store-runtimes.txt`
   (`node scripts/store-runtimes.js --print`, with and without `google-services.json`) and
   note the build numbers there. CI goes green again.

If one store approves days before the other, publish nothing over the air until both are
live: an update built from the new code only reaches the new builds, so the platforms would
drift apart.

## GitHub release notes

Every release, server or not, has a **Store builds** table, so each tag says what was live:

```markdown
## Store builds
| Platform | Version | Status |
|---|---|---|
| Android | 1.0.0 (versionCode 7) | Live on Google Play since 2026-11-04 |
| iOS | 1.0.0 (3) | Live on the App Store since 2026-11-05 |

Over-the-air update: `<update group ID>` (published <date>), or "none since vX.Y.Z".
```

Then **App changes**, **Server** (with "no migration" or the migration), and the deploy line.
