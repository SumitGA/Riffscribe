/**
 * The page the score viewer's WebView loads, from a cache folder next to alphaTab's files
 * (prepareViewer.ts). The app sends it a score with `window.loadScore(musicXml)`; the page
 * reports back through `window.ReactNativeWebView.postMessage` (see ViewerMessage).
 *
 * Playback controls live in the page, not in React Native: browsers only start audio from a
 * tap inside the page. Workers and AudioWorklets are off because they can't load from file://.
 */
export const VIEWER_PAGE = `<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body { margin: 0; font-family: system-ui, sans-serif; background: #fff; color: #1f2328; }
  #bar { position: sticky; top: 0; z-index: 10; display: flex; gap: 8px; align-items: center;
         padding: 8px 12px; background: #f6f8fa; border-bottom: 1px solid #d0d7de; }
  button, select { font-size: 16px; padding: 8px 14px; border-radius: 8px; }
  button { border: 0; background: #1f6feb; color: #fff; font-weight: 600; }
  button.secondary { background: #fff; color: #1f6feb; border: 1px solid #1f6feb; }
  button:disabled { opacity: 0.4; }
  select { border: 1px solid #d0d7de; background: #fff; }
  #status { margin-left: auto; font-size: 13px; color: #59636e; }
  #score { padding: 4px; }
  .at-cursor-bar { background: rgba(31, 111, 235, 0.08); }
  .at-cursor-beat { background: #1f6feb; width: 3px; }
  .at-highlight * { fill: #1f6feb; stroke: #1f6feb; }
</style>
</head>
<body>
<div id="bar">
  <button id="play" disabled>Play</button>
  <button id="stop" class="secondary" disabled>Stop</button>
  <select id="speed" aria-label="Speed">
    <option value="0.5">50%</option><option value="0.75">75%</option>
    <option value="1" selected>100%</option>
  </select>
  <span id="status">Loading…</span>
</div>
<div id="score"></div>
<script src="alphaTab.min.js"></script>
<script>
  const $ = (id) => document.getElementById(id);
  const post = (message) => window.ReactNativeWebView?.postMessage(JSON.stringify(message));
  const setStatus = (text) => { $("status").textContent = text; };
  window.onerror = (message) => post({ type: "error", message: String(message) });
  let api = null;

  function createApi() {
    api = new alphaTab.AlphaTabApi($("score"), {
      core: { fontDirectory: "font/", useWorkers: false },
      display: { layoutMode: alphaTab.LayoutMode.Page, scale: 0.8 },
      player: {
        playerMode: alphaTab.PlayerMode.EnabledSynthesizer,
        outputMode: alphaTab.PlayerOutputMode.WebAudioScriptProcessor,
        soundFont: "sonivox.sf2",
        scrollMode: alphaTab.ScrollMode.Continuous,
      },
    });
    api.error.on((error) => post({ type: "error", message: String(error?.message ?? error) }));
    api.renderStarted.on(() => setStatus("Drawing…"));
    api.renderFinished.on(() => { setStatus(""); post({ type: "rendered" }); });
    api.soundFontLoad.on((e) => setStatus("Sounds " + Math.round((100 * e.loaded) / e.total) + "%"));
    api.playerReady.on(() => { $("play").disabled = false; $("stop").disabled = false; setStatus(""); });
    api.playerStateChanged.on((e) => {
      $("play").textContent = e.state === alphaTab.synth.PlayerState.Playing ? "Pause" : "Play";
    });
    $("play").addEventListener("click", () => api.playPause());
    $("stop").addEventListener("click", () => api.stop());
    $("speed").addEventListener("change", (e) => { api.playbackSpeed = Number(e.target.value); });
  }

  window.loadScore = (musicXml) => {
    if (!api) createApi();
    api.load(new TextEncoder().encode(musicXml));
  };
  post({ type: "ready" });
</script>
</body>
</html>
`;

/** What the page tells the app. */
export type ViewerMessage =
  { type: 'ready' } | { type: 'rendered' } | { type: 'error'; message: string };
