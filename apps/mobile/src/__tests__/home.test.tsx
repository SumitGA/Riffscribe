import { render, screen } from '@testing-library/react-native';

import Home from '@/app/index';

describe('Home', () => {
  it('shows the app name and the API it talks to', async () => {
    await render(<Home />);
    expect(screen.getByText('TabScribe')).toBeTruthy();
    expect(screen.getByTestId('api-url')).toHaveTextContent(/API: http:\/\/\S+:8000/);
  });
});
