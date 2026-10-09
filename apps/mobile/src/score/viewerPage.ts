/**
 * The page the score viewer's WebView loads, from a cache folder next to alphaTab's files
 * (prepareViewer.ts). It only draws and plays: the controls are native (ScoreView) and drive it
 * through `window.riff` (ViewerCommand); it reports back through
 * `window.ReactNativeWebView.postMessage` (ViewerMessage).
 *
 * Workers and AudioWorklets are off because they can't load from file:// (TD-24). The colours
 * match the app's dark theme (src/theme).
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

  function createApi(profile) {
    api = new alphaTab.AlphaTabApi(document.getElementById("score"), {
      core: { fontDirectory: "font/", useWorkers: false },
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
        playerMode: alphaTab.PlayerMode.EnabledSynthesizer,
        outputMode: alphaTab.PlayerOutputMode.WebAudioScriptProcessor,
        soundFont: "sonivox.sf2",
        scrollMode: alphaTab.ScrollMode.Continuous,
      },
    });
    api.error.on((error) => post({ type: "error", message: String(error?.message ?? error) }));
    api.renderFinished.on(() => post({ type: "rendered" }));
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

  window.riff = {
    load(musicXml, profile) {
      if (!api) createApi(profile);
      api.load(new TextEncoder().encode(musicXml));
    },
    setProfile(profile) {
      api.settings.display.staveProfile = PROFILES[profile];
      api.updateSettings();
      api.render();
    },
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
  function readBase64(path) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("GET", path);
      xhr.responseType = "arraybuffer";
      xhr.onload = () => resolve(toBase64(new Uint8Array(xhr.response)));
      xhr.onerror = () => reject(new Error("couldn't read " + path));
      xhr.send();
    });
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

/** What the page tells the app. */
export type ViewerMessage =
  | { type: 'ready' }
  | { type: 'rendered' }
  | { type: 'playerReady' }
  | { type: 'playing'; playing: boolean }
  | { type: 'position'; currentMs: number; endMs: number }
  | { type: 'error'; message: string }
  | { type: 'exported'; id: number; data: string }
  | { type: 'exportFailed'; id: number; message: string };

/** The JavaScript that runs `window.riff.<name>(...args)` in the page. */
export function command(name: string, ...args: unknown[]): string {
  return `window.riff.${name}(${args.map((a) => JSON.stringify(a)).join(', ')}); true;`;
}
