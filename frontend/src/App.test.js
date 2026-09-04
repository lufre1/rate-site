import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';
import { ToastProvider } from './Toast';
import { API } from './shared';

const MENSA = 'Testmensa';

function jsonResponse(data) {
  return Promise.resolve({ ok: true, json: () => Promise.resolve(data) });
}

function errorResponse(status, detail) {
  return Promise.resolve({ ok: false, status, json: () => Promise.resolve({ detail }) });
}

// The app's own local-calendar key (toDateKey in shared.js). NOT
// toISOString().slice(0, 10), which is UTC and lands on the wrong day for a
// Berlin user between midnight and 02:00.
function todayKey() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function breakdown({ comments = [], recent, overall } = {}) {
  return Promise.resolve({
    ok: true,
    json: () => Promise.resolve({
      recent: recent || { ratings: [], avg: 0, count: 0 },
      overall: overall || { avg: 0, count: 0 },
      comments,
    }),
  });
}

// Expand the card, then open the rating form inside it.
async function openRatingForm(dishName) {
  await userEvent.click(await screen.findByText(dishName));
  await userEvent.click(await screen.findByRole('button', { name: /Dieses Gericht bewerten/ }));
}

// Mirrors index.js: the provider sits ABOVE App, because App itself consumes
// the context for its own failed fetches. Without it useToast() falls back to
// its deliberate no-op and nothing would be asserted about the toast.
function renderApp() {
  return render(<ToastProvider><App /></ToastProvider>);
}

function starButtons() {
  return document.querySelectorAll('.star-picker .star-btn');
}

beforeEach(() => {
  global.fetch = jest.fn(() => jsonResponse([]));
  // jsdom implements neither of these; the component guards with `?.`, but
  // stubbing keeps the assertion surface clean.
  Element.prototype.scrollIntoView = jest.fn();
  window.scrollTo = jest.fn();
});

afterEach(() => {
  jest.restoreAllMocks();
  localStorage.clear();
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
    date: '2026-07-05', created_at: '2026-07-05T12:00:00', meal_id: 1, photo_url: null,
  };

  global.fetch = jest.fn((url) => {
    if (url.includes('/mensas')) return jsonResponse([MENSA]);
    if (url.includes('/meals-summary')) return jsonResponse({});
    // Matched EXPLICITLY: `/meals/1/ratings` is a substring of
    // `/meals/1/ratings-breakdown`, so the looser check used to answer the
    // breakdown request with a bare array and the list rendered empty.
    if (url.includes('/ratings-breakdown')) return breakdown({ comments: [review] });
    if (url.includes('/meals?')) return jsonResponse([meal]);
    return jsonResponse([]);
  });

  renderApp();

  // Expanding the dish loads the list directly -- there is no second
  // "Bewertungen" toggle any more.
  await userEvent.click(await screen.findByText('Testgericht'));

  expect(await screen.findByText('Sehr lecker')).toBeInTheDocument();
  expect(screen.getByText('Testgericht')).toBeInTheDocument();
});

test('expanding a dish fetches the ratings breakdown once, not in a loop', async () => {
  // Guards the same regression class as the old side-ratings test (a fresh
  // array identity in an effect's dep list looping fetch -> setState ->
  // fetch), against the request the app actually makes now. loadBreakdown()
  // calls setReviews AND setStats, so it is exactly the shape that could
  // retrigger its own effect.
  const meal = {
    id: 2, name: 'Hauptgericht Test', description: 'Reis, Bohnen', tags: null,
    type: 'main', mensa: MENSA, date: '2026-07-07', avg_rating: 0, rating_count: 0,
  };

  let breakdownCalls = 0;
  global.fetch = jest.fn((url) => {
    if (url.includes('/mensas')) return jsonResponse([MENSA]);
    if (url.includes('/meals-summary')) return jsonResponse({});
    if (url.includes('/ratings-breakdown')) {
      breakdownCalls += 1;
      return breakdown({ recent: { ratings: [], avg: 0, count: 0 }, overall: { avg: 0, count: 0 } });
    }
    if (url.includes('/meals?')) return jsonResponse([meal]);
    return jsonResponse([]);
  });

  renderApp();
  await userEvent.click(await screen.findByText('Hauptgericht Test'));

  await waitFor(() => expect(breakdownCalls).toBeGreaterThanOrEqual(1));
  // Give a looping effect plenty of time to fire again before asserting.
  await new Promise((resolve) => setTimeout(resolve, 300));

  expect(breakdownCalls).toBe(1);
});

test('a review with an uploaded photo renders the photo thumbnail', async () => {
  const meal = {
    id: 3, name: 'Gericht mit Foto', description: '', tags: null, type: 'side',
    mensa: MENSA, date: '2026-07-07', avg_rating: 5, rating_count: 1,
  };
  const review = {
    id: 200, rating: 5, comment: 'Sieht toll aus', user_name: 'Ada',
    date: '2026-07-05', created_at: '2026-07-05T12:00:00', meal_id: 3,
    photo_url: '/uploads/test_abc123.png',
  };

  global.fetch = jest.fn((url) => {
    if (url.includes('/mensas')) return jsonResponse([MENSA]);
    if (url.includes('/meals-summary')) return jsonResponse({});
    if (url.includes('/ratings-breakdown')) return breakdown({ comments: [review] });
    if (url.includes('/meals?')) return jsonResponse([meal]);
    return jsonResponse([]);
  });

  renderApp();
  await userEvent.click(await screen.findByText('Gericht mit Foto'));
  await screen.findByText('Sieht toll aus');

  // Built against `API`, not a hardcoded host: the fallback only applies when
  // REACT_APP_API_URL is absent (which is the `npm test` case), while the
  // deployed bundle builds with it empty and emits a same-origin path.
  expect(document.querySelector(`img[src="${API}${review.photo_url}"]`)).toBeInTheDocument();
});

test('comments use created_at instead of meal date for relative date display', async () => {
  const meal = {
    id: 4, name: 'Testgericht', description: '', tags: null, type: 'main',
    mensa: MENSA, date: '2026-07-22', avg_rating: 4, rating_count: 2,
  };
  const review = {
    id: 300, rating: 5, comment: 'Gut gewuerzt', user_name: 'Ben',
    date: '2026-07-22', created_at: `${todayKey()}T10:30:00`, meal_id: 4, photo_url: null,
  };

  global.fetch = jest.fn((url) => {
    if (url.includes('/mensas')) return jsonResponse([MENSA]);
    if (url.includes('/meals-summary')) return jsonResponse({});
    if (url.includes('/ratings-breakdown')) {
      return breakdown({
        comments: [review],
        recent: { ratings: [review], avg: 5, count: 1 },
        overall: { avg: 4.5, count: 2 },
      });
    }
    if (url.includes('/meals?')) return jsonResponse([meal]);
    return jsonResponse([]);
  });

  renderApp();
  await userEvent.click(await screen.findByText('Testgericht'));

  // dates.today from created_at, not "vor 2 Monaten" from the older meal
  // date. Case-insensitive: the German string is lowercase "heute".
  await screen.findByText('Gut gewuerzt');
  expect(screen.getByText(/^heute$/i)).toBeInTheDocument();
});

test('only today\'s comments get the "recent" badge, not old ones', async () => {
  // Regression test for: every comment with a created_at was flagged
  // "(aktuell)", even old reviews from previous days.
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
    date: meal.date, created_at: `${todayKey()}T09:00:00`, meal_id: 5,
    photo_url: null, is_recent: true,
  };

  global.fetch = jest.fn((url) => {
    if (url.includes('/mensas')) return jsonResponse([MENSA]);
    if (url.includes('/meals-summary')) return jsonResponse({});
    if (url.includes('/ratings-breakdown')) {
      return breakdown({
        comments: [todayReview, oldReview],
        recent: { ratings: [todayReview], avg: 5, count: 1 },
        overall: { avg: 4.5, count: 2 },
      });
    }
    if (url.includes('/meals?')) return jsonResponse([meal]);
    return jsonResponse([]);
  });

  renderApp();
  await userEvent.click(await screen.findByText('Testgericht'));

  await screen.findByText('Heutige Bewertung');
  await screen.findByText('Alte Bewertung');

  // Scoped to the review headers: .badge--positive is also used by the
  // top-photo chip in the photo-vote row.
  expect(document.querySelectorAll('.review__head .badge--positive').length).toBe(1);
});

// -- submitting a review ------------------------------------------------
// Everything below is the flow the reported confusion was about: users could
// not see their own comment and got no usable feedback.

const submitMeal = {
  id: 10, name: 'Neues Gericht', description: '', tags: null, type: 'main',
  mensa: MENSA, date: todayKey(), avg_rating: 0, rating_count: 0,
};

const created = {
  id: 900, meal_id: 10, rating: 5, comment: 'Frisch gekocht',
  user_name: 'Heiterer Hering', user_id: null, photo_url: null,
  created_at: `${todayKey()}T11:00:00`,
};

// The row as ratings-breakdown returns it -- with the six fields the POST
// response does not carry.
const createdAsListed = {
  ...created, date: submitMeal.date, is_recent: true,
  score: 0, vote_direction: null, photo_score: 0, photo_vote_direction: null,
};

// `comments` is answered from a queue so a submit can be observed changing it.
function mockSubmitFlow({ postResponse, breakdowns, onPost }) {
  let call = 0;
  return jest.fn((url, options) => {
    if (url.includes('/mensas')) return jsonResponse([MENSA]);
    if (url.includes('/meals-summary')) return jsonResponse({});
    if (url.includes('/ratings-breakdown')) {
      const payload = breakdowns[Math.min(call, breakdowns.length - 1)];
      call += 1;
      return breakdown(payload);
    }
    if (url.includes('/meals?')) return jsonResponse([submitMeal]);
    if (url.includes('/ratings')) {
      if (onPost) onPost(url, options);
      return postResponse();
    }
    return jsonResponse([]);
  });
}

test('a submitted comment appears in the list without a reload', async () => {
  // The whole point: submitRating used to post and then do nothing, so the
  // new comment stayed invisible until the card was collapsed and reopened.
  let posted = null;
  global.fetch = mockSubmitFlow({
    postResponse: () => Promise.resolve({ ok: true, status: 201, json: () => Promise.resolve(created) }),
    breakdowns: [
      { comments: [] },
      { comments: [createdAsListed], recent: { ratings: [], avg: 5, count: 1 }, overall: { avg: 5, count: 1 } },
    ],
    onPost: (url, options) => { posted = { url, body: JSON.parse(options.body) }; },
  });

  renderApp();
  await openRatingForm('Neues Gericht');
  await userEvent.click(starButtons()[4]);
  await userEvent.type(screen.getByRole('textbox', { name: 'Kommentar (optional)' }), 'Frisch gekocht');

  // Anonymous submitters confirm first: the row is owned by nobody, so it
  // cannot be edited or deleted afterwards.
  await userEvent.click(screen.getByRole('button', { name: 'Bewertung absenden' }));
  expect(await screen.findByText(/So wird deine Bewertung veröffentlicht/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: 'Veröffentlichen' }));

  expect(await screen.findByText('Frisch gekocht')).toBeInTheDocument();
  expect(posted.url).toContain('/meals/10/ratings');
  expect(posted.body).toEqual({ rating: 5, comment: 'Frisch gekocht' });
  expect(await screen.findByText(/Danke! Deine Bewertung steht jetzt oben/)).toBeInTheDocument();
});

test('the submitted row is marked as the visitor\'s own', async () => {
  global.fetch = mockSubmitFlow({
    postResponse: () => Promise.resolve({ ok: true, status: 201, json: () => Promise.resolve(created) }),
    breakdowns: [{ comments: [] }, { comments: [createdAsListed] }],
  });

  renderApp();
  await openRatingForm('Neues Gericht');
  await userEvent.click(starButtons()[4]);
  await userEvent.type(screen.getByRole('textbox', { name: 'Kommentar (optional)' }), 'Frisch gekocht');
  await userEvent.click(screen.getByRole('button', { name: 'Bewertung absenden' }));
  await userEvent.click(screen.getByRole('button', { name: 'Veröffentlichen' }));

  expect(await screen.findByText('Deine Bewertung')).toBeInTheDocument();
  expect(document.querySelector('.review[data-mine="true"]')).toBeInTheDocument();
});

test('a failed submit keeps the typed comment and explains itself', async () => {
  // Regression test for the 1500 ms timer in `finally`: it reset rating and
  // comment REGARDLESS of outcome, so a failed submit wiped the user's text
  // 1.5 s later while the error was still on screen.
  global.fetch = mockSubmitFlow({
    postResponse: () => errorResponse(500, null),
    breakdowns: [{ comments: [] }],
  });

  renderApp();
  await openRatingForm('Neues Gericht');
  await userEvent.click(starButtons()[4]);
  await userEvent.type(screen.getByRole('textbox', { name: 'Kommentar (optional)' }), 'Bleibt stehen');
  await userEvent.click(screen.getByRole('button', { name: 'Bewertung absenden' }));
  await userEvent.click(screen.getByRole('button', { name: 'Veröffentlichen' }));

  expect(await screen.findByText(/Bewertung konnte nicht gespeichert werden/)).toBeInTheDocument();
  // The old wrong fallback for a text-only failure.
  expect(screen.queryByText('Fehler beim Hochladen')).not.toBeInTheDocument();

  // Well past the deleted timer.
  await new Promise((resolve) => setTimeout(resolve, 1700));
  await userEvent.click(screen.getByRole('button', { name: 'Zurück zum Bearbeiten' }));
  expect(screen.getByRole('textbox', { name: 'Kommentar (optional)' })).toHaveValue('Bleibt stehen');
});

test('a stars-only submit says why nothing appears in the list', async () => {
  // ratings-breakdown lists a row only if it has a comment OR a photo, so a
  // stars-only rating legitimately never shows up. Say that, rather than
  // pointing at a list that did not change.
  global.fetch = mockSubmitFlow({
    postResponse: () => Promise.resolve({
      ok: true, status: 201,
      json: () => Promise.resolve({ ...created, comment: null }),
    }),
    breakdowns: [{ comments: [] }, { comments: [] }],
  });

  renderApp();
  await openRatingForm('Neues Gericht');
  await userEvent.click(starButtons()[3]);
  await userEvent.click(screen.getByRole('button', { name: 'Bewertung absenden' }));
  await userEvent.click(screen.getByRole('button', { name: 'Veröffentlichen' }));

  expect(await screen.findByText(/Nur Bewertungen mit Kommentar oder Foto|deine Sterne sind gezählt/i))
    .toBeInTheDocument();
  expect(screen.queryByText(/steht jetzt oben in der Liste/)).not.toBeInTheDocument();
});

test('the card\'s averages update after a submit', async () => {
  global.fetch = mockSubmitFlow({
    postResponse: () => Promise.resolve({ ok: true, status: 201, json: () => Promise.resolve(created) }),
    breakdowns: [
      { comments: [] },
      {
        comments: [createdAsListed],
        recent: { ratings: [created], avg: 5, count: 1 },
        overall: { avg: 5, count: 1 },
      },
    ],
  });

  renderApp();
  await openRatingForm('Neues Gericht');
  await userEvent.click(starButtons()[4]);
  await userEvent.type(screen.getByRole('textbox', { name: 'Kommentar (optional)' }), 'Frisch gekocht');
  await userEvent.click(screen.getByRole('button', { name: 'Bewertung absenden' }));
  await userEvent.click(screen.getByRole('button', { name: 'Veröffentlichen' }));

  // RatingLine renders `${label} ${avg.toFixed(1)} (${count})`. The meal prop
  // says 0/0, so these can only come from the post-submit breakdown.
  expect(await screen.findByText('gesamt 5.0 (1)')).toBeInTheDocument();
  expect(screen.getByText('aktuell 5.0 (1)')).toBeInTheDocument();
});

test('a photo upload takes over an empty dish\'s picture without another request', async () => {
  // A fresh photo starts at score 0 and ties go to the OLDEST photo, so it can
  // only win when the dish had none -- which is exactly when no /top-photo
  // request is needed to find out.
  const withPhoto = { ...created, photo_url: '/uploads/deadbeef.jpg' };
  const listedWithPhoto = {
    ...createdAsListed, photo_url: withPhoto.photo_url,
  };

  let topPhotoCalls = 0;
  global.fetch = jest.fn((url) => {
    if (url.includes('/mensas')) return jsonResponse([MENSA]);
    if (url.includes('/meals-summary')) return jsonResponse({});
    if (url.includes('/top-photo')) { topPhotoCalls += 1; return jsonResponse({ photo_url: null }); }
    if (url.includes('/ratings-breakdown')) return breakdown({ comments: [listedWithPhoto] });
    if (url.includes('/meals?')) return jsonResponse([submitMeal]);
    if (url.includes('/ratings-with-photo')) {
      return Promise.resolve({ ok: true, status: 201, json: () => Promise.resolve(withPhoto) });
    }
    return jsonResponse([]);
  });

  renderApp();
  await openRatingForm('Neues Gericht');
  await userEvent.click(starButtons()[4]);

  const file = new File(['pretend-jpeg'], 'lunch.jpg', { type: 'image/jpeg' });
  await userEvent.upload(document.querySelector('.dropzone input[type="file"]'), file);
  // pickImage reads the file with FileReader before the preview appears.
  await waitFor(() => expect(document.querySelector('.preview__img')).toBeInTheDocument());

  await userEvent.click(screen.getByRole('button', { name: 'Bewertung absenden' }));
  await userEvent.click(screen.getByRole('button', { name: 'Veröffentlichen' }));

  await waitFor(() => {
    expect(document.querySelector(`img.dish__photo[src="${API}${withPhoto.photo_url}"]`))
      .toBeInTheDocument();
  });
  expect(topPhotoCalls).toBe(0);
});

test('a failed vote says so instead of doing nothing', async () => {
  // handleVote used to `// Silent fail - voting is optional`, so a tap that
  // did not register looked exactly like a tap that was not received. This
  // also covers Toast.js, which has no other consumer in this suite.
  const meal = {
    id: 20, name: 'Abstimmgericht', description: '', tags: null, type: 'main',
    mensa: MENSA, date: todayKey(), avg_rating: 4, rating_count: 1,
  };
  const review = {
    id: 500, rating: 4, comment: 'Kann man essen', user_name: 'Ida',
    date: meal.date, created_at: `${todayKey()}T08:00:00`, meal_id: 20,
    photo_url: null, is_recent: true, score: 0, vote_direction: null,
    photo_score: 0, photo_vote_direction: null,
  };

  global.fetch = jest.fn((url, options) => {
    if (url.includes('/mensas')) return jsonResponse([MENSA]);
    if (url.includes('/meals-summary')) return jsonResponse({});
    if (url.includes('/ratings-breakdown')) return breakdown({ comments: [review] });
    if (url.includes('/meals?')) return jsonResponse([meal]);
    if (url.includes('/vote') && options?.method === 'PUT') return errorResponse(503, null);
    return jsonResponse([]);
  });

  renderApp();
  await userEvent.click(await screen.findByText('Abstimmgericht'));
  await screen.findByText('Kann man essen');

  await userEvent.click(screen.getByRole('button', { name: 'Upvote' }));

  const toast = await screen.findByText('Stimme konnte nicht gespeichert werden.');
  expect(toast).toBeInTheDocument();
  // Dismissible by hand, not only on a timer.
  await userEvent.click(screen.getByRole('button', { name: 'Schließen' }));
  expect(screen.queryByText('Stimme konnte nicht gespeichert werden.')).not.toBeInTheDocument();
});
