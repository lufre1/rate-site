import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';

const MENSA = 'Testmensa';

function jsonResponse(data) {
  return Promise.resolve({ ok: true, json: () => Promise.resolve(data) });
}

beforeEach(() => {
  global.fetch = jest.fn(() => jsonResponse([]));
});

afterEach(() => {
  jest.restoreAllMocks();
});

test('opening a dish\'s reviews with dated comments renders them instead of crashing', async () => {
  // Regression test for: formatRelativeDate() used to call useTranslation()
  // inside a plain helper, invoked once per review -- a variable number of
  // hook calls between renders crashed the whole app ("Rendered more hooks
  // than during the previous render"), which is what blanked the tab when a
  // user opened the comments on a dish that had reviews.
  const meal = {
    id: 1, name: 'Testgericht', description: '', tags: null, type: 'side',
    mensa: MENSA, date: '2026-07-07', avg_rating: 5, rating_count: 1,
  };
  const review = {
    id: 100, rating: 5, comment: 'Sehr lecker', user_name: 'Fred',
    date: '2026-07-05', meal_id: 1, photo_url: null,
  };

  global.fetch = jest.fn((url) => {
    if (url.includes('/mensas')) return jsonResponse([MENSA]);
    if (url.includes('/meals?')) return jsonResponse([meal]);
    if (url.includes(`/meals/${meal.id}/ratings`)) return jsonResponse([review]);
    return jsonResponse([]);
  });

  render(<App />);

  const dishHeading = await screen.findByText('Testgericht');
  await userEvent.click(dishHeading); // expand the dish

  const reviewsButton = await screen.findByText(/Bewertungen/i);
  await userEvent.click(reviewsButton); // open the reviews list -> triggers formatRelativeDate

  // The review renders with its relative date, and the app is still mounted
  // (not a blank page) -- both would fail before the fix.
  expect(await screen.findByText('Sehr lecker')).toBeInTheDocument();
  expect(screen.getByText('Testgericht')).toBeInTheDocument();
});

test('expanding a main dish fetches side-ratings once, not in an infinite loop', async () => {
  // Regression test for: `sideNames` was a brand-new array on every render
  // and was a dependency of the side-ratings useEffect, so expanding a main
  // dish triggered an endless fetch -> setState -> re-render -> fetch loop
  // that hung the tab.
  const meal = {
    id: 2, name: 'Hauptgericht Test', description: 'Reis, Bohnen', tags: null,
    type: 'main', mensa: MENSA, date: '2026-07-07', avg_rating: 0, rating_count: 0,
  };

  let sideRatingsCallCount = 0;
  global.fetch = jest.fn((url) => {
    if (url.includes('/mensas')) return jsonResponse([MENSA]);
    if (url.includes('/meals?')) return jsonResponse([meal]);
    if (url.includes(`/meals/${meal.id}/side-ratings`)) {
      sideRatingsCallCount += 1;
      return jsonResponse([]);
    }
    return jsonResponse([]);
  });

  render(<App />);

  const dishHeading = await screen.findByText('Hauptgericht Test');
  await userEvent.click(dishHeading); // expand the main dish -> triggers the side-ratings effect

  await waitFor(() => expect(sideRatingsCallCount).toBeGreaterThanOrEqual(1));
  // Give a buggy, looping effect plenty of time to fire again before asserting.
  await new Promise((resolve) => setTimeout(resolve, 300));

  expect(sideRatingsCallCount).toBe(1);
});

test('a review with an uploaded photo renders the photo thumbnail', async () => {
  // Regression test for: the backend already returns photo_url on each
  // review, but the reviews list never rendered it -- uploaded photos never
  // showed up in the comments section.
  const meal = {
    id: 3, name: 'Gericht mit Foto', description: '', tags: null, type: 'side',
    mensa: MENSA, date: '2026-07-07', avg_rating: 5, rating_count: 1,
  };
  const review = {
    id: 200, rating: 5, comment: 'Sieht toll aus', user_name: 'Ada',
    date: '2026-07-05', meal_id: 3, photo_url: '/uploads/test_abc123.png',
  };

  global.fetch = jest.fn((url) => {
    if (url.includes('/mensas')) return jsonResponse([MENSA]);
    if (url.includes('/meals?')) return jsonResponse([meal]);
    if (url.includes(`/meals/${meal.id}/ratings`)) return jsonResponse([review]);
    return jsonResponse([]);
  });

  render(<App />);

  const dishHeading = await screen.findByText('Gericht mit Foto');
  await userEvent.click(dishHeading); // expand the dish

  const reviewsButton = await screen.findByText(/Bewertungen/i);
  await userEvent.click(reviewsButton); // open the reviews list

  await screen.findByText('Sieht toll aus');

  const photo = document.querySelector(`img[src="http://localhost:8000${review.photo_url}"]`);
  expect(photo).toBeInTheDocument();
});

test('comments use created_at instead of meal date for relative date display', async () => {
  const meal = {
    id: 4, name: 'Testgericht', description: '', tags: null, type: 'main',
    mensa: MENSA, date: '2026-07-22', avg_rating: 4, rating_count: 2,
  };
  const today = new Date().toISOString().split('T')[0];
  const review = {
    id: 300, rating: 5, comment: 'Gut gewuerzt', user_name: 'Ben',
    date: '2026-07-22', created_at: `${today}T10:30:00`, meal_id: 4, photo_url: null,
  };

  global.fetch = jest.fn((url) => {
    if (url.includes('/mensas')) return jsonResponse([MENSA]);
    if (url.includes('/meals?')) return jsonResponse([meal]);
    if (url.includes(`/meals/${meal.id}/ratings-breakdown`)) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          recent: { ratings: [review], avg: 5, count: 1 },
          overall: { avg: 4.5, count: 2 },
          comments: [{ ...review, date: meal.date }]
        })
      });
    }
    return jsonResponse([]);
  });

  render(<App />);

  const dishHeading = await screen.findByText('Testgericht');
  await userEvent.click(dishHeading);

  const reviewsButton = await screen.findByText(/Bewertungen/i);
  await userEvent.click(reviewsButton);

  // The comment should show "today" based on created_at, not "yesterday" based on meal.date
  await screen.findByText('Gut gewuerzt');
  const commentDate = await screen.findByText((content, node) => {
    const hasText = (n) => n.textContent === 'Heute' || n.textContent === 'today';
    return hasText(node);
  });
  expect(commentDate).toBeInTheDocument();
});

test('only today\'s comments get the "recent" badge, not old ones', async () => {
  // Regression test for: every comment with a created_at was flagged "(recent)",
  // even old reviews from previous days. Only comments tied to today's meal
  // instance should carry the recent badge.
  const meal = {
    id: 5, name: 'Testgericht', description: '', tags: null, type: 'main',
    mensa: MENSA, date: '2026-07-22', avg_rating: 4, rating_count: 2,
  };
  const oldReview = {
    id: 400, rating: 4, comment: 'Alte Bewertung', user_name: 'Carl',
    date: '2026-07-15', created_at: '2026-07-15T10:30:00', meal_id: 5,
    photo_url: null, is_recent: false,
  };
  const todayReview = {
    id: 401, rating: 5, comment: 'Heutige Bewertung', user_name: 'Dana',
    date: meal.date, created_at: new Date().toISOString(), meal_id: 5,
    photo_url: null, is_recent: true,
  };

  global.fetch = jest.fn((url) => {
    if (url.includes('/mensas')) return jsonResponse([MENSA]);
    if (url.includes('/meals?')) return jsonResponse([meal]);
    if (url.includes(`/meals/${meal.id}/ratings-breakdown`)) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          recent: { ratings: [todayReview], avg: 5, count: 1 },
          overall: { avg: 4.5, count: 2 },
          comments: [todayReview, oldReview],
        }),
      });
    }
    return jsonResponse([]);
  });

  render(<App />);

  const dishHeading = await screen.findByText('Testgericht');
  await userEvent.click(dishHeading);

  const reviewsButton = await screen.findByText(/Bewertungen/i);
  await userEvent.click(reviewsButton);

  await screen.findByText('Heutige Bewertung');
  await screen.findByText('Alte Bewertung');

  const recentBadges = screen.queryAllByText((content, node) => node.textContent.endsWith('aktuell'));
  expect(recentBadges.length).toBe(1);
});
