import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { API, authHeaders, thumbSrc, thumbErrorHandler, Lightbox } from './shared';

function renderStars(rating) {
  const filled = Math.min(5, Math.max(0, Math.round(rating)));
  return '★'.repeat(filled) + '☆'.repeat(5 - filled);
}

function RewindShell({ children }) {
  const { t } = useTranslation();
  return (
    <>
      <h2 className="view-title">{t('rewind.title')}</h2>
      {children}
    </>
  );
}

function Rewind({ onBack, language, user }) {
  const { t } = useTranslation();
  const [period, setPeriod] = useState('week');
  const [community, setCommunity] = useState(null);
  const [personal, setPersonal] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [enlargedImage, setEnlargedImage] = useState(null);

  useEffect(() => {
    setLoading(true);
    setError('');
    const communityUrl = `${API}/api/v1/rewind?period=${period}&scope=community&lang=${language}`;
    const personalUrl = `${API}/api/v1/rewind?period=${period}&scope=me&lang=${language}`;

    const fetchCommunity = fetch(communityUrl)
      .then(r => (r.ok ? r.json() : Promise.reject(r.status)));

    const fetchPersonal = user
      ? fetch(personalUrl, { headers: authHeaders() })
          .then(r => (r.ok ? r.json() : Promise.reject(r.status)))
      : Promise.resolve(null);

    Promise.all([fetchCommunity, fetchPersonal])
      .then(([commData, persData]) => {
        setCommunity(commData);
        setPersonal(persData);
        setLoading(false);
      })
      .catch(() => {
        setError(t('rewind.error'));
        setLoading(false);
      });
  }, [period, language, user]);

  if (loading) {
    return (
      <RewindShell>
        <div className="loading">{t('rewind.loading')}</div>
      </RewindShell>
    );
  }

  if (error) {
    return (
      <RewindShell>
        <div className="loading error-text">{error}</div>
      </RewindShell>
    );
  }

  return (
    <RewindShell>
      <div className="rewind-toggle">
        <button
          type="button"
          className="btn btn--ghost"
          aria-pressed={period === 'week'}
          onClick={() => setPeriod('week')}
        >
          {t('rewind.week')}
        </button>
        <button
          type="button"
          className="btn btn--ghost"
          aria-pressed={period === 'month'}
          onClick={() => setPeriod('month')}
        >
          {t('rewind.month')}
        </button>
      </div>

      {user && personal && (
        <section className="stats-section">
          <h3 className="stats-section__title">{t('rewind.personal')}</h3>
          <p className="muted-text">
            {t('rewind.ratedCount', { n: personal.dishes_rated })}
          </p>
          {personal.enough ? (
            <div>
              {personal.dishes && personal.dishes.length > 0 ? (
                <div className="rewind-list">
                  {personal.dishes.map((dish, index) => (
                    <div key={dish.id || index} className="rewind-card">
                      <div className="rewind-card__pos" data-medal={index}>
                        {index + 1}
                      </div>
                      {dish.photo_url && (
                        <button
                          type="button"
                          className="rewind-card__photo-btn"
                          onClick={() => setEnlargedImage(`${API}${dish.photo_url}`)}
                        >
                          <img
                            className="rewind-card__photo"
                            src={`${API}${thumbSrc(dish.photo_url)}`}
                            alt=""
                            loading="lazy"
                            decoding="async"
                            onError={thumbErrorHandler(`${API}${dish.photo_url}`)}
                          />
                        </button>
                      )}
                      <div className="rewind-card__body">
                        <div className="rewind-card__name">{dish.name}</div>
                        <div className="rewind-card__sub">{dish.mensa}</div>
                        <div className="rewind-card__score">
                          <div className="stars stars--lg">
                            {renderStars(dish.rating)} {dish.rating.toFixed(1)}
                          </div>
                        </div>
                        {dish.comment && (
                          <div className="rewind-card__comment">
                            <span className="review__text">{dish.comment}</span>
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="muted-text">{t('rewind.notEnough')}</p>
              )}
            </div>
          ) : (
            <p className="muted-text">{t('rewind.notEnough')}</p>
          )}
        </section>
      )}

      {community && (
        <section className="stats-section">
          <h3 className="stats-section__title">{t('rewind.community')}</h3>
          <p className="muted-text">
            {t('rewind.servedCount', { n: community.dishes_rated })}
          </p>
          {community.enough ? (
            <div>
              {community.dishes && community.dishes.length > 0 ? (
                <div className="rewind-list">
                  {community.dishes.map((dish, index) => (
                    <div key={dish.id || index} className="rewind-card">
                      <div className="rewind-card__pos" data-medal={index}>
                        {index + 1}
                      </div>
                      {dish.photo_url && (
                        <button
                          type="button"
                          className="rewind-card__photo-btn"
                          onClick={() => setEnlargedImage(`${API}${dish.photo_url}`)}
                        >
                          <img
                            className="rewind-card__photo"
                            src={`${API}${thumbSrc(dish.photo_url)}`}
                            alt=""
                            loading="lazy"
                            decoding="async"
                            onError={thumbErrorHandler(`${API}${dish.photo_url}`)}
                          />
                        </button>
                      )}
                      <div className="rewind-card__body">
                        <div className="rewind-card__name">{dish.name}</div>
                        <div className="rewind-card__sub">{dish.mensa}</div>
                        <div className="rewind-card__score">
                          <div className="stars stars--lg">
                            {renderStars(dish.avg_rating)} {dish.avg_rating.toFixed(1)}
                          </div>
                          <div className="rewind-card__count">
                            {t('stats.ratings', { count: dish.rating_count })}
                          </div>
                        </div>
                        {dish.comments && dish.comments.length > 0 && (
                          <div className="rewind-card__comment">
                            <span className="review__text">
                              {dish.comments[0].text} — {dish.comments[0].author}
                            </span>
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="muted-text">{t('rewind.notEnough')}</p>
              )}
            </div>
          ) : (
            <p className="muted-text">{t('rewind.notEnough')}</p>
          )}
        </section>
      )}

      <button type="button" className="btn btn--primary" onClick={onBack}>
        {t('ui.backHome')}
      </button>

      {enlargedImage && (
        <Lightbox src={enlargedImage} alt={t('ui.enlargedPhoto')}
          onClose={() => setEnlargedImage(null)} />
      )}
    </RewindShell>
  );
}

export default Rewind;