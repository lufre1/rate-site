// Bits used by both App.js and Account.js. Lives here rather than in App.js so
// Account.js doesn't have to import from its own parent (a cycle).
import React from 'react';

export const API = process.env.REACT_APP_API_URL || 'http://localhost:8000';

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

export function formatRelativeDate(dateStr, t) {
  const days = Math.round((new Date() - new Date(dateStr)) / 86400000);
  if (days <= 0) return t('dates.today');
  if (days === 1) return t('dates.yesterday');
  if (days < 7) return t('dates.daysAgo', { count: days });
  if (days < 30) return t('dates.weeksAgo', { count: Math.round(days / 7) });
  if (days < 365) return t('dates.monthsAgo', { count: Math.round(days / 30) });
  return t('dates.yearsAgo', { count: Math.round(days / 365) });
}

export function StarPicker({ value, onChange, size = 22 }) {
  return (
    <div style={{ display: 'flex', gap: 4 }}>
      {[1, 2, 3, 4, 5].map(i => (
        <button key={i} onClick={() => onChange(i)} style={{
          background: 'none', border: 'none', cursor: 'pointer',
          fontSize: size, lineHeight: 1, padding: '12px 6px',
          minWidth: 48, minHeight: 48,
          color: i <= value ? '#f59e0b' : '#d1d5db'
        }}>&#9733;</button>
      ))}
    </div>
  );
}
