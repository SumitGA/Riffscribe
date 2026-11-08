import { Linking, Platform } from 'react-native';
import Purchases, {
  PACKAGE_TYPE,
  type PurchasesError,
  type PurchasesPackage,
} from 'react-native-purchases';

import { revenueCatKey } from '@/config';

/**
 * Store subscriptions through RevenueCat (ADR-0016). The app only buys and restores; what the
 * user owns is decided on the server (`GET /me`), which the app asks to re-check after each
 * purchase (`POST /me/billing/sync`). Purchases follow the account: RevenueCat's user ID is the
 * Clerk user ID.
 */

/** A Pro option the store offers, with its price as the store formats it. */
export type ProOption = {
  id: string;
  period: 'month' | 'year';
  price: string; // e.g. "A$4.99"
  perMonth: string | null; // the yearly price per month, e.g. "A$3.33"
  trial: string | null; // e.g. "1 week free", when the store offers a free trial
  pkg: PurchasesPackage;
};

let configuredFor: string | null | undefined; // undefined: not configured yet

/** Whether this build can sell Pro (it has RevenueCat's key for this platform). */
export function billingAvailable(): boolean {
  return revenueCatKey() !== null;
}

/** Connect RevenueCat to the signed-in user. Safe to call on every render of the session. */
export async function startBilling(userId: string): Promise<void> {
  const apiKey = revenueCatKey();
  if (!apiKey || configuredFor === userId) {
    return;
  }
  if (configuredFor === undefined) {
    Purchases.configure({ apiKey, appUserID: userId });
  } else {
    await Purchases.logIn(userId);
  }
  configuredFor = userId;
}

/** Disconnect the user (sign-out, account deletion): the next user starts clean. */
export async function stopBilling(): Promise<void> {
  if (!configuredFor) {
    return;
  }
  configuredFor = null;
  try {
    await Purchases.logOut();
  } catch {
    // Already anonymous: nothing to do.
  }
}

function trialText(pkg: PurchasesPackage): string | null {
  const intro = pkg.product.introPrice;
  if (!intro || intro.price !== 0) {
    return null;
  }
  const unit = intro.periodUnit.toLowerCase();
  const n = intro.periodNumberOfUnits;
  return `${n} ${unit}${n === 1 ? '' : 's'} free`;
}

/** The current offering's monthly and yearly options; empty if the store has none. */
export async function proOptions(): Promise<ProOption[]> {
  const offering = (await Purchases.getOfferings()).current;
  const options: ProOption[] = [];
  for (const pkg of offering?.availablePackages ?? []) {
    const period =
      pkg.packageType === PACKAGE_TYPE.MONTHLY
        ? 'month'
        : pkg.packageType === PACKAGE_TYPE.ANNUAL
          ? 'year'
          : null;
    if (!period) {
      continue;
    }
    options.push({
      id: pkg.identifier,
      period,
      price: pkg.product.priceString,
      perMonth: period === 'year' ? pkg.product.pricePerMonthString : null,
      trial: trialText(pkg),
      pkg,
    });
  }
  return options.sort((a, b) => (a.period === b.period ? 0 : a.period === 'month' ? -1 : 1));
}

function cancelled(error: unknown): boolean {
  return !!(error as Partial<PurchasesError> | null)?.userCancelled;
}

/** Buy an option in the store's own sheet. False if the user cancelled it. */
export async function buy(option: ProOption): Promise<boolean> {
  try {
    await Purchases.purchasePackage(option.pkg);
    return true;
  } catch (error) {
    if (cancelled(error)) {
      return false;
    }
    throw error;
  }
}

/** Restore Purchases: re-attach the store account's subscriptions to this user. */
export async function restore(): Promise<void> {
  await Purchases.restorePurchases();
}

/** The store's own subscription settings, where the user changes or cancels. */
export const MANAGE_URL =
  Platform.OS === 'ios'
    ? 'https://apps.apple.com/account/subscriptions'
    : 'https://play.google.com/store/account/subscriptions?package=com.sumitga.riffscribe';

export function manageSubscription(): Promise<void> {
  return Linking.openURL(MANAGE_URL);
}

/** The store's name, for the wording users see. */
export const STORE_NAME = Platform.OS === 'ios' ? 'the App Store' : 'Google Play';
export const STORE_ACCOUNT = Platform.OS === 'ios' ? 'Apple Account' : 'Google Play account';
