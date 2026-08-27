import React, { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { API, authHeaders, setToken, clearToken, formatRelativeDate, StarPicker } from './shared';

const btn = (bg, color) => ({
  padding: '8px 16px', background: bg, color, border: 'none',
  borderRadius: 4, cursor: 'pointer', fontSize: '0.875rem'
});

const input = {
  width: '100%', padding: '0.5rem', borderRadius: '0.5rem',
  border: '1px solid #d1d5db', fontSize: '0.875rem', marginBottom: 8
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
      onAuth({ username: data.username });
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
            style={btn(mode === m ? '#3b82f6' : '#e5e7eb', mode === m ? '#fff' : '#374151')}>
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
      {error && <p style={{ color: '#dc2626', fontSize: '0.8125rem', margin: '0 0 8px' }}>{error}</p>}
      <button type="submit" disabled={busy || !username || !password}
        style={{ ...btn(busy || !username || !password ? '#d1d5db' : '#3b82f6', '#fff'), width: '100%' }}>
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
    <div style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: 8,
      padding: '10px 12px', marginBottom: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontSize: '0.9375rem', fontWeight: 600, color: '#111827' }}>{entry.meal_name}</div>
          <div style={{ fontSize: '0.75rem', color: '#6b7280' }}>
            {entry.mensa}
            {entry.created_at && ` · ${formatRelativeDate(entry.created_at, t)}`}
          </div>
        </div>
        <span style={{ color: '#f59e0b', fontSize: '0.875rem', whiteSpace: 'nowrap' }}>
          {'★'.repeat(entry.rating)}{'☆'.repeat(5 - entry.rating)}
        </span>
      </div>

      {editing ? (
        <div style={{ marginTop: 8 }}>
          <StarPicker value={rating} onChange={setRating} size={18} />
          <textarea value={comment} onChange={e => setComment(e.target.value)} rows={2}
            style={{ ...input, marginTop: 4, resize: 'vertical' }} />
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={save} disabled={busy} style={btn('#3b82f6', '#fff')}>{t('auth.save')}</button>
            <button onClick={() => { setEditing(false); setRating(entry.rating); setComment(entry.comment || ''); }}
              style={btn('#e5e7eb', '#374151')}>{t('auth.cancel')}</button>
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
              maxHeight: 100, borderRadius: 6, border: '1px solid #e5e7eb', display: 'block' }}
              onError={e => { e.target.style.display = 'none'; }} />
          )}
          <div style={{ display: 'flex', gap: 12, marginTop: 6 }}>
            <button onClick={() => setEditing(true)} disabled={busy}
              style={{ background: 'none', border: 'none', color: '#3b82f6', cursor: 'pointer',
                fontSize: '0.75rem', padding: 0 }}>{t('auth.edit')}</button>
            <button onClick={remove} disabled={busy}
              style={{ background: 'none', border: 'none', color: '#dc2626', cursor: 'pointer',
                fontSize: '0.75rem', padding: 0 }}>{t('auth.delete')}</button>
          </div>
        </>
      )}
    </div>
  );
}

function Profile({ user, onLogout, language }) {
  const { t } = useTranslation();
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

  const logout = async () => {
    await fetch(`${API}/api/v1/auth/logout`, { method: 'POST', headers: authHeaders() }).catch(() => {});
    clearToken();
    onLogout();
  };

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        gap: 8, flexWrap: 'wrap', marginBottom: 16 }}>
        <span style={{ fontSize: '1rem', color: '#374151' }}>
          {t('auth.signedInAs')} <strong>{user.username}</strong>
        </span>
        <button onClick={logout} style={btn('#e5e7eb', '#374151')}>{t('auth.logout')}</button>
      </div>

      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        {[['mine', 'auth.myRatings'], ['favourites', 'auth.favourites']].map(([key, label]) => (
          <button key={key} onClick={() => setTab(key)}
            style={btn(tab === key ? '#3b82f6' : '#e5e7eb', tab === key ? '#fff' : '#374151')}>
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

  return (
    <div style={{ maxWidth: '600px', margin: '0 auto', padding: '24px' }}>
      <h1 style={{ fontSize: '1.5rem', fontWeight: 'bold', color: '#1f2937', marginBottom: '24px' }}>
        {t('auth.account')}
      </h1>
      {user
        ? <Profile user={user} onLogout={onLogout} language={language} />
        : <AuthForm onAuth={onAuth} />}
      <button onClick={onBack} style={{ ...btn('#3b82f6', '#fff'), marginTop: 24 }}>
        {t('ui.backHome')}
      </button>
    </div>
  );
}

export default Account;
