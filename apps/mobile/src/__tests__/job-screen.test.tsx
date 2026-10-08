import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react-native';
import type { ReactNode } from 'react';

import type { Api, Job } from '@/api/client';
import { useApi } from '@/api/provider';
import JobScreen from '@/app/jobs/[id]';
import { stageStates } from '@/jobs/status';

jest.mock('@/api/provider', () => ({ useApi: jest.fn() }));
jest.mock('expo-router', () => ({
  useLocalSearchParams: () => ({ id: 'job-1' }),
  Stack: { Screen: () => null },
}));
jest.mock('@/score/exports', () => ({ fileName: jest.fn() }));
jest.mock('@/score/ExportSheet', () => ({ ExportSheet: () => null }));
jest.mock('@/score/ScoreView', () => {
  const { Text } = jest.requireActual<typeof import('react-native')>('react-native');
  return {
    ScoreView: ({ musicXml }: { musicXml: string; hasTab: boolean }) => (
      <Text testID="score">{musicXml}</Text>
    ),
  };
});

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
    expect(await screen.findByTestId('job-headline')).toHaveTextContent('Listening for notes…');
    expect(screen.getByText('17%')).toBeTruthy(); // 1 of 6 stages done
    expect(screen.getAllByTestId('stage-done')).toHaveLength(1);
    expect(screen.getAllByTestId('stage-running')).toHaveLength(1);
  });

  it('shows the score of a finished guitar job, with its tab', async () => {
    const get = (url: string) => ({ method: 'GET', url, headers: {}, expires_in_s: 900 });
    const fetchMock = jest.fn(
      async (url: string) => new Response(`<score-partwise from="${url}"/>`),
    );
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;
    await renderJob(
      job({
        status: 'succeeded',
        outputs: {
          version: 1,
          musicxml: get('https://s3/score'),
          tab_musicxml: get('https://s3/tab'),
          midi: null,
        },
      }),
    );
    expect(await screen.findByTestId('score')).toHaveTextContent(
      '<score-partwise from="https://s3/tab"/>',
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
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
