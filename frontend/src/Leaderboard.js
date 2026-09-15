import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { API, authHeaders, getToken } from './shared';

function Leaderboard({ onBack, language }) {
  const { t } = useTranslation();
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const [myPosition, setMyPosition] = useState(null);

  const LIMIT = 20;

  useEffect(() => {
    loadLeaderboard();
    loadMyPosition();
  }, [offset, language]);

  const loadLeaderboard = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${API}/api/v1/leaderboard?limit=${LIMIT}&offset=${offset}`);
      if (!response.ok) throw new Error('Failed to load leaderboard');
      const data = await response.json();
      setUsers(prev => [...prev, ...data.users]);
      setHasMore(data.users.length === LIMIT);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const loadMyPosition = async () => {
    const token = getToken();
    if (!token) return;
    
    try {
      const response = await fetch(`${API}/api/v1/leaderboard/me`, {
        headers: authHeaders()
      });
      if (response.ok) {
        const data = await response.json();
        setMyPosition(data);
      }
    } catch (err) {
      // Ignore errors - user might not be in leaderboard yet
    }
  };

  const getBadgeColor = (badge) => {
    switch (badge) {
      case 'platinum': return '#e5e4e2';
      case 'gold': return '#ffd700';
      case 'silver': return '#c0c0c0';
      case 'bronze': return '#cd7f32';
      default: return '#ccc';
    }
  };

  const getBadgeLabel = (badge) => {
    switch (badge) {
      case 'platinum': return t('leaderboard.badges.platinum');
      case 'gold': return t('leaderboard.badges.gold');
      case 'silver': return t('leaderboard.badges.silver');
      case 'bronze': return t('leaderboard.badges.bronze');
      default: return badge;
    }
  };

  return (
    <div className="page--narrow">
      <h2 className="view-title">{t('leaderboard.title')}</h2>

      {/* My position card */}
      {myPosition && (
        <div className="card leaderboard-my-position">
          <h3>{t('leaderboard.myPosition')}</h3>
          <div className="leaderboard-entry">
            <span className="leaderboard-rank">#{myPosition.rank}</span>
            <div className="leaderboard-user">
              <span className="leaderboard-username">{myPosition.username}</span>
              <span className="leaderboard-badge" style={{ backgroundColor: getBadgeColor(myPosition.badge) }}>
                {getBadgeLabel(myPosition.badge)}
              </span>
            </div>
            <span className="leaderboard-score">{myPosition.score} {t('leaderboard.points')}</span>
          </div>
        </div>
      )}

      {/* Error state */}
      {error && (
        <div className="error-text">
          {t('leaderboard.error')} {error}
          <button type="button" className="btn--quiet" onClick={loadLeaderboard}>
            {t('ui.retry')}
          </button>
        </div>
      )}

      {/* Leaderboard list */}
      <div className="leaderboard-list">
        {users.map((user, index) => (
          <div key={user.user_id} className="leaderboard-entry">
            <span className="leaderboard-rank">#{user.rank}</span>
            <div className="leaderboard-user">
              <span className="leaderboard-username">{user.username}</span>
              <span className="leaderboard-badge" style={{ backgroundColor: getBadgeColor(user.badge) }}>
                {getBadgeLabel(user.badge)}
              </span>
            </div>
            <span className="leaderboard-score">{user.score} {t('leaderboard.points')}</span>
          </div>
        ))}
      </div>

      {/* Loading more */}
      {loading && (
        <div className="leaderboard-loading">
          {t('leaderboard.loading')}
        </div>
      )}

      {/* Load more button */}
      {hasMore && !loading && (
        <div className="leaderboard-load-more">
          <button type="button" className="btn btn--primary" onClick={() => setOffset(prev => prev + LIMIT)}>
            {t('leaderboard.loadMore')}
          </button>
        </div>
      )}

      <button type="button" className="btn btn--primary mt-6" onClick={onBack}>
        {t('ui.backHome')}
      </button>
    </div>
  );
}

export default Leaderboard;