// Jest's stand-in for RevenueCat's native SDK (node_modules mocks live next to node_modules).
// Tests set what the store returns with jest.mocked(Purchases.getOfferings) and friends.
export const PACKAGE_TYPE = { MONTHLY: 'MONTHLY', ANNUAL: 'ANNUAL', WEEKLY: 'WEEKLY' } as const;

const Purchases = {
  configure: jest.fn(),
  logIn: jest.fn(async () => ({ customerInfo: {}, created: false })),
  logOut: jest.fn(async () => ({})),
  getOfferings: jest.fn(async () => ({ current: null, all: {} })),
  purchasePackage: jest.fn(async () => ({ customerInfo: {} })),
  restorePurchases: jest.fn(async () => ({})),
};

export default Purchases;
