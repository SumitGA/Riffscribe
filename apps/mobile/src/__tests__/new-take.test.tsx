import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { router } from 'expo-router';
import type { ReactNode } from 'react';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import type { Api } from '@/api/client';
import { useApi } from '@/api/provider';
import NewTake from '@/app/new';
import type { AudioClip } from '@/audio/clip';
import { levelFromDecibels, resample } from '@/audio/LevelBars';
import { startTranscription } from '@/jobs/transcribe';

const take: AudioClip = {
  uri: 'file:///cache/take.m4a',
  name: 'Recording.m4a',
  contentType: 'audio/mp4',
  sizeBytes: 71376,
  durationMs: 5200,
  waveform: [0.2, 0.6, 0.9, 0.4],
};

jest.mock('@/api/provider', () => ({ useApi: jest.fn() }));
jest.mock('@/push', () => ({ askForPushOnce: jest.fn(async () => {}) }));
jest.mock('expo-router', () => ({ router: { replace: jest.fn() } }));
jest.mock('expo-audio', () => ({
  useAudioPlayer: () => ({ play: jest.fn(), pause: jest.fn(), seekTo: jest.fn() }),
  useAudioPlayerStatus: () => ({
    playing: false,
    currentTime: 0,
    duration: 5.2,
    didJustFinish: false,
  }),
}));
jest.mock('@/audio/pickAudioFile', () => ({ pickAudioFile: jest.fn() }));
// The recorder needs the microphone; here it hands over a finished take when pressed.
jest.mock('@/audio/Recorder', () => {
  const { Pressable, Text } = jest.requireActual<typeof import('react-native')>('react-native');
  return {
    Recorder: ({ onRecorded }: { onRecorded: (clip: AudioClip) => void }) => (
      <Pressable accessibilityRole="button" onPress={() => onRecorded(take)}>
        <Text>Finish recording</Text>
      </Pressable>
    ),
  };
});
jest.mock('@/jobs/transcribe', () => ({ startTranscription: jest.fn(), uploadFile: jest.fn() }));

beforeEach(() => {
  jest.mocked(useApi).mockReturnValue({
    me: async () => ({ user_id: 'u', jobs_this_month: 3, jobs_per_month: 10 }),
  } as unknown as Api);
  jest.mocked(startTranscription).mockResolvedValue({ id: 'job-1' } as never);
});

async function renderNewTake() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { gcTime: Infinity },
    },
  });
  const metrics = {
    frame: { x: 0, y: 0, width: 390, height: 844 },
    insets: { top: 0, left: 0, right: 0, bottom: 0 },
  };
  const wrapper = ({ children }: { children: ReactNode }) => (
    <SafeAreaProvider initialMetrics={metrics}>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </SafeAreaProvider>
  );
  await render(<NewTake />, { wrapper });
}

describe('NewTake', () => {
  it('sends the take with its name, instrument, tuning and capo', async () => {
    await renderNewTake();
    await fireEvent.press(screen.getByText('Standard tuning'));
    await fireEvent.press(screen.getByRole('radio', { name: /Drop D tuning/ }));
    await fireEvent.press(screen.getByText('No capo'));
    await fireEvent.press(screen.getByRole('radio', { name: 'Capo on fret 2' }));
    await fireEvent.press(screen.getByText('Finish recording'));

    expect(await screen.findByText(/7 remaining transcriptions/)).toBeTruthy();
    await fireEvent.changeText(screen.getByPlaceholderText('Guitar take'), '  Blues riff in A ');
    await fireEvent.press(screen.getByText('Transcribe'));

    expect(startTranscription).toHaveBeenCalledWith(
      expect.anything(),
      take,
      { instrument: 'guitar', tuning: 'drop_d', capo: 2, name: 'Blues riff in A' },
      expect.any(Function),
      expect.any(Function),
    );
    await waitFor(() =>
      expect(router.replace).toHaveBeenCalledWith({
        pathname: '/jobs/[id]',
        params: { id: 'job-1' },
      }),
    );
  });

  it('sends piano takes without guitar settings', async () => {
    await renderNewTake();
    await fireEvent.press(screen.getByRole('radio', { name: 'Piano' }));
    expect(screen.queryByText('Standard tuning')).toBeNull();
    await fireEvent.press(screen.getByText('Finish recording'));
    await screen.findByText(/remaining transcriptions/); // settled
    await fireEvent.press(screen.getByText('Transcribe'));

    expect(startTranscription).toHaveBeenCalledWith(
      expect.anything(),
      take,
      { instrument: 'piano', tuning: undefined, capo: undefined, name: undefined },
      expect.any(Function),
      expect.any(Function),
    );
    await waitFor(() => expect(router.replace).toHaveBeenCalled());
  });
});

describe('level meter', () => {
  it('maps decibels to bar heights, with silence as a sliver', () => {
    expect(levelFromDecibels(0)).toBe(1);
    expect(levelFromDecibels(-30)).toBe(0.5);
    expect(levelFromDecibels(-90)).toBe(0.05);
    expect(levelFromDecibels(undefined)).toBe(0.05);
  });

  it('keeps the peaks when shrinking a waveform', () => {
    expect(resample([0.1, 0.9, 0.2, 0.3, 0.8, 0.1], 3)).toEqual([0.9, 0.3, 0.8]);
    expect(resample([0.5], 3)).toEqual([0.5]);
  });
});
