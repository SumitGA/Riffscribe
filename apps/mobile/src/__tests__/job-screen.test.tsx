import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react-native';
import type { ReactNode } from 'react';

import type { Api, Job } from '@/api/client';
import { useApi } from '@/api/provider';
import JobScreen from '@/app/jobs/[id]';
import { stageStates } from '@/jobs/status';

jest.mock('@/api/provider', () => ({ useApi: jest.fn() }));
jest.mock('expo-router', () => ({ useLocalSearchParams: () => ({ id: 'job-1' }) }));

const t = (s: number) => new Date(Date.UTC(2026, 9, 8, 5, 0, s)).toISOString();
const run = (
  stage: string,
  status: Job['stages'][number]['status'],
  start?: number,
  end?: number,
) => ({
  stage,
  status,
  attempts: 1,
  started_at: start === undefined ? null : t(start),
  finished_at: end === undefined ? null : t(end),
});
const job = (overrides: Partial<Job>): Job =>
  ({
    id: 'job-1',
    status: 'running',
    options: { instrument: 'guitar', tuning: 'standard', capo: 0 },
    created_at: t(0),
    submitted_at: t(0),
    finished_at: null,
    pipeline_version: null,
    error: null,
    stages: [],
    outputs: null,
    ...overrides,
  }) as Job;

async function renderJob(data: Job) {
  jest.mocked(useApi).mockReturnValue({ getJob: async () => data } as unknown as Api);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity, refetchInterval: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  await render(<JobScreen />, { wrapper });
}

describe('stageStates', () => {
  it('lists every stage, with timings for finished ones', () => {
    const states = stageStates({
      stages: [
        run('normalize', 'succeeded', 0, 2),
        run('separate', 'skipped', 2, 2),
        run('transcribe', 'running', 2),
      ],
    } as Job);
    expect(states.map((s) => s.state)).toEqual([
      'done',
      'skipped',
      'running',
      'waiting',
      'waiting',
      'waiting',
    ]);
    expect(states[0]?.seconds).toBe(2);
  });

  it('counts a cached stage as done', () => {
    expect(stageStates({ stages: [run('normalize', 'cached', 0, 0)] } as Job)[0]?.state).toBe(
      'done',
    );
  });
});

describe('JobScreen', () => {
  it('shows a running job stage by stage', async () => {
    await renderJob(
      job({ stages: [run('normalize', 'succeeded', 0, 1), run('transcribe', 'running', 1)] }),
    );
    expect(await screen.findByText('Transcribing')).toBeTruthy();
    expect(screen.getByText('Listening for notes')).toBeTruthy();
    expect(screen.getAllByTestId('stage-done')).toHaveLength(1);
    expect(screen.getAllByTestId('stage-running')).toHaveLength(1);
  });

  it('says when the score is ready', async () => {
    const presigned = { method: 'GET', url: 'u', headers: {}, expires_in_s: 900 };
    await renderJob(
      job({
        status: 'succeeded',
        outputs: { version: 1, musicxml: presigned, tab_musicxml: presigned, midi: presigned },
      }),
    );
    expect(await screen.findByText('Your score is ready')).toBeTruthy();
    expect(screen.getByText(/Sheet music, guitar tab and MIDI/)).toBeTruthy();
  });

  it('shows why a job failed', async () => {
    await renderJob(
      job({
        status: 'failed',
        error: { code: 'invalid_input', message: 'The audio is longer than 5 minutes.' },
      }),
    );
    expect(await screen.findByText(/longer than 5 minutes/)).toBeTruthy();
  });
});
