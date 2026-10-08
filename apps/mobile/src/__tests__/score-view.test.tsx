import { act, render, screen } from '@testing-library/react-native';
import type { ReactNode } from 'react';

import { prepareViewer } from '@/score/prepareViewer';
import { ScoreView } from '@/score/ScoreView';

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

beforeEach(() => {
  mockInjectJavaScript.mockClear();
  jest.mocked(prepareViewer).mockResolvedValue({
    page: 'file:///cache/score-viewer/index.html',
    folder: 'file:///cache/score-viewer/',
  });
});

describe('ScoreView', () => {
  it('sends the score once the page says it is ready', async () => {
    await render(<ScoreView musicXml={'<score-partwise version="4.0"/>'} />);
    await screen.findByTestId('score-view');
    expect(mockInjectJavaScript).not.toHaveBeenCalled();

    await act(async () => mockOnMessage?.({ nativeEvent: { data: '{"type":"ready"}' } }));
    expect(mockInjectJavaScript).toHaveBeenCalledWith(
      'window.loadScore("<score-partwise version=\\"4.0\\"/>"); true;',
    );
  });

  it("explains when the score can't be drawn", async () => {
    await render(<ScoreView musicXml="<bad/>" />);
    await screen.findByTestId('score-view');
    await act(async () =>
      mockOnMessage?.({ nativeEvent: { data: '{"type":"error","message":"unsupported format"}' } }),
    );
    expect(screen.getByText(/unsupported format/)).toBeTruthy();
  });
});
