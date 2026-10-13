# Google Play: listing and Play Console answers

What we enter in Play Console for Riffscribe (com.sumitga.riffscribe), kept here so every
answer matches what the app actually does. Update this file when the app's data handling
changes, then update Play Console to match.

- Developer: Sumit Gautam · contact `sumitga.playstore@gmail.com`
- Website: https://riffscribe.sumitgautam.tech/
- Privacy policy: https://riffscribe.sumitgautam.tech/privacy
- Account deletion: https://riffscribe.sumitgautam.tech/delete-account
- Graphics: `apps/mobile/assets/store/` (icon 512×512, feature graphic 1024×500), rendered by
  `apps/mobile/assets/brand/render.sh`

## Store listing (Grow users > Store presence > Main store listing)

**App name** (30): `Riffscribe`

**Short description** (80):
> Turn your guitar or piano playing into tab and sheet music you can edit.

**Full description** (4000):

> Play it, and Riffscribe writes it down.
>
> Record yourself playing solo guitar or piano, or upload a recording, and Riffscribe turns it
> into sheet music and guitar tab you can read, play along with and fix.
>
> WHAT YOU GET
> • Guitar tab with the strings and frets a guitarist would use, plus standard notation
> • Chord names above the music, and strummed chords kept together
> • Playback in sync with your own recording, or with a guitar sound
> • An editor to fix any note: change the string, fret, pitch or length, add or remove notes,
>   with versions you can go back to
> • Export to PDF, MusicXML, MIDI and Guitar Pro
> • A notification when your score is ready
>
> PRIVATE BY DESIGN
> • Your transcriptions are yours alone. Nothing is published or shared.
> • Your recording is deleted from our servers as soon as it has been transcribed.
> • Delete your account and everything in it at any time, right in the app.
>
> GOOD TO KNOW
> • Works best with one instrument playing: solo guitar or solo piano.
> • Transcription is automatic and can make mistakes; the editor is there to fix them.
> • Free, with a monthly number of transcriptions.
>
> Riffscribe is for your own practice and study. Please only upload recordings you made or
> have the right to use.

**App icon**: `apps/mobile/assets/store/play-icon-512.png`
**Feature graphic**: `apps/mobile/assets/store/feature-graphic.png`
**Phone screenshots** (2 to 8, portrait): taken on a phone with the production app: the
Library, a score with tab, recording a take, the note editor, export.

## Store settings (Grow users > Store presence > Store settings)

- App category: **Music & Audio**
- Tags: Music, Education, Productivity (pick the closest offered)
- Email: `sumitga.playstore@gmail.com` · Website: https://riffscribe.sumitgautam.tech/

## App content (Policy and programs > App content)

**Privacy policy**: https://riffscribe.sumitgautam.tech/privacy

**App access**: *All or some functionality is restricted* → add instructions:
- Name: `Reviewer account` · Username: the demo account's email · Password: its password
- Instructions: "Open the app, choose sign in with email, enter the email and password. Record
  a few seconds of guitar or piano, or upload an audio file, then tap Transcribe."
- The demo account is an ordinary email + password user created in Clerk's **production**
  dashboard (Users > Create user). It must sign in without an emailed code: test it in a
  private browser window or a fresh device before submitting.

**Ads**: No, the app doesn't contain ads.

**Content rating** (IARC questionnaire): category **Utility, Productivity, Communication, or
Other**. No violence, sexual content, profanity, drugs, gambling. Users can't interact with or
see each other; no location sharing; no purchases yet (update when subscriptions arrive).
Expected rating: Everyone / PEGI 3.

**Target audience**: 13 and over (13–15, 16–17, 18+). Not for children under 13 (privacy
policy). Not designed for families.

**News app**: No. **Government app**: No. **Financial features**: None. **Health**: None.

**Data safety**:

| Question | Answer |
|---|---|
| Collects or shares required user data types? | Yes |
| Data encrypted in transit? | Yes (HTTPS everywhere) |
| Users can request data deletion? | Yes: in the app, and https://riffscribe.sumitgautam.tech/delete-account |

Data types (all **collected, not shared**; the processors we use, Clerk, Cloudflare,
Google/Expo push, count as service providers, which Play doesn't treat as sharing):

| Data type | Collected | Required? | Purpose | Ephemeral? |
|---|---|---|---|---|
| Personal info: Name | Yes (from sign-in) | Required | Account management | No |
| Personal info: Email address | Yes | Required | Account management | No |
| Audio: Voice or sound recordings | Yes (the recording you upload) | Required | App functionality | No (deleted after transcription, but stored until then) |
| App activity: Other user-generated content | Yes (transcriptions, edits) | Required | App functionality | No |
| App activity: Other actions | Yes (transcriptions this month, for the free limit) | Required | App functionality | No |
| App info and performance: Diagnostics | Yes (server error logs tied to a transcription) | Required | App functionality | No |
| Device or other IDs | Yes (notification token) | Optional (only if notifications are allowed) | App functionality | No |

Not collected: location, contacts, photos, files outside the recording, health, financial info,
messages, web browsing, advertising ID.

**Account deletion URL**: https://riffscribe.sumitgautam.tech/delete-account

## After the internal test release: Play App Signing

Play re-signs the app with its own key. Its SHA-1 and SHA-256 (Test and release > Setup >
App signing > App signing key certificate) must be added so Google sign-in works in the
Play-installed app: the SHA-256 in Clerk production (Native applications > Android), the
SHA-1 in a Google Cloud Android OAuth client for `com.sumitga.riffscribe`.
