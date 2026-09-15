import React, { useState, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { API, authHeaders, getToken } from './shared';

function Leaderboard({ onBack, language, user }) {
  const { t } = useTranslation();
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const [myPosition, setMyPosition] = useState(null);

  const LIMIT = 20;
  const loadedRef = useRef(false);

  useEffect(() => {
    loadLeaderboard();
    loadMyPosition();
  }, [offset, language]);

  const loadLeaderboard = async () => {
    if (loadedRef.current && offset === 0) {
      // Already loaded initial page, skip duplicate
      return;
    }
    
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${API}/api/v1/leaderboard?limit=${LIMIT}&offset=${offset}`);
      if (!response.ok) throw new Error('Failed to load leaderboard');
      const data = await response.json();
      
      // When offset is 0, replace users; otherwise append
      if (offset === 0) {
        setUsers(data.users);
      } else {
        setUsers(prev => [...prev, ...data.users]);
      }
      
      setHasMore(data.users.length === LIMIT);
      loadedRef.current = true;
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

  // Group users by badge tier
  const getTierForBadge = (badge) => {
    const order = ['platinum', 'gold', 'silver', 'bronze'];
    return order.indexOf(badge);
  };

  const getTierLabel = (badge) => {
    switch (badge) {
      case 'platinum': return t('leaderboard.tier.platinum');
      case 'gold': return t('leaderboard.tier.gold');
      case 'silver': return t('leaderboard.tier.silver');
      case 'bronze': return t('leaderboard.tier.bronze');
      default: return badge;
    }
  };

  // Check if current user matches a leaderboard entry
  const isCurrentUser = (entry) => {
    if (!user || !user.user_id) return false;
    return entry.user_id === user.user_id;
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
              {isCurrentUser(myPosition) && <span className="you-label">{t('leaderboard.you')}</span>}
            </div>
            <span className="leaderboard-score">{myPosition.score} {t('leaderboard.points')}</span>
          </div>
        </div>
      )}

      {/* Error state */}
      {error && (
        <div className="leaderboard-error">
          <span>{t('leaderboard.error')}</span>
          <span>{error}</span>
          <button type="button" className="btn--quiet" onClick={loadLeaderboard}>
            {t('ui.retry')}
          </button>
        </div>
      )}

      {/* Leaderboard table */}
      <div className="leaderboard-table-container">
        <table className="leaderboard-table">
          <thead>
            <tr>
              <th className="numeric">{t('leaderboard.columns.rank')}</th>
              <th>{t('leaderboard.columns.name')}</th>
              <th className="numeric">{t('leaderboard.columns.tokens')}</th>
              <th className="numeric">{t('leaderboard.columns.tokens30d')}</th>
              <th className="numeric">{t('leaderboard.columns.rank30d')}</th>
            </tr>
          </thead>
          <tbody>
            {/* Group users by tier */}
            {['platinum', 'gold', 'silver', 'bronze'].map((tier) => {
              const tierUsers = users.filter(u => u.badge === tier);
              if (tierUsers.length === 0) return null;

              return (
                <React.Fragment key={tier}>
                  <tr className="tier-header" data-tier={tier}>
                    <td colSpan={5}>{getTierLabel(tier)}</td>
                  </tr>
                  {tierUsers.map((userEntry, index) => (
                    <tr 
                      key={userEntry.user_id} 
                      className={isCurrentUser(userEntry) ? 'is-me' : ''}
                    >
                      <td className="numeric leaderboard-rank">#{userEntry.rank}</td>
                      <td className="leaderboard-username">
                        {userEntry.username}
                        {isCurrentUser(userEntry) && <span className="you-label">{t('leaderboard.you')}</span>}
                      </td>
                      <td className="numeric leaderboard-score">{userEntry.score}</td>
                      <td className="numeric placeholder-dash">–</td>
                      <td className="numeric placeholder-dash">–</td>
                    </tr>
                  ))}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
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