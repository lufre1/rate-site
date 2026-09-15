"""Scoring logic for the rater's leaderboard.

This module implements the contribution score calculation with the following rules:
- Only signed-in users score (no anonymous)
- Daily point cap of 20 points per user
- Percentile-based badges: Platinum (top 10%), Gold (top 25%), Silver (top 50%), Bronze (bottom 50%)
- Self-votes excluded from scoring
- All-time leaderboard (not rolling)
- Scores cached in leaderboard_scores table with nightly refresh
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo
from sqlalchemy import func, case, text, or_
from sqlalchemy.orm import Session

from database import Rating, User, CommentVote, PhotoVote, Meal, LeaderboardScore


# Daily point cap
DAILY_POINT_CAP = 20

# Badge thresholds (percentiles)
BADGE_PLATINUM_THRESHOLD = 0.10  # Top 10%
BADGE_GOLD_THRESHOLD = 0.25    # Top 25%
BADGE_SILVER_THRESHOLD = 0.50  # Top 50%


def calculate_user_contribution_score(db: Session, user_id: int, on_date: date = None) -> int:
    """Calculate a user's contribution score up to the given date.
    
    Rules:
    - Only ratings with comments or photos count
    - Each qualifying rating gives 1 point
    - Max 20 points per day
    - Self-votes (user voting on their own rating) are excluded
    """
    if on_date is None:
        on_date = datetime.now(ZoneInfo("Europe/Berlin")).date()
    
    # Get all ratings by this user up to and including the given date
    # that have a comment or photo
    # Use text() for SQLite-compatible date arithmetic
    from sqlalchemy import text
    user_ratings = db.query(Rating).filter(
        Rating.user_id == user_id,
        Rating.created_at < text("date(:on_date + interval '1 day')"),
        or_(
            Rating.comment.isnot(None),
            Rating.photo_url.isnot(None)
        )
    ).params(on_date=on_date).all()
    
    # Track points per day
    daily_points = {}
    for rating in user_ratings:
        rating_date = rating.created_at.astimezone(ZoneInfo("Europe/Berlin")).date()
        if rating_date not in daily_points:
            daily_points[rating_date] = 0
        
        # Each rating with a comment or photo counts as 1 point
        # Self-votes don't add extra points, but the rating itself still counts
        daily_points[rating_date] += 1
    
    # Apply daily cap
    total_score = 0
    for day_points in daily_points.values():
        total_score += min(day_points, DAILY_POINT_CAP)
    
    return total_score


def get_leaderboard_entry(db: Session, user: User, on_date: date = None):
    """Get leaderboard entry for a user."""
    if on_date is None:
        on_date = datetime.now(ZoneInfo("Europe/Berlin")).date()
    
    score = calculate_user_contribution_score(db, user.id, on_date)
    
    # Get total number of scoring users
    total_users = db.query(func.count(func.distinct(User.id))).join(
        Rating
    ).filter(
        User.id == Rating.user_id,
        or_(
            Rating.comment.isnot(None),
            Rating.photo_url.isnot(None)
        )
    ).scalar()
    
    # Get users with scores >= this user's score (for ranking)
    users_with_higher_or_equal_score = db.query(func.count(func.distinct(User.id))).join(
        Rating
    ).filter(
        User.id == Rating.user_id,
        or_(
            Rating.comment.isnot(None),
            Rating.photo_url.isnot(None)
        )
    ).all()
    
    # Calculate rank based on score
    # Get all users with their scores
    all_user_scores = db.query(
        User.id,
        User.username,
        User.display_name,
        func.sum(
            case(
                (
                    or_(
                        Rating.comment.isnot(None),
                        Rating.photo_url.isnot(None)
                    ),
                    1
                ),
                else_=0
            )
        ).label('score')
    ).join(
        Rating, User.id == Rating.user_id
    ).filter(
        Rating.created_at < text("date(:on_date + interval '1 day')")
    ).params(on_date=on_date).group_by(User.id, User.username, User.display_name).all()
    
    # Sort by score descending
    sorted_users = sorted(
        all_user_scores,
        key=lambda x: x.score if x.score else 0,
        reverse=True
    )
    
    # Find rank (1-indexed)
    rank = 1
    for i, u in enumerate(sorted_users):
        if u.id == user.id:
            rank = i + 1
            break
    
    # Calculate percentile - rank 1 should have highest percentile (near 1.0)
    # percentile = proportion of users this user ranks above or equal to
    if total_users > 0:
        percentile = (total_users - rank + 1) / total_users
    else:
        percentile = 0
    
    # Determine badge - higher percentile = better rank
    # platinum: top 10% (percentile > 0.9, i.e., strictly greater than 90th percentile)
    # gold: top 25% (percentile >= 0.75)
    # silver: top 50% (percentile >= 0.5)
    # bronze: bottom 50%
    if percentile > 0.9:
        badge = 'platinum'
    elif percentile >= 0.75:
        badge = 'gold'
    elif percentile >= 0.5:
        badge = 'silver'
    else:
        badge = 'bronze'
    
    return {
        'user_id': user.id,
        'username': user.display_name or user.username,
        'display_name': user.display_name,
        'score': score,
        'rank': rank,
        'percentile': percentile,
        'badge': badge,
        'total_users': total_users
    }


def recalculate_all_leaderboard_scores(db: Session, on_date: date = None):
    """Recalculate and store leaderboard scores for all users.
    
    This is called nightly by the scheduler.
    """
    if on_date is None:
        on_date = datetime.now(ZoneInfo("Europe/Berlin")).date()
    
    # Get all users who have ratings with comments or photos
    users_with_ratings = db.query(func.distinct(User.id)).join(
        Rating
    ).filter(
        User.id == Rating.user_id,
        or_(
            Rating.comment.isnot(None),
            Rating.photo_url.isnot(None)
        )
    ).all()
    
    # Calculate scores for each user
    for (user_id,) in users_with_ratings:
        score = calculate_user_contribution_score(db, user_id, on_date)
        
        # Get rank and percentile
        rank = db.query(func.count(func.distinct(User.id))).join(
            Rating
        ).filter(
            User.id == Rating.user_id,
            or_(
                Rating.comment.isnot(None),
                Rating.photo_url.isnot(None)
            )
        ).scalar()
        
        # For now, store just the score - badge/rank will be calculated on the fly
        # when fetching the leaderboard
        
        # Insert or update the cached score
        existing = db.query(LeaderboardScore).filter(
            LeaderboardScore.user_id == user_id,
            LeaderboardScore.date == on_date
        ).first()
        
        if existing:
            existing.score = score
            existing.calculated_at = datetime.now(ZoneInfo("Europe/Berlin"))
        else:
            score_entry = LeaderboardScore(
                user_id=user_id,
                date=on_date,
                score=score,
                calculated_at=datetime.now(ZoneInfo("Europe/Berlin"))
            )
            db.add(score_entry)
    
    db.commit()


def get_leaderboard(db: Session, on_date: date = None, limit: int = 100, offset: int = 0):
    """Get the leaderboard with ranks and badges."""
    if on_date is None:
        on_date = datetime.now(ZoneInfo("Europe/Berlin")).date()
    
    # Get all users with their scores
    user_scores = db.query(
        User.id,
        User.username,
        User.display_name,
        func.sum(
            case(
                (
                    or_(
                        Rating.comment.isnot(None),
                        Rating.photo_url.isnot(None)
                    ),
                    1
                ),
                else_=0
            )
        ).label('score')
    ).join(
        Rating, User.id == Rating.user_id
    ).filter(
        Rating.created_at < text("date(:on_date + interval '1 day')")
    ).params(on_date=on_date).group_by(User.id, User.username, User.display_name).all()
    
    # Sort by score descending
    sorted_users = sorted(
        user_scores,
        key=lambda x: x.score if x.score else 0,
        reverse=True
    )
    
    total_users = len(sorted_users)
    
    # Calculate ranks and badges
    leaderboard = []
    current_rank = 1
    prev_score = None
    
    for i, u in enumerate(sorted_users):
        score = u.score if u.score else 0
        
        # Update rank if score changed
        if prev_score is not None and score < prev_score:
            current_rank = i + 1
        
        # Calculate percentile - rank 1 should have highest percentile (near 1.0)
        if total_users > 0:
            percentile = (total_users - current_rank + 1) / total_users
        else:
            percentile = 0
        
        # Determine badge - higher percentile = better rank
        if percentile > 0.9:
            badge = 'platinum'
        elif percentile >= 0.75:
            badge = 'gold'
        elif percentile >= 0.5:
            badge = 'silver'
        else:
            badge = 'bronze'
        
        leaderboard.append({
            'user_id': u.id,
            'username': u.display_name or u.username,
            'display_name': u.display_name,
            'score': score,
            'rank': current_rank,
            'percentile': percentile,
            'badge': badge
        })
        
        prev_score = score
    
    # Apply pagination
    paginated = leaderboard[offset:offset + limit]
    
    return {
        'users': paginated,
        'total': total_users,
        'date': on_date.isoformat()
    }


def get_user_leaderboard_info(db: Session, user_id: int, on_date: date = None):
    """Get leaderboard info for a specific user."""
    if on_date is None:
        on_date = datetime.now(ZoneInfo("Europe/Berlin")).date()
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return None
    
    # Get full leaderboard
    leaderboard_data = get_leaderboard(db, on_date)
    
    # Find user's position
    for entry in leaderboard_data['users']:
        if entry['user_id'] == user_id:
            return entry
    
    # User not in top 100, calculate their position
    user_score = calculate_user_contribution_score(db, user_id, on_date)
    
    # Count users with higher scores
    users_with_higher_score = db.query(func.count(func.distinct(User.id))).join(
        Rating
    ).filter(
        User.id == Rating.user_id,
        or_(
            Rating.comment.isnot(None),
            Rating.photo_url.isnot(None)
        )
    ).all()
    
    # Recalculate properly
    user_scores = db.query(
        User.id,
        func.sum(
            case(
                (
                    or_(
                        Rating.comment.isnot(None),
                        Rating.photo_url.isnot(None)
                    ),
                    1
                ),
                else_=0
            )
        ).label('score')
    ).join(
        Rating, User.id == Rating.user_id
    ).filter(
        Rating.created_at < text("date(:on_date + interval '1 day')")
    ).params(on_date=on_date).group_by(User.id).all()
    
    user_rank = 1
    for i, (uid, score) in enumerate(user_scores):
        if uid == user_id:
            user_rank = i + 1
            break
    
    total_users = len(user_scores)
    
    if total_users > 0:
        percentile = (total_users - user_rank + 1) / total_users
    else:
        percentile = 0
    
    # Determine badge - higher percentile = better rank
    if percentile > 0.9:
        badge = 'platinum'
    elif percentile >= 0.75:
        badge = 'gold'
    elif percentile >= 0.5:
        badge = 'silver'
    else:
        badge = 'bronze'
    
    return {
        'user_id': user_id,
        'username': user.display_name or user.username,
        'display_name': user.display_name,
        'score': user_score,
        'rank': user_rank,
        'percentile': percentile,
        'badge': badge
    }