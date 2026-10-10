import { Pause, Play, Repeat, SkipBack, Timer } from 'lucide-react-native';
import { type Ref, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, View } from 'react-native';
import { Directory, File } from 'expo-file-system';
import WebView, { type WebViewMessageEvent } from 'react-native-webview';

import { formatDuration } from '@/audio/clip';
import { colors, fonts, radius, space } from '@/theme';
import { IconButton, ProgressBar, Segmented, Text } from '@/ui';

import type { Edit, TappedBeat, TappedNote } from './edits';
import { prepareViewer, type ViewerFiles } from './prepareViewer';
import {
  command,
  type PlaybackSource,
  type StaveProfile,
  type ViewerMessage,
  type ViewerTake,
} from './viewerPage';

const PROFILES: { value: StaveProfile; label: string }[] = [
  { value: 'score', label: 'Notation' },
  { value: 'tab', label: 'Tab' },
  { value: 'both', label: 'Both' },
];
const SOURCES: { value: PlaybackSource; label: string }[] = [
  { value: 'recording', label: 'Your recording' },
  { value: 'synth', label: 'Guitar sound' },
];
const SPEEDS = [1, 0.75, 0.5];

/** The user's recording on this phone, and when each bar starts in it (sync.json). */
export type Take = { uri: string; barStartsMs: number[] };

/**
 * Sheet music and tab rendered by alphaTab from a MusicXML document, with native playback
 * controls. alphaTab is a web library, so it runs in a WebView on files bundled with the app;
 * nothing loads from the network (TD-24).
 */
/** What a screen can ask of a ScoreView beyond showing the score. */
export type ScoreHandle = {
  /** The score as a Guitar Pro 7 file, base64-encoded. */
  guitarPro: () => Promise<string>;
  /** A self-contained black-on-white HTML page of the whole score, to print to PDF. */
  printable: () => Promise<string>;
  /** Removes the highlight from the tapped note (its sheet closed). */
  clearSelection: () => void;
};

export function ScoreView({
  musicXml,
  hasTab,
  take = null,
  editing = false,
  onNoteTap,
  onBeatTap,
  onTapMissed,
  marks,
  ref,
}: {
  musicXml: string;
  hasTab: boolean;
  /** Plays this recording in step with the score instead of the synthesized sound. */
  take?: Take | null;
  /** Edit mode: tapping a note reports it through `onNoteTap` (ADR-0011). */
  editing?: boolean;
  onNoteTap?: (note: TappedNote) => void;
  onBeatTap?: (beat: TappedBeat) => void;
  /** A tap in edit mode that hit neither a note nor a beat. */
  onTapMissed?: () => void;
  /** Pending edits, marked on the score until saved or cancelled. */
  marks?: Edit[];
  ref?: Ref<ScoreHandle>;
}) {
  const webView = useRef<WebView>(null);
  // Exports in flight, by id: the page answers each with an `exported` or `exportFailed` message.
  const requests = useRef(
    new Map<number, { resolve: (data: string) => void; reject: (e: Error) => void }>(),
  );
  const nextId = useRef(1);
  const [files, setFiles] = useState<ViewerFiles | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [profile, setProfile] = useState<StaveProfile>(hasTab ? 'both' : 'score');
  const [playerReady, setPlayerReady] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [position, setPosition] = useState({ currentMs: 0, endMs: 0 });
  const [speed, setSpeed] = useState(1);
  const [metronome, setMetronome] = useState(false);
  const [loop, setLoop] = useState(false);
  const [source, setSource] = useState<PlaybackSource>(take ? 'recording' : 'synth');
  const [pageTake, setPageTake] = useState<ViewerTake | null>(null);

  const run = (name: string, ...args: unknown[]) =>
    webView.current?.injectJavaScript(command(name, ...args));

  useImperativeHandle(ref, () => {
    const ask = (name: string) =>
      new Promise<string>((resolve, reject) => {
        const id = nextId.current++;
        requests.current.set(id, { resolve, reject });
        webView.current?.injectJavaScript(command(name, id));
      });
    return {
      guitarPro: () => ask('exportGuitarPro'),
      printable: () => ask('exportPrintable'),
      clearSelection: () => webView.current?.injectJavaScript(command('clearSelection')),
    };
  }, []);

  // Lay out the viewer's files; a take is copied next to the page, the only folder the WebView
  // may read. The take is fixed for the life of the view (the screen waits for it).
  useEffect(() => {
    const prepare = async () => {
      const prepared = await prepareViewer();
      if (take) {
        try {
          const file = await copyTake(take.uri, prepared.folder);
          setPageTake({ file, barStartsMs: take.barStartsMs });
        } catch (e) {
          console.warn("couldn't use the recording; playing the guitar sound", e);
          setSource('synth');
        }
      }
      setFiles(prepared);
    };
    prepare().catch((e: unknown) => setError(String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Send the score once the page is up, and again if it changes.
  useEffect(() => {
    if (ready) {
      webView.current?.injectJavaScript(command('load', musicXml, profile, pageTake));
    }
    // The profile is applied separately (changeProfile); reloading the score isn't needed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, musicXml]);

  const onMessage = (event: WebViewMessageEvent) => {
    const message = JSON.parse(event.nativeEvent.data) as ViewerMessage;
    switch (message.type) {
      case 'ready':
        setReady(true);
        break;
      case 'playerReady':
        setPlayerReady(true);
        break;
      case 'playing':
        setPlaying(message.playing);
        break;
      case 'position':
        setPosition({ currentMs: message.currentMs, endMs: message.endMs });
        break;
      case 'error':
        setError(message.message);
        break;
      case 'noteTapped':
        onNoteTap?.(message.note);
        break;
      case 'beatTapped':
        onBeatTap?.(message.beat);
        break;
      case 'tapMissed':
        onTapMissed?.();
        break;
      case 'exported':
      case 'exportFailed': {
        const request = requests.current.get(message.id);
        requests.current.delete(message.id);
        if (message.type === 'exported') {
          request?.resolve(message.data);
        } else {
          request?.reject(new Error(message.message));
        }
        break;
      }
    }
  };

  useEffect(() => {
    if (ready) {
      webView.current?.injectJavaScript(command('setEditing', editing));
    }
  }, [ready, editing, musicXml]);

  useEffect(() => {
    if (ready && editing) {
      webView.current?.injectJavaScript(command('setMarks', marks ?? []));
    }
  }, [ready, editing, marks]);

  const changeProfile = (value: StaveProfile) => {
    setProfile(value);
    run('setProfile', value);
  };
  const changeSource = (value: PlaybackSource) => {
    // The page starts a fresh player, so playback settings start over too.
    setSource(value);
    setPlayerReady(false);
    setPlaying(false);
    setPosition({ currentMs: 0, endMs: 0 });
    setSpeed(1);
    setMetronome(false);
    setLoop(false);
    run('setSource', value);
  };
  const nextSpeed = () => {
    const next = SPEEDS[(SPEEDS.indexOf(speed) + 1) % SPEEDS.length] ?? 1;
    setSpeed(next);
    run('setSpeed', next);
  };

  if (error) {
    return <Text style={styles.error}>The score couldn&apos;t be shown: {error}</Text>;
  }
  return (
    <View style={styles.container}>
      {hasTab && (
        <View style={styles.profiles}>
          <Segmented
            label="Show"
            options={PROFILES}
            value={profile}
            onChange={changeProfile}
            emphasis="subtle"
          />
        </View>
      )}
      {pageTake && (
        <View style={styles.profiles}>
          <Segmented
            label="Sound"
            options={SOURCES}
            value={source}
            onChange={changeSource}
            emphasis="subtle"
          />
        </View>
      )}
      <View style={styles.paper}>
        {files ? (
          <WebView
            ref={webView}
            testID="score-view"
            source={{ uri: files.page }}
            originWhitelist={['*']}
            // The page loads alphaTab, its font and soundfont from its own folder (file://).
            allowFileAccess
            allowFileAccessFromFileURLs
            allowUniversalAccessFromFileURLs
            allowingReadAccessToURL={files.folder}
            mediaPlaybackRequiresUserAction={false}
            onMessage={onMessage}
            style={styles.webView}
          />
        ) : (
          <ActivityIndicator color={colors.accent} style={styles.loading} />
        )}
      </View>

      <View style={styles.transport}>
        <View style={styles.timeline}>
          <Text variant="mono">{formatDuration(position.currentMs)}</Text>
          <View style={styles.bar}>
            <ProgressBar
              fraction={position.endMs ? position.currentMs / position.endMs : 0}
              height={4}
            />
          </View>
          <Text variant="mono">{formatDuration(position.endMs)}</Text>
        </View>
        <View style={styles.buttons}>
          <IconButton
            label={loop ? 'Stop looping' : 'Loop'}
            accessibilityState={{ selected: loop }}
            onPress={() => {
              setLoop(!loop);
              run('setLoop', !loop);
            }}
          >
            <Repeat color={loop ? colors.accent : colors.muted} size={22} />
          </IconButton>
          <IconButton label="Back to the start" onPress={() => run('stop')} disabled={!playerReady}>
            <SkipBack color={colors.text} fill={colors.text} size={22} />
          </IconButton>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={playing ? 'Pause' : 'Play'}
            disabled={!playerReady}
            onPress={() => run('playPause')}
            style={({ pressed }) => [styles.play, (!playerReady || pressed) && styles.dimmed]}
          >
            {!playerReady ? (
              <ActivityIndicator color={colors.onAccent} />
            ) : playing ? (
              <Pause color={colors.onAccent} fill={colors.onAccent} size={26} />
            ) : (
              <Play color={colors.onAccent} fill={colors.onAccent} size={26} />
            )}
          </Pressable>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={`Playback speed ${Math.round(speed * 100)} percent`}
            onPress={nextSpeed}
            style={styles.speed}
          >
            <Text style={styles.speedText}>{Math.round(speed * 100)}%</Text>
          </Pressable>
          <IconButton
            label={metronome ? 'Metronome off' : 'Metronome on'}
            accessibilityState={{ selected: metronome }}
            onPress={() => {
              setMetronome(!metronome);
              run('setMetronome', !metronome);
            }}
          >
            <Timer color={metronome ? colors.accent : colors.muted} size={22} />
          </IconButton>
        </View>
      </View>
    </View>
  );
}

/** Copies the take into the viewer's folder as `take.<ext>` and returns that name. */
async function copyTake(uri: string, folder: string): Promise<string> {
  const source = new File(uri);
  const name = `take${source.extension || '.m4a'}`;
  const target = new File(new Directory(folder), name);
  if (target.exists) {
    target.delete();
  }
  await source.copy(target);
  return name;
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  profiles: { paddingHorizontal: space.xl, paddingBottom: space.md },
  paper: {
    flex: 1,
    marginHorizontal: space.md,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.surface,
    overflow: 'hidden',
  },
  webView: { backgroundColor: colors.surface },
  loading: { marginTop: 48 },
  error: { color: colors.dangerText, padding: space.lg },
  transport: {
    paddingHorizontal: space.xl,
    paddingTop: space.md,
    paddingBottom: space.lg,
    gap: 10,
  },
  timeline: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  bar: { flex: 1 },
  buttons: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  play: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: colors.accent,
    alignItems: 'center',
    justifyContent: 'center',
  },
  dimmed: { opacity: 0.6 },
  speed: {
    minWidth: 56,
    height: 44,
    paddingHorizontal: 10,
    borderRadius: 22,
    borderWidth: 1,
    borderColor: colors.line,
    alignItems: 'center',
    justifyContent: 'center',
  },
  speedText: { fontFamily: fonts.monoBold, fontSize: 13 },
});
