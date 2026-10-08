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
  };
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
  | { type: 'error'; message: string };

/** The JavaScript that runs `window.riff.<name>(...args)` in the page. */
export function command(name: string, ...args: unknown[]): string {
  return `window.riff.${name}(${args.map((a) => JSON.stringify(a)).join(', ')}); true;`;
}
