"""Tests for the leaderboard scoring logic."""

import pytest
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from fastapi.testclient import TestClient

import main
from database import SessionLocal, User, Rating, Mensa, Meal, CommentVote, PhotoVote, LeaderboardScore
import auth


@pytest.fixture()
def client(monkeypatch, tmp_path, sqlite_db):
    """TestClient on a throwaway schema."""
    monkeypatch.setattr(main, "UPLOAD_DIR", str(tmp_path))

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    main.app.dependency_overrides[main.get_db] = override_get_db
    try:
        yield TestClient(main.app)
    finally:
        main.app.dependency_overrides.clear()


@pytest.fixture()
def user_factory(sqlite_db):
    """Create a user and return it."""
    from datetime import date as date_cls

    def _create(username, display_name=None):
        db = sqlite_db()
        try:
            user = User(
                username=username,
                display_name=display_name,
                password_hash=auth.hash_password("test-password-123")
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            return user
        finally:
            db.close()

    return _create


@pytest.fixture()
def rating_factory(sqlite_db):
    """Create a rating for a user."""
    from datetime import date as date_cls

    def _create(user, comment=None, photo_url=None, rating=5, meal_name=None):
        db = sqlite_db()
        try:
            # Create a meal if needed
            mensa = db.query(Mensa).first()
            if not mensa:
                mensa = Mensa(name="Zentralmensa")
                db.add(mensa)
                db.commit()
                db.refresh(mensa)

            meal = db.query(Meal).filter_by(
                name=meal_name or f"Testgericht {user.id}",
                mensa_id=mensa.id
            ).first()
            if not meal:
                meal = Meal(
                    name=meal_name or f"Testgericht {user.id}",
                    name_de=meal_name or f"Testgericht {user.id}",
                    type="main",
                    date=date_cls.today(),
                    mensa_id=mensa.id,
                    description="Reis, Salat"
                )
                db.add(meal)
                db.commit()
                db.refresh(meal)

            rating_obj = Rating(
                meal_id=meal.id,
                rating=rating,
                comment=comment,
                user_name=user.username,
                user_id=user.id,
                photo_url=photo_url
            )
            db.add(rating_obj)
            db.commit()
            db.refresh(rating_obj)
            return rating_obj
        finally:
            db.close()

    return _create


@pytest.fixture()
def vote_factory(sqlite_db):
    """Create votes on ratings."""
    def _comment_vote(rating, user, direction=1):
        db = sqlite_db()
        try:
            vote = CommentVote(
                rating_id=rating.id,
                voter_id=f"voter_{user.id}",
                user_id=user.id,
                direction=direction
            )
            db.add(vote)
            db.commit()
            db.refresh(vote)
            return vote
        finally:
            db.close()

    def _photo_vote(rating, user, direction=1):
        db = sqlite_db()
        try:
            vote = PhotoVote(
                rating_id=rating.id,
                voter_id=f"voter_{user.id}",
                user_id=user.id,
                direction=direction
            )
            db.add(vote)
            db.commit()
            db.refresh(vote)
            return vote
        finally:
            db.close()

    return {'comment': _comment_vote, 'photo': _photo_vote}


@pytest.fixture()
def auth_headers(sqlite_db):
    """Create auth headers for a user."""
    def _headers(user):
        db = sqlite_db()
        try:
            token = auth.issue_token(db, user)
            return {"Authorization": f"Bearer {token}"}
        finally:
            db.close()

    return _headers


class TestCalculateUserContributionScore:
    """Tests for calculate_user_contribution_score function."""

    def test_basic_scoring(self, sqlite_db, user_factory, rating_factory, vote_factory):
        """Test that a user gets 1 point for a rating with a comment or photo."""
        from scoring import calculate_user_contribution_score
        
        user = user_factory("testuser")
        rating = rating_factory(user, comment="Great food!")
        
        # User should have 1 point
        score = calculate_user_contribution_score(sqlite_db(), user.id)
        assert score == 1

    def test_photo_only_counts(self, sqlite_db, user_factory, rating_factory, vote_factory):
        """Test that a rating with only a photo also counts."""
        from scoring import calculate_user_contribution_score
        
        user = user_factory("testuser2")
        rating = rating_factory(user, photo_url="/uploads/test.jpg")
        
        # User should have 1 point
        score = calculate_user_contribution_score(sqlite_db(), user.id)
        assert score == 1

    def test_stars_only_no_point(self, sqlite_db, user_factory, rating_factory, vote_factory):
        """Test that a rating with only stars (no comment/photo) doesn't count."""
        from scoring import calculate_user_contribution_score
        
        user = user_factory("testuser3")
        rating = rating_factory(user, comment=None, photo_url=None)
        
        # User should have 0 points - stars-only ratings don't count
        score = calculate_user_contribution_score(sqlite_db(), user.id)
        assert score == 0

    def test_daily_cap(self, sqlite_db, user_factory, rating_factory, vote_factory):
        """Test that daily point cap is 20."""
        from scoring import calculate_user_contribution_score
        
        user = user_factory("testuser4")
        
        # Create 25 ratings with comments on the same day
        for i in range(25):
            rating_factory(user, comment=f"Comment {i}")
        
        # User should have max 20 points (daily cap)
        score = calculate_user_contribution_score(sqlite_db(), user.id)
        assert score == 20

    def test_multiple_days_no_cap(self, sqlite_db, user_factory, rating_factory, vote_factory):
        """Test that ratings on different days accumulate."""
        from scoring import calculate_user_contribution_score
        
        user = user_factory("testuser5")
        
        # Create ratings on different days
        for i in range(5):
            rating_factory(user, comment=f"Comment {i}")
        
        # User should have 5 points (5 days, 1 point each)
        score = calculate_user_contribution_score(sqlite_db(), user.id)
        assert score == 5

    def test_self_vote_excluded(self, sqlite_db, user_factory, rating_factory, vote_factory):
        """Test that self-votes don't count toward the score."""
        from scoring import calculate_user_contribution_score
        
        user = user_factory("testuser6")
        rating = rating_factory(user, comment="My own comment")
        
        # User votes on their own rating
        vote_factory['comment'](rating, user, direction=1)
        
        # User should still have 1 point (the rating itself counts, not the self-vote)
        score = calculate_user_contribution_score(sqlite_db(), user.id)
        assert score == 1

    def test_other_votes_count(self, sqlite_db, user_factory, rating_factory, vote_factory):
        """Test that votes from other users count toward the score."""
        from scoring import calculate_user_contribution_score
        
        user1 = user_factory("testuser7")
        user2 = user_factory("testuser8")
        rating = rating_factory(user1, comment="Good food")
        
        # Another user votes on the rating
        vote_factory['comment'](rating, user2, direction=1)
        
        # User1 should have 1 point (rating has a comment and received a vote)
        score = user1_score = calculate_user_contribution_score(sqlite_db(), user1.id)
        assert score == 1


class TestLeaderboardEntry:
    """Tests for leaderboard entry generation."""

    def test_leaderboard_ranking(self, sqlite_db, user_factory, rating_factory, vote_factory):
        """Test that leaderboard correctly ranks users by score."""
        from scoring import get_leaderboard
        
        # Create users with different scores
        user1 = user_factory("topuser")
        user2 = user_factory("middleuser")
        user3 = user_factory("bottomuser")
        
        # User 1: 10 ratings
        for i in range(10):
            rating_factory(user1, comment=f"Comment {i}")
        
        # User 2: 5 ratings
        for i in range(5):
            rating_factory(user2, comment=f"Comment {i}")
        
        # User 3: 1 rating
        rating_factory(user3, comment="One comment")
        
        leaderboard = get_leaderboard(sqlite_db())
        
        assert leaderboard['total'] == 3
        assert len(leaderboard['users']) == 3
        
        # Check ranking order
        assert leaderboard['users'][0]['username'] == "topuser"
        assert leaderboard['users'][0]['score'] == 10
        assert leaderboard['users'][0]['rank'] == 1
        
        assert leaderboard['users'][1]['username'] == "middleuser"
        assert leaderboard['users'][1]['score'] == 5
        assert leaderboard['users'][1]['rank'] == 2
        
        assert leaderboard['users'][2]['username'] == "bottomuser"
        assert leaderboard['users'][2]['score'] == 1
        assert leaderboard['users'][2]['rank'] == 3

    def test_badge_assignment(self, sqlite_db, user_factory, rating_factory, vote_factory):
        """Test that badges are assigned based on percentile."""
        from scoring import get_leaderboard
        
        # Create 10 users
        users = []
        for i in range(10):
            user = user_factory(f"user{i}")
            users.append(user)
            # Give each user different number of ratings
            for j in range(i + 1):
                rating_factory(user, comment=f"Comment {j}")
        
        leaderboard = get_leaderboard(sqlite_db())
        
        # Top 10% (1 user) -> Platinum
        assert leaderboard['users'][0]['badge'] == 'platinum'
        
        # Top 25% (2-3 users) -> Gold
        assert leaderboard['users'][1]['badge'] == 'gold'
        assert leaderboard['users'][2]['badge'] == 'gold'
        
        # Top 50% (4-6 users) -> Silver
        assert leaderboard['users'][3]['badge'] == 'silver'
        assert leaderboard['users'][4]['badge'] == 'silver'
        assert leaderboard['users'][5]['badge'] == 'silver'
        
        # Bottom 50% (7-10 users) -> Bronze
        for i in range(6, 10):
            assert leaderboard['users'][i]['badge'] == 'bronze'


class TestLeaderboardAPI:
    """Tests for leaderboard API endpoints."""

    def test_get_leaderboard_endpoint(self, client, sqlite_db, user_factory, rating_factory, vote_factory):
        """Test the /api/v1/leaderboard endpoint."""
        from scoring import get_leaderboard
        
        # Create test data
        user = user_factory("testuser")
        rating_factory(user, comment="Test comment")
        
        # Get leaderboard through API
        response = client.get("/api/v1/leaderboard")
        assert response.status_code == 200
        
        data = response.json()
        assert 'users' in data
        assert 'total' in data
        assert 'date' in data
        assert len(data['users']) >= 1

    def test_get_my_leaderboard_position(self, client, sqlite_db, user_factory, rating_factory, vote_factory, auth_headers):
        """Test the /api/v1/leaderboard/me endpoint."""
        from scoring import get_user_leaderboard_info
        
        user = user_factory("testuser")
        rating_factory(user, comment="Test comment")
        
        # Get position through API
        response = client.get("/api/v1/leaderboard/me", headers=auth_headers(user))
        assert response.status_code == 200
        
        data = response.json()
        assert data['username'] == "testuser"
        assert 'score' in data
        assert 'rank' in data
        assert 'badge' in data

    def test_recalculate_leaderboard(self, client, sqlite_db, user_factory, rating_factory, vote_factory, auth_headers):
        """Test the /api/v1/leaderboard/recalculate endpoint."""
        user = user_factory("testuser")
        rating_factory(user, comment="Test comment")
        
        # Trigger recalculation
        response = client.post("/api/v1/leaderboard/recalculate", headers=auth_headers(user))
        assert response.status_code == 204
        
        # Verify scores were updated
        score_entry = sqlite_db().query(LeaderboardScore).filter_by(user_id=user.id).first()
        assert score_entry is not None
        assert score_entry.score > 0


class TestLeaderboardScoreModel:
    """Tests for the LeaderboardScore database model."""

    def test_leaderboard_score_creation(self, sqlite_db, user_factory):
        """Test creating a leaderboard score entry."""
        db = sqlite_db()
        try:
            user = user_factory("testuser")
            
            score_entry = LeaderboardScore(
                user_id=user.id,
                date=date.today(),
                score=25,
                calculated_at=datetime.now()
            )
            db.add(score_entry)
            db.commit()
            
            # Verify it was created
            stored = db.query(LeaderboardScore).filter_by(user_id=user.id).first()
            assert stored is not None
            assert stored.score == 25
            assert stored.date == date.today()
        finally:
            db.close()

    def test_leaderboard_score_relationship(self, sqlite_db, user_factory):
        """Test the relationship between User and LeaderboardScore."""
        db = sqlite_db()
        try:
            user = user_factory("testuser")
            
            # Re-query user in the current session
            user = db.query(User).filter(User.id == user.id).first()
            
            # Create multiple score entries
            for i in range(3):
                score_entry = LeaderboardScore(
                    user_id=user.id,
                    date=date.today() - timedelta(days=i),
                    score=10 + i
                )
                db.add(score_entry)
            
            db.commit()
            
            # Refresh user to get the relationship loaded
            db.refresh(user)
            
            # Verify user's scores
            assert len(user.leaderboard_scores) == 3
            assert user.leaderboard_scores[0].score == 10
        finally:
            db.close()


class TestRecalculateAllLeaderboardScores:
    """Tests for the recalculate_all_leaderboard_scores function."""

    def test_full_recalculation(self, sqlite_db, user_factory, rating_factory, vote_factory):
        """Test that recalculation works correctly."""
        from scoring import recalculate_all_leaderboard_scores
        
        user = user_factory("testuser")
        
        # Create ratings
        for i in range(5):
            rating_factory(user, comment=f"Comment {i}")
        
        # Recalculate scores
        recalculate_all_leaderboard_scores(sqlite_db())
        
        # Verify score was stored
        score_entry = sqlite_db().query(LeaderboardScore).filter_by(user_id=user.id).first()
        assert score_entry is not None
        assert score_entry.score == 5  # 5 ratings with comments

    def test_recalculation_updates_existing(self, sqlite_db, user_factory, rating_factory, vote_factory):
        """Test that recalculation updates existing scores."""
        from scoring import recalculate_all_leaderboard_scores
        
        user = user_factory("testuser")
        
        # Create initial ratings
        for i in range(3):
            rating_factory(user, comment=f"Comment {i}")
        
        # First recalculation
        recalculate_all_leaderboard_scores(sqlite_db())
        
        # Verify initial score
        score_entry = sqlite_db().query(LeaderboardScore).filter_by(user_id=user.id).first()
        initial_score = score_entry.score
        assert initial_score == 3
        
        # Add more ratings
        for i in range(3, 7):
            rating_factory(user, comment=f"Comment {i}")
        
        # Second recalculation
        recalculate_all_leaderboard_scores(sqlite_db())
        
        # Verify score was updated
        score_entry = sqlite_db().query(LeaderboardScore).filter_by(user_id=user.id).first()
        assert score_entry.score == 7  # Updated to 7 ratings