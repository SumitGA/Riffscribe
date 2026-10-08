import { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';
import WebView, { type WebViewMessageEvent } from 'react-native-webview';

import { prepareViewer, type ViewerFiles } from './prepareViewer';
import type { ViewerMessage } from './viewerPage';

/**
 * Sheet music and tab rendered by alphaTab, with playback, from a MusicXML document. alphaTab is
 * a web library, so it runs in a WebView on files bundled with the app; nothing loads from the
 * network.
 */
export function ScoreView({ musicXml }: { musicXml: string }) {
  const webView = useRef<WebView>(null);
  const [files, setFiles] = useState<ViewerFiles | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    prepareViewer().then(setFiles, (e: unknown) => setError(String(e)));
  }, []);

  // Send the score once the page is up, and again if it changes.
  useEffect(() => {
    if (ready) {
      webView.current?.injectJavaScript(`window.loadScore(${JSON.stringify(musicXml)}); true;`);
    }
  }, [ready, musicXml]);

  const onMessage = (event: WebViewMessageEvent) => {
    const message = JSON.parse(event.nativeEvent.data) as ViewerMessage;
    if (message.type === 'ready') {
      setReady(true);
    } else if (message.type === 'error') {
      setError(message.message);
    }
  };

  if (error) {
    return <Text style={styles.error}>The score couldn&apos;t be shown: {error}</Text>;
  }
  if (!files) {
    return <ActivityIndicator style={styles.loading} />;
  }
  return (
    <View style={styles.container}>
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
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  loading: { marginTop: 48 },
  error: { color: '#b00020', padding: 16 },
});
