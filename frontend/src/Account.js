import React, { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { API, authHeaders, setToken, clearToken, formatRelativeDate, StarPicker, setDisplayName, clearDisplayName, getDisplayName } from './shared';

const btn = (bg, color) => ({
  padding: '8px 16px', background: bg, color, border: 'none',
  borderRadius: 8, cursor: 'pointer', fontSize: '0.875rem', fontWeight: 600,
  transition: 'all 0.2s ease', boxShadow: bg === '#3b82f6' ? '0 2px 4px rgba(0,0,0,0.1)' : 'none'
});

const input = {
  width: '100%', padding: '0.5rem', borderRadius: '8px',
  border: '1px solid #d1d5db', fontSize: '0.875rem', marginBottom: 8, transition: 'border-color 0.2s ease, box-shadow 0.2s ease'
};

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
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        {['login', 'register'].map(m => (
          <button key={m} type="button" onClick={() => { setMode(m); setError(''); }}
            style={btn(mode === m ? '#ea580c' : '#f3f4f6', mode === m ? '#fff' : '#6b7280')}>
            {t(`auth.${m}`)}
          </button>
        ))}
      </div>
      <input style={input} type="text" autoComplete="username"
        placeholder={t('auth.username')} value={username}
        onChange={e => setUsername(e.target.value)} />
      <input style={input} type="password"
        autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
        placeholder={t('auth.password')} value={password}
        onChange={e => setPassword(e.target.value)} />
      {mode === 'register' && (
        <p style={{ fontSize: '0.75rem', color: '#6b7280', margin: '0 0 8px' }}>{t('auth.rules')}</p>
      )}
      {error && <p style={{ color: '#dc2626', fontSize: '0.8125rem', margin: '0 0 8px', fontWeight: 500 }}>{error}</p>}
      <button type="submit" disabled={busy || !username || !password}
        style={{ ...btn(busy || !username || !password ? '#f3f4f6' : '#ea580c', busy || !username || !password ? '#9ca3af' : '#fff'), width: '100%', fontWeight: 600 }}>
        {busy ? '...' : t(`auth.${mode}`)}
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
    <div style={{ background: '#fff', border: '1px solid #f3f4f6', borderRadius: 12,
      padding: '12px 16px', marginBottom: 12, boxShadow: '0 2px 4px rgba(0,0,0,0.05)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontSize: '0.9375rem', fontWeight: 600, color: '#111827' }}>{entry.meal_name}</div>
          <div style={{ fontSize: '0.75rem', color: '#6b7280' }}>
            {entry.mensa}
            {entry.created_at && ` · ${formatRelativeDate(entry.created_at, t)}`}
          </div>
        </div>
        <span style={{ color: '#f59e0b', fontSize: '0.875rem', whiteSpace: 'nowrap', fontWeight: 600 }}>
          {'★'.repeat(entry.rating)}{'☆'.repeat(5 - entry.rating)}
        </span>
      </div>

      {editing ? (
        <div style={{ marginTop: 8 }}>
          <StarPicker value={rating} onChange={setRating} size={18} />
          <textarea value={comment} onChange={e => setComment(e.target.value)} rows={2}
            style={{ ...input, marginTop: 4, resize: 'vertical' }} />
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={save} disabled={busy} style={btn('#ea580c', '#fff')}>{t('auth.save')}</button>
            <button onClick={() => { setEditing(false); setRating(entry.rating); setComment(entry.comment || ''); }}
              style={btn('#f3f4f6', '#6b7280')}>{t('auth.cancel')}</button>
          </div>
        </div>
      ) : (
        <>
          {entry.comment && (
            <p style={{ margin: '6px 0 0', fontSize: '0.8125rem', color: '#374151',
              wordBreak: 'break-word', whiteSpace: 'pre-wrap' }}>{entry.comment}</p>
          )}
          {entry.photo_url && (
            <img src={`${API}${entry.photo_url}`} alt="" style={{ marginTop: 6, maxWidth: 100,
              maxHeight: 100, borderRadius: 8, border: '1px solid #f3f4f6', display: 'block' }}
              onError={e => { e.target.style.display = 'none'; }} />
          )}
          <div style={{ display: 'flex', gap: 12, marginTop: 6 }}>
            <button onClick={() => setEditing(true)} disabled={busy}
              style={{ background: 'none', border: 'none', color: '#ea580c', cursor: 'pointer',
                fontSize: '0.75rem', padding: 0, fontWeight: 600 }}>{t('auth.edit')}</button>
            <button onClick={remove} disabled={busy}
              style={{ background: 'none', border: 'none', color: '#dc2626', cursor: 'pointer',
                fontSize: '0.75rem', padding: 0, fontWeight: 600 }}>{t('auth.delete')}</button>
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

  const saveDisplayName = async () => {
    setDisplayBusy(true);
    setDisplayError('');
    try {
      const trimmed = displayName.trim();
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
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        gap: 8, flexWrap: 'wrap', marginBottom: 16 }}>
        <span style={{ fontSize: '1rem', color: '#374151', fontWeight: 600 }}>
          {t('auth.signedInAs')} <strong>{user.username}</strong>
        </span>
        <button onClick={logout} style={btn('#f3f4f6', '#6b7280')}>{t('auth.logout')}</button>
      </div>

      <div style={{ background: '#fff', border: '1px solid #f3f4f6', borderRadius: 12,
        padding: '20px', marginBottom: 16, boxShadow: '0 2px 4px rgba(0,0,0,0.05)' }}>
        <label style={{ display: 'block', fontSize: '0.875rem', fontWeight: 600, color: '#111827', marginBottom: 8 }}>
          {t('auth.displayName')}
        </label>
        <input style={{ ...input, marginBottom: 8 }} type="text"
          placeholder={t('auth.displayNameHint')}
          value={displayName}
          onChange={e => { setDisplayNameLocal(e.target.value); setDisplayError(''); }}
          maxLength={30} />
        {displayError && <p style={{ color: '#dc2626', fontSize: '0.75rem', margin: '0 0 8px', fontWeight: 500 }}>{displayError}</p>}
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={() => saveDisplayName()} disabled={displayBusy}
            style={{ ...btn(displayBusy ? '#f3f4f6' : '#ea580c', displayBusy ? '#9ca3af' : '#fff'), padding: '6px 12px', fontWeight: 600 }}>
            {displayBusy ? '...' : t('auth.save')}
          </button>
          {displayName && (
            <button onClick={() => { setDisplayNameLocal(''); saveDisplayName(); }}
              style={{ ...btn('#f3f4f6', '#6b7280'), padding: '6px 12px' }}>
              {t('auth.clear')}
            </button>
          )}
        </div>
      </div>

      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        {[['mine', 'auth.myRatings'], ['favourites', 'auth.favourites']].map(([key, label]) => (
          <button key={key} onClick={() => setTab(key)}
            style={btn(tab === key ? '#ea580c' : '#f3f4f6', tab === key ? '#fff' : '#6b7280')}>
            {t(label)}
          </button>
        ))}
      </div>

      {loading ? (
        <p style={{ color: '#6b7280', fontSize: '0.875rem' }}>{t('search.loadingMenu')}</p>
      ) : entries.length === 0 ? (
        <p style={{ color: '#9ca3af', fontSize: '0.875rem' }}>
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
    <div style={{ maxWidth: '600px', margin: '0 auto', padding: '24px' }}>
      <h1 style={{ fontSize: '1.5rem', fontWeight: '700', color: '#1f2937', marginBottom: '24px' }}>
        {t('auth.account')}
      </h1>
      {user
        ? <Profile user={userState || user} onLogout={onLogout} language={language} onUpdate={handleProfileUpdate} />
        : <AuthForm onAuth={onAuth} />}
      <button onClick={onBack} style={{ ...btn('#ea580c', '#fff'), marginTop: 24, fontWeight: 600 }}>
        {t('ui.backHome')}
      </button>
    </div>
  );
}

export default Account;
