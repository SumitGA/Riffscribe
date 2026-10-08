# Riffscribe app

Expo SDK 57 (React Native, TypeScript strict) with expo-router. Sign-in is Clerk's native screen,
scores render with alphaTab in a WebView, and the app talks to the API through types generated
from its OpenAPI schema.

## What's where

| Path | What |
|---|---|
| `src/app/` | Screens (expo-router): `(tabs)/` Library and Account, `new` (record, review, send), `jobs/[id]` (progress, then the score), `sign-in`. |
| `src/api/` | The typed API client. `schema.d.ts` and `openapi.json` are generated: `make api-types` after API changes. |
| `src/audio/` | Recorder with level meter, file picker, waveform bars. |
| `src/jobs/` | Starting a transcription (create, upload, submit) and job status helpers. |
| `src/score/` | The alphaTab viewer page, its native controls (`ScoreView`), and export (PDF, Guitar Pro, MusicXML, MIDI). |
| `src/push/` | Push notification permission, registration and taps. |
| `src/theme/`, `src/ui/` | The dark "studio" design: tokens, fonts and shared components. Screens use these, not raw colours. |
| `scripts/viewer-assets.js` | Copies alphaTab's script, font and soundfont into `assets/viewer/` on `npm install`. |

## Accounts and keys

Copy `.env.example` to `.env.local` (git-ignored) and fill it in. Only public values go there:
anything named `EXPO_PUBLIC_*` is bundled into the app.

| Service | What to set up | Where it goes |
|---|---|---|
| **Clerk** (sign-in) | A development instance with email, Google and (once there's a paid Apple account) Apple. **Configure → Native applications**: enable, add Android package `com.sumitga.riffscribe` with the SHA-256 of the signing key. | Publishable key → `EXPO_PUBLIC_CLERK_PUBLISHABLE_KEY`. The API only needs the issuer: `make api CLERK_ISSUER=https://<instance>.clerk.accounts.dev`. Never put the secret key (`sk_…`) anywhere in this repo. |
| **Google Cloud** (Google sign-in) | Google Auth Platform: External app, test users. Two OAuth clients: **Web** (redirect URI from Clerk's Google settings; its ID and secret go into Clerk) and **Android** (package + SHA-1). | Clerk's dashboard only. The app reads the client ID from Clerk at runtime. |
| **Expo + Firebase** (push notifications) | `npx eas init` (writes the project ID to `app.json`); a Firebase project with this Android app, its `google-services.json`, and its FCM V1 key uploaded with `npx eas credentials`. | Until this is done the app reports push as unavailable and hides the option. The worker sends with `WORKER_NOTIFIER=expo`. |
| **Apple Developer** (iOS, Sign in with Apple, iOS push) | Paid account; then set `appleSignIn: true` for the `@clerk/expo` plugin in `app.json` (TD-22). | |

The debug build is signed with React Native's shared debug key: SHA-1
`5E:8F:16:06:2E:A3:CD:2C:4A:0D:54:78:76:BA:A6:F3:8C:AB:F6:25`, SHA-256
`FA:C6:17:45:DC:09:03:78:6F:B9:ED:E6:2A:96:2B:39:9F:73:48:F0:BB:6F:89:9B:83:32:66:75:91:03:3B:9C`.
Release and Play Store keys need their own entries in Clerk and Google Cloud.

## Running it

The app needs a **development build**, not Expo Go (Clerk's native sign-in and other native
modules). Build it once, then JavaScript changes reach the phone through Metro in seconds; only
new native modules need another build.

**Android** needs Android Studio (SDK, platform 36, NDK 27.1) and **JDK 17**: Android Studio's
own JDK 25 breaks the native build (TD-23). `make mobile-android` picks JDK 17 by itself.

```sh
make up && make migrate
make api CLERK_ISSUER=https://<instance>.clerk.accounts.dev   # terminal 1
make worker                                                   # terminal 2
make mobile-android        # build and install (emulator, or a phone over USB)
```

Then start Metro for the device you use:

| Device | Backend | Metro |
|---|---|---|
| Android Emulator | as above | `make mobile` (the app uses `10.0.2.2`) |
| Phone over **USB** | as above | `make mobile-usb` (forwards ports; rerun after replugging), then `make mobile USB=1` |
| Phone on **Wi-Fi** | `make up HOST_IP=<Mac's LAN IP>`, `make api HOST_IP=… CLERK_ISSUER=…` | `make mobile HOST_IP=<Mac's LAN IP>` |
| iOS Simulator | as above | `make mobile-ios`, then `make mobile` (needs Xcode) |

For Wi-Fi without a cable, pair once: on the phone, **Developer options → Wireless debugging →
Pair device with pairing code**, then `adb pair <ip:port> <code>` and `adb connect <ip:port>`
(`adb mdns services` shows the port). Pairing ends when the phone restarts or changes network.

Local `make api` allows 1000 transcriptions a month so testing doesn't run out; production keeps
the free tier's 10.

## Checks

```sh
make mobile-check   # API types current, tsc, ESLint + Prettier, Jest, iOS + Android bundles
```

Tests mock native modules (Clerk, the WebView, audio, files, notifications); Lucide icons are
mocked in `__mocks__/` because Jest can't load their `.mjs` files.

## Pitfalls we hit

- **The phone shows old code:** Metro was started with `CI=1`, which turns file watching off.
  Start it with `make mobile` (or `npx expo start --dev-client` without `CI`); after moving or
  adding screens, restart with `--clear`.
- **"There was a problem loading the project" / `ECONNREFUSED 127.0.0.1:8081`:** the USB port
  forwarding was dropped; run `make mobile-usb` again.
- **Xiaomi phones:** turn on **Developer options → Install via USB** (needs a Mi account) or
  installs fail with `INSTALL_FAILED_USER_RESTRICTED`. Developer options open by tapping the
  MIUI/OS version seven times.
- **Gradle times out downloading `react-android`:** `repo.reactnative.dev` can be very slow; see
  TD-23 for the resumable download workaround.
- **Google sign-in in the emulator opens a browser and loops:** the emulator has no Google
  account, and Clerk's browser fallback doesn't finish first-time sign-ups (TD-22). Add a Google
  account in the emulator's settings, or test on a real phone.
- **Clerk logs `external_account_not_found` on a first Google sign-in:** normal; Clerk then
  turns it into a sign-up.
