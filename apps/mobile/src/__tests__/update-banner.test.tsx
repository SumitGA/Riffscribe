import { fireEvent, render, screen } from '@testing-library/react-native';
import * as Updates from 'expo-updates';

import { UpdateBanner } from '@/updates/UpdateBanner';

jest.mock('expo-updates', () => ({
  isEnabled: true,
  useUpdates: jest.fn(),
  checkForUpdateAsync: jest.fn(() => Promise.resolve({ isAvailable: false })),
  fetchUpdateAsync: jest.fn(() => Promise.resolve({ isNew: true })),
  reloadAsync: jest.fn(() => Promise.resolve()),
}));
jest.mock('react-native-safe-area-context', () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));

const state = (s: { isUpdateAvailable?: boolean; isUpdatePending?: boolean }) =>
  jest.mocked(Updates.useUpdates).mockReturnValue({
    isUpdateAvailable: false,
    isUpdatePending: false,
    ...s,
  } as ReturnType<typeof Updates.useUpdates>);

beforeEach(() => jest.clearAllMocks());

describe('UpdateBanner', () => {
  it('checks on start and downloads an available update quietly', async () => {
    state({ isUpdateAvailable: true });
    await render(<UpdateBanner />);

    expect(Updates.checkForUpdateAsync).toHaveBeenCalled();
    expect(Updates.fetchUpdateAsync).toHaveBeenCalled();
    expect(screen.queryByText('A new version is ready')).toBeNull();
  });

  it('offers a one-tap restart once the update is downloaded', async () => {
    state({ isUpdateAvailable: true, isUpdatePending: true });
    await render(<UpdateBanner />);

    await fireEvent.press(screen.getByText('Restart'));
    expect(Updates.reloadAsync).toHaveBeenCalled();
  });
});
