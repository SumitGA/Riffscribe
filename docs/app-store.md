# App Store: listing and App Store Connect answers

What we enter in App Store Connect for Riffscribe (`com.sumitga.riffscribe`, Apple team
73B6SX3Z9M), kept here so every answer matches what the app does. The Google Play
equivalents are in `play-store.md`; update both when the app's data handling changes.

- Developer: Sumit Gautam (individual) · contact `sumitga.playstore@gmail.com`
- Support URL and marketing URL: https://riffscribe.sumitgautam.tech/
- Privacy policy: https://riffscribe.sumitgautam.tech/privacy
- Builds: `eas build --platform ios --profile production`, then `eas submit --platform ios --latest`

## App information

- **Name** (30): `Riffscribe`
- **Subtitle** (30): `Guitar tabs from your playing`
- **Category**: primary **Music**, secondary **Education**
- **Content rights**: doesn't contain, show or access third-party content (users upload their
  own recordings; transcriptions are private to them, ADR-0009)
- **Age rating**: answer **None / No** to every question (no violence, sexual content,
  profanity, gambling, medical, unrestricted web access, user-to-user contact or sharing).
  Expected: **4+**. Our terms still say 13 and over; that is a privacy-policy limit, not a
  content rating.

## Version page

**Promotional text** (170, can change without a review):
> Play a riff, get the tab. Record or upload solo guitar or piano and Riffscribe writes out the
> notes, chords and tab, ready to edit, play back and export.

**Keywords** (100, comma-separated; the name and category are indexed already, so they aren't
repeated):
`guitar,tabs,chords,sheet music,transcribe,transcription,piano,notes,midi,guitar pro,musicxml,riff`

**Description** (4000):

> Turn your guitar or piano playing into tabs, chords and sheet music.
>
> Record yourself playing solo guitar or piano, or upload a recording, and Riffscribe
> transcribes it into guitar tab and standard notation you can read, play along with and fix.
>
> WHAT YOU GET
> • Guitar tab with the strings and frets a guitarist would use, plus standard notation
> • Chord names above the music, and strummed chords kept together
> • Playback in sync with your own recording, or with a guitar sound
> • An editor to fix any note: change the string, fret, pitch or length, add or remove notes,
>   with versions you can go back to
> • Export to PDF, Guitar Pro, MusicXML and MIDI
> • A notification when your score is ready
>
> PRIVATE BY DESIGN
> • Your transcriptions are yours alone. Nothing is published or shared.
> • Your recording is deleted from our servers as soon as it has been transcribed.
> • Delete your account and everything in it at any time, right in the app.
>
> GOOD TO KNOW
> • Works best with one instrument playing: solo guitar or solo piano, up to 5 minutes.
> • Transcription is automatic and can make mistakes; the editor is there to fix them.
> • Free, with a monthly number of transcriptions.
>
> Riffscribe is for your own practice and study. Please only upload recordings you made or
> have the right to use.

**Screenshots**: App Store Connect offered one iPhone slot, "6.1" or 6.3" displays", which
takes **1206 × 2622** (or 1179 × 2556), portrait, as **JPEG or PNG without an alpha channel**
(simulator PNGs have one: convert with `sips -s format jpeg`). 3 to 10: a score with tab,
playback, the note editor, recording a take, the Library, Account. Taken from a production
release build in the simulator (`xcrun simctl status_bar booted override --time 9:41`), signed
in as the reviewer account, with GuitarSet clips as demo audio (CC BY 4.0, credited in the app's
Acknowledgements). iPad screenshots aren't needed (`supportsTablet` is false).

**Copyright**: `2026 Sumit Gautam`

## App Review information

- **Sign-in required**: yes. The reviewer account is the same one Google Play's reviewers use
  (`play-store.md`, App access): an email + password user in Clerk's **production** instance.
  Check it signs in without an emailed code before every submission.
- **Notes**:
  > Sign in with email and the password above (no code is needed). Tap the microphone tab to
  > record a few seconds of guitar or piano, or tap the folder icon to upload an audio file,
  > then tap Transcribe. The score is usually ready within a minute or two; open it to see the
  > tab, play it back, tap the pencil and then a note to edit it, or use the share icon to
  > export. Account deletion: Account tab > Delete account. Sign in with Apple is offered on
  > the sign-in screen.
- Contact: Sumit Gautam, `sumitga.playstore@gmail.com`

## App Privacy (nutrition label)

**Tracking**: No. We don't link data with other companies' data for advertising, and there's
no advertising ID or third-party analytics.

Data types collected, all **linked to the user** (they belong to the account), **not used
for tracking**, purpose **App Functionality** only:

| Apple category | Data type | What it is |
|---|---|---|
| Contact Info | Name | From sign-in (Google, Apple), shown in Account |
| Contact Info | Email Address | The sign-in email (or Apple relay address) |
| User Content | Audio Data | The recording the user uploads, deleted after transcription |
| User Content | Other User Content | Transcriptions, edits and their versions |
| Identifiers | User ID | The account ID (Clerk) that scopes every record |
| Usage Data | Product Interaction | Transcriptions this month, for the free limit |
| Diagnostics | Other Diagnostic Data | Server error logs tied to a transcription |

Not collected: location, contacts, photos or videos, browsing or search history, health,
financial info, purchases (none yet; update with subscriptions), sensitive info, device ID
(the push token isn't a device identifier in Apple's definition).

## Export compliance

Uses only standard HTTPS: `ITSAppUsesNonExemptEncryption` is false in the build
(`ios.config.usesNonExemptEncryption` in `app.json`), so App Store Connect doesn't ask.

## Known gap

Deleting an account deletes the Clerk user but doesn't call Apple's token-revocation API
(TD-41). Apple's account-deletion guidance says apps with Sign in with Apple *should* revoke;
the in-app deletion it *requires* is in place.
