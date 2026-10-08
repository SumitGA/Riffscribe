import { useQueryClient } from '@tanstack/react-query';
import { router } from 'expo-router';
import * as Notifications from 'expo-notifications';
import { useEffect } from 'react';

import { jobIdOf } from './index';

// Notifications that arrive while the app is open still show as a banner.
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
});

/**
 * While signed in: tapping a "score ready" notification opens that job (also when it launched
 * the app), and any job notification refreshes the Library and that job.
 */
export function usePushResponses() {
  const queryClient = useQueryClient();
  const launchedBy = Notifications.useLastNotificationResponse();

  useEffect(() => {
    const open = (jobId: string | undefined) => {
      if (jobId) {
        router.push({ pathname: '/jobs/[id]', params: { id: jobId } });
      }
    };
    open(jobIdOf(launchedBy));

    const tapped = Notifications.addNotificationResponseReceivedListener((response) =>
      open(jobIdOf(response)),
    );
    const received = Notifications.addNotificationReceivedListener(() => {
      void queryClient.invalidateQueries({ queryKey: ['jobs'] });
      void queryClient.invalidateQueries({ queryKey: ['job'] });
    });
    return () => {
      tapped.remove();
      received.remove();
    };
  }, [launchedBy, queryClient]);
}
