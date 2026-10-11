import { useQueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';
import { AppState } from 'react-native';

import { useApi } from '@/api/provider';

import { syncPush } from './index';

/** While signed in: register this device for notifications at sign-in and app start (syncPush). */
export function usePushSync() {
  const api = useApi();
  const queryClient = useQueryClient();
  useEffect(() => {
    // The Account switch shows whether this device is registered.
    const sync = () =>
      void syncPush(api).then(() => queryClient.invalidateQueries({ queryKey: ['push'] }));
    sync();
    // Coming back from the phone's Settings, where notifications may just have been allowed.
    const subscription = AppState.addEventListener('change', (state) => {
      if (state === 'active') {
        sync();
      }
    });
    return () => subscription.remove();
  }, [api, queryClient]);
}
