import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react-native';
import { router } from 'expo-router';
import type { ReactNode } from 'react';

import { ApiError, type Api, type JobList } from '@/api/client';
import { useApi } from '@/api/provider';
import Library from '@/app/(tabs)/index';
import { hasSeenWelcome } from '@/welcome/seen';

jest.mock('@/api/provider', () => ({ useApi: jest.fn() }));
// No Link here on purpose: <Link asChild> drops a Pressable's style function, which broke the
// cards' layout; the Library navigates with router.push.
jest.mock('expo-router', () => ({ router: { push: jest.fn() } }));
jest.mock('@/welcome/seen', () => ({ hasSeenWelcome: jest.fn(() => true) }));

const me = jest.fn<ReturnType<Api['me']>, []>();
const listJobs = jest.fn<Promise<JobList>, []>();

async function renderLibrary() {
  const queryClient = new QueryClient({
    // No retries, and gcTime Infinity starts no cleanup timer that would keep Jest running.
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { gcTime: Infinity },
    },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  await render(<Library />, { wrapper });
}

const jobList: JobList = {
  jobs: [
    {
      id: 'a',
      name: 'Blues riff in A',
      status: 'running',
      instrument: 'guitar',
      created_at: '2026-10-08T05:22:00Z',
    },
    {
      id: 'b',
      name: null,
      status: 'succeeded',
      instrument: 'piano',
      created_at: '2026-10-07T05:22:00Z',
    },
    {
      id: 'c',
      name: null,
      status: 'failed',
      instrument: 'guitar',
      created_at: '2026-10-06T05:22:00Z',
    },
  ],
  next_cursor: null,
};

beforeEach(() => {
  jest.mocked(useApi).mockReturnValue({ me, listJobs } as unknown as Api);
  me.mockResolvedValue({
    user_id: 'user_1',
    plan: 'free',
    jobs_this_month: 3,
    jobs_per_month: 10,
    terms_version: '2026-10-11',
    terms_accepted: true,
  });
  listJobs.mockResolvedValue({ jobs: [], next_cursor: null });
});

describe('Library', () => {
  it('opens the welcome guide on a phone that has never shown it, and only then', async () => {
    me.mockResolvedValue({
      user_id: 'u',
      plan: 'free',
      jobs_this_month: 0,
      jobs_per_month: 10,
      terms_version: 'v',
      terms_accepted: true,
    });
    listJobs.mockResolvedValue({ jobs: [], next_cursor: null });
    jest.mocked(useApi).mockReturnValue({ me, listJobs } as unknown as Api);
    jest.mocked(hasSeenWelcome).mockReturnValueOnce(false);
    await renderLibrary();
    expect(router.push).toHaveBeenCalledWith('/welcome');
    jest.mocked(router.push).mockClear();
    await renderLibrary();
    expect(router.push).not.toHaveBeenCalledWith('/welcome');
  });

  it("shows this month's quota and an empty state", async () => {
    await renderLibrary();
    expect(await screen.findByText('3 of 10 transcriptions')).toBeTruthy();
    expect(await screen.findByText('Nothing here yet')).toBeTruthy();
  });

  it('shows the unlimited plan without a limit', async () => {
    me.mockResolvedValue({
      user_id: 'user_1',
      plan: 'unlimited',
      jobs_this_month: 23,
      jobs_per_month: 10,
      terms_version: '2026-10-11',
      terms_accepted: true,
    });
    await renderLibrary();
    expect(await screen.findByText('23 transcriptions this month')).toBeTruthy();
    expect(screen.getByText('Unlimited plan')).toBeTruthy();
    expect(screen.queryByText(/of 10/)).toBeNull();
  });

  it("lists the user's transcriptions with their status", async () => {
    listJobs.mockResolvedValue(jobList);
    await renderLibrary();
    expect(await screen.findByText('Transcribing')).toBeTruthy();
    expect(screen.getByText('Ready')).toBeTruthy();
    expect(screen.getByText('Failed')).toBeTruthy();
    expect(screen.getByText('Blues riff in A')).toBeTruthy();
    expect(screen.getByText('Guitar take')).toBeTruthy();
  });

  it('lays each transcription out as a card that opens it', async () => {
    listJobs.mockResolvedValue(jobList);
    await renderLibrary();
    const card = await screen.findByRole('button', { name: /^Blues riff in A, / });
    // A row with the icon beside the title.
    expect(card).toHaveStyle({ flexDirection: 'row' });
    await fireEvent.press(card);
    expect(router.push).toHaveBeenCalledWith({
      pathname: '/jobs/[id]',
      params: { id: expect.any(String) },
    });
  });

  it('filters by instrument', async () => {
    listJobs.mockResolvedValue(jobList);
    await renderLibrary();
    await screen.findByText('Ready');

    await fireEvent.press(screen.getByRole('button', { name: 'Piano' }));
    expect(screen.queryByText('Guitar take')).toBeNull();
    expect(screen.queryByText('Blues riff in A')).toBeNull();
    expect(screen.getByText('Piano take')).toBeTruthy();
  });

  it("says so when the API can't be reached", async () => {
    me.mockRejectedValue(new ApiError(503, 'auth unavailable'));
    await renderLibrary();
    expect(await screen.findByText(/Can.t reach the API: auth unavailable/)).toBeTruthy();
  });
});
