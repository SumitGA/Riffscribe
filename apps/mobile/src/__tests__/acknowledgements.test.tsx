import { fireEvent, render, screen } from '@testing-library/react-native';

import { assets, packages, texts } from '@/about/licenses';
import Acknowledgements from '@/app/acknowledgements';

describe('Acknowledgements', () => {
  it('lists the bundled sounds and fonts and every package with a licence text', () => {
    expect(assets.map((a) => a.name).join()).toMatch(/MuseScore_General.*Bravura.*Sonivox/);
    expect(packages.find((p) => p.name === '@coderline/alphatab')?.license).toBe('MPL-2.0');
    expect(packages.filter((p) => p.text === null).length).toBeLessThan(3);
  });

  it('shows an entry’s licence when tapped', async () => {
    await render(<Acknowledgements />);
    const font = assets[0]!;
    await fireEvent.press(screen.getByText(font.name));
    expect(screen.getByText(font.copyright[0]!)).toBeTruthy();
    expect(screen.getByText(texts[font.text!]!)).toBeTruthy();
  });
});
