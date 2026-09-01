import React, { useState, useEffect, useCallback } from 'react';
import { initReactI18next, useTranslation } from 'react-i18next';
import i18n from 'i18next';
import de from './translations/de.json';
import en from './translations/en.json';
import Impressum from './Impressum';
import Account from './Account';
import Stats from './Stats';
import {
  API, authHeaders, getToken, clearToken, formatRelativeDate, StarPicker,
  getVoterId, ThemeToggle, toDateKey,
} from './shared';

const ICON_BASE = 'https://www.studierendenwerk-goettingen.de/fileadmin/templates/images/mensaspeiseplan/png/';

// Initialize i18next
i18n
  .use(initReactI18next)
  .init({
    resources: {
      de: { translation: de },
      en: { translation: en }
    },
    lng: 'de', // Default language
    fallbackLng: 'de',
    interpolation: {
      escapeValue: false
    }
  });

const TYPE_ORDER = { main: 0, side: 1, dessert: 2 };

// Only the keys matter -- the labels come from the translation files and the
// colours from the .badge[data-tag] rules in components.css.
const TAG_KEYS = [
  'vegan', 'vegetarisch', 'fleisch', 'fisch',
  'strohschwein', 'leinetalerrind', 'NDS',
];

function formatDate(dateStr, lang) {
  const date = new Date(dateStr);
  const day = String(date.getDate()).padStart(2, '0');
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const year = date.getFullYear();
  const weekdayOptions = { weekday: 'short' };
  const weekday = date.toLocaleDateString(lang === 'en' ? 'en-GB' : 'de-DE', weekdayOptions);
  return `${weekday} ${day}.${month}.${year}`;
}

// Generate min/max date strings for input[type="date"].
// All three go through toDateKey (local), not toISOString (UTC) -- see shared.js.
function getMinDate() {
  const d = new Date();
  d.setDate(d.getDate() - 7);
  return toDateKey(d);
}

function getMaxDate() {
  const d = new Date();
  d.setDate(d.getDate() + 7);
  return toDateKey(d);
}

const today = () => toDateKey();

function IconLegend() {
  const { t } = useTranslation();
  return (
    <div className="legend">
      <span className="legend__title">{t('ui.legend')}</span>
      {TAG_KEYS.map(tag => (
        <div key={tag} className="legend__item">
          <img className="legend__icon" src={`${ICON_BASE}${tag}.png`} alt="" />
          <span>{t('tags.' + tag)}</span>
        </div>
      ))}
    </div>
  );
}

// -- loading placeholders ----------------------------------------------
// Shown in place of the old bare "Lade Menü..." line so the page keeps its
// shape while the request is in flight.

function DishCardSkeleton() {
  return (
    <div className="dish" aria-hidden="true">
      <div className="skeleton skeleton--title" />
      <div className="skeleton skeleton--sub" />
      <div className="skeleton skeleton--meta" />
    </div>
  );
}

function DishListSkeleton({ count = 5 }) {
  return (
    <div>
      {Array.from({ length: count }, (_, i) => <DishCardSkeleton key={i} />)}
    </div>
  );
}

function EmptyState({ icon, text, actionLabel, onAction }) {
  return (
    <div className="empty">
      <span className="empty__icon" aria-hidden="true">{icon}</span>
      <p className="empty__text">{text}</p>
      {actionLabel && (
        <button type="button" className="btn btn--primary" onClick={onAction}>
          {actionLabel}
        </button>
      )}
    </div>
  );
}

function App() {
  const { t, i18n } = useTranslation();
  const [menu, setMenu] = useState([]);
  const [date, setDate] = useState(today);
  const [filter, setFilter] = useState('all');
  const [sortMode, setSortMode] = useState('default');
  const [loading, setLoading] = useState(false);
  const [mensas, setMensas] = useState([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [includePast, setIncludePast] = useState(false);
  const [language, setLanguage] = useState('de');
  const [showImpressum, setShowImpressum] = useState(false);
  const [showStats, setShowStats] = useState(false);
  const [user, setUser] = useState(null);
  const [showAccount, setShowAccount] = useState(false);

  // Restore the session on load. A token the backend no longer recognises
  // (logged out elsewhere, DB reset) is dropped rather than left to 401 forever.
  useEffect(() => {
    if (!getToken()) return;
    fetch(`${API}/api/v1/me`, { headers: authHeaders() })
      .then(r => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(data => setUser({ username: data.username, display_name: data.display_name }))
      .catch(() => { clearToken(); setUser(null); });
  }, []);

  // Function to change language
  const changeLanguage = (lng) => {
    i18n.changeLanguage(lng);
    setLanguage(lng);
  };

  useEffect(() => {
    fetch(`${API}/api/v1/mensas`)
      .then(r => r.json())
      .then(m => setMensas(Array.isArray(m) ? m : ['Zentralmensa', 'CGiN', 'Mensa am Turm', 'Bistro HAWK']))
      .catch(() => setMensas(['Zentralmensa', 'CGiN', 'Mensa am Turm', 'Bistro HAWK']));
  }, []);

  // Navigate from a search result to the dish's day + mensa in the menu view.
  const navigateTo = (dateStr, mensa) => {
    setSearchQuery('');
    setSearchResults([]);
    setFilter(mensa || 'all');
    setDate(dateStr);
  };

  // Reset to the default view: today's menu with the search cleared and filter reset to all mensas.
  const goHome = () => {
    setSearchQuery('');
    setSearchResults([]);
    setFilter('all');
    setDate(today());
    setShowStats(false);
    setShowAccount(false);
    setShowImpressum(false);
  };

  // Only one secondary view is ever open, so opening one closes the others.
  const openView = (view) => {
    setShowStats(view === 'stats');
    setShowAccount(view === 'account');
    setShowImpressum(view === 'impressum');
  };

  useEffect(() => {
    setSearchQuery('');
    setSearchResults([]);
    setLoading(true);
    fetch(`${API}/api/v1/meals?date=${date}&lang=${language}`)
      .then(r => r.json())
      .then(data => {
        setMenu(Array.isArray(data) ? data : []);
        setLoading(false);
      })
      .catch(() => { setLoading(false); });
  }, [date, language]);

  const searchDishes = useCallback((query) => {
    if (!query || query.trim().length < 2) {
      setSearchResults([]);
      return;
    }
    setSearchLoading(true);
    fetch(`${API}/api/v1/meals/search?q=${encodeURIComponent(query.trim())}&past=${includePast}&lang=${language}`)
      .then(r => r.json())
      .then(data => { setSearchResults(Array.isArray(data) ? data : []); setSearchLoading(false); })
      .catch(() => { setSearchResults([]); setSearchLoading(false); });
  }, [includePast, language]);

  useEffect(() => {
    const timer = setTimeout(() => searchDishes(searchQuery), 300);
    return () => clearTimeout(timer);
  }, [searchQuery, searchDishes, language]);

  const filteredMenu = filter === 'all' ? menu : menu.filter(m => m.mensa === filter);
  const grouped = {};
  filteredMenu.forEach(m => {
    const key = m.mensa + '|' + m.type;
    if (!grouped[key]) grouped[key] = [];
    grouped[key].push(m);
  });

  const sortedKeys = Object.keys(grouped).sort((a, b) => {
    const [mensaA, typeA] = a.split('|');
    const [mensaB, typeB] = b.split('|');
    const mensaComp = mensaA.localeCompare(mensaB);
    if (mensaComp !== 0) return mensaComp;
    return (TYPE_ORDER[typeA] || 0) - (TYPE_ORDER[typeB] || 0);
  });

  const menuView = (
    <>
      <div className="toolbar">
        <input
          type="date"
          className="field"
          aria-label={t('ui.showToday')}
          value={date}
          onChange={e => { setFilter('all'); setDate(e.target.value); }}
          min={getMinDate()}
          max={getMaxDate()}
        />
        <select
          className="field"
          aria-label={t('ui.allMensas')}
          value={filter}
          onChange={e => setFilter(e.target.value)}
        >
          <option value="all">{t('ui.allMensas')}</option>
          {mensas.map(m => <option key={m} value={m}>{m}</option>)}
        </select>
        <select
          className="field"
          aria-label={t('ui.sortStandard')}
          value={sortMode}
          onChange={e => setSortMode(e.target.value)}
        >
          <option value="default">{t('ui.sortStandard')}</option>
          <option value="alpha">{t('ui.sortAlphabetical')}</option>
        </select>

        <div className="toolbar__search">
          <input
            type="search"
            className="field"
            placeholder={t('ui.searchPlaceholder')}
            aria-label={t('ui.searchPlaceholder')}
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
          />
          {searchQuery && (
            <button
              type="button"
              className="toolbar__clear"
              onClick={() => setSearchQuery('')}
              aria-label={t('ui.clearSearch')}
            >
              <span aria-hidden="true">&times;</span>
            </button>
          )}
        </div>

        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={includePast}
            onChange={e => setIncludePast(e.target.checked)}
          />
          {t('ui.includePast')}
        </label>
      </div>

      <IconLegend />

      <div aria-live="polite">
        {searchLoading ? (
          <DishListSkeleton count={3} />
        ) : searchResults.length > 0 ? (
          <>
            <p className="result-count">
              {t('ui.foundResults', { count: searchResults.length, query: searchQuery })}
              {!includePast && ' ' + t('ui.futureOnly')}
            </p>
            <SearchResults
              results={searchResults}
              onNavigate={navigateTo}
              formatDate={formatDate}
              language={language}
            />
          </>
        ) : loading ? (
          <DishListSkeleton count={5} />
        ) : searchQuery.trim().length >= 2 ? (
          <EmptyState
            icon="🔍"
            text={t('ui.foundResults', { count: 0, query: searchQuery })}
            actionLabel={t('ui.clearSearch')}
            onAction={() => setSearchQuery('')}
          />
        ) : menu.length === 0 ? (
          <EmptyState
            icon="🍽️"
            text={t('ui.noMenu')}
            actionLabel={date !== today() ? t('ui.showToday') : null}
            onAction={() => setDate(today())}
          />
        ) : filteredMenu.length === 0 ? (
          <EmptyState
            icon="🍽️"
            text={t('ui.noMeals', { filter })}
            actionLabel={t('ui.allMensas')}
            onAction={() => setFilter('all')}
          />
        ) : (
          sortedKeys.map(key => {
            const [mensa, type] = key.split('|');
            const rawItems = grouped[key];
            // Safety net: drop any duplicate dishes by name (backend already
            // returns a single language-correct row per dish).
            const seenNames = new Set();
            const items = rawItems.filter(item => {
              if (seenNames.has(item.name)) return false;
              seenNames.add(item.name);
              return true;
            });
            const sortedItems = sortMode === 'alpha'
              ? [...items].sort((a, b) => a.name.localeCompare(b.name))
              : items;
            return (
              <React.Fragment key={key}>
                {/* One heading per mensa+course, so the id needs both --
                    keying on the mensa alone produced duplicate ids. */}
                <h2 className="section-heading" id={`beilage-${mensa}-${type}`}>
                  {mensa} — {t('mealTypes.' + type) || type}
                </h2>
                {sortedItems.map(meal => (
                  <DishCard key={meal.id} meal={meal} />
                ))}
              </React.Fragment>
            );
          })
        )}
      </div>
    </>
  );

  return (
    <div className="app">
      <header className="site-header">
        <h1>
          <button
            type="button"
            className="wordmark"
            onClick={goHome}
            title={t('ui.backHome')}
          >
            {t('app.title')}
          </button>
        </h1>
        <p className="site-header__tagline">{t('app.subtitle')}</p>

        <nav className="site-nav" aria-label={t('ui.navLabel')}>
          <button type="button" className="nav-btn"
            aria-pressed={language === 'de'}
            onClick={() => changeLanguage('de')}>DE</button>
          <button type="button" className="nav-btn"
            aria-pressed={language === 'en'}
            onClick={() => changeLanguage('en')}>EN</button>
          <button type="button" className="nav-btn"
            aria-pressed={showStats}
            onClick={() => openView(showStats ? null : 'stats')}>
            {t('stats.title')}
          </button>
          <button type="button" className="nav-btn"
            aria-pressed={showAccount}
            onClick={() => openView(showAccount ? null : 'account')}>
            {user ? (user.display_name || user.username) : t('auth.login')}
          </button>
          <ThemeToggle />
        </nav>
      </header>

      <main className="page">
        {showStats ? (
          <Stats onBack={goHome} language={language} />
        ) : showAccount ? (
          <Account
            user={user}
            onAuth={u => setUser(u)}
            onLogout={() => setUser(null)}
            onBack={goHome}
            language={language}
          />
        ) : showImpressum ? (
          <Impressum onBack={goHome} />
        ) : menuView}
      </main>

      <footer className="site-footer">
        <div className="footer-links">
          <button type="button" className="btn--quiet"
            aria-pressed={showImpressum}
            onClick={() => openView(showImpressum ? null : 'impressum')}>
            {t('footer.impressum')}
          </button>
          <span className="footer-sep" aria-hidden="true">|</span>
          <a href="https://github.com/lufre1/rate-site"
            target="_blank" rel="noopener noreferrer">
            {t('footer.github')}
          </a>
        </div>
      </footer>
    </div>
  );
}

function SearchResults({ results, onNavigate, formatDate, language }) {
  const { t } = useTranslation();
  if (results.length === 0) return null;
  const grouped = {};
  results.forEach(m => {
    const key = m.date + '|' + m.mensa + '|' + m.type;
    if (!grouped[key]) grouped[key] = [];
    grouped[key].push(m);
  });

  const sortedKeys = Object.keys(grouped).sort((a, b) => {
    const [dA, mA] = a.split('|');
    const [dB, mB] = b.split('|');
    const dateComp = dB.localeCompare(dA);
    if (dateComp !== 0) return dateComp;
    return mA.localeCompare(mB);
  });

  return (
    <div>
      {sortedKeys.map(key => {
        const [dateStr, mensa, type] = key.split('|');
        const items = grouped[key];
        const dayLabel = formatDate(dateStr, language);
        return (
          <div key={key} className="result-group">
            <div className="result-group__head">
              <span className="result-group__mensa">{mensa}</span>
              <span className="badge" data-type={type}>{t('mealTypes.' + type) || type}</span>
              <button type="button" className="btn--quiet"
                onClick={() => onNavigate(dateStr, mensa)}>
                {dayLabel} &rarr;
              </button>
              <span className="result-group__count">({items.length})</span>
            </div>
            {items.map(meal => (
              <DishCardSearch key={meal.id} meal={meal} onNavigate={onNavigate} />
            ))}
          </div>
        );
      })}
    </div>
  );
}

function DishCardSearch({ meal, onNavigate }) {
  const { t } = useTranslation();
  const tags = typeof meal.tags === 'string' ? JSON.parse(meal.tags) : (meal.tags || []);

  return (
    <button
      type="button"
      className="result"
      onClick={() => onNavigate && onNavigate(meal.date, meal.mensa)}
      title={`${meal.mensa} · ${meal.date}`}
    >
      <span className="result__name">{meal.name}</span>
      {tags.length > 0 && (
        <span className="result__tags">
          {tags.map(tag => (
            <img
              key={tag}
              className="tag-icon tag-icon--sm"
              src={`${ICON_BASE}${tag}`}
              alt=""
              title={t('tags.' + tag.replace('.png', '')) || tag}
              onError={(e) => { e.target.style.display = 'none'; }}
            />
          ))}
        </span>
      )}
      {meal.rating_count > 0 && (
        <span className="result__rating">
          {'★'.repeat(Math.round(meal.avg_rating))} {meal.avg_rating} ({meal.rating_count})
        </span>
      )}
    </button>
  );
}

function IconTags({ tags }) {
  const { t } = useTranslation();
  if (!tags || tags.length === 0) return null;
  return (
    <span className="tag-icons">
      {tags.map(tag => (
        <img
          key={tag}
          className="tag-icon"
          src={`${ICON_BASE}${tag}`}
          alt={t('tags.' + tag.replace('.png', '')) || tag}
          onError={(e) => { e.target.style.display = 'none'; }}
        />
      ))}
    </span>
  );
}

// One "★★★☆☆  <label> 4.2 (12)" line. Used for the recent and overall averages.
function RatingLine({ avg, count, label, tone }) {
  const rounded = Math.round(avg);
  return (
    <div className="rating-line">
      <span className="stars" aria-hidden="true">
        {'★'.repeat(rounded)}{'☆'.repeat(Math.max(0, 5 - rounded))}
      </span>
      <span className="rating-line__label" data-tone={tone}>
        {label} {avg.toFixed(1)} ({count})
      </span>
    </div>
  );
}

function Lightbox({ src, alt, onClose }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div className="lightbox" role="dialog" aria-modal="true" aria-label={alt}
      onClick={onClose}>
      <img className="lightbox__img" src={src} alt={alt}
        onClick={(e) => e.stopPropagation()} />
    </div>
  );
}

function SideRatingRow({ mealId, sideName, avgRating, ratingCount, recentAvg = 0, recentCount = 0 }) {
  const { t } = useTranslation();
  const [rating, setRating] = useState(0);
  const [justRated, setJustRated] = useState(false);
  const [comment, setComment] = useState('');
  const [showComment, setShowComment] = useState(false);

  const handleRate = async (i) => {
    setRating(i);
    setJustRated(true);
    setTimeout(() => setJustRated(false), 1500);
    await fetch(`${API}/api/v1/meals/${mealId}/side-ratings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ side_name: sideName, rating: i, comment: comment || null }),
    });
  };

  return (
    <div className="side-row">
      <span className="side-row__name">{sideName}</span>
      {recentCount > 0 && (
        <span className="badge badge--positive">
          {t('ui.recent')} {recentAvg.toFixed(1)} ({recentCount}) ★
        </span>
      )}
      {ratingCount > 0 && (
        <span className="hint-text">
          {'★'.repeat(Math.round(avgRating))} {avgRating} {t('ui.overall')} ({ratingCount})
        </span>
      )}
      <StarPicker value={rating} onChange={handleRate} size={16} />
      <span aria-live="polite">
        {justRated && <span className="badge badge--positive">{t('ui.thanksForRating')}</span>}
      </span>
      {showComment && (
        <input
          type="text"
          className="field"
          placeholder={t('ui.sideComment')}
          aria-label={t('ui.sideComment')}
          value={comment}
          onChange={(e) => setComment(e.target.value)}
        />
      )}
      <button
        type="button"
        className="btn--quiet"
        onClick={() => setShowComment(!showComment)}
        aria-expanded={showComment}
        title={comment ? t('ui.removeComment') : t('ui.addComment')}
      >
        <span aria-hidden="true">{comment ? '✏️' : '💬'}</span>
        <span className="sr-only">{comment ? t('ui.removeComment') : t('ui.addComment')}</span>
      </button>
    </div>
  );
}

function DishCard({ meal }) {
  const { t } = useTranslation();
  const [rating, setRating] = useState(0);
  const [comment, setComment] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [reviews, setReviews] = useState({
    recent: { ratings: [], avg: 0, count: 0 },
    overall: { avg: 0, count: 0 },
    comments: []
  });
  const [showRatingForm, setShowRatingForm] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [selectedImage, setSelectedImage] = useState(null);
  const [imagePreview, setImagePreview] = useState(null);
  const [imageError, setImageError] = useState('');
  const [enlargedImage, setEnlargedImage] = useState(null);
  const [topPhoto, setTopPhoto] = useState(null);

  // Fetch ratings-breakdown on mount (not just when expanded)
  useEffect(() => {
    fetch(`${API}/api/v1/meals/${meal.id}/ratings-breakdown`)
      .then(r => r.json())
      .then(data => {
        setReviews({
          recent: data.recent || { ratings: [], avg: 0, count: 0 },
          overall: data.overall || { avg: 0, count: 0 },
          comments: data.comments || []
        });
      })
      .catch(() => {});
  }, [meal.id]);

  // Fetch top photo on mount
  useEffect(() => {
    fetch(`${API}/api/v1/meals/${meal.id}/top-photo`)
      .then(r => r.json())
      .then(data => { setTopPhoto(data.photo_url); })
      .catch(() => {});
  }, [meal.id]);

  const submitRating = async () => {
    if (rating === 0) return;
    if (uploading) return;

    setUploading(true);
    setImageError('');

    try {
      let response;
      if (selectedImage) {
        const formData = new FormData();
        formData.append('rating', rating);
        if (comment) formData.append('comment', comment);
        formData.append('photo', selectedImage);

        response = await fetch(`${API}/api/v1/meals/${meal.id}/ratings-with-photo`, {
          method: 'POST',
          headers: authHeaders(),
          body: formData,
        });
      } else {
        response = await fetch(`${API}/api/v1/meals/${meal.id}/ratings`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...authHeaders() },
          body: JSON.stringify({ rating, comment: comment || null }),
        });
      }

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
      }

      setSubmitted(true);
    } catch (err) {
      setImageError(err.message || t('ui.photoError'));
    } finally {
      setUploading(false);
      setTimeout(() => {
        setSubmitted(false);
        setRating(0);
        setComment('');
        setSelectedImage(null);
        setImagePreview(null);
      }, 1500);
    }
  };

  const handleVote = async (ratingId, direction) => {
    try {
      const voterId = getVoterId();
      if (!voterId) return;

      const response = await fetch(`${API}/api/v1/ratings/${ratingId}/vote`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', 'X-Voter-Id': voterId, ...authHeaders() },
        body: JSON.stringify({ direction }),
      });

      if (response.ok) {
        const data = await response.json();
        setReviews(prev => ({
          ...prev,
          comments: prev.comments.map(c =>
            c.id === ratingId
              ? { ...c, score: data.score, vote_direction: data.direction }
              : c
          )
        }));
      }
    } catch (e) {
      // Silent fail - voting is optional
    }
  };

  const pickImage = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const validTypes = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp'];
    if (!validTypes.includes(file.type)) {
      setImageError(t('ui.photoTypeError'));
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      setImageError(t('ui.photoSizeError'));
      return;
    }
    setSelectedImage(file);
    const reader = new FileReader();
    reader.onloadend = () => { setImagePreview(reader.result); };
    reader.readAsDataURL(file);
  };

  let tags = [];
  try {
    tags = typeof meal.tags === 'string' ? JSON.parse(meal.tags) : (meal.tags || []);
  } catch (e) {
    tags = []; // Fallback to empty array on parse error
  }

  // The API already returns name/description in the selected language.
  const displayName = meal.name;
  const displayDescription = meal.description || '';
  const noBreakdown = reviews.overall.count === 0 && reviews.recent.count === 0;

  return (
    <div className="dish">
      <button type="button" className="dish__toggle"
        onClick={() => setExpanded(e => !e)} aria-expanded={expanded}>
        <span className="dish__main">
          <span className="dish__titlerow">
            <span className="dish__name" data-unavailable={meal.is_available === false}>
              {displayName}
            </span>
            <span className="badge badge--upper" data-type={meal.type}>
              {t('mealTypes.' + meal.type)}
            </span>
            {meal.is_available === false && (
              <span className="badge badge--upper badge--danger">{t('ui.notAvailable')}</span>
            )}
            <IconTags tags={tags} />
          </span>
          {displayDescription && typeof displayDescription === 'string' && (
            <span className="dish__desc">{displayDescription.replace(/, +/g, ', ')}</span>
          )}
        </span>

        <span className="dish__meta">
          {reviews.recent.count > 0 && (
            <RatingLine avg={reviews.recent.avg} count={reviews.recent.count}
              label={t('ui.recent')} tone="recent" />
          )}
          {reviews.overall.count > 0 && (
            <RatingLine avg={reviews.overall.avg} count={reviews.overall.count}
              label={t('ui.overall')} />
          )}
          {/* Fallback to meal.avg_rating if no detailed breakdown available */}
          {noBreakdown && meal.rating_count > 0 && (
            <RatingLine avg={meal.avg_rating} count={meal.rating_count}
              label={t('ui.recent')} tone="recent" />
          )}
          <span className="dish__chevron" aria-hidden="true">{expanded ? '▲' : '▼'}</span>
        </span>
      </button>

      {/* Outside the toggle: a button inside a button is invalid markup, and as
          a bare <img onClick> this was unreachable by keyboard. */}
      {topPhoto && (
        <>
          <button type="button" className="dish__photo-btn"
            onClick={() => setEnlargedImage(`${API}${topPhoto}`)}>
            <img className="dish__photo" src={`${API}${topPhoto}`} alt={t('ui.topPhoto')} />
          </button>
          <p className="dish__photo-caption">{t('ui.topPhoto')}</p>
        </>
      )}

      {expanded && (
        <div className="dish__body">
          {reviews.comments.length === 0 ? (
            <p className="muted-text">{t('ui.noReviews')}</p>
          ) : (
            reviews.comments.map(r => (
              <div key={r.id} className="review">
                <div className="review__head">
                  <span className="review__author">{r.user_name || 'Anonymous'}</span>
                  <span className="stars" aria-hidden="true">
                    {'★'.repeat(r.rating)}{'☆'.repeat(5 - r.rating)}
                  </span>
                  <span className="sr-only">{t('ui.starLabel', { count: r.rating })}</span>
                  {r.created_at && <span>{formatRelativeDate(r.created_at, t)}</span>}
                  {r.is_recent && (
                    <span className="badge badge--positive">({t('ui.recent')})</span>
                  )}
                </div>
                {r.comment && <p className="review__text">{r.comment}</p>}
                <div className="review__votes">
                  <button type="button" className="vote-btn" data-dir="up"
                    aria-pressed={r.vote_direction === 1}
                    onClick={() => handleVote(r.id, 1)}
                    title={t('ui.upvote')} aria-label={t('ui.upvote')}>
                    <span aria-hidden="true">▲</span>
                    {r.score > 0 ? `+${r.score}` : r.score}
                  </button>
                  <button type="button" className="vote-btn" data-dir="down"
                    aria-pressed={r.vote_direction === -1}
                    onClick={() => handleVote(r.id, -1)}
                    title={t('ui.downvote')} aria-label={t('ui.downvote')}>
                    <span aria-hidden="true">▼</span>
                  </button>
                </div>
                {r.photo_url && (
                  <button type="button" className="review__photo-btn"
                    onClick={() => setEnlargedImage(`${API}${r.photo_url}`)}>
                    <img className="review__photo" src={`${API}${r.photo_url}`}
                      alt={t('ui.enlargedPhoto')}
                      onError={(e) => { e.target.style.display = 'none'; }} />
                  </button>
                )}
              </div>
            ))
          )}

          <button type="button" className="btn--quiet"
            onClick={() => setShowRatingForm(!showRatingForm)}
            aria-expanded={showRatingForm}>
            <span aria-hidden="true">{showRatingForm ? '▲' : '▼'}</span> {t('ui.rate')}
          </button>

          {showRatingForm && (
            <div className="rating-form" aria-live="polite">
              {submitted ? (
                <p className="badge badge--positive">{t('ui.thanksForRating')}</p>
              ) : (
                <>
                  <StarPicker value={rating} onChange={setRating} size={22} />

                  {imageError && <p className="error-text">{imageError}</p>}

                  <div className="rating-form__photo">
                    {imagePreview ? (
                      <div className="preview">
                        <img className="preview__img" src={imagePreview} alt="" />
                        <button
                          type="button"
                          className="preview__remove"
                          onClick={() => { setSelectedImage(null); setImagePreview(null); setImageError(''); }}
                          title={t('ui.removePhoto')}
                          aria-label={t('ui.removePhoto')}
                        >
                          <span aria-hidden="true">&times;</span>
                        </button>
                      </div>
                    ) : (
                      <label className="dropzone">
                        <input
                          type="file"
                          accept="image/jpeg,image/jpg,image/png,image/webp"
                          onChange={pickImage}
                          className="sr-only"
                        />
                        <span className="dropzone__title">{t('ui.uploadPhoto')}</span>
                        <span className="dropzone__hint">JPG, PNG, WebP (max 5MB)</span>
                      </label>
                    )}
                  </div>

                  <div className="rating-form__row">
                    <textarea
                      className="field field--textarea"
                      placeholder={t('ui.rate')}
                      aria-label={t('ui.rate')}
                      value={comment}
                      onChange={e => setComment(e.target.value)}
                      rows={Math.max(2, comment.split('\n').length)}
                    />
                    <button
                      type="button"
                      className="btn btn--primary"
                      onClick={submitRating}
                      disabled={rating === 0 || uploading}
                    >
                      {uploading ? t('ui.uploading') : t('ui.rate')}
                    </button>
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      )}

      {enlargedImage && (
        <Lightbox src={enlargedImage} alt={t('ui.enlargedPhoto')}
          onClose={() => setEnlargedImage(null)} />
      )}
    </div>
  );
}

export default App;
