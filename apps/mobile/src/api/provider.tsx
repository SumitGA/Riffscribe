import { useAuth } from '@clerk/expo';
import { createContext, useContext, useMemo, type ReactNode } from 'react';

import { apiUrl } from '@/config';

import { createApi, type Api } from './client';

const ApiContext = createContext<Api | null>(null);

/** Provides an API client that sends the signed-in user's Clerk session token. */
export function ApiProvider({ children }: { children: ReactNode }) {
  const { getToken } = useAuth();
  // Clerk's tokens live about a minute; getToken() returns a cached one or refreshes it.
  const api = useMemo(
    () => createApi({ baseUrl: apiUrl(), getToken: () => getToken() }),
    [getToken],
  );
  return <ApiContext.Provider value={api}>{children}</ApiContext.Provider>;
}

export function useApi(): Api {
  const api = useContext(ApiContext);
  if (!api) {
    throw new Error('useApi() needs an <ApiProvider> above it');
  }
  return api;
}
