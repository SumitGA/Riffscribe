import { Alert, Linking } from 'react-native';
import { useClerk, useUser } from '@clerk/expo';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen } from '@testing-library/react-native';
import type { ReactNode } from 'react';

import type { Api } from '@/api/client';
import { useApi } from '@/api/provider';
import Account from '@/app/(tabs)/account';

jest.mock('@clerk/expo', () => ({ useClerk: jest.fn(), useUser: jest.fn() }));
jest.mock('@/api/provider', () => ({ useApi: jest.fn() }));
jest.mock('expo-router', () => ({ Link: ({ children }: { children: ReactNode }) => children }));
let mockCanBuy = false;
jest.mock('@/billing', () => ({
  ...jest.requireActual<object>('@/billing'),
  billingAvailable: () => mockCanBuy,
  stopBilling: jest.fn(async () => {}),
  manageSubscription: jest.fn(async () => {}),
}));
let meExtra: Record<string, unknown> = {};
jest.mock('@/push', () => ({
  pushState: jest.fn(async () => 'unavailable'),
  enablePush: jest.fn(),
  disablePush: jest.fn(async () => {}),
}));

const signOut = jest.fn(async () => {});
const deleteAccount = jest.fn(async () => {});

beforeEach(() => {
  mockCanBuy = false;
  meExtra = {};
  jest.mocked(useClerk).mockReturnValue({ signOut } as unknown as ReturnType<typeof useClerk>);
  jest.mocked(useUser).mockReturnValue({
    user: {
      fullName: 'Ada Lovelace',
      primaryEmailAddress: { emailAddress: 'ada@example.com' },
      externalAccounts: [{ provider: 'google' }],
    },
  } as unknown as ReturnType<typeof useUser>);
  jest.mocked(useApi).mockReturnValue({
    me: async () => ({
      user_id: 'u',
      plan: 'free',
      plan_source: 'default',
      limits: { jobs_per_month: 10, max_clip_s: 300, max_upload_bytes: 67108864, priority: false },
      jobs_this_month: 3,
      jobs_per_month: 10,
      terms_version: '2026-10-11',
      terms_accepted: true,
      ...meExtra,
    }),
    deleteAccount,
  } as unknown as Api);
});

async function renderAccount() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { gcTime: Infinity },
    },
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
    await screen.findByText(/3 of 10 transcriptions this month/); // settled
    await fireEvent.press(screen.getByRole('button', { name: 'Sign out' }));
    expect(signOut).toHaveBeenCalled();
    expect(queryClient.getQueryData(['jobs'])).toBeUndefined();
  });

  it('deletes the account after a warning, then signs out', async () => {
    const alert = jest.spyOn(Alert, 'alert');
    const queryClient = await renderAccount();
    await screen.findByText(/3 of 10 transcriptions this month/);
    await fireEvent.press(screen.getByRole('button', { name: 'Delete account' }));

    expect(deleteAccount).not.toHaveBeenCalled(); // nothing happens before confirming
    const buttons = alert.mock.calls[0]?.[2] ?? [];
    await act(async () => buttons.find((b) => b.text === 'Delete')?.onPress?.());

    expect(deleteAccount).toHaveBeenCalled();
    expect(signOut).toHaveBeenCalled();
    expect(queryClient.getQueryData(['jobs'])).toBeUndefined();
  });

  it('opens an email for feedback, or says where to write without an email app', async () => {
    const openURL = jest.spyOn(Linking, 'openURL').mockResolvedValueOnce(true);
    await renderAccount();
    await screen.findByText(/3 of 10 transcriptions this month/);
    await fireEvent.press(screen.getByRole('button', { name: 'Send feedback' }));
    expect(openURL.mock.calls[0]?.[0]).toMatch(/^mailto:sumitga\.playstore@gmail\.com\?/);

    const alert = jest.spyOn(Alert, 'alert');
    openURL.mockRejectedValueOnce(new Error('no mail app'));
    await act(async () => fireEvent.press(screen.getByRole('button', { name: 'Send feedback' })));
    expect(alert).toHaveBeenCalledWith(
      'No email app',
      expect.stringContaining('sumitga.playstore'),
    );
  });

  it('links to the welcome guide', async () => {
    await renderAccount();
    expect(screen.getByRole('link', { name: 'How Riffscribe works' })).toBeTruthy();
  });

  it('offers Pro on the free plan when this build can sell it', async () => {
    await renderAccount();
    await screen.findByText(/3 of 10 transcriptions this month · up to 5 min each/);
    expect(screen.queryByRole('button', { name: 'Upgrade to Pro' })).toBeNull();
    mockCanBuy = true;
    await renderAccount();
    expect(await screen.findByRole('button', { name: 'Upgrade to Pro' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Restore purchases' })).toBeTruthy();
  });

  it('shows a store subscription and warns before deleting the account', async () => {
    mockCanBuy = true;
    meExtra = {
      plan: 'pro',
      plan_source: 'store',
      limits: { jobs_per_month: 100, max_clip_s: 900, max_upload_bytes: 1, priority: true },
      jobs_per_month: 100,
      subscription: {
        store: 'app_store',
        product_id: 'pro_monthly',
        active: true,
        in_trial: false,
        expires_at: '2026-12-07T10:00:00Z',
        will_renew: true,
        billing_issue: false,
        refunded: false,
      },
    };
    const alert = jest.spyOn(Alert, 'alert');
    await renderAccount();
    expect(
      await screen.findByText(/3 of 100 transcriptions this month · up to 15 min each/),
    ).toBeTruthy();
    expect(screen.getByTestId('plan-name')).toHaveTextContent('Pro');
    expect(screen.getByTestId('subscription')).toHaveTextContent('Renews on 7 Dec 2026');
    expect(screen.getByRole('button', { name: 'Manage subscription' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Upgrade to Pro' })).toBeNull();

    await fireEvent.press(screen.getByRole('button', { name: 'Delete account' }));
    expect(alert.mock.calls.at(-1)?.[1]).toMatch(/keeps renewing until you cancel it/);
  });
});
