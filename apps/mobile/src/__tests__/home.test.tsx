import { useClerk } from '@clerk/expo';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react-native';
import type { ReactNode } from 'react';

import { ApiError, type Api, type JobList } from '@/api/client';
import { useApi } from '@/api/provider';
import Home from '@/app/index';

jest.mock('@clerk/expo', () => ({ useClerk: jest.fn() }));
jest.mock('@/api/provider', () => ({ useApi: jest.fn() }));
jest.mock('expo-router', () => ({ Link: ({ children }: { children: ReactNode }) => children }));

const signOut = jest.fn(async () => {});
const me = jest.fn<ReturnType<Api['me']>, []>();
const listJobs = jest.fn<Promise<JobList>, []>();

async function renderHome() {
  const queryClient = new QueryClient({
    // No retries, and gcTime Infinity starts no cleanup timer that would keep Jest running.
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  await render(<Home />, { wrapper });
  return queryClient;
}

beforeEach(() => {
  jest.mocked(useClerk).mockReturnValue({ signOut } as unknown as ReturnType<typeof useClerk>);
  jest.mocked(useApi).mockReturnValue({ me, listJobs } as unknown as Api);
  me.mockResolvedValue({ user_id: 'user_1', jobs_this_month: 2, jobs_per_month: 10 });
  listJobs.mockResolvedValue({ jobs: [], next_cursor: null });
});

describe('Home', () => {
  it("shows this month's quota and the way to start", async () => {
    await renderHome();
    expect(await screen.findByText('2 of 10 transcriptions used this month')).toBeTruthy();
    expect(screen.getByText('New transcription')).toBeTruthy();
    expect(await screen.findByText(/Nothing yet/)).toBeTruthy();
  });

  it("lists the user's jobs with their status", async () => {
    listJobs.mockResolvedValue({
      jobs: [
        { id: 'a', status: 'running', instrument: 'guitar', created_at: '2026-10-08T05:22:00Z' },
        { id: 'b', status: 'succeeded', instrument: 'piano', created_at: '2026-10-07T05:22:00Z' },
      ],
      next_cursor: null,
    });
    await renderHome();
    expect(await screen.findByText('Transcribing')).toBeTruthy();
    expect(screen.getByText('Ready')).toBeTruthy();
    expect(screen.getByText('Guitar')).toBeTruthy();
    expect(screen.getByText('Piano')).toBeTruthy();
  });

  it("says so when the API can't be reached", async () => {
    me.mockRejectedValue(new ApiError(503, 'auth unavailable'));
    await renderHome();
    expect(await screen.findByText("Can't reach the API: auth unavailable")).toBeTruthy();
  });

  it('signs out and forgets the cached data', async () => {
    const queryClient = await renderHome();
    await screen.findByText('2 of 10 transcriptions used this month');

    await fireEvent.press(screen.getByText('Sign out'));
    expect(signOut).toHaveBeenCalled();
    expect(queryClient.getQueryData(['me'])).toBeUndefined();
  });
});
