import type PurchasesType from 'react-native-purchases';

jest.mock('@/config', () => ({ revenueCatKey: () => 'appl_test' }));

// The module keeps the current user, so each test loads a fresh copy (with its own SDK mock).
let Purchases: typeof PurchasesType;
function load(): typeof import('@/billing') {
  let billing: typeof import('@/billing') | undefined;
  jest.isolateModules(() => {
    billing = jest.requireActual<typeof import('@/billing')>('@/billing');
    // The same registry as the copy of @/billing just loaded, so the same mock instance.
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    Purchases = (require('react-native-purchases') as { default: typeof PurchasesType }).default;
  });
  return billing!;
}

describe('billing', () => {
  it('configures RevenueCat as the signed-in user', async () => {
    const billing = load();
    jest.mocked(Purchases.isConfigured).mockResolvedValue(false);
    await billing.startBilling('user_1');
    expect(Purchases.configure).toHaveBeenCalledWith({ apiKey: 'appl_test', appUserID: 'user_1' });
  });

  it('logs in before buying when the SDK is anonymous (e.g. after a reload)', async () => {
    const billing = load();
    jest.mocked(Purchases.isConfigured).mockResolvedValue(true);
    jest.mocked(Purchases.getAppUserID).mockResolvedValue('$RCAnonymousID:abc');
    await billing.startBilling('user_1');
    jest.mocked(Purchases.logIn).mockClear();

    await billing.buy({ pkg: {} } as never);
    expect(Purchases.logIn).toHaveBeenCalledWith('user_1');
    expect(jest.mocked(Purchases.logIn).mock.invocationCallOrder[0]).toBeLessThan(
      jest.mocked(Purchases.purchasePackage).mock.invocationCallOrder[0]!,
    );
  });

  it("doesn't log in again when RevenueCat already has the user", async () => {
    const billing = load();
    jest.mocked(Purchases.isConfigured).mockResolvedValue(true);
    jest.mocked(Purchases.getAppUserID).mockResolvedValue('user_1');
    await billing.startBilling('user_1');
    await billing.restore();
    expect(Purchases.logIn).not.toHaveBeenCalled();
    expect(Purchases.restorePurchases).toHaveBeenCalled();
  });

  it('treats a cancelled purchase as no purchase', async () => {
    const billing = load();
    jest.mocked(Purchases.purchasePackage).mockRejectedValueOnce({ userCancelled: true });
    expect(await billing.buy({ pkg: {} } as never)).toBe(false);
  });

  it('logs out on sign-out', async () => {
    const billing = load();
    jest.mocked(Purchases.isConfigured).mockResolvedValue(true);
    jest.mocked(Purchases.getAppUserID).mockResolvedValue('user_1');
    await billing.startBilling('user_1');
    await billing.stopBilling();
    expect(Purchases.logOut).toHaveBeenCalled();
  });
});
