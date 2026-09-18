import React, { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { API, formatRelativeDate, thumbSrc, thumbErrorHandler } from './shared';

// A read-only view of someone else's contributions. There is no edit/delete
// here -- ownership is enforced server-side (owned_rating), and a public
// profile is exactly "what this user chose to make public".
function ProfileEntry({ entry }) {
  const { t } = useTranslation();
  return (
    <div className="entry">
      <div className="entry__head">
        <div>
          <div className="entry__name">{entry.meal_name}</div>
          <div className="entry__sub">
            {entry.mensa}
            {entry.created_at && ` · ${formatRelativeDate(entry.created_at, t)}`}
          </div>
        </div>
        <span className="stars" role="img"
          aria-label={t('ui.starLabel', { count: entry.rating })}>
          {'★'.repeat(entry.rating)}{'☆'.repeat(5 - entry.rating)}
        </span>
      </div>
      {entry.comment && <p className="review__text">{entry.comment}</p>}
      {entry.photo_url && (
        <img className="review__photo" src={`${API}${thumbSrc(entry.photo_url)}`} alt=""
          loading="lazy" decoding="async"
          onError={thumbErrorHandler(`${API}${entry.photo_url}`)} />
      )}
    </div>
  );
}

function Profile({ username, onBack, language }) {
  const { t } = useTranslation();
  const [profile, setProfile] = useState(null);
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [loadError, setLoadError] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    setNotFound(false);
    setLoadError(false);
    const base = `${API}/api/v1/users/${encodeURIComponent(username)}`;
    // Sequential, not Promise.all: if the profile resolves but the ratings
    // fetch then fails, we still keep the profile header instead of losing it
    // to the first rejection.
    fetch(`${base}?lang=${language}`)
      .then(r => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(p => {
        setProfile(p);
        return fetch(`${base}/ratings?sort=date&lang=${language}`)
          .then(r => (r.ok ? r.json() : Promise.reject(r.status)));
      })
      .then(list => {
        setEntries(Array.isArray(list) ? list : []);
        setLoading(false);
      })
      .catch(status => {
        // A private profile and a nonexistent one both 404 -- the backend makes
        // them indistinguishable on purpose, so the message says "or private".
        if (status === 404) setNotFound(true);
        else setLoadError(true);
        setLoading(false);
      });
  }, [username, language]);

  useEffect(() => { load(); }, [load]);

  const title = loading || !profile
    ? t('profile.title')
    : (profile.display_name || profile.username);

  return (
    <div className="page--narrow">
      <h2 className="view-title">{title}</h2>

      {loading ? (
        <div className="loading">{t('profile.loading')}</div>
      ) : notFound ? (
        <p className="muted-text">{t('profile.notFound')}</p>
      ) : !profile ? (
        // The profile fetch itself failed (not a 404): show the retry, not a
        // header built from a null object.
        <p className="error-text">
          {t('profile.loadFailed')}{' '}
          <button type="button" className="btn--quiet" onClick={load}>
            {t('ui.retry')}
          </button>
        </p>
      ) : (
        <>
          <p className="muted-text">
            {t('profile.ratingsCount', { count: profile.rating_count })}
          </p>
          {loadError ? (
            <p className="error-text">
              {t('profile.loadFailed')}{' '}
              <button type="button" className="btn--quiet" onClick={load}>
                {t('ui.retry')}
              </button>
            </p>
          ) : entries.length === 0 ? (
            <p className="muted-text">{t('profile.noRatings')}</p>
          ) : (
            entries.map(e => <ProfileEntry key={e.id} entry={e} />)
          )}
        </>
      )}

      <button type="button" className="btn btn--primary mt-6" onClick={onBack}>
        {t('ui.backHome')}
      </button>
    </div>
  );
}

export default Profile;
