import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import Profile from './Profile';

// Mock the i18n and shared modules
jest.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key, opts) => {
      const translations = {
        'profile.title': 'Profile',
        'profile.loading': 'Loading…',
        'profile.notFound': 'This profile is private or does not exist.',
        'profile.ratingsCount': '{{count}} ratings',
        'profile.loadFailed': 'The reviews could not be loaded.',
        'profile.noRatings': 'No ratings yet.',
        'ui.backHome': 'Back home',
        'ui.retry': 'Retry',
        'ui.starLabel': '{{count}} stars',
      };
      let val = translations[key] || key;
      if (opts && opts.count !== undefined) val = val.replace('{{count}}', opts.count);
      return val;
    }
  })
}));

jest.mock('./shared', () => ({
  API: 'http://localhost:8000',
  formatRelativeDate: () => '3 days ago',
  thumbSrc: (url) => url,
  thumbErrorHandler: () => () => {},
}));

describe('Profile', () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    global.fetch = jest.fn();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  // The component fetches the profile first, then the ratings list.
  const mockProfileFetch = (profile, ratings) => {
    global.fetch.mockImplementation((url) => {
      if (url.includes('/ratings?')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(ratings) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve(profile) });
    });
  };

  test('renders the display name as the title and the rating count', async () => {
    mockProfileFetch(
      { username: 'alice', display_name: 'Alice Wonder', rating_count: 2, created_at: null },
      [
        { id: 1, meal_name: 'Curry', mensa: 'Zentralmensa', rating: 5, comment: 'Great', photo_url: null, created_at: '2026-09-01T12:00:00' },
        { id: 2, meal_name: 'Pasta', mensa: 'CGiN', rating: 4, comment: null, photo_url: null, created_at: '2026-09-02T12:00:00' },
      ]
    );

    render(<Profile username="alice" onBack={jest.fn()} language="de" />);

    await waitFor(() => {
      expect(screen.getByText('Alice Wonder')).toBeInTheDocument();
      expect(screen.getByText('2 ratings')).toBeInTheDocument();
    });
  });

  test('falls back to the username when no display name is set', async () => {
    mockProfileFetch(
      { username: 'bob', display_name: null, rating_count: 1, created_at: null },
      [{ id: 1, meal_name: 'Soup', mensa: 'Zentralmensa', rating: 3, comment: null, photo_url: null, created_at: '2026-09-01T12:00:00' }]
    );

    render(<Profile username="bob" onBack={jest.fn()} language="de" />);

    await waitFor(() => {
      expect(screen.getByText('bob')).toBeInTheDocument();
    });
  });

  test('renders each rating with its comment', async () => {
    mockProfileFetch(
      { username: 'alice', display_name: null, rating_count: 1, created_at: null },
      [{ id: 1, meal_name: 'Curry', mensa: 'Zentralmensa', rating: 5, comment: 'Absolutely superb', photo_url: null, created_at: '2026-09-01T12:00:00' }]
    );

    render(<Profile username="alice" onBack={jest.fn()} language="de" />);

    await waitFor(() => {
      expect(screen.getByText('Curry')).toBeInTheDocument();
      // The mensa and the relative date share one element, so match by substring.
      expect(screen.getByText(/Zentralmensa/)).toBeInTheDocument();
      expect(screen.getByText('Absolutely superb')).toBeInTheDocument();
    });
  });

  test('shows the not-found message for a private or missing profile (404)', async () => {
    global.fetch.mockResolvedValue({ ok: false, status: 404 });

    render(<Profile username="ghost" onBack={jest.fn()} language="de" />);

    await waitFor(() => {
      expect(screen.getByText('This profile is private or does not exist.')).toBeInTheDocument();
    });
  });

  test('shows the load-failed message for a non-404 error', async () => {
    global.fetch.mockResolvedValue({ ok: false, status: 500 });

    render(<Profile username="alice" onBack={jest.fn()} language="de" />);

    await waitFor(() => {
      expect(screen.getByText('The reviews could not be loaded.')).toBeInTheDocument();
    });
  });

  test('shows the no-ratings message when the profile has none', async () => {
    mockProfileFetch(
      { username: 'carol', display_name: null, rating_count: 0, created_at: null },
      []
    );

    render(<Profile username="carol" onBack={jest.fn()} language="de" />);

    await waitFor(() => {
      expect(screen.getByText('No ratings yet.')).toBeInTheDocument();
    });
  });

  test('calls onBack when the back button is clicked', async () => {
    const onBack = jest.fn();
    mockProfileFetch(
      { username: 'alice', display_name: null, rating_count: 0, created_at: null },
      []
    );

    render(<Profile username="alice" onBack={onBack} language="de" />);

    const backBtn = await screen.findByText('Back home');
    fireEvent.click(backBtn);
    expect(onBack).toHaveBeenCalled();
  });

  test('shows the loading state before the fetch resolves', async () => {
    global.fetch.mockImplementation(() => new Promise(() => {})); // never resolves

    render(<Profile username="alice" onBack={jest.fn()} language="de" />);

    expect(screen.getByText('Loading…')).toBeInTheDocument();
  });
});
