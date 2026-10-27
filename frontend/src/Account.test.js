import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import de from './translations/de.json';
import en from './translations/en.json';
import Account from './Account';
import { ToastProvider } from './Toast';

// Account.js consumes useTranslation() but does not init i18n itself (App.js
// does), so initialise it here with the real resources -- a typo'd key would
// otherwise render the raw key and the assertion would pass on the wrong text.
beforeAll(() => {
  i18n.use(initReactI18next).init({
    resources: { de: { translation: de }, en: { translation: en } },
    lng: 'de',
    fallbackLng: 'de',
    interpolation: { escapeValue: false },
  });
});

beforeEach(() => {
  global.fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve([]) }));
});

afterEach(() => {
  jest.restoreAllMocks();
  localStorage.clear();
});

function renderAccount(user) {
  const onAuth = jest.fn();
  const utils = render(
    <ToastProvider>
      <Account user={user} onAuth={onAuth} onLogout={jest.fn()} onBack={jest.fn()} language="de" />
    </ToastProvider>
  );
  return { onAuth, ...utils };
}

test('the default-mensa dropdown saves the chosen mensa', async () => {
  const user = { username: 'alice', display_name: null, default_mensa: null };
  // The /me endpoint is the source of truth and re-fetched whenever the user
  // object changes (onUpdate -> onAuth -> new user prop), so it must reflect
  // the saved value or it would clobber the selection.
  let savedDefault = null;

  global.fetch = jest.fn((url, opts) => {
    if (url.endsWith('/api/v1/me/default-mensa')) {
      savedDefault = JSON.parse(opts.body).default_mensa;
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ default_mensa: savedDefault }) });
    }
    if (url.endsWith('/api/v1/me')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ is_public: false, default_mensa: savedDefault }) });
    }
    if (url.includes('/mensas')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(['Zentralmensa', 'CGiN']) });
    }
    if (url.includes('/leaderboard/me')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ score: 0, rank: null }) });
    }
    if (url.includes('/me/streak')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ current: 0, best: 0, active: false }) });
    }
    if (url.includes('/me/ratings')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
  });

  const { onAuth } =   renderAccount(user);

  const select = await screen.findByLabelText('Standard-Mensa');
  expect(select).toHaveValue('');

  // The /me effect also writes defaultMensa, so wait for it to settle before
  // interacting -- otherwise a slow /me response would clobber the selection.
  // The profile-visibility button is disabled until /me sets isPublic.
  const visBtn = await screen.findByRole('button', { name: /Privat – öffentlich machen/ });
  await waitFor(() => expect(visBtn).toBeEnabled());

  // Wait for the mensa list to load so the option exists before selecting.
  await screen.findByText('CGiN');
  await userEvent.selectOptions(select, 'CGiN');

  // The PATCH carries the chosen mensa name.
  await waitFor(() => {
    const patch = global.fetch.mock.calls.find(
      ([u, o]) => u.endsWith('/api/v1/me/default-mensa') && o && o.method === 'PATCH'
    );
    expect(patch).toBeDefined();
  });
  const patch = global.fetch.mock.calls.find(
    ([u, o]) => u.endsWith('/api/v1/me/default-mensa') && o && o.method === 'PATCH'
  );
  expect(JSON.parse(patch[1].body)).toEqual({ default_mensa: 'CGiN' });

  // The select reflects the saved value, and App's user object is updated.
  await waitFor(() => expect(select).toHaveValue('CGiN'));
  expect(onAuth).toHaveBeenCalledWith(
    expect.objectContaining({ username: 'alice', default_mensa: 'CGiN' })
  );
});

test('choosing "all mensas" clears the default', async () => {
  const user = { username: 'alice', display_name: null, default_mensa: 'CGiN' };
  let savedDefault = 'CGiN';

  global.fetch = jest.fn((url, opts) => {
    if (url.endsWith('/api/v1/me/default-mensa')) {
      savedDefault = JSON.parse(opts.body).default_mensa;
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ default_mensa: savedDefault }) });
    }
    if (url.endsWith('/api/v1/me')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ is_public: false, default_mensa: savedDefault }) });
    }
    if (url.includes('/mensas')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(['Zentralmensa', 'CGiN']) });
    }
    if (url.includes('/leaderboard/me')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ score: 0, rank: null }) });
    }
    if (url.includes('/me/streak')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ current: 0, best: 0, active: false }) });
    }
    if (url.includes('/me/ratings')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
  });

  renderAccount(user);

  const select = await screen.findByLabelText('Standard-Mensa');
  // The /me effect confirms the stored default, so the select shows CGiN.
  await waitFor(() => expect(select).toHaveValue('CGiN'));

  // Wait for /me to settle before interacting (see the other test).
  const visBtn = await screen.findByRole('button', { name: /Privat – öffentlich machen/ });
  await waitFor(() => expect(visBtn).toBeEnabled());

  await userEvent.selectOptions(select, '');

  await waitFor(() => {
    const patch = global.fetch.mock.calls.find(
      ([u, o]) => u.endsWith('/api/v1/me/default-mensa') && o && o.method === 'PATCH'
    );
    expect(patch).toBeDefined();
  });
  const patch = global.fetch.mock.calls.find(
    ([u, o]) => u.endsWith('/api/v1/me/default-mensa') && o && o.method === 'PATCH'
  );
  expect(JSON.parse(patch[1].body)).toEqual({ default_mensa: null });
  await waitFor(() => expect(select).toHaveValue(''));
});
