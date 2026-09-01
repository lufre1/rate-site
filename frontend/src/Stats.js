import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { API, authHeaders } from './shared';

function Stats({ onBack, language }) {
  const { t } = useTranslation();
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    fetch(`${API}/api/v1/stats/overview?lang=${language}`)
      .then(r => r.json())
      .then(data => {
        setStats(data);
        setLoading(false);
      })
      .catch(err => {
        setError(err.message || t('stats.error'));
        setLoading(false);
      });
  }, [language]);

  if (loading) {
    return (
      <div style={{ maxWidth: '800px', margin: '0 auto', padding: '24px' }}>
        <h1 style={{ fontSize: '1.5rem', fontWeight: '700', color: '#1f2937', marginBottom: '24px' }}>
          {t('stats.title')}
        </h1>
        <div style={{ textAlign: 'center', padding: '40px', color: '#6b7280', fontWeight: 500 }}>
          {t('search.loadingMenu')}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ maxWidth: '800px', margin: '0 auto', padding: '24px' }}>
        <h1 style={{ fontSize: '1.5rem', fontWeight: '700', color: '#1f2937', marginBottom: '24px' }}>
          {t('stats.title')}
        </h1>
        <div style={{ textAlign: 'center', padding: '40px', color: '#dc2626', fontWeight: 500 }}>
          {error}
        </div>
      </div>
    );
  }

  if (!stats) {
    return (
      <div style={{ maxWidth: '800px', margin: '0 auto', padding: '24px' }}>
        <h1 style={{ fontSize: '1.5rem', fontWeight: '700', color: '#1f2937', marginBottom: '24px' }}>
          {t('stats.title')}
        </h1>
        <div style={{ textAlign: 'center', padding: '40px', color: '#6b7280', fontWeight: 500 }}>
          {t('stats.noData')}
        </div>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: '800px', margin: '0 auto', padding: '24px' }}>
      <h1 style={{ fontSize: '1.5rem', fontWeight: '700', color: '#1f2937', marginBottom: '24px' }}>
        {t('stats.title')}
      </h1>

      {/* Overview Cards */}
      <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap', marginBottom: '24px' }}>
        <div style={{ 
          flex: 1, 
          minWidth: '200px', 
          background: '#fff', 
          borderRadius: '16px', 
          padding: '20px',
          boxShadow: '0 2px 4px rgba(0,0,0,0.05)',
          textAlign: 'center'
        }}>
          <div style={{ fontSize: '2.5rem', fontWeight: '700', color: '#ea580c' }}>
            {stats.total_ratings}
          </div>
          <div style={{ fontSize: '0.875rem', color: '#6b7280', marginTop: '8px', fontWeight: 500 }}>
            {t('stats.totalRatings')}
          </div>
        </div>
        <div style={{ 
          flex: 1, 
          minWidth: '200px', 
          background: '#fff', 
          borderRadius: '16px', 
          padding: '20px',
          boxShadow: '0 2px 4px rgba(0,0,0,0.05)',
          textAlign: 'center'
        }}>
          <div style={{ fontSize: '2.5rem', fontWeight: '700', color: '#ea580c' }}>
            {stats.total_meals}
          </div>
          <div style={{ fontSize: '0.875rem', color: '#6b7280', marginTop: '8px', fontWeight: 500 }}>
            {t('stats.totalMeals')}
          </div>
        </div>
        <div style={{ 
          flex: 1, 
          minWidth: '200px', 
          background: '#fff', 
          borderRadius: '16px', 
          padding: '20px',
          boxShadow: '0 2px 4px rgba(0,0,0,0.05)',
          textAlign: 'center'
        }}>
          <div style={{ fontSize: '2.5rem', fontWeight: '700', color: '#ea580c' }}>
            {stats.total_mensas}
          </div>
          <div style={{ fontSize: '0.875rem', color: '#6b7280', marginTop: '8px', fontWeight: 500 }}>
            {t('stats.totalMensas')}
          </div>
        </div>
      </div>

      {/* Top Rated Dishes */}
      <div style={{ marginBottom: '24px' }}>
        <h2 style={{ fontSize: '1.25rem', fontWeight: '700', color: '#1f2937', marginBottom: '16px' }}>
          {t('stats.topDishes')}
        </h2>
        {stats.top_rated_dishes && stats.top_rated_dishes.length > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {stats.top_rated_dishes.map((dish, index) => (
              <div key={dish.id} style={{
                background: '#fff',
                borderRadius: '12px',
                padding: '16px',
                boxShadow: '0 2px 4px rgba(0,0,0,0.05)',
                display: 'flex',
                alignItems: 'center',
                gap: '16px'
              }}>
                <div style={{
                  fontSize: '1.5rem',
                  fontWeight: '700',
                  color: index === 0 ? '#f59e0b' : index === 1 ? '#9ca3af' : '#d1d5db',
                  minWidth: '32px'
                }}>
                  {index + 1}
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: '1rem', fontWeight: '600', color: '#111827' }}>
                    {dish.name}
                  </div>
                  <div style={{ fontSize: '0.875rem', color: '#6b7280' }}>
                    {dish.mensa}
                  </div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ color: '#f59e0b', fontSize: '1.125rem', fontWeight: '600' }}>
                    {'★'.repeat(Math.round(dish.avg_rating))} {dish.avg_rating}
                  </div>
                  <div style={{ fontSize: '0.875rem', color: '#9ca3af' }}>
                    {dish.rating_count} {t('stats.ratings')}
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p style={{ color: '#9ca3af', fontSize: '0.875rem' }}>{t('stats.noData')}</p>
        )}
      </div>

      {/* Mensa Rankings */}
      <div style={{ marginBottom: '24px' }}>
        <h2 style={{ fontSize: '1.25rem', fontWeight: '700', color: '#1f2937', marginBottom: '16px' }}>
          {t('stats.mensaRankings')}
        </h2>
        {stats.mensa_rankings && stats.mensa_rankings.length > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {stats.mensa_rankings.map((mensa, index) => (
              <div key={mensa.name} style={{
                background: '#fff',
                borderRadius: '12px',
                padding: '16px',
                boxShadow: '0 2px 4px rgba(0,0,0,0.05)',
                display: 'flex',
                alignItems: 'center',
                gap: '16px'
              }}>
                <div style={{
                  fontSize: '1.5rem',
                  fontWeight: '700',
                  color: index === 0 ? '#f59e0b' : index === 1 ? '#9ca3af' : '#d1d5db',
                  minWidth: '32px'
                }}>
                  {index + 1}
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: '1rem', fontWeight: '600', color: '#111827' }}>
                    {mensa.name}
                  </div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ color: '#f59e0b', fontSize: '1.125rem', fontWeight: '600' }}>
                    {'★'.repeat(Math.round(mensa.avg_rating))} {mensa.avg_rating}
                  </div>
                  <div style={{ fontSize: '0.875rem', color: '#9ca3af' }}>
                    {mensa.total_ratings} {t('stats.ratings')}
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p style={{ color: '#9ca3af', fontSize: '0.875rem' }}>{t('stats.noData')}</p>
        )}
      </div>

      {/* Weekly Trends */}
      <div style={{ marginBottom: '24px' }}>
        <h2 style={{ fontSize: '1.25rem', fontWeight: '700', color: '#1f2937', marginBottom: '16px' }}>
          {t('stats.weeklyTrends')}
        </h2>
        {stats.weekly_trends && Object.keys(stats.weekly_trends).length > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {Object.entries(stats.weekly_trends).map(([day, count]) => (
              <div key={day} style={{
                background: '#fff',
                borderRadius: '12px',
                padding: '12px 16px',
                boxShadow: '0 2px 4px rgba(0,0,0,0.05)',
                display: 'flex',
                alignItems: 'center',
                gap: '12px'
              }}>
                <div style={{ width: '80px', fontSize: '0.875rem', fontWeight: 500, color: '#374151' }}>
                  {day}
                </div>
                <div style={{ flex: 1, height: '8px', background: '#f3f4f6', borderRadius: '4px', overflow: 'hidden' }}>
                  <div style={{
                    height: '100%',
                    background: '#ea580c',
                    borderRadius: '4px',
                    width: `${Math.min((count / (Object.values(stats.weekly_trends)[0] || 1)) * 100, 100)}%`,
                    transition: 'width 0.3s ease'
                  }} />
                </div>
                <div style={{ fontSize: '0.875rem', fontWeight: 600, color: '#ea580c', minWidth: '48px' }}>
                  {count}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p style={{ color: '#9ca3af', fontSize: '0.875rem' }}>{t('stats.noData')}</p>
        )}
      </div>

      <button
        onClick={onBack}
        style={{
          padding: '8px 16px',
          background: '#ea580c',
          color: '#fff',
          border: 'none',
          borderRadius: '8px',
          cursor: 'pointer',
          fontSize: '0.875rem',
          fontWeight: 600,
          transition: 'all 0.2s ease',
          boxShadow: '0 2px 4px rgba(0,0,0,0.1)'
        }}
      >
        {t('ui.backHome')}
      </button>
    </div>
  );
}

export default Stats;