// A dismissible announcement banner shown once per browser per announcement.
//
// The server owns the announcement content (GET /api/v1/announcement returns
// the current active one with a stable `id`). This component remembers which
// ids this browser has already dismissed in localStorage, so a *new* announcement
// (a new id) shows again even to a visitor who dismissed the old one -- which is
// exactly the "inform users about new features or updates" use case.
//
// The seen-list is a new localStorage key and is therefore disclosed in
// Datenschutz.js and asserted in legal.test.js -- keep those in step.
import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { API } from './shared';

const SEEN_KEY = 'mensa_seen_announcements';

function getSeen() {
  try {
    const raw = localStorage.getItem(SEEN_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch (e) {
    return []; // private mode / storage disabled: just show it
  }
}

function markSeen(id) {
  try {
    const seen = getSeen();
    if (!seen.includes(id)) {
      seen.push(id);
      localStorage.setItem(SEEN_KEY, JSON.stringify(seen));
    }
  } catch (e) { /* non-fatal: the banner just reappears next load */ }
}

export default function AnnouncementBanner() {
  const { t, i18n } = useTranslation();
  const [announcement, setAnnouncement] = useState(null);

  useEffect(() => {
    let cancelled = false;
    fetch(`${API}/api/v1/announcement?lang=${i18n.language}`)
      .then(r => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(data => {
        if (cancelled) return;
        // A 404 (no announcement) rejects above; anything else that is not a
        // well-formed {id, text} is treated as "no announcement" rather than
        // crashing the page.
        if (!data || typeof data.id !== 'number' || typeof data.text !== 'string') return;
        if (getSeen().includes(data.id)) return;
        setAnnouncement(data);
      })
      .catch(() => { /* no announcement / network error: show nothing */ });
    return () => { cancelled = true; };
  }, [i18n.language]);

  if (!announcement) return null;

  const dismiss = () => {
    markSeen(announcement.id);
    setAnnouncement(null);
  };

  return (
    <div className="announcement" role="status">
      <p className="announcement__text">{announcement.text}</p>
      <button
        type="button"
        className="announcement__close"
        onClick={dismiss}
        title={t('ui.dismissBanner')}
        aria-label={t('ui.dismissBanner')}
      >
        <span aria-hidden="true">&times;</span>
      </button>
    </div>
  );
}
