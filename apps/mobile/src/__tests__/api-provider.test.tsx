import { useAuth } from '@clerk/expo';
import { renderHook } from '@testing-library/react-native';
import type { ReactNode } from 'react';

import { ApiProvider, useApi } from '@/api/provider';

jest.mock('@clerk/expo', () => ({ useAuth: jest.fn() }));

describe('ApiProvider', () => {
  const realFetch = globalThis.fetch;
  afterEach(() => {
    globalThis.fetch = realFetch;
  });

  it("sends the Clerk session token with the app's API requests", async () => {
    jest.mocked(useAuth).mockReturnValue({
      getToken: async () => 'clerk-session-token',
    } as unknown as ReturnType<typeof useAuth>);
    const fetch = jest.fn(
      async (_request: Request) =>
        new Response(JSON.stringify({ user_id: 'u', jobs_this_month: 0, jobs_per_month: 10 }), {
          headers: { 'Content-Type': 'application/json' },
        }),
    );
    globalThis.fetch = fetch as unknown as typeof globalThis.fetch;

    const wrapper = ({ children }: { children: ReactNode }) => (
      <ApiProvider>{children}</ApiProvider>
    );
    const { result } = await renderHook(() => useApi(), { wrapper });
    await result.current.me();

    const request = fetch.mock.calls[0]?.[0];
    expect(request?.url).toMatch(/:8000\/me$/);
    expect(request?.headers.get('Authorization')).toBe('Bearer clerk-session-token');
  });

  it('fails loudly without a provider', async () => {
    jest.spyOn(console, 'error').mockImplementation(() => {});
    await expect(renderHook(() => useApi())).rejects.toThrow('needs an <ApiProvider>');
  });
});
