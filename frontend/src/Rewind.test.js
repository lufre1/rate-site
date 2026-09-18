import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import Rewind from './Rewind';

// Mock the i18n and shared modules
jest.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key) => {
      const translations = {
        'rewind.title': 'Rewind',
        'rewind.week': 'This week',
        'rewind.month': 'This month',
        'rewind.community': 'Community',
        'rewind.personal': 'Your week',
        'rewind.notEnough': 'Not enough ratings for a rewind yet.',
        'rewind.yourDishes': 'Your dishes',
        'rewind.topDishes': 'Top dishes',
        'rewind.ratedCount': 'You rated {{n}} dishes',
        'rewind.servedCount': '{{n}} dishes rated',
        'rewind.loading': 'Loading…',
        'rewind.error': 'Could not load the rewind.',
        'ui.backHome': 'Back home',
        'stats.ratings': '{{count}} ratings',
      };
      return translations[key] || key;
    }
  })
}));

jest.mock('./shared', () => {
  const React = require('react');
  return {
    API: 'http://localhost:8000',
    authHeaders: () => ({ 'Authorization': 'Bearer test-token' }),
    thumbSrc: (url) => url,
    thumbErrorHandler: () => () => {},
    Lightbox: ({ src, alt, onClose }) =>
      React.createElement('div', { className: 'lightbox', role: 'dialog', 'aria-modal': 'true', 'aria-label': alt },
        React.createElement('button', { type: 'button', className: 'lightbox__close', 'aria-label': 'close', onClick: onClose }, '×'),
        React.createElement('img', { className: 'lightbox__img', src, alt })
      )
  };
});

describe('Rewind', () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    global.fetch = jest.fn();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  test('renders rewind title', async () => {
    global.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        period: 'week',
        scope: 'community',
        enough: true,
        total_ratings: 100,
        dishes_rated: 10,
        dishes: []
      })
    });

    render(<Rewind onBack={jest.fn()} language="de" user={null} />);

    await waitFor(() => {
      expect(screen.getByText('Rewind')).toBeInTheDocument();
    });
  });

  test('renders period toggle buttons', async () => {
    global.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        period: 'week',
        scope: 'community',
        enough: true,
        total_ratings: 100,
        dishes_rated: 10,
        dishes: []
      })
    });

    render(<Rewind onBack={jest.fn()} language="de" user={null} />);

    await waitFor(() => {
      expect(screen.getByText('This week')).toBeInTheDocument();
      expect(screen.getByText('This month')).toBeInTheDocument();
    });
  });

  test('renders community dishes when enough data', async () => {
    global.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        period: 'week',
        scope: 'community',
        enough: true,
        total_ratings: 100,
        dishes_rated: 10,
        dishes: [
          {
            id: 1,
            name: 'Test Dish',
            mensa: 'Zentralmensa',
            avg_rating: 4.5,
            rating_count: 20,
            photo_url: '/uploads/test.jpg',
            comments: [{ text: 'Great food!', author: 'user1' }]
          }
        ]
      })
    });

    render(<Rewind onBack={jest.fn()} language="de" user={null} />);

    await waitFor(() => {
      expect(screen.getByText('Test Dish')).toBeInTheDocument();
      expect(screen.getByText('Zentralmensa')).toBeInTheDocument();
      expect(screen.getByText(/4\.5/)).toBeInTheDocument();
      expect(screen.getByText('Great food! — user1')).toBeInTheDocument();
    });
  });

  test('shows not enough state for community', async () => {
    global.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        period: 'week',
        scope: 'community',
        enough: false,
        total_ratings: 2,
        dishes_rated: 2,
        dishes: []
      })
    });

    render(<Rewind onBack={jest.fn()} language="de" user={null} />);

    await waitFor(() => {
      expect(screen.getByText('Not enough ratings for a rewind yet.')).toBeInTheDocument();
    });
  });

  test('renders personal section when user is provided', async () => {
    let fetchCallCount = 0;
    global.fetch.mockImplementation((url) => {
      fetchCallCount++;
      if (url.includes('scope=me')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            period: 'week',
            scope: 'me',
            enough: true,
            dishes_rated: 5,
            photos: 2,
            dishes: [
              {
                id: 1,
                name: 'My Dish',
                mensa: 'CGiN',
                rating: 5,
                comment: 'Amazing!',
                photo_url: '/uploads/myphoto.jpg'
              }
            ]
          })
        });
      }
      // Community fetch
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          period: 'week',
          scope: 'community',
          enough: true,
          total_ratings: 100,
          dishes_rated: 10,
          dishes: []
        })
      });
    });

    render(<Rewind onBack={jest.fn()} language="de" user={{ username: 'testuser' }} />);

    await waitFor(() => {
      expect(screen.getByText('Your week')).toBeInTheDocument();
      expect(screen.getByText('My Dish')).toBeInTheDocument();
      expect(screen.getByText('Amazing!')).toBeInTheDocument();
    });
  });

  test('does not render personal section when user is not provided', async () => {
    global.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        period: 'week',
        scope: 'community',
        enough: true,
        total_ratings: 100,
        dishes_rated: 10,
        dishes: []
      })
    });

    render(<Rewind onBack={jest.fn()} language="de" user={null} />);

    await waitFor(() => {
      expect(screen.queryByText('Your week')).not.toBeInTheDocument();
    });
  });

  test('calls onBack when back button is clicked', async () => {
    const onBack = jest.fn();

    global.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        period: 'week',
        scope: 'community',
        enough: true,
        total_ratings: 100,
        dishes_rated: 10,
        dishes: []
      })
    });

    render(<Rewind onBack={onBack} language="de" user={null} />);

    await waitFor(() => {
      expect(screen.getByText('Back home')).toBeInTheDocument();
    });

    const backBtn = await screen.findByText('Back home');
    fireEvent.click(backBtn);

    expect(onBack).toHaveBeenCalled();
  });

  test('fetches with period=month when month button is clicked', async () => {
    let fetchCount = 0;
    global.fetch.mockImplementation((url) => {
      fetchCount++;
      if (fetchCount === 1) {
        // Initial fetch with week
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            period: 'week',
            scope: 'community',
            enough: true,
            total_ratings: 100,
            dishes_rated: 10,
            dishes: []
          })
        });
      }
      // Month fetch
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          period: 'month',
          scope: 'community',
          enough: true,
          total_ratings: 500,
          dishes_rated: 50,
          dishes: []
        })
      });
    });

    render(<Rewind onBack={jest.fn()} language="de" user={null} />);

    // Wait for the toggle buttons to be rendered (initial waitFor on 'Rewind' passes immediately while loading)
    await waitFor(() => {
      expect(screen.getByText('This week')).toBeInTheDocument();
      expect(screen.getByText('This month')).toBeInTheDocument();
    });

    // Click month button
    const monthBtn = screen.getByText('This month');
    fireEvent.click(monthBtn);

    // Wait for the month fetch to be called
    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith('http://localhost:8000/api/v1/rewind?period=month&scope=community&lang=de');
    });
  });

  test('shows loading state', async () => {
    global.fetch.mockResolvedValue({
      ok: true,
      json: () => new Promise(resolve => {
        setTimeout(() => resolve({
          period: 'week',
          scope: 'community',
          enough: true,
          total_ratings: 100,
          dishes_rated: 10,
          dishes: []
        }), 100);
      })
    });

    render(<Rewind onBack={jest.fn()} language="de" user={null} />);

    expect(screen.getByText('Loading…')).toBeInTheDocument();
  });

  test('shows error state on fetch failure', async () => {
    global.fetch.mockResolvedValue({
      ok: false,
      status: 500
    });

    render(<Rewind onBack={jest.fn()} language="de" user={null} />);

    await waitFor(() => {
      expect(screen.getByText(/Could not load the rewind\./)).toBeInTheDocument();
    });
  });

  test('opens the lightbox when a dish photo is clicked', async () => {
    global.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        period: 'week',
        scope: 'community',
        enough: true,
        total_ratings: 100,
        dishes_rated: 10,
        dishes: [
          {
            id: 1,
            name: 'Test Dish',
            mensa: 'Zentralmensa',
            avg_rating: 4.5,
            rating_count: 20,
            photo_url: '/uploads/test.jpg',
            comments: []
          }
        ]
      })
    });

    const { container } = render(<Rewind onBack={jest.fn()} language="de" user={null} />);

    await waitFor(() => {
      expect(screen.getByText('Test Dish')).toBeInTheDocument();
    });

    const photoBtn = container.querySelector('.rewind-card__photo-btn');
    fireEvent.click(photoBtn);

    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeInTheDocument();
    });
    expect(screen.getByRole('dialog').querySelector('img').src)
      .toBe('http://localhost:8000/uploads/test.jpg');
  });
});