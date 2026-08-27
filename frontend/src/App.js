import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { initReactI18next, useTranslation } from 'react-i18next';
import i18n from 'i18next';
import de from './translations/de.json';
import en from './translations/en.json';
import Impressum from './Impressum';

const API = process.env.REACT_APP_API_URL || 'http://localhost:8000';
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
const TYPE_LABELS = { main: 'Main', side: 'Side', dessert: 'Dessert' };
const TAG_LABELS = {
  vegan: 'Vegan',
  vegetarisch: 'Vegetarisch',
  fleisch: 'Fleisch',
  fisch: 'Fisch/Meeresfrüchte',
  strohschwein: 'Leinekrone Strohschwein',
  leinetalerrind: 'Leinetaler Bauernrind',
  NDS: 'Niedersachsenmenü',
};
const TAG_COLORS = {
  vegan: { bg: '#dcfce7', color: '#166534' },
  vegetarisch: { bg: '#fef9c3', color: '#854d0e' },
  fleisch: { bg: '#fecaca', color: '#991b1b' },
  fisch: { bg: '#dbeafe', color: '#1e40af' },
  strohschwein: { bg: '#fae8d7', color: '#9a3412' },
  leinetalerrind: { bg: '#fef3c7', color: '#92400e' },
};

const TYPE_COLORS = {
  main: { bg: '#dbeafe', color: '#1e40af' },
  side: { bg: '#fef3c7', color: '#92400e' },
  dessert: { bg: '#fce7f3', color: '#9d174d' },
};

function formatRelativeDate(dateStr, t) {
  const days = Math.round((new Date() - new Date(dateStr)) / 86400000);
  if (days <= 0) return t('dates.today');
  if (days === 1) return t('dates.yesterday');
  if (days < 7) return t('dates.daysAgo', { count: days });
  if (days < 30) return t('dates.weeksAgo', { count: Math.round(days / 7) });
  if (days < 365) return t('dates.monthsAgo', { count: Math.round(days / 30) });
  return t('dates.yearsAgo', { count: Math.round(days / 365) });
}

function formatDate(dateStr, lang) {
  const date = new Date(dateStr);
  const day = String(date.getDate()).padStart(2, '0');
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const year = date.getFullYear();
  const weekdayOptions = { weekday: 'short' };
  const weekday = date.toLocaleDateString(lang === 'en' ? 'en-GB' : 'de-DE', weekdayOptions);
  return `${weekday} ${day}.${month}.${year}`;
}

// Convert ISO date (YYYY-MM-DD) to display format based on language
function getDisplayDate(isoDate, lang) {
  if (!isoDate) return '';
  const [year, month, day] = isoDate.split('-');
  if (!year || !month || !day) return isoDate;
  if (lang === 'de') {
    return `${day}.${month}.${year}`;  // DD.MM.YYYY
  }
  return `${month}/${day}/${year}`;    // MM/DD/YYYY
}

// Convert display format back to ISO date (YYYY-MM-DD)
function parseDate(displayDate, lang) {
  if (!displayDate) return null;
  let parts;
  if (lang === 'de') {
    parts = displayDate.split('.');
  } else {
    parts = displayDate.split('/');
  }
  if (parts.length !== 3) return null;
  
  const [first, second, third] = parts;
  // Validate basic format
  if (!/^\d{1,4}$/.test(first) || !/^\d{1,4}$/.test(second) || !/^\d{1,4}$/.test(third)) {
    return null;
  }
  
  if (lang === 'de') {
    // DD.MM.YYYY -> YYYY-MM-DD
    const [day, month, year] = parts;
    return `${year.padStart(4, '0')}-${month.padStart(2, '0')}-${day.padStart(2, '0')}`;
  } else {
    // MM/DD/YYYY -> YYYY-MM-DD
    const [month, day, year] = parts;
    return `${year.padStart(4, '0')}-${month.padStart(2, '0')}-${day.padStart(2, '0')}`;
  }
}

// Generate the next 7 days with display names
function getNext7Days(lang) {
  const dates = [];
  const today = new Date();
  const weekdayOptions = { weekday: 'short' };
  
  for (let i = 0; i < 7; i++) {
    const date = new Date(today);
    date.setDate(today.getDate() + i);
    
    const iso = date.toISOString().slice(0, 10);
    const day = String(date.getDate()).padStart(2, '0');
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const year = date.getFullYear();
    
    const weekday = date.toLocaleDateString(lang === 'en' ? 'en-GB' : 'de-DE', weekdayOptions);
    
    let display;
    if (lang === 'de') {
      display = `${weekday} ${day}.${month}.${year}`;
    } else {
      display = `${weekday} ${month}/${day}/${year}`;
    }
    
    dates.push({ iso, display });
  }
  return dates;
}

function IconLegend() {
  const { t } = useTranslation();
  return (
    <div style={{ 
      background: '#fff', 
      borderRadius: 10, 
      padding: '12px', 
      marginBottom: '20px', 
      border: '1px solid #e5e7eb', 
      display: 'flex', 
      gap: '16px', 
      flexWrap: 'wrap', 
      justifyContent: 'center', 
      alignItems: 'center',
      boxShadow: '0 1px 2px rgba(0,0,0,0.05)' 
    }}>
      <span style={{ fontSize: '13px', fontWeight: 600, color: '#6b7280', marginRight: '8px' }}>{t('ui.legend')}</span>
      {Object.entries(TAG_LABELS).map(([tag, label]) => (
        <div key={tag} style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
          <img 
            src={`${ICON_BASE}${tag}.png`}
            alt={tag}
            style={{ width: '16px', height: '16px', objectFit: 'contain' }} 
          />
          <span style={{ fontSize: '12px', color: '#4b5563' }}>{t('tags.' + tag)}</span>
        </div>
      ))}
    </div>
  );
}

function App() {
  const { t, i18n } = useTranslation();
  const [menu, setMenu] = useState([]);
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [filter, setFilter] = useState('all');
  const [sortMode, setSortMode] = useState('default');
  const [loading, setLoading] = useState(false);
  const [mensas, setMensas] = useState([]);
  const [showReviews, setShowReviews] = useState({});
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [includePast, setIncludePast] = useState(false);
  const [language, setLanguage] = useState('de');
  const [selectedImage, setSelectedImage] = useState(null);
  const [imagePreview, setImagePreview] = useState(null);
const [uploading, setUploading] = useState(false);
   const [imageError, setImageError] = useState('');
   const [showImpressum, setShowImpressum] = useState(false);

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
    setDate(new Date().toISOString().slice(0, 10));
  };

  useEffect(() => {
    setSearchQuery('');
    setSearchResults([]);
    setLoading(true);
    fetch(`${API}/api/v1/meals?date=${date}&lang=${language}`)
      .then(r => r.json())
      .then(data => { setMenu(Array.isArray(data) ? data : []); setLoading(false); })
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

  return (
    <div style={{ minHeight: '100vh', background: '#f0f2f5', fontFamily: '-apple-system, sans-serif' }}>
      <header style={{ background: 'linear-gradient(135deg, #1e40af, #3b82f6)', padding: '20px', textAlign: 'center' }}>
        <h1
          role="button"
          tabIndex={0}
          onClick={goHome}
          onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); goHome(); } }}
          onMouseEnter={e => { e.currentTarget.style.opacity = '0.85'; }}
          onMouseLeave={e => { e.currentTarget.style.opacity = '1'; }}
          aria-label={t('ui.backHome')}
          title={t('ui.backHome')}
          style={{ margin: 0, color: '#fff', fontSize: '1.75rem', cursor: 'pointer', display: 'inline-block' }}
        >{t('app.title')}</h1>
        <p style={{ margin: '4px 0 0', color: '#bfdbfe', fontSize: '0.875rem' }}>{t('app.subtitle')}</p>
        <div style={{ marginTop: '10px' }}>
          <button 
            onClick={() => changeLanguage('de')} 
            style={{ 
              background: language === 'de' ? '#3b82f6' : '#e5e7eb', 
              color: language === 'de' ? '#fff' : '#000',
              border: 'none', 
              padding: '4px 8px', 
              borderRadius: '4px',
              cursor: 'pointer',
              fontSize: '0.8rem'
            }}
          >
            DE
          </button>
          <button 
            onClick={() => changeLanguage('en')} 
            style={{ 
              background: language === 'en' ? '#3b82f6' : '#e5e7eb', 
              color: language === 'en' ? '#fff' : '#000',
              border: 'none', 
              padding: '4px 8px', 
              borderRadius: '4px',
              cursor: 'pointer',
              fontSize: '0.8rem',
              marginLeft: '4px'
            }}
          >
            EN
          </button>
        </div>
      </header>

      <div style={{ maxWidth: '800px', margin: '0 auto', padding: '16px' }}>
<div style={{ display: 'flex', gap: '0.625rem', marginBottom: '1rem', flexWrap: 'wrap', justifyContent: 'center', width: '100%' }}>
            <select
              value={date}
              onChange={e => { setFilter('all'); setDate(e.target.value); }}
              style={{ padding: '0.5rem', borderRadius: '0.5rem', border: '1px solid #d1d5db', fontSize: '0.875rem', width: '100%' }}
            >
              {getNext7Days(language).map(d => (
                <option key={d.iso} value={d.iso}>{d.display}</option>
              ))}
            </select>
            <select
              value={filter}
              onChange={e => setFilter(e.target.value)}
              style={{ padding: '0.5rem', borderRadius: '0.5rem', border: '1px solid #d1d5db', fontSize: '0.875rem', width: '100%' }}
            >
              <option value="all">{t('ui.allMensas')}</option>
              {mensas.map(m => <option key={m} value={m}>{m}</option>)}
            </select>
            <select
              value={sortMode}
              onChange={e => setSortMode(e.target.value)}
              style={{ padding: '0.5rem', borderRadius: '0.5rem', border: '1px solid #d1d5db', fontSize: '0.875rem', width: '100%' }}
            >
              <option value="default">{t('ui.sortStandard')}</option>
              <option value="alpha">{t('ui.sortAlphabetical')}</option>
            </select>
         </div>
         <div style={{ display: 'flex', gap: '0.625rem', marginBottom: '0.75rem', flexWrap: 'wrap', justifyContent: 'center', alignItems: 'center', width: '100%', position: 'relative' }}>
           <div style={{ position: 'relative', width: '100%' }}>
             <input
               type="text"
               placeholder={t('ui.searchPlaceholder')}
               value={searchQuery}
               onChange={e => setSearchQuery(e.target.value)}
               style={{ padding: '0.5rem 0.75rem', borderRadius: '0.5rem', border: '1px solid #d1d5db', fontSize: '0.875rem', width: '100%' }}
             />
             {searchQuery && (
               <button
                 onClick={() => setSearchQuery('')}
                 style={{
                   position: 'absolute',
                   right: '0.75rem',
                   top: '50%',
                   transform: 'translateY(-50%)',
                   background: 'none',
                   border: 'none',
                   cursor: 'pointer',
                   fontSize: '1.25rem',
                   color: '#9ca3af',
                   padding: '0',
                   width: '20px',
                   height: '20px',
                   display: 'flex',
                   alignItems: 'center',
                   justifyContent: 'center'
                 }}
                 aria-label={t('ui.clearSearch')}
               >
                 ×
               </button>
             )}
           </div>
           <label style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', fontSize: '0.8125rem', color: '#4b5563', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={includePast}
              onChange={e => setIncludePast(e.target.checked)}
            />
            {t('ui.includePast')}
          </label>
         </div>
        <IconLegend />
        
        {searchLoading ? (
          <div style={{ textAlign: 'center', padding: 40, color: '#6b7280' }}>{t('search.loading')}</div>
        ) : searchResults.length > 0 ? (
          <>
            <p style={{ color: '#374151', fontSize: '14px', marginBottom: '4px' }}>
              {t('ui.foundResults', { count: searchResults.length, query: searchQuery })}
              {!includePast && " " + t('ui.futureOnly')}
            </p>
            <SearchResults results={searchResults} onNavigate={navigateTo} TYPE_LABELS={TYPE_LABELS} formatRelativeDate={(d) => formatRelativeDate(d, t)} formatDate={formatDate} language={language} />
          </>
        ) : loading ? (
          <div style={{ textAlign: 'center', padding: 40, color: '#6b7280' }}>{t('search.loadingMenu')}</div>
        ) : menu.length === 0 ? (
          <div style={{ textAlign: 'center', padding: 40, color: '#6b7280' }}>
            <p>{t('ui.noMenu')}</p>
          </div>
        ) : filteredMenu.length === 0 ? (
          <div style={{ textAlign: 'center', padding: 40, color: '#6b7280' }}>
            <p>{t('ui.noMeals', { filter: filter })}</p>
          </div>
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
                <h2 style={{ color: '#374151', fontSize: '18px', marginTop: 24, marginBottom: 8,
                  borderBottom: '3px solid #3b82f6', paddingBottom: 8 }}>
                  {mensa} - {t('mealTypes.' + type) || type}
                </h2>
                {sortedItems.map(meal => (
                  <DishCard key={meal.id} meal={meal} />
                ))}
              </React.Fragment>
            );
          })
        )}
      </div>

      <footer style={{
        background: '#fff',
        padding: '20px 16px',
        marginTop: '40px',
        borderTop: '1px solid #e5e7eb',
        textAlign: 'center'
      }}>
        <div style={{ maxWidth: '800px', margin: '0 auto' }}>
          <p style={{ fontSize: '0.75rem', color: '#6b7280', margin: '0 0 8px' }}>
                {showImpressum ? (
                  <span>
                    <strong>{t('footer.impressum')}</strong>
                    <span style={{ margin: '0 8px', color: '#9ca3af' }}>|</span>
                    <button
                      onClick={() => setShowImpressum(false)}
                      style={{
                        background: 'none',
                        border: 'none',
                        color: '#3b82f6',
                        textDecoration: 'none',
                        cursor: 'pointer',
                        fontSize: '0.75rem'
                      }}
                    >
                      {t('ui.backHome')}
                    </button>
                    <span style={{ margin: '0 8px', color: '#9ca3af' }}>|</span>
                    <a
                      href="https://github.com/lufre1/rate-site"
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ color: '#3b82f6', textDecoration: 'none', marginLeft: '4px' }}
                    >
                      {t('footer.github')}
                    </a>
                  </span>
                ) : (
                  <span>
                    <button
                      onClick={() => setShowImpressum(true)}
                      style={{
                        background: 'none',
                        border: 'none',
                        color: '#3b82f6',
                        textDecoration: 'none',
                        cursor: 'pointer',
                        fontSize: '0.75rem'
                      }}
                    >
                      {t('footer.impressum')}
                    </button>
                    <span style={{ margin: '0 8px', color: '#9ca3af' }}>|</span>
                    <a
                      href="https://github.com/lufre1/rate-site"
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ color: '#3b82f6', textDecoration: 'none', marginLeft: '4px' }}
                    >
                      {t('footer.github')}
                    </a>
                  </span>
                )}
              </p>
        </div>
      </footer>

      {showImpressum && (
        <div style={{ padding: '16px' }}>
          <Impressum onBack={() => setShowImpressum(false)} />
        </div>
      )}
    </div>
  );
}

function SearchResults({ results, onNavigate, TYPE_LABELS, formatRelativeDate, formatDate, language }) {
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
     <div style={{ marginBottom: 24 }}>
       {sortedKeys.map(key => {
         const [dateStr, mensa, type] = key.split('|');
         const items = grouped[key];
         const dayLabel = formatDate(dateStr, language);
        return (
          <div key={key} style={{ marginBottom: 16 }}>
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center', marginBottom: 8 }}>
              <span style={{ color: '#374151', fontSize: '15px', fontWeight: 600 }}>{mensa}</span>
              <span style={{ fontSize: '11px', padding: '2px 6px', borderRadius: 4, background: '#f3f4f6', color: '#374151' }}>{TYPE_LABELS[type] || type}</span>
              <span style={{ fontSize: '12px', color: '#8b5cf6', cursor: 'pointer', fontWeight: 500 }}
                onClick={() => onNavigate(dateStr, mensa)}>
                {dayLabel} →
              </span>
              <span style={{ fontSize: '11px', color: '#9ca3af' }}>({items.length})</span>
            </div>
            {items.map(meal => (
              <DishCardSearch key={meal.id} meal={meal} TYPE_COLORS={TYPE_COLORS} onNavigate={onNavigate} />
            ))}
          </div>
        );
      })}
    </div>
  );
}

function DishCardSearch({ meal, TYPE_COLORS, onNavigate }) {
  const { t } = useTranslation();
  const tags = typeof meal.tags === 'string' ? JSON.parse(meal.tags) : (meal.tags || []);
  const go = () => onNavigate && onNavigate(meal.date, meal.mensa);

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={go}
      onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } }}
      onMouseEnter={e => { e.currentTarget.style.background = '#f9fafb'; e.currentTarget.style.borderColor = '#c7d2fe'; }}
      onMouseLeave={e => { e.currentTarget.style.background = '#fff'; e.currentTarget.style.borderColor = '#e5e7eb'; }}
      title={`${meal.mensa} · ${meal.date}`}
      style={{ background: '#fff', borderRadius: 8, border: '1px solid #e5e7eb', cursor: 'pointer',
      padding: '8px 12px', marginBottom: 4, display: 'flex', alignItems: 'flex-start', gap: '10px' }}>
      <div style={{ flex: 1 }}>
        <span style={{ fontSize: '14px', fontWeight: 500, color: '#111827' }}>{meal.name}</span>
      </div>
      {tags.length > 0 && (
        <div style={{ display: 'flex', gap: '4px', alignItems: 'center', flexShrink: 0 }}>
          {tags.map(tag => (
            <img
              key={tag}
              src={`${ICON_BASE}${tag}`}
              alt={tag.replace('.png', '')}
              title={t('tags.' + tag.replace('.png', '')) || tag}
              style={{ width: '12px', height: '12px', objectFit: 'contain' }}
              onError={(e) => { e.target.style.display = 'none'; }}
            />
          ))}
        </div>
      )}
      {meal.rating_count > 0 && (
        <span style={{ fontSize: '11px', color: '#f59e0b', flexShrink: 0 }}>
          {"\u2605".repeat(Math.round(meal.avg_rating))} {meal.avg_rating} ({meal.rating_count})
        </span>
      )}
    </div>
  );
}

function IconTags({ tags }) {
  if (!tags || tags.length === 0) return null;
  return (
    <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
      {tags.map(tag => (
        <img
          key={tag}
          src={`${ICON_BASE}${tag}`}
          alt={tag.replace('.png', '')}
          style={{ width: '16px', height: '16px', objectFit: 'contain' }}
          onError={(e) => { e.target.style.display = 'none'; }}
        />
      ))}
    </div>
  );
}

function StarPicker({ value, onChange, size = 22 }) {
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

function SideRatingRow({ mealId, sideName, avgRating, ratingCount, recentAvg = 0, recentCount = 0 }) {
  const { t } = useTranslation();
  const [rating, setRating] = useState(0);
  const [justRated, setJustRated] = useState(false);

  const handleRate = async (i) => {
    setRating(i);
    setJustRated(true);
    setTimeout(() => setJustRated(false), 1500);
    await fetch(`${API}/api/v1/meals/${mealId}/side-ratings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ side_name: sideName, rating: i, comment: null }),
    });
  };

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 4 }}>
      <span style={{ fontSize: '0.8125rem', color: '#374151', flexShrink: 0 }}>{sideName}</span>
      {recentCount > 0 && (
        <span style={{ fontSize: '10px', color: '#16a34a', flexShrink: 0, background: '#dcfce7', padding: '2px 6px', borderRadius: 4 }}>
            {t('ui.recent')} {recentAvg.toFixed(1)} ({recentCount}) {'★'}
        </span>
      )}
      {ratingCount > 0 && (
        <span style={{ fontSize: '11px', color: '#9ca3af', flexShrink: 0 }}>
          {"★".repeat(Math.round(avgRating))} {avgRating} {t('ui.overall')} ({ratingCount})
        </span>
      )}
      <StarPicker value={rating} onChange={handleRate} size={16} />
      {justRated && (
        <span style={{ fontSize: '11px', color: '#16a34a' }}>{t('ui.thanksForRating')}</span>
      )}
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
  const [sideRatings, setSideRatings] = useState({});
  const [uploading, setUploading] = useState(false);
  const [selectedImage, setSelectedImage] = useState(null);
  const [imagePreview, setImagePreview] = useState(null);
  const [imageError, setImageError] = useState('');
  const [enlargedImage, setEnlargedImage] = useState(null);

  const sideNames = useMemo(() => (
    meal.type === 'main' && meal.description
      ? meal.description.split(',').map(s => s.trim()).filter(Boolean)
      : []
  ), [meal.type, meal.description]);

// Fetch ratings-breakdown on mount (not just when expanded)
  useEffect(() => {
    if (reviews.overall.count === 0) {
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
    }
  }, [meal.id]);

  useEffect(() => {
    if (expanded && sideNames.length > 0) {
      fetch(`${API}/api/v1/meals/${meal.id}/side-ratings`)
        .then(r => r.json())
        .then(data => {
          const map = {};
          (Array.isArray(data) ? data : []).forEach(s => { map[s.side_name] = s; });
          setSideRatings(map);
        })
        .catch(() => {});
    }
  }, [expanded, meal.id, sideNames]);

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
          body: formData,
        });
      } else {
        response = await fetch(`${API}/api/v1/meals/${meal.id}/ratings`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ rating, comment: comment || null }),
        });
      }

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
      }

      setSubmitted(true);
    } catch (err) {
      setImageError(err.message || t('ui.photoError') || 'Upload failed');
    } finally {
      setUploading(false);
      setTimeout(() => { 
        setSubmitted(false); 
        setRating(0); 
        setComment(''); 
        setSelectedImage(null);
        setImagePreview(null);
        setShow(true); 
      }, 1500);
    }
  };

  const tc = TYPE_COLORS[meal.type] || TYPE_COLORS.main;
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
    <div style={{ background: '#fff', borderRadius: 10, border: '1px solid #e5e7eb',
      boxShadow: '0 1px 3px rgba(0,0,0,0.06)', padding: '14px 16px', marginBottom: 8 }}>
      <button onClick={() => setExpanded(e => !e)} aria-expanded={expanded} style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
        width: '100%', background: 'none', border: 'none', padding: 0,
        textAlign: 'left', cursor: 'pointer', font: 'inherit'
      }}>
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 2 }}>
            <span style={{ fontSize: '1rem', fontWeight: 600,
              color: meal.is_available ? '#111827' : '#9ca3af',
              textDecoration: meal.is_available ? 'none' : 'line-through' }}>{displayName}</span>
            <span style={{ fontSize: '0.6875rem', padding: '2px 6px', borderRadius: 4,
              background: tc.bg, color: tc.color, fontWeight: 500, textTransform: 'uppercase' }}>
              {t('mealTypes.' + meal.type)}
            </span>
            {meal.is_available === false && (
              <span style={{ fontSize: '0.6875rem', padding: '2px 6px', borderRadius: 4,
                background: '#fee2e2', color: '#dc2626', fontWeight: 500, textTransform: 'uppercase' }}>
                {t('ui.notAvailable')}
              </span>
            )}
            <IconTags tags={tags} />
          </div>
          {displayDescription && typeof displayDescription === 'string' && (
            <p style={{ margin: '6px 0 0', color: '#6b7280', fontSize: '0.8125rem' }}>
              {displayDescription.replace(/, +/g, ', ')}
            </p>
          )}

</div>
            <div style={{ textAlign: 'right', marginLeft: 12, display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4 }}>
              {/* Recent rating - only show if count > 0 */}
              {reviews.recent.count > 0 && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <span style={{ color: '#f59e0b', fontSize: '0.875rem' }}>
                    {"★".repeat(Math.round(reviews.recent.avg))}
                    {"☆".repeat(5 - Math.round(reviews.recent.avg))}
                  </span>
                  <span style={{ color: '#16a34a', fontSize: '0.75rem', fontWeight: 600 }}>
                    {t('ui.recent')} {reviews.recent.avg.toFixed(1)} ({reviews.recent.count})
                  </span>
                </div>
              )}
              {/* Overall rating - only show if count > 0 */}
              {reviews.overall.count > 0 && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <span style={{ color: '#f59e0b', fontSize: '0.875rem' }}>
                    {"★".repeat(Math.round(reviews.overall.avg))}
                    {"☆".repeat(5 - Math.round(reviews.overall.avg))}
                  </span>
                  <span style={{ color: '#9ca3af', fontSize: '0.75rem', fontWeight: 600 }}>
                    {t('ui.overall')} {reviews.overall.avg.toFixed(1)} ({reviews.overall.count})
                  </span>
                </div>
              )}
              {/* Fallback to meal.avg_rating if no detailed breakdown available */}
              {reviews.overall.count === 0 && reviews.recent.count === 0 && meal.rating_count > 0 && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <span style={{ color: '#f59e0b', fontSize: '0.875rem' }}>
                    {"★".repeat(Math.round(meal.avg_rating))}
                    {"☆".repeat(5 - Math.round(meal.avg_rating))}
                  </span>
                  <span style={{ color: '#16a34a', fontSize: '0.75rem', fontWeight: 600 }}>
                    {t('ui.recent')} {meal.avg_rating.toFixed(1)} ({meal.rating_count})
                  </span>
                </div>
              )}
              <span style={{ color: '#9ca3af', fontSize: '12px' }}>{expanded ? '\u25B2' : '\u25BC'}</span>
        </div>
      </button>

{expanded && (
        <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid #f3f4f6' }}>

          {reviews.comments.length === 0 ? (
            <p style={{ color: '#9ca3af', fontSize: '12px', margin: '6px 0 0' }}>{t('ui.noReviews')}</p>
          ) : (
            reviews.comments.map(r => (
              <div key={r.id} style={{ padding: '4px 0' }}>
                <span style={{ color: '#6b7280', fontSize: '12px',
                  display: 'flex', alignItems: 'center', gap: '2px', flexWrap: 'wrap' }}>
                  {r.user_name || 'Anonymous'}
                  {"\u2605".repeat(r.rating)}{"\u2606".repeat(5 - r.rating)}
                  {r.created_at && (
                     <span style={{ color: '#9ca3af', marginLeft: 4 }}>{formatRelativeDate(r.created_at, t)}</span>
                   )}
                  {r.is_recent && (
                    <span style={{ color: '#16a34a', fontSize: '9px', marginLeft: 4 }}>
                        ({t('ui.recent')})
                    </span>
                  )}
                </span>
                {r.comment && (
                  <p style={{ margin: '2px 0 0', fontSize: '13px', color: '#374151', wordBreak: 'break-word', whiteSpace: 'pre-wrap' }}>{r.comment}</p>
                )}
                {r.photo_url && (
                  <img
                    src={`${API}${r.photo_url}`}
                    alt=""
                    style={{
                      marginTop: 4, maxWidth: '120px', maxHeight: '120px',
                      borderRadius: '8px', border: '1px solid #e5e7eb', display: 'block', cursor: 'pointer',
                    }}
                    onError={(e) => { e.target.style.display = 'none'; }}
                    onClick={(e) => { e.stopPropagation(); setEnlargedImage(`${API}${r.photo_url}`); }}
                  />
                )}
              </div>
            ))
          )}

          <button onClick={() => setShowRatingForm(!showRatingForm)} style={{ border: 'none', background: 'none', color: '#3b82f6', cursor: 'pointer', fontSize: '12px', padding: '6px 0' }}>
            {showRatingForm ? '\u25B2' : '\u25BC'} {t('ui.rate')}
          </button>

          {showRatingForm && (
          <>
          {submitted ? (
            <p style={{ color: '#16a34a', fontSize: '13px', margin: 0 }}>{t('ui.thanksForRating')}</p>
          ) : (
            <>
              <div style={{ marginBottom: 6 }}>
                <StarPicker value={rating} onChange={setRating} size={22} />
              </div>
              {/* Photo upload section */}
              {imageError && (
                <p style={{ color: '#dc2626', fontSize: '12px', margin: '4px 0' }}>{imageError}</p>
              )}

              <div style={{ marginBottom: 8 }}>
                {imagePreview ? (
                  <div style={{ position: 'relative', display: 'inline-block' }}>
                    <img 
                      src={imagePreview} 
                      alt="Preview" 
                      style={{ maxWidth: '150px', maxHeight: '150px', borderRadius: '8px', border: '1px solid #e5e7eb' }}
                    />
                    <button
                      onClick={() => { setSelectedImage(null); setImagePreview(null); setImageError(''); }}
                      style={{
                        position: 'absolute',
                        top: '-8px',
                        right: '-8px',
                        background: '#dc2626',
                        color: '#fff',
                        border: 'none',
                        borderRadius: '50%',
                        width: '24px',
                        height: '24px',
                        fontSize: '12px',
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center'
                      }}
                      title={t('ui.removePhoto')}
                    >
                      ×
                    </button>
                  </div>
                ) : (
                  <label style={{
                    display: 'block',
                    padding: '12px',
                    border: '2px dashed #d1d5db',
                    borderRadius: '8px',
                    textAlign: 'center',
                    cursor: 'pointer',
                    background: '#f9fafb'
                  }}>
                    <input
                      type="file"
                      accept="image/jpeg,image/jpg,image/png,image/webp"
                      onChange={(e) => {
                        const file = e.target.files[0];
                        if (!file) return;
                        const validTypes = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp'];
                        if (!validTypes.includes(file.type)) {
                          setImageError(t('ui.photoTypeError') || 'Only JPG, PNG, and WebP images are allowed');
                          return;
                        }
                        if (file.size > 5 * 1024 * 1024) {
                          setImageError(t('ui.photoSizeError') || 'File size exceeds 5MB');
                          return;
                        }
                        setSelectedImage(file);
                        const reader = new FileReader();
                        reader.onloadend = () => { setImagePreview(reader.result); };
                        reader.readAsDataURL(file);
                      }}
                      style={{ display: 'none' }}
                    />
                    <span style={{ color: '#3b82f6', fontSize: '13px', fontWeight: 500 }}>
                      {t('ui.uploadPhoto')}
                    </span>
                    <p style={{ margin: '4px 0 0', fontSize: '11px', color: '#6b7280' }}>
                      JPG, PNG, WebP (max 5MB)
                    </p>
                  </label>
                )}
              </div>

              <div style={{ display: 'flex', gap: '8px' }}>
               <textarea placeholder={t('ui.rate')} value={comment}
                 onChange={e => setComment(e.target.value)}
                 rows={Math.max(1, comment.split('\n').length)}
                 style={{ flex: 1, padding: '4px 8px', border: '1px solid #d1d5db',
                    borderRadius: 6, fontSize: '0.8125rem', resize: 'none' }}
                 />
               <button
                 onClick={submitRating}
                 disabled={rating === 0 || uploading}
                 style={{
                    padding: '0.75rem 1rem', borderRadius: '0.5rem', border: 'none',
                    background: rating > 0 && !uploading ? '#3b82f6' : '#d1d5db',
                    color: rating > 0 && !uploading ? '#fff' : '#9ca3af',
                    cursor: rating > 0 && !uploading ? 'pointer' : 'not-allowed',
                    fontSize: '0.875rem', fontWeight: 500, whiteSpace: 'nowrap'
                  }}>
                  {uploading ? t('ui.uploading') : t('ui.rate')}
                </button>
                </div>
              </>
            )}

            {sideNames.length > 0 && (
              <div style={{ marginTop: 10, paddingTop: 8, borderTop: '1px solid #f3f4f6' }}>
                <p style={{ fontSize: 11, fontWeight: 600, color: '#6b7280', textTransform: 'uppercase', margin: '0 0 6px' }}>
                  {t('ui.rateSides')}
                </p>
                {sideNames.map(name => (
<SideRatingRow
    key={name}
    mealId={meal.id}
    sideName={name}
    avgRating={sideRatings[name]?.avg_rating || 0}
    ratingCount={sideRatings[name]?.rating_count || 0}
    recentAvg={sideRatings[name]?.recent_avg || 0}
    recentCount={sideRatings[name]?.recent_count || 0}
/>
))}
              </div>
            )}
            </>
          )}
          </div>
        )}

        {enlargedImage && (
          <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.8)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999, cursor: 'pointer' }}
               onClick={() => setEnlargedImage(null)}>
            <img src={enlargedImage} alt=""
                 style={{ maxHeight: '90vh', maxWidth: '90vw', borderRadius: 4 }}
                 onClick={(e) => e.stopPropagation()} />
          </div>
        )}
     </div>
   );
}

export default App;