import { fireEvent, render, screen } from '@testing-library/react-native';
import { router } from 'expo-router';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import Welcome from '@/app/welcome';
import { markWelcomeSeen } from '@/welcome/seen';

jest.mock('expo-router', () => ({
  router: { back: jest.fn(), replace: jest.fn(), canGoBack: jest.fn(() => true) },
}));
jest.mock('@/welcome/seen', () => ({ markWelcomeSeen: jest.fn() }));

beforeEach(() => jest.clearAllMocks());

const metrics = {
  frame: { x: 0, y: 0, width: 390, height: 844 },
  insets: { top: 47, left: 0, right: 0, bottom: 34 },
};
const renderWelcome = () =>
  render(
    <SafeAreaProvider initialMetrics={metrics}>
      <Welcome />
    </SafeAreaProvider>,
  );

describe('Welcome guide', () => {
  it('walks through the three pages, then remembers it was shown and closes', async () => {
    await renderWelcome();
    expect(screen.getByText('Record or upload')).toBeTruthy();
    expect(screen.getByText('Get tab and sheet music')).toBeTruthy();
    expect(screen.getByText('Play, fix and export')).toBeTruthy();
    expect(screen.getByLabelText('Page 1 of 3')).toBeTruthy();

    await fireEvent.press(screen.getByRole('button', { name: 'Next' }));
    await fireEvent.press(screen.getByRole('button', { name: 'Next' }));
    expect(screen.getByLabelText('Page 3 of 3')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Skip' })).toBeNull(); // nothing left to skip
    expect(markWelcomeSeen).not.toHaveBeenCalled();

    await fireEvent.press(screen.getByRole('button', { name: 'Get started' }));
    expect(markWelcomeSeen).toHaveBeenCalled();
    expect(router.back).toHaveBeenCalled();
  });

  it('can be skipped from the first page', async () => {
    await renderWelcome();
    await fireEvent.press(screen.getByRole('button', { name: 'Skip' }));
    expect(markWelcomeSeen).toHaveBeenCalled();
    expect(router.back).toHaveBeenCalled();
  });

  it('goes to the library when there is nothing to go back to', async () => {
    jest.mocked(router.canGoBack).mockReturnValueOnce(false);
    await renderWelcome();
    await fireEvent.press(screen.getByRole('button', { name: 'Skip' }));
    expect(router.replace).toHaveBeenCalledWith('/');
  });
});
