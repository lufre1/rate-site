import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { API } from './shared';

function renderStars(rating) {
  const fullStars = Math.floor(rating);
  const hasHalfStar = rating % 1 >= 0.5;
  const emptyStars = 5 - fullStars - (hasHalfStar ? 1 : 0);

  let stars = '★'.repeat(fullStars);
  if (hasHalfStar) {
    stars += '☆';
  }
  stars += '☆'.repeat(emptyStars);
  return stars;
}

function StatSkeleton() {
  return (
    <div className="stat" aria-hidden="true">
      <div className="skeleton skeleton--value" />
      <div className="skeleton skeleton--label" />
    </div>
  );
}

// Every state of this screen keeps the same heading, so it lives here rather
// than being repeated in each early return.
function StatsShell({ children }) {
  const { t } = useTranslation();
  return (
    <>
      <h2 className="view-title">{t('stats.title')}</h2>
      {children}
    </>
  );
}

function Stats({ onBack, language }) {
  const { t } = useTranslation();
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    setLoading(true);
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
  }, [language, t]);

  if (loading) {
    return (
      <StatsShell>
        <div className="stats-grid">
          <StatSkeleton />
          <StatSkeleton />
          <StatSkeleton />
        </div>
      </StatsShell>
    );
  }

  if (error) {
    return (
      <StatsShell>
        <div className="loading error-text">{error}</div>
      </StatsShell>
    );
  }

  if (!stats) {
    return (
      <StatsShell>
        <div className="loading">{t('stats.noData')}</div>
      </StatsShell>
    );
  }

  const peakTrend = Math.max(...Object.values(stats.weekly_trends || {}), 0) || 1;

  return (
    <StatsShell>
      {/* Overview cards */}
      <div className="stats-grid">
        <div className="stat">
          <div className="stat__value">{stats.total_ratings}</div>
          <div className="stat__label">{t('stats.totalRatings')}</div>
        </div>
        <div className="stat">
          <div className="stat__value">{stats.total_meals}</div>
          <div className="stat__label">{t('stats.totalMeals')}</div>
        </div>
        <div className="stat">
          <div className="stat__value">{stats.total_mensas}</div>
          <div className="stat__label">{t('stats.totalMensas')}</div>
        </div>
      </div>

      {/* Top rated dishes */}
      <section className="stats-section">
        <h3 className="stats-section__title">{t('stats.topDishes')}</h3>
        {stats.top_rated_dishes && stats.top_rated_dishes.length > 0 ? (
          <div className="rank-list">
            {stats.top_rated_dishes.map((dish, index) => (
              <div key={dish.id} className="rank">
                <div className="rank__pos" data-medal={index}>{index + 1}</div>
                <div className="rank__body">
                  <div className="rank__name">{dish.name}</div>
                  <div className="rank__sub">{dish.mensa}</div>
                </div>
                <div className="rank__score">
                  <div className="stars stars--lg">
                    {renderStars(dish.avg_rating)} {dish.avg_rating}
                  </div>
                  <div className="rank__count">
                    {dish.rating_count} {t('stats.ratings')}
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="muted-text">{t('stats.noData')}</p>
        )}
      </section>

      {/* Mensa rankings */}
      <section className="stats-section">
        <h3 className="stats-section__title">{t('stats.mensaRankings')}</h3>
        {stats.mensa_rankings && stats.mensa_rankings.length > 0 ? (
          <div className="rank-list">
            {stats.mensa_rankings.map((mensa, index) => (
              <div key={mensa.name} className="rank">
                <div className="rank__pos" data-medal={index}>{index + 1}</div>
                <div className="rank__body">
                  <div className="rank__name">{mensa.name}</div>
                </div>
                <div className="rank__score">
                  <div className="stars stars--lg">
                    {renderStars(mensa.avg_rating)} {mensa.avg_rating}
                  </div>
                  <div className="rank__count">
                    {mensa.total_ratings} {t('stats.ratings')}
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="muted-text">{t('stats.noData')}</p>
        )}
      </section>

      {/* Weekly trends */}
      <section className="stats-section">
        <h3 className="stats-section__title">{t('stats.weeklyTrends')}</h3>
        {stats.weekly_trends && Object.keys(stats.weekly_trends).length > 0 ? (
          <div className="rank-list">
            {Object.entries(stats.weekly_trends).map(([day, count]) => (
              <div key={day} className="trend">
                <div className="trend__day">{t(`stats.days.${day}`)}</div>
                {/* The bar length is the one genuinely per-row value, so it
                    rides in as a custom property rather than a style object. */}
                <div className="trend-bar">
                  <div
                    className="trend-bar__fill"
                    style={{ '--bar': `${Math.min((count / peakTrend) * 100, 100)}%` }}
                  />
                </div>
                <div className="trend__count">{count}</div>
              </div>
            ))}
          </div>
        ) : (
          <p className="muted-text">{t('stats.noData')}</p>
        )}
      </section>

      <button type="button" className="btn btn--primary" onClick={onBack}>
        {t('ui.backHome')}
      </button>
    </StatsShell>
  );
}

export default Stats;
