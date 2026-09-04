import React, { useState, useEffect, useCallback, useRef } from 'react';
import { initReactI18next, useTranslation } from 'react-i18next';
import i18n from 'i18next';
import de from './translations/de.json';
import en from './translations/en.json';
import Impressum from './Impressum';
import Datenschutz from './Datenschutz';
import Account from './Account';
import Stats from './Stats';
import { useToast } from './Toast';
import {
  API, authHeaders, getToken, clearToken, formatRelativeDate, StarPicker,
  getVoterId, voteHeaders, ThemeToggle, toDateKey,
} from './shared';

const ICON_BASE = 'https://www.studierendenwerk-goettingen.de/fileadmin/templates/images/mensaspeiseplan/png/';

// Shown when GET /api/v1/mensas fails, so the filter still works. The user is
// told, because a wrong list must not look authoritative.
const FALLBACK_MENSAS = ['Zentralmensa', 'CGiN', 'Mensa am Turm', 'Bistro HAWK'];

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

// Switching view kept the old scroll offset, so opening Datenschutz from the
// footer landed the reader in the middle of the document.
function scrollToTop() {
  const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
  window.scrollTo?.({ top: 0, behavior: reduce ? 'auto' : 'smooth' });
}

// A <details>, not a permanent block: seven items across the full width cost
// ~60px of every phone viewport for a key that is read once.
function IconLegend() {
  const { t } = useTranslation();
  return (
    <details className="legend">
      <summary className="legend__summary">{t('ui.legend')}</summary>
      <div className="legend__items">
        {TAG_KEYS.map(tag => (
          <div key={tag} className="legend__item">
            <img className="legend__icon" src={`${ICON_BASE}${tag}.png`} alt="" />
            <span>{t('tags.' + tag)}</span>
          </div>
        ))}
      </div>
    </details>
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
  const notify = useToast();
  const [menu, setMenu] = useState([]);
  // Per-meal `recent` figures and top photo, keyed by meal id, from the single
  // /api/v1/meals-summary request the effect below makes for the whole page.
  const [summaries, setSummaries] = useState({});
  const [date, setDate] = useState(today);
  const [filter, setFilter] = useState('all');
  const [sortMode, setSortMode] = useState('default');
  const [loading, setLoading] = useState(false);
  const [mensas, setMensas] = useState([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [searchLoading, setSearchLoading] = useState(false);
  // A failed request and an empty result are different facts. Conflating them
  // made the UI blame the user's date or query for a network error.
  const [menuError, setMenuError] = useState(false);
  const [searchError, setSearchError] = useState(false);
  // Bumped by the retry button. `setDate(d => d)` cannot work here: the value
  // is unchanged, so React bails out and the effect never re-runs.
  const [menuReload, setMenuReload] = useState(0);
  // The toolbar is sticky, so everything in it costs screen space on every
  // scroll. Date and search stay out; the rest collapses. In-memory only:
  // remembering it would need a new localStorage key, and Datenschutz.js
  // enumerates those (legal.test.js asserts the list).
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [includePast, setIncludePast] = useState(false);
  const [language, setLanguage] = useState('de');
  const [showImpressum, setShowImpressum] = useState(false);
  const [showDatenschutz, setShowDatenschutz] = useState(false);
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

  // index.html hardcodes lang="de", so without this a screen reader reads the
  // English site with German pronunciation rules.
  useEffect(() => { document.documentElement.lang = language; }, [language]);

  useEffect(() => {
    fetch(`${API}/api/v1/mensas`)
      .then(r => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(m => setMensas(Array.isArray(m) ? m : FALLBACK_MENSAS))
      .catch(() => {
        // The hardcoded list keeps the filter usable, but substituting it
        // without a word means a stale or wrong mensa list looks authoritative.
        setMensas(FALLBACK_MENSAS);
        notify(t('ui.mensasFailed'));
      });
    // notify is useCallback-stable and t changes only with the language, so
    // this refetches at most once per language toggle.
  }, [notify, t]);

  // Navigate from a search result to the dish's day + mensa in the menu view.
  const navigateTo = (dateStr, mensa) => {
    setSearchQuery('');
    setSearchResults([]);
    setFilter(mensa || 'all');
    setDate(dateStr);
  };

  // Reset to the default view: today's menu with the search cleared and filter reset to all mensas.
  const goHome = () => {
    scrollToTop();
    setSearchQuery('');
    setSearchResults([]);
    setFilter('all');
    setDate(today());
    setShowStats(false);
    setShowAccount(false);
    setShowImpressum(false);
    setShowDatenschutz(false);
  };

  // Only one secondary view is ever open, so opening one closes the others.
  const openView = (view) => {
    scrollToTop();
    setShowStats(view === 'stats');
    setShowAccount(view === 'account');
    setShowImpressum(view === 'impressum');
    setShowDatenschutz(view === 'datenschutz');
  };

  useEffect(() => {
    setSearchQuery('');
    setSearchResults([]);
    setSearchError(false);
    setLoading(true);
    setMenuError(false);
    setSummaries({});
    // Guards against a slower response for a previous date landing after this
    // one -- the two chained requests below make that race reachable.
    let cancelled = false;
    fetch(`${API}/api/v1/meals?date=${date}&lang=${language}`)
      .then(r => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(data => {
        if (cancelled) return;
        const meals = Array.isArray(data) ? data : [];
        setMenu(meals);
        setLoading(false);
        if (!meals.length) return;
        // ONE request for the whole page. Every DishCard used to fetch its own
        // ratings-breakdown and top-photo on mount: 66 requests for a 33-dish
        // menu, all queueing for a 10-connection pool, which is what made the
        // site stall for ~10s whenever anything else held a connection.
        fetch(`${API}/api/v1/meals-summary?ids=${meals.map(m => m.id).join(',')}`)
          .then(r => (r.ok ? r.json() : Promise.reject(r.status)))
          .then(s => { if (!cancelled) setSummaries(s || {}); })
          .catch(() => {
            // Without this the page silently loses every "aktuell" average and
            // every dish photo, and reads as "nobody has ever rated anything".
            if (!cancelled) notify(t('ui.summaryFailed'));
          });
      })
      .catch(() => { if (!cancelled) { setMenuError(true); setLoading(false); } });
    return () => { cancelled = true; };
  }, [date, language, menuReload, notify, t]);

  const searchDishes = useCallback((query) => {
    if (!query || query.trim().length < 2) {
      setSearchResults([]);
      setSearchError(false);
      return;
    }
    setSearchLoading(true);
    setSearchError(false);
    fetch(`${API}/api/v1/meals/search?q=${encodeURIComponent(query.trim())}&past=${includePast}&lang=${language}`)
      .then(r => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(data => { setSearchResults(Array.isArray(data) ? data : []); setSearchLoading(false); })
      .catch(() => { setSearchResults([]); setSearchError(true); setSearchLoading(false); });
  }, [includePast, language]);

  useEffect(() => {
    const timer = setTimeout(() => searchDishes(searchQuery), 300);
    return () => clearTimeout(timer);
  }, [searchQuery, searchDishes, language]);

  // Named in the collapsed toggle, so nothing is hidden invisibly.
  const filterSummary = [
    filter === 'all' ? t('ui.allMensas') : filter,
    sortMode === 'alpha' ? t('ui.sortAlphabetical') : null,
    includePast ? t('ui.includePast') : null,
  ].filter(Boolean).join(' \u00b7 ');

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
        {/* Date and search stay out of the disclosure: they are the two
            controls a lunch menu is actually used through. */}
        <input
          type="date"
          className="field"
          aria-label={t('ui.pickDate')}
          value={date}
          onChange={e => { if (e.target.value) setDate(e.target.value); }}
          min={getMinDate()}
          max={getMaxDate()}
        />

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

        {/* The label names what is active, so a collapsed panel never hides a
            filter the user has forgotten they set. */}
        <button
          type="button"
          className="toolbar__toggle"
          onClick={() => setFiltersOpen(v => !v)}
          aria-expanded={filtersOpen}
          aria-controls="toolbar-filters"
          aria-label={filtersOpen ? t('ui.hideFilters') : t('ui.showFilters')}
        >
          <span aria-hidden="true">{filtersOpen ? '▲' : '▼'}</span>
          <span>{t('ui.filters')}</span>
          <span className="toolbar__summary">{filterSummary}</span>
        </button>

        <div className="toolbar__panel" id="toolbar-filters" hidden={!filtersOpen}>
          <select
            className="field"
            aria-label={t('ui.filterByMensa')}
            value={filter}
            onChange={e => setFilter(e.target.value)}
          >
            <option value="all">{t('ui.allMensas')}</option>
            {mensas.map(m => <option key={m} value={m}>{m}</option>)}
          </select>
          <select
            className="field"
            aria-label={t('ui.sortBy')}
            value={sortMode}
            onChange={e => setSortMode(e.target.value)}
          >
            <option value="default">{t('ui.sortStandard')}</option>
            <option value="alpha">{t('ui.sortAlphabetical')}</option>
          </select>

          {/* Only affects search, which is why it reads as a stray menu
              filter out in the open. */}
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={includePast}
              onChange={e => setIncludePast(e.target.checked)}
            />
            {t('ui.includePast')}
          </label>
        </div>
      </div>

      <IconLegend />

      {/* Announce only the COUNT. This wrapper used to be aria-live and hold
          the entire list, so every card expand, every vote and every skeleton
          swap re-announced the whole menu. */}
      <p className="sr-only" role="status">
        {searchResults.length > 0
          ? t('ui.foundResults', { count: searchResults.length, query: searchQuery })
          : t('ui.dishCount', { count: filteredMenu.length })}
      </p>

      <div>
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
        ) : searchError ? (
          <EmptyState
            icon="⚠️"
            text={t('ui.searchLoadError')}
            actionLabel={t('ui.retry')}
            onAction={() => searchDishes(searchQuery)}
          />
        ) : searchQuery.trim().length >= 2 ? (
          <EmptyState
            icon="🔍"
            text={t('ui.foundResults', { count: 0, query: searchQuery })}
            actionLabel={t('ui.clearSearch')}
            onAction={() => setSearchQuery('')}
          />
        ) : menuError ? (
          // Checked BEFORE menu.length: an empty `menu` after a failed request
          // is not an empty menu, and offering "show today" for a network
          // failure sends the user round the same loop.
          <EmptyState
            icon="⚠️"
            text={t('ui.menuLoadError')}
            actionLabel={t('ui.retry')}
            onAction={() => setMenuReload(n => n + 1)}
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
                  <DishCard key={meal.id} meal={meal} summary={summaries[meal.id]}
                    user={user} onSignIn={() => openView('account')} />
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
      <a className="skip-link" href="#main">{t('ui.skipToContent')}</a>

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

      <main className="page" id="main" tabIndex={-1}>
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
        ) : showDatenschutz ? (
          <Datenschutz onBack={goHome} />
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
          <button type="button" className="btn--quiet"
            aria-pressed={showDatenschutz}
            onClick={() => openView(showDatenschutz ? null : 'datenschutz')}>
            {t('footer.datenschutz')}
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
          <span aria-hidden="true">{'★'.repeat(Math.round(meal.avg_rating))}</span>
          {' '}{meal.avg_rating} ({meal.rating_count})
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

// aria-modal="true" tells assistive tech that everything outside is
// unavailable, so this has to actually behave that way: something focusable
// inside, focus moved in and returned on close, Tab kept in, and a visible
// way out. Previously the only exit was tapping the sliver of backdrop around
// a 90vw/90vh image -- the image itself stops propagation.
function Lightbox({ src, alt, onClose }) {
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

// Mirrors RatingInput's max_length in main.py. A client-only cap would be
// cosmetic; a server-only cap would reject a comment after the user wrote it.
const COMMENT_MAX = 1000;

// FastAPI's `detail` strings (main.py) are English and the UI defaults to
// German, so never render one raw. The two known 400s map onto the existing
// specific photo messages; everything else gets one honest line that also says
// the user's text is still there -- which is now true.
function submitErrorMessage(err, t) {
  if (err.status === undefined) return t('ui.submitErrorNetwork'); // fetch itself rejected
  const detail = String(err.detail || '');
  if (/size exceeds/i.test(detail)) return t('ui.photoSizeError');
  if (/file type/i.test(detail)) return t('ui.photoTypeError');
  return t('ui.submitError');
}

function DishCard({ meal, summary, user, onSignIn }) {
  const { t } = useTranslation();
  const notify = useToast();
  const [rating, setRating] = useState(0);
  const [comment, setComment] = useState('');
  // null | 'saved' | 'starsOnly'. Persists until the next deliberate
  // interaction -- the old boolean was cleared by a 1500 ms timer.
  const [submitStatus, setSubmitStatus] = useState(null);
  // Only the comment list still needs its own request. The two figures the
  // collapsed card shows arrive with the page: `overall` from the meal list
  // (GET /api/v1/meals aggregates it over the same (name, mensa_id)) and
  // `recent` plus the top photo from the single /meals-summary call. Once the
  // card has been expanded, ratings-breakdown's own figures take over (`stats`
  // below) so a rating submitted here moves them without a reload.
  const [reviews, setReviews] = useState({ comments: [] });
  const [showRatingForm, setShowRatingForm] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [selectedImage, setSelectedImage] = useState(null);
  const [imagePreview, setImagePreview] = useState(null);
  // Not `imageError`: the same state now carries text-only submit failures,
  // whose old fallback message ("Fehler beim Hochladen") was simply wrong.
  const [submitError, setSubmitError] = useState('');
  const [enlargedImage, setEnlargedImage] = useState(null);
  // undefined = not overridden, so a re-vote that clears the winner is still
  // distinguishable from "use whatever the page load reported".
  const [votedTopPhoto, setVotedTopPhoto] = useState(undefined);
  // Ids this visitor created while this card has been mounted. Session-only on
  // purpose -- see the .review[data-mine] comment in components.css.
  const [myReviewIds, setMyReviewIds] = useState([]);
  // `recent`/`overall` as last recomputed by ratings-breakdown. null = never
  // fetched, so the figures that arrived with the page still win.
  const [stats, setStats] = useState(null);
  const [scrollToId, setScrollToId] = useState(null);
  // `reviews` starts empty, so without these every expand flashed "Noch keine
  // Bewertungen" before the request landed -- and showed it forever if the
  // request failed, which is the same lie the menu empty state told.
  const [reviewsLoading, setReviewsLoading] = useState(false);
  const [reviewsError, setReviewsError] = useState(false);
  // Anonymous rows are owned by nobody (owned_rating() in main.py), so an
  // anonymous post is permanent. Confirm it instead of silently publishing it.
  // Signed-in users can edit and delete from their profile, so for them this
  // step would be pure friction.
  const [confirming, setConfirming] = useState(false);
  const myRowRef = useRef(null);
  const commentRef = useRef(null);
  const errorId = `rating-error-${meal.id}`;

  // The breakdown's own figures win once fetched: it groups by exactly the same
  // (name, mensa_id) as /meals-summary and /meals, so a rating submitted here
  // moves both lines without a page reload.
  const recent = stats?.recent ?? summary?.recent ?? { avg: 0, count: 0 };
  const overall = stats?.overall ?? { avg: meal.avg_rating || 0, count: meal.rating_count || 0 };
  const topPhoto = votedTopPhoto !== undefined ? votedTopPhoto : (summary?.top_photo ?? null);
  // The API defines "recent" as TODAY's servings of this dish, not the card's
  // date (main.py), so on any other day the figure describes different meals.
  const isToday = String(meal.date) === today();

  // The comment list is the expensive half -- ~6 queries per dish -- and is only
  // rendered once the card is open, so it loads on expand rather than on mount.
  // voteHeaders() carries X-Voter-Id: without it the API cannot tell which
  // comments and photos this viewer already voted on, and every button renders
  // un-pressed.
  const loadBreakdown = useCallback(() => {
    setReviewsLoading(true);
    setReviewsError(false);
    return fetch(`${API}/api/v1/meals/${meal.id}/ratings-breakdown`, { headers: voteHeaders() })
      .then(r => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(data => {
        setReviews({ comments: data.comments || [] });
        // The same two figures the collapsed card shows, recomputed server-side.
        if (data.recent && data.overall) setStats({ recent: data.recent, overall: data.overall });
        setReviewsLoading(false);
        return data;
      })
      .catch(() => { setReviewsError(true); setReviewsLoading(false); return null; });
  }, [meal.id]);

  useEffect(() => { if (expanded) loadBreakdown(); }, [expanded, loadBreakdown]);

  const loadTopPhoto = useCallback(() => {
    fetch(`${API}/api/v1/meals/${meal.id}/top-photo`)
      .then(r => r.json())
      .then(data => { setVotedTopPhoto(data.photo_url ?? null); })
      .catch(() => {});
  }, [meal.id]);

  const submitRating = async () => {
    if (rating === 0) return;
    if (uploading) return;
    // First submit by an anonymous visitor only opens the preview. It stays
    // open if the request fails, so retrying is one tap on the same button.
    if (!user && !confirming) { setConfirming(true); return; }

    // Read at click time: the resets below are queued state updates, not
    // synchronous reassignments, so the closure would still see the old values
    // -- but naming them here makes that not something to reason about.
    const hadPhoto = Boolean(selectedImage);
    const hadComment = Boolean(comment);

    setUploading(true);
    setSubmitError('');
    setSubmitStatus(null);

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
        throw Object.assign(new Error('submit failed'),
          { status: response.status, detail: errorData.detail });
      }

      // The full created row: id, created_at, photo_url, and user_name as the
      // SERVER decided it (rating_identity() ignores any client-sent name).
      const created = await response.json();

      // Reset only now that it actually succeeded. This used to run on a
      // 1500 ms timer in `finally`, which also wiped the user's typed comment
      // 1.5 s after a FAILED submit, while the error was still on screen.
      setRating(0);
      setComment('');
      setSelectedImage(null);
      setImagePreview(null);
      setConfirming(false);
      setShowRatingForm(false);
      setMyReviewIds(ids => [...ids, created.id]);

      // Re-fetch rather than splice `created` into the list: the POST body
      // carries none of date/is_recent/score/vote_direction/photo_score/
      // photo_vote_direction, and is_recent is a Europe/Berlin date comparison
      // (main.py) the browser cannot make. The same GET refreshes both averages.
      const data = await loadBreakdown();
      const listed = (data?.comments || []).some(c => c.id === created.id);

      if (!data) {
        // Saved, but the breakdown failed -- show the row anyway rather than
        // leave the user wondering. is_recent is omitted, not guessed.
        setReviewsError(false);
        setReviews(prev => ({
          comments: [{
            ...created,
            date: meal.date,
            score: 0,
            vote_direction: null,
            photo_score: 0,
            photo_vote_direction: null,
          }, ...prev.comments],
        }));
      }

      // A stars-only rating legitimately never appears in the list (the
      // breakdown lists a row only if it has a comment OR a photo), so say so
      // instead of pointing at a list that did not change.
      setSubmitStatus(listed || (!data && (hadComment || hadPhoto)) ? 'saved' : 'starsOnly');
      if (listed) setScrollToId(created.id);

      // A fresh photo starts at score 0 and ties go to the OLDEST photo, so it
      // can only take over the dish picture when there was no photo at all.
      // No extra request for the cases where it provably cannot have changed.
      if (hadPhoto && created.photo_url && !topPhoto) setVotedTopPhoto(created.photo_url);
    } catch (err) {
      setSubmitError(submitErrorMessage(err, t));
    } finally {
      setUploading(false); // and nothing else -- no timer
    }
  };

  // Scroll the visitor's own row into view once, after the re-fetch rendered
  // it. `block: 'nearest'` so a row already on screen does not move the page.
  // Both optional calls matter: jsdom implements neither scrollIntoView nor
  // matchMedia, and the frontend tests run in jsdom.
  useEffect(() => {
    if (!scrollToId || !myRowRef.current) return;
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
    myRowRef.current.scrollIntoView?.({ block: 'nearest', behavior: reduce ? 'auto' : 'smooth' });
    setScrollToId(null);
  }, [scrollToId, reviews]);

  // Grow the textarea to fit what is actually in it. `rows` used to be derived
  // from the NEWLINE COUNT alone, so a long single paragraph stayed two rows
  // tall on a phone and only its last line was visible.
  useEffect(() => {
    const el = commentRef.current;
    if (!el) return;
    el.style.height = 'auto';
    // scrollHeight is 0 in jsdom, so the max() keeps the two-row floor there.
    el.style.height = `${Math.min(Math.max(el.scrollHeight, 48), 320)}px`;
  }, [comment, showRatingForm]);

  const handleVote = async (ratingId, direction) => {
    try {
      const voterId = getVoterId();
      if (!voterId) return;

      const response = await fetch(`${API}/api/v1/ratings/${ratingId}/vote`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', 'X-Voter-Id': voterId, ...authHeaders() },
        body: JSON.stringify({ direction }),
      });

      if (!response.ok) throw new Error('vote failed');
      const data = await response.json();
      setReviews(prev => ({
        ...prev,
        comments: prev.comments.map(c =>
          c.id === ratingId
            ? { ...c, score: data.score, vote_direction: data.direction }
            : c
        )
      }));
    } catch (e) {
      // Voting is optional, but a tap that does nothing and says nothing is
      // indistinguishable from a tap that was not registered at all.
      notify(t('ui.voteFailed'));
    }
  };

  // Separate from handleVote: photo votes are their own tally and are the only
  // thing that decides which picture represents the dish.
  const handlePhotoVote = async (ratingId, direction) => {
    try {
      const voterId = getVoterId();
      if (!voterId) return;

      const response = await fetch(`${API}/api/v1/ratings/${ratingId}/photo-vote`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', 'X-Voter-Id': voterId, ...authHeaders() },
        body: JSON.stringify({ direction }),
      });

      if (!response.ok) throw new Error('vote failed');
      const data = await response.json();
      setReviews(prev => ({
        ...prev,
        comments: prev.comments.map(c =>
          c.id === ratingId
            ? { ...c, photo_score: data.score, photo_vote_direction: data.direction }
            : c
        )
      }));
      // The winner may have changed -- ask the server rather than guess.
      loadTopPhoto();
    } catch (e) {
      notify(t('ui.voteFailed'));
    }
  };

  const pickImage = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const validTypes = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp'];
    if (!validTypes.includes(file.type)) {
      setSubmitError(t('ui.photoTypeError'));
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      setSubmitError(t('ui.photoSizeError'));
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

  return (
    <div className="dish">
      <button type="button" className="dish__toggle"
        onClick={() => {
          if (expanded) { setSubmitStatus(null); setConfirming(false); }
          setExpanded(e => !e);
        }}
        aria-expanded={expanded}>
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
          {isToday && recent.count > 0 && (
            <RatingLine avg={recent.avg} count={recent.count}
              label={t('ui.recent')} tone="recent" />
          )}
          {overall.count > 0 && (
            <RatingLine avg={overall.avg} count={overall.count}
              label={t('ui.overall')} />
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
            <img className="dish__photo" src={`${API}${topPhoto}`}
              alt={t('ui.dishPhotoOf', { dish: displayName })}
              loading="lazy" decoding="async" />
          </button>
          {/* NOT "top rated": every photo sits at 0 until someone votes and
              ties go to the oldest, so a dish's only photo wins unvoted. The
              confident wording stays in the list, where photo_score is known. */}
          <p className="dish__photo-caption">{t('ui.dishPhoto')}</p>
        </>
      )}

      {expanded && (
        <div className="dish__body">
          <p className="dish__note">{t('ui.ratingScopeNote')}</p>
          {reviewsLoading && reviews.comments.length === 0 ? (
            <div aria-hidden="true">
              <div className="skeleton skeleton--sub" />
              <div className="skeleton skeleton--meta" />
            </div>
          ) : reviewsError ? (
            <p className="error-text">
              {t('ui.reviewsLoadError')}{' '}
              <button type="button" className="btn--quiet" onClick={loadBreakdown}>
                {t('ui.retry')}
              </button>
            </p>
          ) : reviews.comments.length === 0 ? (
            <p className="muted-text">{t('ui.noReviews')}</p>
          ) : (
            reviews.comments.map(r => {
              const mine = myReviewIds.includes(r.id);
              return (
              // `undefined`, not 'false': an absent attribute cannot match the
              // CSS selector, unlike the data-unavailable="false" shape above.
              <div key={r.id} className="review"
                data-mine={mine ? 'true' : undefined}
                ref={r.id === scrollToId ? myRowRef : null}>
                <div className="review__head">
                  <span className="review__author">{r.user_name || 'Anonymous'}</span>
                  {mine && <span className="badge badge--accent">{t('ui.yourReview')}</span>}
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
                {/* Comment votes rate the review text only. An entry with a
                    photo and no text has nothing to vote on here, and the
                    endpoint rejects it. */}
                {r.comment && (
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
                )}
                {r.photo_url && (
                  <>
                    <button type="button" className="review__photo-btn"
                      onClick={() => setEnlargedImage(`${API}${r.photo_url}`)}>
                      <img className="review__photo" src={`${API}${r.photo_url}`}
                        alt={t('ui.dishPhotoOf', { dish: displayName })}
                        loading="lazy" decoding="async"
                        onError={(e) => { e.target.style.display = 'none'; }} />
                    </button>
                    <div className="review__photo-votes">
                      <button type="button" className="vote-btn" data-dir="up"
                        aria-pressed={r.photo_vote_direction === 1}
                        onClick={() => handlePhotoVote(r.id, 1)}
                        title={t('ui.upvotePhoto')} aria-label={t('ui.upvotePhoto')}>
                        <span aria-hidden="true">▲</span>
                        {r.photo_score > 0 ? `+${r.photo_score}` : r.photo_score}
                      </button>
                      <button type="button" className="vote-btn" data-dir="down"
                        aria-pressed={r.photo_vote_direction === -1}
                        onClick={() => handlePhotoVote(r.id, -1)}
                        title={t('ui.downvotePhoto')} aria-label={t('ui.downvotePhoto')}>
                        <span aria-hidden="true">▼</span>
                      </button>
                      {topPhoto === r.photo_url && (
                        <span className="badge badge--positive">{t('ui.topPhoto')}</span>
                      )}
                    </div>
                  </>
                )}
              </div>
              );
            })
          )}

          {/* Mounted unconditionally, like the search region above: a live
              region inserted TOGETHER with its text is not reliably announced.
              No timer clears it -- that is the whole point. */}
          <div role="status" aria-live="polite">
            {submitStatus && (
              <p className="rating-form__status">
                {t(submitStatus === 'saved' ? 'ui.reviewSaved' : 'ui.reviewSavedStarsOnly')}
              </p>
            )}
          </div>

          <button type="button" className="btn--quiet"
            onClick={() => {
              setShowRatingForm(v => !v);
              setSubmitStatus(null);
              setSubmitError('');
              setConfirming(false);
            }}
            aria-expanded={showRatingForm}>
            <span aria-hidden="true">{showRatingForm ? '▲' : '▼'}</span> {t('ui.rateThisDish')}
          </button>

          {/* A real form, like AuthForm in Account.js: implicit submit and a
              proper mobile keyboard. aria-live stays because the error below
              mutates an already-mounted region, which IS announced. */}
          {showRatingForm && (
            <form className="rating-form" aria-live="polite"
              onSubmit={e => { e.preventDefault(); submitRating(); }}>
              {confirming ? (
                <div className="rating-form__confirm">
                  <p className="rating-form__confirm-title">{t('ui.confirmTitle')}</p>
                  <p className="stars" aria-hidden="true">
                    {'★'.repeat(rating)}{'☆'.repeat(5 - rating)}
                  </p>
                  <span className="sr-only">{t('ui.starLabel', { count: rating })}</span>
                  <p className="review__text">
                    {comment || <span className="muted-text">{t('ui.confirmNoComment')}</span>}
                  </p>
                  {imagePreview && (
                    <img className="preview__img" src={imagePreview} alt="" />
                  )}
                  <p className="rating-form__note">{t('ui.anonWarning')}</p>
                  {submitError && <p className="error-text" id={errorId}>{submitError}</p>}
                  <div className="row-2">
                    <button type="submit" className="btn btn--primary" disabled={uploading}
                      aria-describedby={submitError ? errorId : undefined}>
                      {uploading
                        ? (selectedImage ? t('ui.uploading') : t('ui.saving'))
                        : t('ui.confirmPublish')}
                    </button>
                    <button type="button" className="btn btn--ghost"
                      onClick={() => setConfirming(false)} disabled={uploading}>
                      {t('ui.confirmBack')}
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <StarPicker value={rating} onChange={setRating} size={22} />

                  {submitError && <p className="error-text" id={errorId}>{submitError}</p>}

                  <div className="rating-form__photo">
                    {imagePreview ? (
                      <div className="preview">
                        <img className="preview__img" src={imagePreview} alt="" />
                        <button
                          type="button"
                          className="preview__remove"
                          onClick={() => { setSelectedImage(null); setImagePreview(null); setSubmitError(''); }}
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
                        {/* Restates what Datenschutz.js already claims and
                            images.strip_metadata() already does. Do not extend
                            it beyond that -- see AGENTS.md "Photo uploads". */}
                        <span className="dropzone__hint">{t('ui.photoPublicNote')}</span>
                      </label>
                    )}
                  </div>

                  <div className="rating-form__row">
                    <textarea
                      ref={commentRef}
                      className="field field--textarea"
                      placeholder={t('ui.commentOptional')}
                      aria-label={t('ui.commentOptional')}
                      value={comment}
                      onChange={e => setComment(e.target.value)}
                      maxLength={COMMENT_MAX}
                      rows={2}
                    />
                    <button
                      type="submit"
                      className="btn btn--primary"
                      disabled={rating === 0 || uploading}
                      aria-describedby={submitError ? errorId : undefined}
                    >
                      {uploading
                        ? (selectedImage ? t('ui.uploading') : t('ui.saving'))
                        : t('ui.submitReview')}
                    </button>
                  </div>

                  {/* Only once there is something to count, so an empty form
                      stays uncluttered. The hint says why submit is disabled --
                      until now the only cue was opacity: .55. */}
                  <p className="rating-form__hint">
                    {rating === 0 && <span>{t('ui.needStars')}</span>}
                    {comment.length > 0 && (
                      <span className="rating-form__count">
                        {t('ui.charCount', { used: comment.length, max: COMMENT_MAX })}
                      </span>
                    )}
                  </p>

                  {/* Anonymous posting is a one-way door: rating_identity()
                      stamps a fresh random name and no user_id, and
                      owned_rating() then treats the row as owned by nobody. */}
                  {!user && (
                    <p className="rating-form__note">
                      {t('ui.anonName')}{' '}
                      {onSignIn && (
                        <button type="button" className="btn--quiet" onClick={onSignIn}>
                          {t('ui.signIn')}
                        </button>
                      )}
                    </p>
                  )}
                </>
              )}
            </form>
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
