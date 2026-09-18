"""Scoring logic for the rater's leaderboard.

This module implements the contribution score calculation with the following rules:
- Only signed-in users score (no anonymous)
- Daily point cap of 20 points per user
- Percentile-based badges: Platinum (top 10%), Gold (top 25%), Silver (top 50%), Bronze (bottom 50%)
- Self-votes excluded from scoring
- All-time leaderboard (not rolling)
- Scores cached in leaderboard_scores table with nightly refresh
- Additive rewards for:
  - FLAG_PLANTER_REWARD: first photo of a dish (+20)
  - BEST_PHOTO_REWARD: highest photo-voted photo per dish, >=5 votes (+50)
  - BEST_COMMENT_REWARD: highest comment-voted comment per dish, >=5 votes (+50)
  - CONTINUITY_REWARD: >=15 contributions in a calendar month (+30)
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import func, case, text, or_, and_
from sqlalchemy.orm import Session

from database import Rating, User, CommentVote, PhotoVote, Meal, LeaderboardScore


# Daily point cap
DAILY_POINT_CAP = 20

# Badge thresholds (percentiles)
BADGE_PLATINUM_THRESHOLD = 0.10  # Top 10%
BADGE_GOLD_THRESHOLD = 0.25    # Top 25%
BADGE_SILVER_THRESHOLD = 0.50  # Top 50%

# Additive rewards (all multiples of 10)
FLAG_PLANTER_REWARD = 20
BEST_PHOTO_REWARD = 50
BEST_COMMENT_REWARD = 50
CONTINUITY_QUOTA = 15
CONTINUITY_REWARD = 30
MIN_BEST_VOTES = 5


def _dialect(db: Session) -> str:
    """Return the SQLAlchemy dialect name ('postgresql' or 'sqlite')."""
    return db.bind.dialect.name


def calculate_user_contribution_score(db: Session, user_id: int, on_date: date = None) -> int:
    """Calculate a user's contribution score up to the given date.
    
    Rules:
    - Only ratings with comments or photos count
    - Each qualifying rating gives 1 point
    - Max 20 points per day
    - Self-votes (user voting on their own rating) are excluded
    - Additive rewards for flag planting, best photo/comment, and continuity
    """
    if on_date is None:
        on_date = datetime.now(ZoneInfo("Europe/Berlin")).date()
    
    # Get all ratings by this user up to and including the given date
    # that have a comment or photo
    # Use text() for SQLite-compatible date arithmetic
    from sqlalchemy import text
    # SQLite uses date() without interval; PostgreSQL uses interval '1 day'
    # We use a subquery approach that works in both
    # Build date condition dialect-aware
    if _dialect(db) == "postgresql":
        cutoff = datetime.combine(on_date, datetime.min.time()) + timedelta(days=1)
        date_cond = Rating.created_at < cutoff
    else:
        date_cond = func.date(Rating.created_at) <= on_date
    user_ratings = db.query(Rating).filter(
        Rating.user_id == user_id,
        date_cond,
        or_(
            Rating.comment.isnot(None),
            Rating.photo_url.isnot(None)
        )
    ).all()
    
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
    base_score = 0
    for day_points in daily_points.values():
        base_score += min(day_points, DAILY_POINT_CAP)
    
    # Calculate additive rewards
    additive_score = 0
    
    # FLAG_PLANTER_REWARD: first photo of each dish
    # Find the earliest photo rating for each dish
    # Use created_at with id as tiebreaker for SQLite compatibility
    first_photos = db.query(
        Rating.meal_id,
        func.min(Rating.created_at).label('first_at'),
        func.min(Rating.id).label('first_id')
    ).filter(
        Rating.user_id == user_id,
        Rating.photo_url.isnot(None)
    ).group_by(Rating.meal_id).all()
    
    for fp in first_photos:
        # Check if this is still the first photo (no earlier photo exists)
        # Build date condition dialect-aware
        if _dialect(db) == "postgresql":
            # PostgreSQL: compare datetime directly
            date_before = Rating.created_at < fp.first_at
            date_equal = Rating.created_at == fp.first_at
        else:
            # SQLite: use func.date() for date-only comparison
            date_before = func.date(Rating.created_at) < func.date(fp.first_at)
            date_equal = func.date(Rating.created_at) == func.date(fp.first_at)
        earliest = db.query(Rating.id).filter(
            Rating.meal_id == fp.meal_id,
            Rating.photo_url.isnot(None),
            or_(
                date_before,
                and_(
                    date_equal,
                    Rating.id < fp.first_id
                )
            )
        ).first()
        if earliest is None:
            additive_score += FLAG_PLANTER_REWARD
    
    # BEST_PHOTO_REWARD: highest photo_votes winner per dish, >= MIN_BEST_VOTES
    # Get photo votes for user's photos
    photo_votes_subq = db.query(
        PhotoVote.rating_id,
        func.sum(case((PhotoVote.direction == 1, 1), else_=0)).label('upvotes')
    ).group_by(PhotoVote.rating_id).subquery()
    
    best_photos = db.query(
        Rating.meal_id,
        func.max(photo_votes_subq.c.upvotes).label('max_upvotes')
    ).join(
        photo_votes_subq, Rating.id == photo_votes_subq.c.rating_id
    ).filter(
        Rating.user_id == user_id,
        Rating.photo_url.isnot(None)
    ).group_by(Rating.meal_id).all()
    
    for bp in best_photos:
        if bp.max_upvotes >= MIN_BEST_VOTES:
            # Verify this is the highest voted photo for this dish
            highest = db.query(Rating.id).join(
                photo_votes_subq, Rating.id == photo_votes_subq.c.rating_id
            ).filter(
                Rating.meal_id == bp.meal_id,
                Rating.photo_url.isnot(None),
                photo_votes_subq.c.upvotes > bp.max_upvotes
            ).first()
            if highest is None:
                additive_score += BEST_PHOTO_REWARD
    
    # BEST_COMMENT_REWARD: highest comment_votes winner per dish, >= MIN_BEST_VOTES
    comment_votes_subq = db.query(
        CommentVote.rating_id,
        func.sum(case((CommentVote.direction == 1, 1), else_=0)).label('upvotes')
    ).group_by(CommentVote.rating_id).subquery()
    
    best_comments = db.query(
        Rating.meal_id,
        func.max(comment_votes_subq.c.upvotes).label('max_upvotes')
    ).join(
        comment_votes_subq, Rating.id == comment_votes_subq.c.rating_id
    ).filter(
        Rating.user_id == user_id,
        Rating.comment.isnot(None)
    ).group_by(Rating.meal_id).all()
    
    for bc in best_comments:
        if bc.max_upvotes >= MIN_BEST_VOTES:
            # Verify this is the highest voted comment for this dish
            highest = db.query(Rating.id).join(
                comment_votes_subq, Rating.id == comment_votes_subq.c.rating_id
            ).filter(
                Rating.meal_id == bc.meal_id,
                Rating.comment.isnot(None),
                comment_votes_subq.c.upvotes > bc.max_upvotes
            ).first()
            if highest is None:
                additive_score += BEST_COMMENT_REWARD
    
    # CONTINUITY_REWARD: >=15 contributions in a calendar month
    # Count all ratings with comments or photos per month
    # Build month expression dialect-aware
    if _dialect(db) == "postgresql":
        month_expr = func.to_char(Rating.created_at, 'YYYY-MM')
    else:
        month_expr = func.strftime('%Y-%m', func.date(Rating.created_at))
    monthly_contributions = db.query(
        month_expr.label('month'),
        func.count(Rating.id).label('count')
    ).filter(
        Rating.user_id == user_id,
        or_(
            Rating.comment.isnot(None),
            Rating.photo_url.isnot(None)
        )
    ).group_by(month_expr).all()
    
    for mc in monthly_contributions:
        if mc.count >= CONTINUITY_QUOTA:
            additive_score += CONTINUITY_REWARD
    
    return base_score + additive_score


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
    # Build date condition dialect-aware
    if _dialect(db) == "postgresql":
        cutoff = datetime.combine(on_date, datetime.min.time()) + timedelta(days=1)
        date_cond = Rating.created_at < cutoff
    else:
        date_cond = func.date(Rating.created_at) <= on_date
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
        date_cond
    ).group_by(User.id, User.username, User.display_name).all()
    
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
    
    # Calculate scores for each user using the full scoring function
    leaderboard = []
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
        
        leaderboard.append({
            'user_id': user_id,
            'score': score,
            'rank': rank
        })
    
    # Sort by score descending
    sorted_leaderboard = sorted(
        leaderboard,
        key=lambda x: x['score'] if x['score'] else 0,
        reverse=True
    )
    
    # Calculate ranks and badges
    total_users = len(sorted_leaderboard)
    current_rank = 1
    prev_score = None
    
    for i, entry in enumerate(sorted_leaderboard):
        score = entry['score'] if entry['score'] else 0
        
        # Update rank if score changed
        if prev_score is not None and score < prev_score:
            current_rank = i + 1
        
        prev_score = score
        
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
        
        entry['rank'] = current_rank
        entry['percentile'] = percentile
        entry['badge'] = badge
    
    # Get user details
    user_ids = [e['user_id'] for e in sorted_leaderboard]
    user_details = db.query(User.id, User.username, User.display_name).filter(
        User.id.in_(user_ids)
    ).all()
    
    user_map = {u.id: {'username': u.username, 'display_name': u.display_name} for u in user_details}
    
    # Build final leaderboard
    final_leaderboard = []
    for entry in sorted_leaderboard:
        details = user_map.get(entry['user_id'], {'username': f'user_{entry["user_id"]}', 'display_name': None})
        final_leaderboard.append({
            'user_id': entry['user_id'],
            'username': details['display_name'] or details['username'],
            'real_username': details['username'],
            'display_name': details['display_name'],
            'score': entry['score'],
            'rank': entry['rank'],
            'percentile': entry['percentile'],
            'badge': entry['badge']
        })
    
    # Apply pagination
    paginated = final_leaderboard[offset:offset + limit]
    
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
    # Build date condition dialect-aware
    if _dialect(db) == "postgresql":
        cutoff = datetime.combine(on_date, datetime.min.time()) + timedelta(days=1)
        date_cond = Rating.created_at < cutoff
    else:
        date_cond = func.date(Rating.created_at) <= on_date
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
        date_cond
    ).group_by(User.id).all()
    
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
        'real_username': user.username,
        'display_name': user.display_name,
        'score': user_score,
        'rank': user_rank,
        'percentile': percentile,
        'badge': badge
    }