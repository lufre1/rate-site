// Bits used by both App.js and Account.js. Lives here rather than in App.js so
// Account.js doesn't have to import from its own parent (a cycle).
import React, { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';

// `??`, not `||`. Behind the reverse proxy the correct value is the EMPTY string
// -- calls are same-origin, so `${API}/api/v1/x` must come out as `/api/v1/x`.
// An empty string is falsy, so `||` would silently swap it for the localhost
// fallback and every request would go to the *visitor's own* machine (and be
// blocked as mixed content on an HTTPS page). `??` falls back only on
// undefined/null, which is still the `npm start` case: CRA leaves the identifier
// undefined when the variable is absent.
export const API = process.env.REACT_APP_API_URL ?? 'http://localhost:8000';

// Every upload is stored twice: its own name is the display copy (capped at
// 1600px, what the lightbox opens) and /uploads/thumbs/<same name> is a 240px
// version for the grid. Deriving one URL from the other keeps the pairing out
// of the database and out of every API response -- see backend/images.py.
// Anything that is not an upload path is handed back untouched.
const UPLOADS_PREFIX = '/uploads/';

export function thumbSrc(photoUrl) {
  if (!photoUrl || !photoUrl.startsWith(UPLOADS_PREFIX)) return photoUrl;
  return `${UPLOADS_PREFIX}thumbs/${photoUrl.slice(UPLOADS_PREFIX.length)}`;
}

// A thumbnail is allowed to be missing: render_upload() returns none for an
// image it cannot decode, so the grid falls back to the full photo once and
// only then hides the element, which is what it did before thumbnails existed.
export function thumbErrorHandler(fullSrc) {
  return (e) => {
    if (!e.target.dataset.fullFallback) {
      e.target.dataset.fullFallback = '1';
      e.target.src = fullSrc;
      return;
    }
    e.target.style.display = 'none';
  };
}

const TOKEN_KEY = 'mensa_token';

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch (e) {
    return null; // private mode / storage disabled
  }
}

export function setToken(token) {
  try {
    localStorage.setItem(TOKEN_KEY, token);
  } catch (e) { /* non-fatal: the session just won't survive a reload */ }
}

export function clearToken() {
  try {
    localStorage.removeItem(TOKEN_KEY);
  } catch (e) { /* nothing to do */ }
}

// Spread into a fetch's headers. Empty when signed out, which is what keeps
// anonymous rating working through the exact same request.
export function authHeaders() {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// Local-calendar YYYY-MM-DD. NOT toISOString().slice(0, 10), which is UTC: for a
// Berlin user between midnight and 02:00 that returns *yesterday*, so the app
// opened on the wrong day's menu. Everything else in the UI reads local getters
// (formatDate in App.js), so the date key has to be local too.
export function toDateKey(d = new Date()) {
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

// The API serialises naive UTC timestamps with no offset (`.isoformat()` on a
// tz-naive datetime, e.g. "2026-09-01T12:00:00"). ES2015 parses the date-TIME
// form without an offset as LOCAL, so those instants land 1-2h off for Berlin --
// enough to flip "today"/"yesterday" near a boundary. Appending Z fixes that.
// Date-ONLY strings ("2026-09-01") are already spec'd as UTC; leave them alone.
export function parseServerDate(dateStr) {
  const needsZ = /T/.test(dateStr) && !/(Z|[+-]\d{2}:?\d{2})$/.test(dateStr);
  return new Date(needsZ ? `${dateStr}Z` : dateStr);
}

export function formatRelativeDate(dateStr, t) {
  const days = Math.round((new Date() - parseServerDate(dateStr)) / 86400000);
  if (days <= 0) return t('dates.today');
  if (days === 1) return t('dates.yesterday');
  if (days < 7) return t('dates.daysAgo', { count: days });
  if (days < 30) return t('dates.weeksAgo', { count: Math.round(days / 7) });
  if (days < 365) return t('dates.monthsAgo', { count: Math.round(days / 30) });
  return t('dates.yearsAgo', { count: Math.round(days / 365) });
}

// -- theme -------------------------------------------------------------
// Three states: 'light' and 'dark' write data-theme on <html> and win over the
// OS; 'system' removes the attribute and lets prefers-color-scheme decide.
// The same key is read by the inline script in public/index.html, which
// applies the theme before first paint to avoid a flash -- keep them in sync.

const THEME_KEY = 'mensa_theme';
export const THEME_ORDER = ['system', 'light', 'dark'];

export function getTheme() {
  try {
    const stored = localStorage.getItem(THEME_KEY);
    return THEME_ORDER.includes(stored) ? stored : 'system';
  } catch (e) {
    return 'system';
  }
}

export function applyTheme(theme) {
  const root = document.documentElement;
  if (theme === 'light' || theme === 'dark') {
    root.setAttribute('data-theme', theme);
  } else {
    root.removeAttribute('data-theme');
  }
}

export function setTheme(theme) {
  applyTheme(theme);
  try {
    if (theme === 'system') {
      localStorage.removeItem(THEME_KEY);
    } else {
      localStorage.setItem(THEME_KEY, theme);
    }
  } catch (e) { /* non-fatal: the choice just won't survive a reload */ }
}

const THEME_ICONS = { system: '🖥️', light: '☀️', dark: '🌙' };

// One button that cycles system -> light -> dark. A three-way control needs
// three labels, so the accessible name says which mode is active and the
// visible glyph matches it.
export function ThemeToggle() {
  const { t } = useTranslation();
  const [theme, setThemeState] = React.useState(getTheme);

  const cycle = () => {
    const next = THEME_ORDER[(THEME_ORDER.indexOf(theme) + 1) % THEME_ORDER.length];
    setTheme(next);
    setThemeState(next);
  };

  const label = t('ui.themeSwitch', { mode: t(`ui.theme_${theme}`) });

  return (
    <button type="button" className="nav-btn" onClick={cycle}
      aria-label={label} title={label}>
      <span aria-hidden="true">{THEME_ICONS[theme]}</span>
    </button>
  );
}

export function StarPicker({ value, onChange, size = 22 }) {
  const { t } = useTranslation();
  return (
    <div className="star-picker">
      {[1, 2, 3, 4, 5].map(i => (
        <button
          key={i}
          type="button"
          className="star-btn"
          onClick={() => onChange(i)}
          aria-pressed={i <= value}
          aria-label={t('ui.starLabel', { count: i })}
          style={{ '--star-size': `${size}px` }}
        >
          <span aria-hidden="true">&#9733;</span>
        </button>
      ))}
    </div>
  );
}

const VOTER_ID_KEY = 'mensa_voter_id';

export function getVoterId() {
  try {
    let id = localStorage.getItem(VOTER_ID_KEY);
    if (!id) {
      id = 'v_' + Math.random().toString(36).substring(2) + '_' + Date.now();
      localStorage.setItem(VOTER_ID_KEY, id);
    }
    return id;
  } catch (e) {
    return null;
  }
}

export function voteHeaders() {
  const id = getVoterId();
  return id ? { 'X-Voter-Id': id } : {};
}

// -- diet filter -------------------------------------------------------
const DIET_KEY = 'mensa_diet';
export const DIET_ORDER = ['all', 'vegetarian', 'vegan'];

export function getDietFilter() {
  try {
    const stored = localStorage.getItem(DIET_KEY);
    return DIET_ORDER.includes(stored) ? stored : 'all';
  } catch (e) {
    return 'all';
  }
}

export function setDietFilter(filter) {
  try {
    if (filter === 'all') {
      localStorage.removeItem(DIET_KEY);
    } else {
      localStorage.setItem(DIET_KEY, filter);
    }
  } catch (e) { /* non-fatal: the choice just won't survive a reload */ }
}

// Full-screen image overlay. Lives here (not in App.js) so both App.js and
// Rewind.js can open one without importing from each other (a cycle).
export function Lightbox({ src, alt, onClose, children }) {
  const { t } = useTranslation();
  const closeRef = useRef(null);
  const dialogRef = useRef(null);

  useEffect(() => {
    const previous = document.activeElement;
    closeRef.current?.focus();

    const onKey = (e) => {
      if (e.key === 'Escape') { onClose(); return; }
      if (e.key !== 'Tab') return;
      // Only the close button is focusable, so Tab simply stays on it.
      const focusable = dialogRef.current?.querySelectorAll('button');
      if (!focusable || focusable.length === 0) return;
      e.preventDefault();
      focusable[0].focus();
    };
    document.addEventListener('keydown', onKey);

    // The page behind must not scroll under a full-screen overlay.
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = previousOverflow;
      // Return focus to whatever opened it, or the reader is dumped at the
      // top of the tab order.
      if (previous instanceof HTMLElement) previous.focus();
    };
  }, [onClose]);

  return (
    <div className="lightbox" role="dialog" aria-modal="true" aria-label={alt}
      ref={dialogRef} onClick={onClose}>
      <button
        type="button"
        ref={closeRef}
        className="lightbox__close"
        onClick={onClose}
        title={t('ui.close')}
        aria-label={t('ui.close')}
      >
        <span aria-hidden="true">&times;</span>
      </button>
      {children ? (
        <div className="lightbox__content" onClick={(e) => e.stopPropagation()}>
          <img className="lightbox__img lightbox__img--compact" src={src} alt={alt}
            onClick={(e) => e.stopPropagation()} />
          {children}
        </div>
      ) : (
        <img className="lightbox__img" src={src} alt={alt}
          onClick={(e) => e.stopPropagation()} />
      )}
    </div>
  );
}
