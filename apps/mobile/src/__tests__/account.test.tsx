import { useClerk, useUser } from '@clerk/expo';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react-native';
import type { ReactNode } from 'react';

import type { Api } from '@/api/client';
import { useApi } from '@/api/provider';
import Account from '@/app/(tabs)/account';

jest.mock('@clerk/expo', () => ({ useClerk: jest.fn(), useUser: jest.fn() }));
jest.mock('@/api/provider', () => ({ useApi: jest.fn() }));

const signOut = jest.fn(async () => {});

beforeEach(() => {
  jest.mocked(useClerk).mockReturnValue({ signOut } as unknown as ReturnType<typeof useClerk>);
  jest.mocked(useUser).mockReturnValue({
    user: {
      fullName: 'Ada Lovelace',
      primaryEmailAddress: { emailAddress: 'ada@example.com' },
      externalAccounts: [{ provider: 'google' }],
    },
  } as unknown as ReturnType<typeof useUser>);
  jest.mocked(useApi).mockReturnValue({
    me: async () => ({ user_id: 'u', jobs_this_month: 3, jobs_per_month: 10 }),
  } as unknown as Api);
});

async function renderAccount() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  queryClient.setQueryData(['jobs'], { jobs: [], next_cursor: null });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  await render(<Account />, { wrapper });
  return queryClient;
}

describe('Account', () => {
  it('shows who is signed in and their usage', async () => {
    await renderAccount();
    expect(screen.getByTestId('account-name')).toHaveTextContent('Ada Lovelace');
    expect(screen.getByText('Signed in with Google')).toBeTruthy();
    expect(await screen.findByText(/3 of 10 transcriptions this month/)).toBeTruthy();
  });

  it('signs out and forgets the cached data', async () => {
    const queryClient = await renderAccount();
    await fireEvent.press(screen.getByRole('button', { name: 'Sign out' }));
    expect(signOut).toHaveBeenCalled();
    expect(queryClient.getQueryData(['jobs'])).toBeUndefined();
  });
});
