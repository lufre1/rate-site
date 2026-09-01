import React, { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import {
  API, authHeaders, setToken, clearToken, formatRelativeDate, StarPicker,
  getDisplayName,
} from './shared';

function AuthForm({ onAuth }) {
  const { t } = useTranslation();
  const [mode, setMode] = useState('login');   // 'login' | 'register'
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      const resp = await fetch(`${API}/api/v1/auth/${mode}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data.detail || t('auth.failed'));
      setToken(data.token);
      const displayName = getDisplayName();
      onAuth({ username: data.username, display_name: displayName || null });
    } catch (err) {
      setError(err.message || t('auth.failed'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit}>
      <div className="tabs">
        {['login', 'register'].map(m => (
          <button key={m} type="button" className="btn btn--ghost"
            aria-pressed={mode === m}
            onClick={() => { setMode(m); setError(''); }}>
            {t(`auth.${m}`)}
          </button>
        ))}
      </div>

      <div className="stack-2">
        <input className="field" type="text" autoComplete="username"
          placeholder={t('auth.username')} aria-label={t('auth.username')}
          value={username} onChange={e => setUsername(e.target.value)} />
        <input className="field" type="password"
          autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
          placeholder={t('auth.password')} aria-label={t('auth.password')}
          value={password} onChange={e => setPassword(e.target.value)} />
      </div>

      {mode === 'register' && <p className="hint-text">{t('auth.rules')}</p>}
      <p aria-live="polite">
        {error && <span className="error-text">{error}</span>}
      </p>

      <button type="submit" className="btn btn--primary btn--block"
        disabled={busy || !username || !password}>
        {busy ? '…' : t(`auth.${mode}`)}
      </button>
    </form>
  );
}

function RatingRow({ entry, onChanged }) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [rating, setRating] = useState(entry.rating);
  const [comment, setComment] = useState(entry.comment || '');
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    const resp = await fetch(`${API}/api/v1/ratings/${entry.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ rating, comment }),
    }).catch(() => null);
    setBusy(false);
    if (resp && resp.ok) { setEditing(false); onChanged(); }
  };

  const remove = async () => {
    if (!window.confirm(t('auth.confirmDelete'))) return;
    setBusy(true);
    const resp = await fetch(`${API}/api/v1/ratings/${entry.id}`, {
      method: 'DELETE',
      headers: authHeaders(),
    }).catch(() => null);
    setBusy(false);
    if (resp && resp.ok) onChanged();
  };

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
        <span className="stars" aria-label={t('ui.starLabel', { count: entry.rating })}>
          {'★'.repeat(entry.rating)}{'☆'.repeat(5 - entry.rating)}
        </span>
      </div>

      {editing ? (
        <div className="stack-2">
          <StarPicker value={rating} onChange={setRating} size={18} />
          <textarea className="field field--textarea" rows={2}
            aria-label={t('ui.sideComment')}
            value={comment} onChange={e => setComment(e.target.value)} />
          <div className="row-2">
            <button type="button" className="btn btn--primary btn--sm"
              onClick={save} disabled={busy}>{t('auth.save')}</button>
            <button type="button" className="btn btn--ghost btn--sm"
              onClick={() => { setEditing(false); setRating(entry.rating); setComment(entry.comment || ''); }}>
              {t('auth.cancel')}
            </button>
          </div>
        </div>
      ) : (
        <>
          {entry.comment && <p className="review__text">{entry.comment}</p>}
          {entry.photo_url && (
            <img className="review__photo" src={`${API}${entry.photo_url}`} alt=""
              onError={e => { e.target.style.display = 'none'; }} />
          )}
          <div className="entry__actions">
            <button type="button" className="btn--quiet"
              onClick={() => setEditing(true)} disabled={busy}>{t('auth.edit')}</button>
            <button type="button" className="btn--quiet" data-tone="danger"
              onClick={remove} disabled={busy}>{t('auth.delete')}</button>
          </div>
        </>
      )}
    </div>
  );
}

function Profile({ user, onLogout, language, onUpdate }) {
  const { t } = useTranslation();
  const [displayName, setDisplayNameLocal] = useState(user.display_name || '');
  const [displayError, setDisplayError] = useState('');
  const [displayBusy, setDisplayBusy] = useState(false);

  // "favourites" is not a separate store -- it is the same endpoint filtered to
  // the dishes this user actually rated 4 or 5.
  const [tab, setTab] = useState('mine');
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    const query = tab === 'favourites' ? 'min_rating=4&sort=rating' : 'sort=date';
    fetch(`${API}/api/v1/me/ratings?${query}&lang=${language}`, { headers: authHeaders() })
      .then(r => (r.ok ? r.json() : []))
      .then(data => { setEntries(Array.isArray(data) ? data : []); setLoading(false); })
      .catch(() => { setEntries([]); setLoading(false); });
  }, [tab, language]);

  useEffect(() => { load(); }, [load]);

  const saveDisplayName = async (value) => {
    setDisplayBusy(true);
    setDisplayError('');
    try {
      const trimmed = (value !== undefined ? value : displayName).trim();
      if (trimmed.length > 30) {
        throw new Error(t('auth.displayNameLong'));
      }
      if (trimmed.length > 0 && !/^[A-Za-z0-9 _-]+$/.test(trimmed)) {
        throw new Error(t('auth.displayNameInvalid'));
      }
      const resp = await fetch(`${API}/api/v1/me/display-name`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ display_name: trimmed.length > 0 ? trimmed : null }),
      });
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        throw new Error(data.detail || t('auth.failed'));
      }
      const data = await resp.json();
      setDisplayNameLocal(data.display_name || '');
      if (onUpdate) onUpdate({ username: user.username, display_name: data.display_name });
    } catch (err) {
      setDisplayError(err.message);
    } finally {
      setDisplayBusy(false);
    }
  };

  const logout = async () => {
    await fetch(`${API}/api/v1/auth/logout`, { method: 'POST', headers: authHeaders() }).catch(() => {});
    clearToken();
    onLogout();
  };

  return (
    <>
      <div className="account-head">
        <span className="account-head__who">
          {t('auth.signedInAs')} <strong>{user.username}</strong>
        </span>
        <button type="button" className="btn btn--ghost" onClick={logout}>
          {t('auth.logout')}
        </button>
      </div>

      <div className="card">
        <label className="form-label" htmlFor="display-name">
          {t('auth.displayName')}
        </label>
        <input id="display-name" className="field" type="text"
          placeholder={t('auth.displayNameHint')}
          value={displayName}
          onChange={e => { setDisplayNameLocal(e.target.value); setDisplayError(''); }}
          maxLength={30} />
        <p aria-live="polite">
          {displayError && <span className="error-text">{displayError}</span>}
        </p>
        <div className="row-2">
          <button type="button" className="btn btn--primary btn--sm"
            onClick={() => saveDisplayName()} disabled={displayBusy}>
            {displayBusy ? '…' : t('auth.save')}
          </button>
          {displayName && (
            <button type="button" className="btn btn--ghost btn--sm"
              onClick={() => { setDisplayNameLocal(''); saveDisplayName(''); }}>
              {t('auth.clear')}
            </button>
          )}
        </div>
      </div>

      <div className="tabs mt-4">
        {[['mine', 'auth.myRatings'], ['favourites', 'auth.favourites']].map(([key, label]) => (
          <button key={key} type="button" className="btn btn--ghost"
            aria-pressed={tab === key} onClick={() => setTab(key)}>
            {t(label)}
          </button>
        ))}
      </div>

      {loading ? (
        <p className="muted-text">{t('search.loadingMenu')}</p>
      ) : entries.length === 0 ? (
        <p className="muted-text">
          {t(tab === 'favourites' ? 'auth.noFavourites' : 'auth.noRatings')}
        </p>
      ) : (
        entries.map(e => <RatingRow key={e.id} entry={e} onChanged={load} />)
      )}
    </>
  );
}

function Account({ user, onAuth, onLogout, onBack, language }) {
  const { t } = useTranslation();
  const [userState, setUserState] = useState(user);

  const handleProfileUpdate = (updatedUser) => {
    setUserState(updatedUser);
    onAuth(updatedUser);
  };

  return (
    <div className="page--narrow">
      <h2 className="view-title">{t('auth.account')}</h2>
      {user
        ? <Profile user={userState || user} onLogout={onLogout} language={language} onUpdate={handleProfileUpdate} />
        : <AuthForm onAuth={onAuth} />}
      <button type="button" className="btn btn--primary mt-6" onClick={onBack}>
        {t('ui.backHome')}
      </button>
    </div>
  );
}

export default Account;
