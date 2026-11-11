import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { router, useLocalSearchParams } from 'expo-router';
import type { ReactNode } from 'react';
import { Alert } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import type { Api, Me } from '@/api/client';
import { useApi } from '@/api/provider';
import Pro from '@/app/pro';
import { buy, type ProOption, proOptions, restore } from '@/billing';

jest.mock('@/api/provider', () => ({ useApi: jest.fn() }));
jest.mock('expo-router', () => ({
  router: { back: jest.fn() },
  useLocalSearchParams: jest.fn(() => ({})),
}));
jest.mock('@/billing', () => ({
  ...jest.requireActual<object>('@/billing'),
  billingAvailable: () => true,
  proOptions: jest.fn(),
  buy: jest.fn(),
  restore: jest.fn(async () => {}),
  manageSubscription: jest.fn(async () => {}),
}));

const MONTHLY = {
  id: '$rc_monthly',
  period: 'month',
  price: 'A$4.99',
  perMonth: null,
  trial: null,
  pkg: {},
} as unknown as ProOption;
const YEARLY = {
  id: '$rc_annual',
  period: 'year',
  price: 'A$39.99',
  perMonth: 'A$3.33',
  trial: '1 week free',
  pkg: {},
} as unknown as ProOption;

const FREE: Me = {
  user_id: 'u',
  plan: 'free',
  plan_source: 'default',
  limits: { jobs_per_month: 10, max_clip_s: 300, max_upload_bytes: 1, priority: false },
  jobs_this_month: 10,
  jobs_per_month: 10,
  terms_version: 'v',
  terms_accepted: true,
};
const PRO: Me = { ...FREE, plan: 'pro', plan_source: 'store' };

let plan: Me;
const syncBilling = jest.fn(async () => {});

beforeEach(() => {
  jest.clearAllMocks();
  plan = FREE;
  jest.mocked(useApi).mockReturnValue({ me: async () => plan, syncBilling } as unknown as Api);
  jest.mocked(proOptions).mockResolvedValue([MONTHLY, YEARLY]);
  jest.mocked(useLocalSearchParams).mockReturnValue({});
});

async function renderPro() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { gcTime: Infinity },
    },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <SafeAreaProvider
      initialMetrics={{
        frame: { x: 0, y: 0, width: 390, height: 844 },
        insets: { top: 0, left: 0, right: 0, bottom: 0 },
      }}
    >
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </SafeAreaProvider>
  );
  await render(<Pro />, { wrapper });
}

describe('Pro paywall', () => {
  it('shows what Pro gives, the store prices and the renewal terms', async () => {
    jest.mocked(useLocalSearchParams).mockReturnValue({ reason: 'limit' });
    await renderPro();
    expect(screen.getByTestId('pro-reason')).toHaveTextContent(/free transcriptions/);
    expect(screen.getByText('100 transcriptions a month')).toBeTruthy();
    expect(await screen.findByRole('radio', { name: 'Monthly, A$4.99 / month' })).toBeTruthy();
    // Yearly is chosen first; its terms name the trial, the price and auto-renewal.
    expect(screen.getByRole('radio', { name: 'Yearly, A$39.99 / year' })).toBeSelected();
    expect(screen.getByTestId('renewal-terms')).toHaveTextContent(
      /^1 week free, then A\$39.99 \/ year\. Renews automatically until you cancel\./,
    );
    expect(screen.getByRole('link', { name: 'Terms of Use' })).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Privacy Policy' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Start free trial' })).toBeTruthy();
  });

  it('buys the chosen option, has the server re-check, and closes', async () => {
    const alert = jest.spyOn(Alert, 'alert');
    jest.mocked(buy).mockImplementation(async () => {
      plan = PRO; // the store took the payment
      return true;
    });
    await renderPro();
    await fireEvent.press(await screen.findByRole('radio', { name: /Monthly/ }));
    await fireEvent.press(screen.getByRole('button', { name: 'Subscribe' }));

    await waitFor(() => expect(router.back).toHaveBeenCalled());
    expect(buy).toHaveBeenCalledWith(MONTHLY);
    expect(syncBilling).toHaveBeenCalled();
    expect(alert).toHaveBeenCalledWith('Welcome to Pro', expect.any(String));
  });

  it('does nothing when the purchase is cancelled', async () => {
    jest.mocked(buy).mockResolvedValue(false);
    await renderPro();
    await fireEvent.press(await screen.findByRole('button', { name: 'Start free trial' }));
    await act(async () => {});
    expect(syncBilling).not.toHaveBeenCalled();
    expect(router.back).not.toHaveBeenCalled();
  });

  it('says when there is nothing to restore', async () => {
    const alert = jest.spyOn(Alert, 'alert');
    await renderPro();
    await fireEvent.press(screen.getByRole('button', { name: 'Restore purchases' }));
    await waitFor(() =>
      expect(alert).toHaveBeenCalledWith('Nothing to restore', expect.any(String)),
    );
    expect(restore).toHaveBeenCalled();
    expect(router.back).not.toHaveBeenCalled();
  });

  it('offers to try again when the store has no prices', async () => {
    jest.mocked(proOptions).mockResolvedValue([]);
    await renderPro();
    expect(await screen.findByText(/Couldn’t load prices/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Subscribe' })).toBeDisabled();
  });

  it('sends a subscriber to the store to manage it', async () => {
    plan = PRO;
    await renderPro();
    expect(await screen.findByText('You’re on Pro.')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Subscribe' })).toBeNull();
  });
});
