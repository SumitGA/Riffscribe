import type { TappedBeat, TappedNote } from './edits';

/**
 * The page the score viewer's WebView loads, from a cache folder next to alphaTab's files
 * (prepareViewer.ts). It only draws and plays: the controls are native (ScoreView) and drive it
 * through `window.riff` (ViewerCommand); it reports back through
 * `window.ReactNativeWebView.postMessage` (ViewerMessage).
 *
 * Workers and AudioWorklets are off because they can't load from file:// (TD-24). The colours
 * match the app's dark theme (src/theme).
 *
 * Sound: Sonivox (alphaTab's small General MIDI font) for everything, then MuseScore_General's
 * guitars and metronome click on top (assets/soundfont; a later font's presets win, TD-28).
 *
 * With a take (the user's recording, copied next to the page), playback uses it as alphaTab's
 * backing track instead of the synthesizer, with a sync point at the start of every bar so the
 * cursor follows the recording's real timing (sync.json from the pipeline).
 */
export const VIEWER_PAGE = `<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  html, body { margin: 0; background: #16181D; }
  #score { padding: 4px 0; }
  .at-cursor-bar { background: rgba(255, 178, 36, 0.12); }
  .at-cursor-beat { background: #FFB224; width: 3px; }
  .at-highlight * { fill: #FFB224; stroke: #FFB224; }
  .at-selection div { background: rgba(255, 178, 36, 0.2); }
</style>
</head>
<body>
<div id="score"></div>
<script src="alphaTab.min.js"></script>
<script>
  const post = (message) => window.ReactNativeWebView?.postMessage(JSON.stringify(message));
  window.onerror = (message) => post({ type: "error", message: String(message) });
  const PROFILES = {
    both: alphaTab.StaveProfile.ScoreTab,
    score: alphaTab.StaveProfile.Score,
    tab: alphaTab.StaveProfile.Tab,
  };
  let api = null;
  let lastPosition = 0;
  let current = null; // { musicXml, profile, take, source } of the score on screen
  let editing = false;

  const gcd = (a, b) => (b ? gcd(b, a % b) : a);
  const beats = (ticks) => { const g = gcd(ticks, 960); return (ticks / g) + "/" + (960 / g); };

  // A tapped note as the server's score addresses it (ADR-0011): onset in beats from the start
  // of the first (possibly pickup) bar, pitch, and tab position with string 1 = highest
  // (alphaTab counts strings from the lowest). A tied continuation is the note it started as.
  // Where a new note would go: the tapped beat's onset (and its length, as a default).
  function beatInfo(beat) {
    const barStart = api.score.masterBars
      .slice(0, beat.voice.bar.index).reduce((sum, mb) => sum + mb.calculateDuration(), 0);
    const strings = beat.voice.bar.staff.tuning.length;
    return {
      onsetBeats: beats(barStart + beat.playbackStart),
      durationBeats: beats(beat.playbackDuration),
      tab: strings > 0,
    };
  }

  function noteInfo(note) {
    let origin = note;
    while (origin.isTieDestination && origin.tieOrigin) origin = origin.tieOrigin;
    let end = note;
    while (end.isTieOrigin && end.tieDestination) end = end.tieDestination;
    const barStart = (bar) => api.score.masterBars
      .slice(0, bar.index).reduce((sum, mb) => sum + mb.calculateDuration(), 0);
    const start = barStart(origin.beat.voice.bar) + origin.beat.playbackStart;
    const stop = barStart(end.beat.voice.bar) + end.beat.playbackStart + end.beat.playbackDuration;
    const strings = origin.beat.voice.bar.staff.tuning.length;
    return {
      onsetBeats: beats(start),
      durationBeats: beats(stop - start),
      pitch: origin.realValue,
      string: origin.isStringed && strings ? strings - origin.string + 1 : null,
      fret: origin.isStringed ? origin.fret : null,
    };
  }

  function createApi(profile, source) {
    if (api) api.destroy();
    api = new alphaTab.AlphaTabApi(document.getElementById("score"), {
      core: { fontDirectory: "font/", useWorkers: false, includeNoteBounds: true },
      display: {
        layoutMode: alphaTab.LayoutMode.Page,
        scale: 0.85,
        staveProfile: PROFILES[profile],
        resources: {
          staffLineColor: "#4A505C",
          barSeparatorColor: "#4A505C",
          barNumberColor: "#9CA3AF",
          mainGlyphColor: "#E5E7EB",
          secondaryGlyphColor: "#9CA3AF",
        },
      },
      player: {
        playerMode: source === "recording"
          ? alphaTab.PlayerMode.EnabledBackingTrack
          : alphaTab.PlayerMode.EnabledSynthesizer,
        outputMode: alphaTab.PlayerOutputMode.WebAudioScriptProcessor,
        scrollMode: alphaTab.ScrollMode.Continuous,
      },
    });
    api.error.on((error) => post({ type: "error", message: String(error?.message ?? error) }));
    api.renderFinished.on(() => post({ type: "rendered" }));
    // A tap on a note fires beatMouseDown too: report the beat only if no note follows at once.
    let beatTap = null;
    api.beatMouseDown.on((beat) => {
      if (!editing) return;
      clearTimeout(beatTap);
      beatTap = setTimeout(() => post({ type: "beatTapped", beat: beatInfo(beat) }), 80);
    });
    api.noteMouseDown.on((note) => {
      if (!editing) return;
      clearTimeout(beatTap);
      post({ type: "noteTapped", note: noteInfo(note) });
    });
    api.playerReady.on(() => post({ type: "playerReady" }));
    api.playerStateChanged.on((e) =>
      post({ type: "playing", playing: e.state === alphaTab.synth.PlayerState.Playing }));
    api.playerPositionChanged.on((e) => {
      const now = Date.now();
      if (now - lastPosition < 200 && e.currentTime < e.endTime) return; // a few updates a second
      lastPosition = now;
      post({ type: "position", currentMs: e.currentTime, endMs: e.endTime });
    });
  }

  // take: null, or { file: "take.m4a", barStartsMs: [...] } with the file in this folder.
  async function show(musicXml, profile, take, source) {
    current = { musicXml, profile, take, source };
    createApi(profile, source);
    // Synchronous without workers, so the player is ready once, with both fonts.
    api.loadSoundFont(new Uint8Array(await readBytes("sonivox.sf2")), false);
    api.loadSoundFont(new Uint8Array(await readBytes("musescore-guitars.sf3")), true);
    const bytes = new TextEncoder().encode(musicXml);
    if (source !== "recording") {
      api.load(bytes);
      return;
    }
    const score = alphaTab.importer.ScoreLoader.loadScoreFromBytes(bytes, api.settings);
    score.backingTrack = new alphaTab.model.BackingTrack();
    score.backingTrack.rawAudioFile = new Uint8Array(await readBytes(take.file));
    score.masterBars.forEach((bar, i) => {
      const ms = take.barStartsMs[i];
      if (ms === undefined) return; // bars past the timings play at the last bar's pace
      const sync = new alphaTab.model.Automation();
      sync.type = alphaTab.model.AutomationType.SyncPoint;
      sync.ratioPosition = 0;
      sync.syncPointValue = new alphaTab.model.SyncPointData();
      sync.syncPointValue.barOccurence = 0;
      sync.syncPointValue.millisecondOffset = Math.max(0, ms);
      bar.addSyncPoint(sync);
    });
    api.renderScore(score);
  }

  window.riff = {
    load(musicXml, profile, take) {
      show(musicXml, profile, take, take ? "recording" : "synth")
        .catch((error) => post({ type: "error", message: String(error?.message ?? error) }));
    },
    // "recording" (the take as backing track) or "synth"; needs a take for "recording".
    setSource(source) {
      if (!current || source === current.source) return;
      show(current.musicXml, current.profile, current.take, source)
        .catch((error) => post({ type: "error", message: String(error?.message ?? error) }));
    },
    setProfile(profile) {
      if (current) current.profile = profile;
      api.settings.display.staveProfile = PROFILES[profile];
      api.updateSettings();
      api.render();
    },
    setEditing(on) { editing = on; },
    playPause() { api.playPause(); },
    stop() { api.stop(); },
    setSpeed(speed) { api.playbackSpeed = speed; },
    setMetronome(on) { api.metronomeVolume = on ? 1 : 0; },
    setLoop(on) { api.isLooping = on; },

    // Exports answer with { type: "exported", id, data } or { type: "exportFailed", id, message }.
    exportGuitarPro(id) {
      try {
        const bytes = new alphaTab.exporter.Gp7Exporter().export(api.score, api.settings);
        post({ type: "exported", id, data: toBase64(bytes) });
      } catch (error) {
        post({ type: "exportFailed", id, message: String(error?.message ?? error) });
      }
    },
    // A self-contained, black-on-white HTML page of the whole score, for printing to PDF.
    exportPrintable(id) {
      printable().then(
        (html) => post({ type: "exported", id, data: html }),
        (error) => post({ type: "exportFailed", id, message: String(error?.message ?? error) }),
      );
    },
  };

  function toBase64(bytes) {
    let binary = "";
    for (let i = 0; i < bytes.length; i += 0x8000) {
      binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    }
    return btoa(binary);
  }

  // fetch() can't read file:// URLs; XHR can (the WebView allows file access from file URLs).
  function readBytes(path) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("GET", path);
      xhr.responseType = "arraybuffer";
      xhr.onload = () => resolve(xhr.response);
      xhr.onerror = () => reject(new Error("couldn't read " + path));
      xhr.send();
    });
  }

  async function readBase64(path) {
    return toBase64(new Uint8Array(await readBytes(path)));
  }

  function printable() {
    return new Promise((resolve, reject) => {
      const host = document.createElement("div");
      host.style.cssText = "position: absolute; left: -10000px; top: 0; width: 700px;";
      document.body.appendChild(host);
      const printer = new alphaTab.AlphaTabApi(host, {
        core: { fontDirectory: "font/", useWorkers: false, enableLazyLoading: false, engine: "svg" },
        display: { layoutMode: alphaTab.LayoutMode.Page, scale: 0.9, staveProfile: api.settings.display.staveProfile },
        player: { playerMode: alphaTab.PlayerMode.Disabled },
      });
      let done = false;
      printer.error.on((error) => reject(error));
      printer.renderFinished.on(async () => {
        if (done) return;
        done = true;
        try {
          const font = await readBase64("font/Bravura.woff2");
          const css = Array.from(document.querySelectorAll("style"))
            .map((style) => style.innerHTML)
            .join(" ")
            // The music font goes inside the document: the PDF printer can't read our files.
            .replace(/src:[^;]*;/g, "src: url(data:font/woff2;base64," + font + ") format('woff2');");
          host.style.cssText = "width: 700px;";
          const html = "<!doctype html><html><head><meta charset='utf-8'><style>" + css +
            " body { margin: 0; background: #fff; } .sheet { zoom: 0.78; }</style></head><body>" +
            "<div class='sheet'>" + host.outerHTML + "</div></body></html>";
          resolve(html);
        } catch (error) {
          reject(error);
        } finally {
          printer.destroy();
          host.remove();
        }
      });
      printer.renderScore(api.score);
    });
  }
  post({ type: "ready" });
</script>
</body>
</html>
`;

export type StaveProfile = 'both' | 'score' | 'tab';

/** What playback sounds like: the user's own recording, or alphaTab's synthesized guitar. */
export type PlaybackSource = 'recording' | 'synth';

/** The user's recording for the page: a file in the viewer's folder and the bar timings. */
export type ViewerTake = { file: string; barStartsMs: number[] };

/** What the page tells the app. */
export type ViewerMessage =
  | { type: 'ready' }
  | { type: 'rendered' }
  | { type: 'playerReady' }
  | { type: 'playing'; playing: boolean }
  | { type: 'position'; currentMs: number; endMs: number }
  | { type: 'error'; message: string }
  | { type: 'noteTapped'; note: TappedNote }
  | { type: 'beatTapped'; beat: TappedBeat }
  | { type: 'exported'; id: number; data: string }
  | { type: 'exportFailed'; id: number; message: string };

/** The JavaScript that runs `window.riff.<name>(...args)` in the page. */
export function command(name: string, ...args: unknown[]): string {
  return `window.riff.${name}(${args.map((a) => JSON.stringify(a)).join(', ')}); true;`;
}
