import { useClerk, useUser } from '@clerk/expo';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react-native';
import type { ReactNode } from 'react';

import { ApiError, type Api } from '@/api/client';
import { useApi } from '@/api/provider';
import Home from '@/app/index';

jest.mock('@clerk/expo', () => ({ useClerk: jest.fn(), useUser: jest.fn() }));
jest.mock('@/api/provider', () => ({ useApi: jest.fn() }));

const signOut = jest.fn(async () => {});
const me = jest.fn<ReturnType<Api['me']>, []>();

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
  jest.mocked(useUser).mockReturnValue({
    user: { primaryEmailAddress: { emailAddress: 'alice@example.com' } },
  } as unknown as ReturnType<typeof useUser>);
  jest.mocked(useApi).mockReturnValue({ me } as unknown as Api);
});

describe('Home', () => {
  it("shows the account and this month's quota from the API", async () => {
    me.mockResolvedValue({ user_id: 'user_1', jobs_this_month: 2, jobs_per_month: 10 });
    await renderHome();

    expect(screen.getByTestId('account')).toHaveTextContent('alice@example.com');
    expect(await screen.findByText('2 of 10 transcriptions used this month')).toBeTruthy();
    expect(screen.getByTestId('api-url')).toHaveTextContent(/API: http:\/\/\S+:8000/);
  });

  it("says so when the API can't be reached", async () => {
    me.mockRejectedValue(new ApiError(503, 'auth unavailable'));
    await renderHome();

    expect(await screen.findByText("Can't reach the API: auth unavailable")).toBeTruthy();
  });

  it('signs out and forgets the cached data', async () => {
    me.mockResolvedValue({ user_id: 'user_1', jobs_this_month: 2, jobs_per_month: 10 });
    const queryClient = await renderHome();
    await screen.findByText('2 of 10 transcriptions used this month');

    await fireEvent.press(screen.getByText('Sign out'));
    expect(signOut).toHaveBeenCalled();
    expect(queryClient.getQueryData(['me'])).toBeUndefined();
  });
});
