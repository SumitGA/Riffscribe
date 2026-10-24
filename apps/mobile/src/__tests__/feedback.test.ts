import { FEEDBACK_EMAIL, feedbackMailto } from '@/feedback';

describe('feedbackMailto', () => {
  it('addresses the support email with the app version and phone filled in', () => {
    const url = feedbackMailto({ version: '1.0.0', os: 'iOS 27.1', model: 'iPhone 15 Pro Max' });
    expect(url.startsWith(`mailto:${FEEDBACK_EMAIL}?`)).toBe(true);
    const params = new URLSearchParams(url.split('?')[1]);
    expect(params.get('subject')).toBe('Riffscribe feedback');
    expect(params.get('body')).toContain('App version: 1.0.0');
    expect(params.get('body')).toContain('Phone: iPhone 15 Pro Max (iOS 27.1)');
    expect(url).not.toContain(' '); // every part is encoded
  });
});
