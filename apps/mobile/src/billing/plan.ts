import type { Me } from '@/api/client';

import { STORE_NAME } from './index';

/**
 * What Pro gives, for the paywall. It matches the server's Pro limits (ADR-0016) and the store
 * listings; a change to those is a change here too.
 */
export const PRO_BENEFITS = [
  { title: '100 transcriptions a month', detail: 'Free has 10.' },
  { title: 'Recordings up to 15 minutes', detail: 'Free stops at 5 minutes.' },
  { title: 'Faster queue', detail: 'Your songs go ahead of free ones.' },
] as const;

export const FREE_MAX_CLIP_S = 300;

export function planName(me: Me | undefined): string {
  switch (me?.plan) {
    case 'pro':
      return 'Pro';
    case 'unlimited':
      return 'Unlimited plan';
    default:
      return 'Free plan';
  }
}

/** The longest recording the user's plan allows, in seconds. */
export function maxClipSeconds(me: Me | undefined): number {
  return me?.limits?.max_clip_s ?? FREE_MAX_CLIP_S;
}

/** "5 min" or "15 min". */
export function minutes(seconds: number): string {
  return `${Math.round(seconds / 60)} min`;
}

/** No monthly limit (unlimited): nothing to count against. */
export function hasMonthlyLimit(me: Me | undefined): boolean {
  return me?.limits ? me.limits.jobs_per_month !== null : me?.plan !== 'unlimited';
}

export function monthlyLimit(me: Me): number {
  return me.limits?.jobs_per_month ?? me.jobs_per_month;
}

const DATE = new Intl.DateTimeFormat('en-AU', { day: 'numeric', month: 'short', year: 'numeric' });

/** One line about the user's subscription for the Account screen, or null if there's none. */
export function subscriptionLine(me: Me | undefined): string | null {
  const sub = me?.subscription;
  if (!sub) {
    return null;
  }
  const date = sub.expires_at ? DATE.format(new Date(sub.expires_at)) : null;
  if (sub.refunded) {
    return 'Refunded';
  }
  if (sub.active && sub.billing_issue) {
    return `Payment problem: update your payment method in ${STORE_NAME} to keep Pro.`;
  }
  if (!sub.active) {
    return date ? `Pro ended on ${date}` : 'Pro ended';
  }
  if (!date) {
    return null;
  }
  if (sub.in_trial) {
    return sub.will_renew ? `Free trial · Pro starts on ${date}` : `Free trial ends on ${date}`;
  }
  return sub.will_renew ? `Renews on ${date}` : `Ends on ${date}`;
}
