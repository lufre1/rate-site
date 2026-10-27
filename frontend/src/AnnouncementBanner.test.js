/**
 * Tests for the once-per-browser announcement banner.
 *
 * The banner fetches the current announcement from the server and shows it only
 * if its id is not already in the browser's seen-list (localStorage). Dismissing
 * adds the id to that list. These tests pin that contract.
 */
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

import de from './translations/de.json';
import en from './translations/en.json';
import AnnouncementBanner from './AnnouncementBanner';

beforeAll(() => {
  i18n.use(initReactI18next).init({
    resources: { de: { translation: de }, en: { translation: en } },
    lng: 'de',
    fallbackLng: 'de',
    interpolation: { escapeValue: false },
  });
});

function jsonResponse(data) {
  return Promise.resolve({ ok: true, json: () => Promise.resolve(data) });
}

function errorResponse(status) {
  return Promise.resolve({ ok: false, status, json: () => Promise.resolve({ detail: 'x' }) });
}

beforeEach(() => {
  global.fetch = jest.fn(() => jsonResponse({ id: 1, text: 'Neues Feature!' }));
});

afterEach(() => {
  jest.restoreAllMocks();
  localStorage.clear();
});

test('shows the announcement when it has not been seen', async () => {
  render(<AnnouncementBanner />);
  expect(await screen.findByText('Neues Feature!')).toBeInTheDocument();
});

test('dismissing stores the id and hides the banner', async () => {
  render(<AnnouncementBanner />);
  const dismiss = await screen.findByRole('button', { name: 'Hinweis schließen' });
  await userEvent.click(dismiss);
  expect(screen.queryByText('Neues Feature!')).not.toBeInTheDocument();
  expect(JSON.parse(localStorage.getItem('mensa_seen_announcements'))).toEqual([1]);
});

test('does not show an announcement already in the seen-list', async () => {
  localStorage.setItem('mensa_seen_announcements', JSON.stringify([1]));
  render(<AnnouncementBanner />);
  await waitFor(() => expect(global.fetch).toHaveBeenCalled());
  expect(screen.queryByText('Neues Feature!')).not.toBeInTheDocument();
});

test('renders nothing when the server has no announcement (404)', async () => {
  global.fetch = jest.fn(() => errorResponse(404));
  render(<AnnouncementBanner />);
  await waitFor(() => expect(global.fetch).toHaveBeenCalled());
  expect(screen.queryByText('Neues Feature!')).not.toBeInTheDocument();
});

test('renders nothing when the response is not a well-formed announcement', async () => {
  global.fetch = jest.fn(() => jsonResponse([]));
  render(<AnnouncementBanner />);
  await waitFor(() => expect(global.fetch).toHaveBeenCalled());
  expect(screen.queryByText('Neues Feature!')).not.toBeInTheDocument();
});
