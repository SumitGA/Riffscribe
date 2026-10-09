import { act, fireEvent, render, screen } from '@testing-library/react-native';
import { Directory, File, Paths } from 'expo-file-system';
import { createRef, type ReactNode } from 'react';

import { prepareViewer } from '@/score/prepareViewer';
import { type ScoreHandle, ScoreView } from '@/score/ScoreView';
import { command } from '@/score/viewerPage';

const mockInjectJavaScript = jest.fn();
let mockOnMessage: ((event: { nativeEvent: { data: string } }) => void) | undefined;

jest.mock('@/score/prepareViewer', () => ({ prepareViewer: jest.fn() }));
jest.mock('react-native-webview', () => {
  const React = jest.requireActual<typeof import('react')>('react');
  const { View } = jest.requireActual<typeof import('react-native')>('react-native');
  const WebView = React.forwardRef(
    (props: { onMessage: typeof mockOnMessage; testID: string; children?: ReactNode }, ref) => {
      React.useImperativeHandle(ref, () => ({ injectJavaScript: mockInjectJavaScript }));
      mockOnMessage = props.onMessage;
      return <View testID={props.testID} />;
    },
  );
  WebView.displayName = 'WebView';
  return { __esModule: true, default: WebView };
});

const send = (message: object) =>
  act(async () => mockOnMessage?.({ nativeEvent: { data: JSON.stringify(message) } }));

beforeEach(() => {
  mockInjectJavaScript.mockClear();
  jest.mocked(prepareViewer).mockResolvedValue({
    page: 'file:///cache/score-viewer/index.html',
    folder: 'file:///cache/score-viewer/',
  });
});

describe('command', () => {
  it('calls the page with JSON arguments', () => {
    expect(command('load', '<a x="1"/>', 'both')).toBe(
      'window.riff.load("<a x=\\"1\\"/>", "both"); true;',
    );
  });
});

describe('ScoreView', () => {
  it('sends the score once the page says it is ready', async () => {
    await render(<ScoreView musicXml="<score-partwise/>" hasTab />);
    await screen.findByTestId('score-view');
    expect(mockInjectJavaScript).not.toHaveBeenCalled();

    await send({ type: 'ready' });
    expect(mockInjectJavaScript).toHaveBeenCalledWith(
      command('load', '<score-partwise/>', 'both', null),
    );
  });

  it("plays the user's recording, with a switch back to the guitar sound", async () => {
    const dir = new Directory(Paths.document, 'takes');
    dir.create({ idempotent: true, intermediates: true });
    const take = new File(dir, 'job.m4a');
    take.write('audio');
    new Directory('file:///cache/score-viewer/').create({ idempotent: true, intermediates: true });

    await render(
      <ScoreView
        musicXml="<score-partwise/>"
        hasTab
        take={{ uri: take.uri, barStartsMs: [0, 2000] }}
      />,
    );
    await screen.findByTestId('score-view');
    await send({ type: 'ready' });
    expect(mockInjectJavaScript).toHaveBeenCalledWith(
      command('load', '<score-partwise/>', 'both', { file: 'take.m4a', barStartsMs: [0, 2000] }),
    );
    expect(new File('file:///cache/score-viewer/take.m4a').exists).toBe(true);

    await fireEvent.press(screen.getByText('Guitar sound'));
    expect(mockInjectJavaScript).toHaveBeenLastCalledWith(command('setSource', 'synth'));
  });

  it('drives playback, speed and the view from native controls', async () => {
    await render(<ScoreView musicXml="<score-partwise/>" hasTab />);
    await screen.findByTestId('score-view');
    await send({ type: 'ready' });
    await send({ type: 'playerReady' });
    await send({ type: 'position', currentMs: 6000, endMs: 72000 });
    expect(screen.getByText('0:06')).toBeTruthy();
    expect(screen.getByText('1:12')).toBeTruthy();

    await fireEvent.press(screen.getByRole('button', { name: 'Play' }));
    expect(mockInjectJavaScript).toHaveBeenLastCalledWith(command('playPause'));
    await send({ type: 'playing', playing: true });
    expect(screen.getByRole('button', { name: 'Pause' })).toBeTruthy();

    await fireEvent.press(screen.getByRole('button', { name: /speed 100 percent/ }));
    expect(mockInjectJavaScript).toHaveBeenLastCalledWith(command('setSpeed', 0.75));

    await fireEvent.press(screen.getByRole('radio', { name: 'Tab' }));
    expect(mockInjectJavaScript).toHaveBeenLastCalledWith(command('setProfile', 'tab'));
  });

  it('shows notation only, without the switch, for piano', async () => {
    await render(<ScoreView musicXml="<score-partwise/>" hasTab={false} />);
    await screen.findByTestId('score-view');
    await send({ type: 'ready' });
    expect(screen.queryByRole('radio', { name: 'Tab' })).toBeNull();
    expect(mockInjectJavaScript).toHaveBeenCalledWith(
      command('load', '<score-partwise/>', 'score', null),
    );
  });

  it('asks the page for exports and returns its answers', async () => {
    const handle = createRef<ScoreHandle>();
    await render(<ScoreView ref={handle} musicXml="<score-partwise/>" hasTab />);
    await screen.findByTestId('score-view');

    const gp = handle.current?.guitarPro();
    expect(mockInjectJavaScript).toHaveBeenLastCalledWith(command('exportGuitarPro', 1));
    const pdf = handle.current?.printable();
    expect(mockInjectJavaScript).toHaveBeenLastCalledWith(command('exportPrintable', 2));

    const gpChecked = expect(gp).resolves.toBe('UEsDBA==');
    const pdfChecked = expect(pdf).rejects.toThrow('render failed');
    await send({ type: 'exportFailed', id: 2, message: 'render failed' });
    await send({ type: 'exported', id: 1, data: 'UEsDBA==' });
    await gpChecked;
    await pdfChecked;
  });

  it("explains when the score can't be drawn", async () => {
    await render(<ScoreView musicXml="<bad/>" hasTab />);
    await screen.findByTestId('score-view');
    await send({ type: 'error', message: 'unsupported format' });
    expect(screen.getByText(/unsupported format/)).toBeTruthy();
  });
});
