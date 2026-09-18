import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import Leaderboard from './Leaderboard';

// Mock the i18n and shared modules
jest.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key) => {
      const translations = {
        'leaderboard.title': 'Leaderboard',
        'leaderboard.myPosition': 'Your Position',
        'leaderboard.points': 'points',
        'leaderboard.error': 'Error:',
        'leaderboard.loading': 'Loading...',
        'leaderboard.loadMore': 'Load more',
        'ui.retry': 'Try again',
        'ui.backHome': 'Back home',
        'leaderboard.badges.platinum': 'Platinum',
        'leaderboard.badges.gold': 'Gold',
        'leaderboard.badges.silver': 'Silver',
        'leaderboard.badges.bronze': 'Bronze',
        'leaderboard.tier.platinum': 'Platinum Tier',
        'leaderboard.tier.gold': 'Gold Tier',
        'leaderboard.tier.silver': 'Silver Tier',
        'leaderboard.tier.bronze': 'Bronze Tier',
        'leaderboard.columns.rank': 'Rank',
        'leaderboard.columns.name': 'Name',
        'leaderboard.columns.tokens': 'Tokens',
        'leaderboard.columns.tokens30d': 'Tokens (30d)',
        'leaderboard.columns.rank30d': 'Rank (30d)',
        'leaderboard.you': 'You',
        'leaderboard.scoring.title': 'How the leaderboard works',
        'leaderboard.scoring.baseTitle': 'Base points',
        'leaderboard.scoring.base': 'Each rating with a comment or photo earns 1 point.',
        'leaderboard.scoring.rewardsTitle': 'Bonus rewards',
        'leaderboard.scoring.rewardFirstPhoto': '+20 points: first photo of a dish.',
        'leaderboard.scoring.rewardBestPhoto': '+50 points: best photo for a dish.',
        'leaderboard.scoring.rewardBestComment': '+50 points: best comment for a dish.',
        'leaderboard.scoring.rewardContinuity': '+30 points: 15 dishes in a month.',
        'leaderboard.scoring.badgesTitle': 'Badges by rank',
        'leaderboard.scoring.badgePlatinum': 'Platinum: top 10% of raters',
        'leaderboard.scoring.badgeGold': 'Gold: top 25% of raters',
        'leaderboard.scoring.badgeSilver': 'Silver: top 50% of raters',
        'leaderboard.scoring.badgeBronze': 'Bronze: everyone else',
        'leaderboard.scoring.climbTitle': 'How to climb',
        'leaderboard.scoring.climb': 'Rate dishes regularly to climb the leaderboard.',
        'leaderboard.scoring.anonymousTitle': 'Anonymous ratings',
        'leaderboard.scoring.anonymous': 'Anonymous ratings don\'t count for the leaderboard.',
      };
      return translations[key] || key;
    }
  })
}));

jest.mock('./shared', () => ({
  API: 'http://localhost:8000',
  authHeaders: () => ({ 'Authorization': 'Bearer test-token' }),
  getToken: () => 'test-token'
}));

describe('Leaderboard', () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    global.fetch = jest.fn();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  test('renders leaderboard title', async () => {
    global.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        users: [],
        total: 0,
        date: new Date().toISOString()
      })
    });

    render(<Leaderboard onBack={jest.fn()} language="de" />);

    expect(screen.getByText('Leaderboard')).toBeInTheDocument();
  });

  test('shows loading state', async () => {
    global.fetch.mockResolvedValue({
      ok: true,
      json: () => new Promise(resolve => {
        setTimeout(() => resolve({
          users: [],
          total: 0,
          date: new Date().toISOString()
        }), 100);
      })
    });

    render(<Leaderboard onBack={jest.fn()} language="de" />);

    expect(screen.getByText('Loading...')).toBeInTheDocument();
  });

  test('displays leaderboard entries', async () => {
    const mockUsers = [
      {
        user_id: 1,
        username: 'topuser',
        score: 100,
        rank: 1,
        badge: 'platinum'
      },
      {
        user_id: 2,
        username: 'seconduser',
        score: 80,
        rank: 2,
        badge: 'gold'
      }
    ];

    global.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        users: mockUsers,
        total: 2,
        date: new Date().toISOString()
      })
    });

    render(<Leaderboard onBack={jest.fn()} language="de" />);

    await waitFor(() => {
      expect(screen.getByText('topuser')).toBeInTheDocument();
      expect(screen.getByText('seconduser')).toBeInTheDocument();
      expect(screen.getByText('100')).toBeInTheDocument();
      expect(screen.getByText('80')).toBeInTheDocument();
    });
  });

  test('displays badge colors', async () => {
    const mockUsers = [
      {
        user_id: 1,
        username: 'platinumuser',
        score: 100,
        rank: 1,
        badge: 'platinum'
      }
    ];

    const mockMyPosition = {
      user_id: 1,
      username: 'platinumuser',
      score: 100,
      rank: 1,
      badge: 'platinum'
    };

    let fetchCount = 0;
    global.fetch.mockImplementation((url) => {
      fetchCount++;
      if (url.includes('/leaderboard/me')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockMyPosition)
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          users: mockUsers,
          total: 1,
          date: new Date().toISOString()
        })
      });
    });

    render(<Leaderboard onBack={jest.fn()} language="de" />);

    await waitFor(() => {
      const badge = screen.getByText('Platinum');
      expect(badge).toBeInTheDocument();
    });
  });

  test('calls onBack when back button is clicked', async () => {
    const onBack = jest.fn();

    global.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        users: [],
        total: 0,
        date: new Date().toISOString()
      })
    });

    render(<Leaderboard onBack={onBack} language="de" />);

    const backBtn = screen.getByText('Back home');
    fireEvent.click(backBtn);

    expect(onBack).toHaveBeenCalled();
  });

  test('shows load more button when more data available', async () => {
    const mockUsers = Array.from({ length: 20 }, (_, i) => ({
      user_id: i,
      username: `user${i}`,
      score: 100 - i,
      rank: i + 1,
      badge: 'bronze'
    }));

    global.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        users: mockUsers,
        total: 50,
        date: new Date().toISOString()
      })
    });

    render(<Leaderboard onBack={jest.fn()} language="de" />);

    await waitFor(() => {
      expect(screen.getByText('Load more')).toBeInTheDocument();
    });
  });

  test('handles error state', async () => {
    global.fetch.mockResolvedValue({
      ok: false,
      status: 500
    });

    render(<Leaderboard onBack={jest.fn()} language="de" />);

    await waitFor(() => {
      expect(screen.getByText(/Error:/)).toBeInTheDocument();
    });
  });

  test('displays my position when user is logged in', async () => {
    const mockMyPosition = {
      user_id: 5,
      username: 'me',
      score: 50,
      rank: 5,
      badge: 'silver'
    };

    const mockLeaderboard = {
      users: [],
      total: 0,
      date: new Date().toISOString()
    };

    let fetchCount = 0;
    global.fetch.mockImplementation((url) => {
      fetchCount++;
      if (url.includes('/leaderboard/me')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockMyPosition)
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(mockLeaderboard)
      });
    });

    render(<Leaderboard onBack={jest.fn()} language="de" />);

    await waitFor(() => {
      expect(screen.getByText('Your Position')).toBeInTheDocument();
      expect(screen.getByText('me')).toBeInTheDocument();
      expect(screen.getByText('50 points')).toBeInTheDocument();
    });
  });

  test('renders the scoring legend collapsed by default', async () => {
    global.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        users: [],
        total: 0,
        date: new Date().toISOString()
      })
    });

    render(<Leaderboard onBack={jest.fn()} language="de" />);

    // The summary is always visible...
    expect(screen.getByText('How the leaderboard works')).toBeInTheDocument();
    // ...and the <details> starts collapsed (no `open` attribute).
    const details = document.querySelector('.scoring-legend');
    expect(details).toBeInTheDocument();
    expect(details).not.toHaveAttribute('open');
  });

  test('expands the scoring legend when the summary is clicked', async () => {
    global.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        users: [],
        total: 0,
        date: new Date().toISOString()
      })
    });

    render(<Leaderboard onBack={jest.fn()} language="de" />);

    const details = document.querySelector('.scoring-legend');
    const summary = screen.getByText('How the leaderboard works');
    fireEvent.click(summary);

    await waitFor(() => {
      expect(details).toHaveAttribute('open');
    });
  });
});