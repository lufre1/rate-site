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

test('the admin announcement section is hidden for non-admins', async () => {
  const user = { username: 'alice', display_name: null, default_mensa: null, is_admin: false };
  renderAccount(user);
  // The section title must not appear for a plain user.
  await waitFor(() => {
    expect(screen.queryByText('Ankündigung')).not.toBeInTheDocument();
  });
});

test('an admin can publish and retire the announcement', async () => {
  const user = { username: 'boss', display_name: null, default_mensa: null, is_admin: true };
  let active = false;

  global.fetch = jest.fn((url, opts) => {
    if (url.endsWith('/api/v1/announcement') && (!opts || !opts.method)) {
      // GET: reflect the current active state.
      return active
        ? Promise.resolve({ ok: true, json: () => Promise.resolve({ id: 1, text_de: 'Neu', text_en: 'New' }) })
        : Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
    }
    if (url.endsWith('/api/v1/admin/announcement') && opts && opts.method === 'POST') {
      active = true;
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ id: 2, text_de: 'Neu', text_en: 'New' }) });
    }
    if (url.endsWith('/api/v1/admin/announcement') && opts && opts.method === 'DELETE') {
      active = false;
      return Promise.resolve({ ok: true, status: 204, json: () => Promise.resolve({}) });
    }
    if (url.endsWith('/api/v1/me')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ is_public: false, default_mensa: null }) });
    }
    if (url.includes('/mensas')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
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

  // The admin section is visible.
  const title = await screen.findByText('Ankündigung');
  expect(title).toBeInTheDocument();

  // Fill both texts and publish.
  const deField = await screen.findByLabelText('Deutscher Text');
  const enField = await screen.findByLabelText('Englischer Text');
  await userEvent.type(deField, 'Neu');
  await userEvent.type(enField, 'New');
  await userEvent.click(screen.getByRole('button', { name: 'Veröffentlichen' }));

  await waitFor(() => {
    const post = global.fetch.mock.calls.find(
      ([u, o]) => u.endsWith('/api/v1/admin/announcement') && o && o.method === 'POST'
    );
    expect(post).toBeDefined();
  });
  const post = global.fetch.mock.calls.find(
    ([u, o]) => u.endsWith('/api/v1/admin/announcement') && o && o.method === 'POST'
  );
  expect(JSON.parse(post[1].body)).toEqual({ text_de: 'Neu', text_en: 'New' });

  // The retire button appears once something is active; clicking it DELETEs.
  const retire = await screen.findByRole('button', { name: 'Entfernen' });
  await userEvent.click(retire);
  await waitFor(() => {
    const del = global.fetch.mock.calls.find(
      ([u, o]) => u.endsWith('/api/v1/admin/announcement') && o && o.method === 'DELETE'
    );
    expect(del).toBeDefined();
  });
});
