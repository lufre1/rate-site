/**
 * Render guards for the two legal pages.
 *
 * They are long walls of t() calls, so a typo'd key does not throw -- i18next
 * just renders the key name, and "datenschutz.logsRetention" then sits in the
 * middle of a privacy notice looking like a bug report. These tests render both
 * pages in both languages and fail if a raw key leaks through, which the
 * key-parity test in translations/ cannot catch on its own.
 */
import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

import de from './translations/de.json';
import en from './translations/en.json';
import Impressum from './Impressum';
import Datenschutz from './Datenschutz';

beforeAll(() => {
  i18n.use(initReactI18next).init({
    resources: { de: { translation: de }, en: { translation: en } },
    lng: 'de',
    fallbackLng: 'de',
    interpolation: { escapeValue: false },
  });
});

/** Any "namespace.key" token left in the output is an unresolved i18next key. */
function unresolvedKeys(container) {
  const pattern = /\b(?:impressum|datenschutz|ui|footer|auth)\.[a-zA-Z][\w.]*/g;
  return container.textContent.match(pattern) || [];
}

describe.each(['de', 'en'])('rendered in %s', (lng) => {
  beforeEach(async () => {
    await i18n.changeLanguage(lng);
  });

  test('Impressum resolves every key', () => {
    const { container } = render(<Impressum onBack={() => {}} />);
    expect(unresolvedKeys(container)).toEqual([]);
    expect(container.textContent.length).toBeGreaterThan(500);
  });

  test('Datenschutz resolves every key', () => {
    const { container } = render(<Datenschutz onBack={() => {}} />);
    expect(unresolvedKeys(container)).toEqual([]);
    expect(container.textContent.length).toBeGreaterThan(3000);
  });

  test('the back button calls onBack on both pages', async () => {
    const label = (lng === 'de' ? de : en).ui.backHome;
    for (const Page of [Impressum, Datenschutz]) {
      const onBack = jest.fn();
      const { unmount } = render(<Page onBack={onBack} />);
      await userEvent.click(screen.getByRole('button', { name: label }));
      expect(onBack).toHaveBeenCalledTimes(1);
      unmount();
    }
  });
});

describe('content the audit requires', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('de');
  });

  test('the Impressum publishes no postal address', () => {
    // The site is a private, non-commercial project and so carries no § 5 DDG
    // obligation. If an address is ever added back, impressum.natureText has
    // to change with it -- see AGENTS.md.
    const { container } = render(<Impressum onBack={() => {}} />);
    expect(container.textContent).not.toMatch(/Goldschmid/i);
    expect(container.textContent).not.toMatch(/\b\d{5}\s+G[oö]ttingen\b/);
    expect(container.textContent).toContain('luca.freckmann@stud.uni-goettingen.de');
  });

  test('the Impressum disclaims any link to the Studierendenwerk', () => {
    const { container } = render(<Impressum onBack={() => {}} />);
    expect(container.textContent).toMatch(/keiner Verbindung zum Studierendenwerk/i);
  });

  test('Datenschutz discloses what the code actually does', () => {
    const { container } = render(<Datenschutz onBack={() => {}} />);
    const text = container.textContent.toLowerCase();
    for (const claim of [
      'mensa_voter_id',   // the persistent pseudonymous vote id
      'mensa_token',
      'studierendenwerk', // the third-party icon host
      'gwdg',             // the hoster
      'scrypt',           // how passwords are stored
      'exif',             // metadata removal
    ]) {
      expect(text).toContain(claim);
    }
  });

  test('Datenschutz makes no claim the code cannot keep', () => {
    const { container } = render(<Datenschutz onBack={() => {}} />);
    const text = container.textContent.toLowerCase();
    // Sessions never expire (auth.py) and logs rotate by size, not by age
    // (docker log-opts), so neither may be promised here.
    expect(text).not.toMatch(/sitzung(en)? laufen .{0,20}automatisch ab/);
    expect(text).not.toMatch(/cookies? (setzen|verwenden|nutzen) wir/);
    expect(text).toMatch(/keine cookies|setzt keine cookies/);
  });
});
