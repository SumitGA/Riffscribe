import type { Me, Subscription } from '@/api/client';
import {
  hasMonthlyLimit,
  maxClipSeconds,
  monthlyLimit,
  planName,
  subscriptionLine,
} from '@/billing/plan';

const FREE: Me = {
  user_id: 'u',
  plan: 'free',
  plan_source: 'default',
  limits: { jobs_per_month: 10, max_clip_s: 300, max_upload_bytes: 1, priority: false },
  jobs_this_month: 0,
  jobs_per_month: 10,
  terms_version: 'v',
  terms_accepted: true,
};

const SUB: Subscription = {
  store: 'app_store',
  product_id: 'pro_monthly',
  active: true,
  in_trial: false,
  expires_at: '2026-12-07T10:00:00Z',
  will_renew: true,
  billing_issue: false,
  refunded: false,
};

const pro = (sub: Partial<Subscription>): Me => ({
  ...FREE,
  plan: 'pro',
  plan_source: 'store',
  limits: { jobs_per_month: 100, max_clip_s: 900, max_upload_bytes: 1, priority: true },
  jobs_per_month: 100,
  subscription: { ...SUB, ...sub },
});

describe('plan', () => {
  it('names the plan and its limits', () => {
    expect(planName(FREE)).toBe('Free plan');
    expect(planName(pro({}))).toBe('Pro');
    expect(maxClipSeconds(pro({}))).toBe(900);
    expect(monthlyLimit(pro({}))).toBe(100);
    const unlimited = {
      ...FREE,
      plan: 'unlimited' as const,
      limits: { ...FREE.limits, jobs_per_month: null },
    };
    expect(planName(unlimited)).toBe('Unlimited plan');
    expect(hasMonthlyLimit(unlimited)).toBe(false);
    expect(maxClipSeconds(undefined)).toBe(300);
  });

  it('describes the subscription', () => {
    expect(subscriptionLine(FREE)).toBeNull();
    expect(subscriptionLine(pro({}))).toBe('Renews on 7 Dec 2026');
    expect(subscriptionLine(pro({ will_renew: false }))).toBe('Ends on 7 Dec 2026');
    expect(subscriptionLine(pro({ in_trial: true }))).toBe('Free trial · Pro starts on 7 Dec 2026');
    expect(subscriptionLine(pro({ billing_issue: true }))).toMatch(/^Payment problem/);
    expect(subscriptionLine(pro({ active: false, will_renew: false }))).toBe(
      'Pro ended on 7 Dec 2026',
    );
    expect(subscriptionLine(pro({ active: false, refunded: true }))).toBe('Refunded');
  });
});
