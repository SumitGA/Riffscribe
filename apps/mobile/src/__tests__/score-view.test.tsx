import { act, fireEvent, render, screen } from '@testing-library/react-native';
import type { ReactNode } from 'react';

import { prepareViewer } from '@/score/prepareViewer';
import { ScoreView } from '@/score/ScoreView';
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
    expect(mockInjectJavaScript).toHaveBeenCalledWith(command('load', '<score-partwise/>', 'both'));
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
      command('load', '<score-partwise/>', 'score'),
    );
  });

  it("explains when the score can't be drawn", async () => {
    await render(<ScoreView musicXml="<bad/>" hasTab />);
    await screen.findByTestId('score-view');
    await send({ type: 'error', message: 'unsupported format' });
    expect(screen.getByText(/unsupported format/)).toBeTruthy();
  });
});
