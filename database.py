from sqlalchemy import create_engine, Column, Integer, String, Text, Float, DateTime, Boolean, JSON, Index, inspect, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.pool import QueuePool
from datetime import datetime
from contextlib import contextmanager
from config import db_config, api_config

Base = declarative_base()


def tmdb_poster_url(poster_path):
    """Visitors load images straight from TMDB's servers, not through HomeFlix and the tunnel"""
    return f'{api_config.TMDB_IMAGE_BASE_URL}{poster_path}' if poster_path else None


def tmdb_backdrop_url(backdrop_path):
    return f'{api_config.TMDB_BACKDROP_BASE_URL}{backdrop_path}' if backdrop_path else None


class Movie(Base):
    __tablename__ = 'movies'
    
    id = Column(Integer, primary_key=True)
    imdb_id = Column(String(20), unique=True, index=True, nullable=False)
    tmdb_id = Column(Integer, unique=True, index=True)
    title = Column(String(255), nullable=False, index=True)
    overview = Column(Text)
    release_date = Column(String(20), index=True)  # Index for sorting by date
    year = Column(String(4))
    rating = Column(String(10))
    duration = Column(String(20))
    genres = Column(JSON)
    poster_path = Column(String(255))
    backdrop_path = Column(String(255))
    vote_average = Column(Float)
    vote_count = Column(Integer)
    popularity = Column(Float, index=True)  # Index for sorting by popularity
    quality = Column(String(10), default='HD')
    is_trending = Column(Boolean, default=False, index=True)  # Index for filtering trending
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Composite indexes for common query patterns
    __table_args__ = (
        Index('idx_movie_trending_popularity', 'is_trending', 'popularity'),
        Index('idx_movie_release_date', 'release_date'),
    )
    
    def to_dict(self):
        return {
            'type': 'movie',  # Add type field
            'imdb_id': self.imdb_id,
            'id': self.imdb_id,  # Add id alias for consistency
            'tmdb_id': self.tmdb_id,
            'title': self.title,
            'overview': self.overview,
            'release_date': self.release_date,
            'year': self.year,
            'rating': self.rating,
            'duration': self.duration,
            'genres': self.genres,
            'poster_url': tmdb_poster_url(self.poster_path),
            'backdrop_url': tmdb_backdrop_url(self.backdrop_path),
            'vote_average': self.vote_average,
            'popularity': self.popularity,
            'quality': self.quality,
            'is_trending': self.is_trending,
        }

class TVShow(Base):
    __tablename__ = 'tvshows'
    
    id = Column(Integer, primary_key=True)
    imdb_id = Column(String(20), unique=True, index=True, nullable=False)
    tmdb_id = Column(Integer, unique=True, index=True)
    title = Column(String(255), nullable=False, index=True)
    overview = Column(Text)
    first_air_date = Column(String(20), index=True)  # Index for sorting by date
    year = Column(String(4))
    rating = Column(String(10))
    number_of_seasons = Column(Integer)
    genres = Column(JSON)
    poster_path = Column(String(255))
    backdrop_path = Column(String(255))
    vote_average = Column(Float)
    vote_count = Column(Integer)
    popularity = Column(Float, index=True)  # Index for sorting by popularity
    is_trending = Column(Boolean, default=False, index=True)  # Index for filtering trending
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Composite indexes for common query patterns
    __table_args__ = (
        Index('idx_tvshow_trending_popularity', 'is_trending', 'popularity'),
        Index('idx_tvshow_first_air_date', 'first_air_date'),
    )
    
    def to_dict(self):
        return {
            'type': 'series',  # Add type field
            'imdb_id': self.imdb_id,
            'id': self.imdb_id,  # Add id alias for consistency
            'tmdb_id': self.tmdb_id,
            'title': self.title,
            'overview': self.overview,
            'first_air_date': self.first_air_date,
            'year': self.year,
            'rating': self.rating,
            'number_of_seasons': self.number_of_seasons,
            'genres': self.genres,
            'poster_url': tmdb_poster_url(self.poster_path),
            'backdrop_url': tmdb_backdrop_url(self.backdrop_path),
            'vote_average': self.vote_average,
            'popularity': self.popularity,
            'is_trending': self.is_trending,
        }

class User(Base):
    """A person who signs in; My List, watch history and watched marks belong to one user"""
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    username = Column(String(30), unique=True, nullable=False, index=True)  # stored lowercase
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class MyList(Base):
    __tablename__ = 'my_list'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    media_type = Column(String(10), nullable=False, index=True)  # 'movie' or 'series'
    media_id = Column(String(20), nullable=False, index=True)  # imdb_id
    tmdb_id = Column(Integer)
    title = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)  # Index for sorting
    
    # Composite unique constraint to prevent duplicates
    __table_args__ = (
        Index('idx_mylist_user_type_id', 'user_id', 'media_type', 'media_id', unique=True),
    )
    
    def to_dict(self):
        # Simple dict representation without nested queries
        return {
            'type': self.media_type,
            'id': self.media_id,
            'imdb_id': self.media_id,
            'tmdb_id': self.tmdb_id,
            'title': self.title,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class WatchHistory(Base):
    """Track user's watch history and progress"""
    __tablename__ = 'watch_history'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    media_type = Column(String(10), nullable=False, index=True)  # 'movie' or 'series'
    media_id = Column(String(20), nullable=False, index=True)  # imdb_id
    tmdb_id = Column(Integer)
    title = Column(String(255), nullable=False)
    
    # Progress tracking
    progress_seconds = Column(Integer, default=0)  # Current position in seconds
    duration_seconds = Column(Integer, default=0)  # Total duration in seconds
    progress_percent = Column(Float, default=0.0)  # Progress percentage
    
    # Episode tracking (for TV shows)
    season_number = Column(Integer, nullable=True)
    episode_number = Column(Integer, nullable=True)
    
    # Metadata
    poster_path = Column(String(255))
    is_completed = Column(Boolean, default=False)  # Marked as watched if >95% complete
    last_watched = Column(DateTime, default=datetime.utcnow, index=True)  # Index for sorting
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Composite unique constraint for movies, unique per episode for series
    __table_args__ = (
        Index('idx_watch_history_user_lookup', 'user_id', 'media_type', 'media_id', 'season_number', 'episode_number', unique=True),
        Index('idx_watch_history_last_watched', 'last_watched'),
    )
    
    def to_dict(self):
        """Convert to dictionary for API responses"""
        result = {
            'type': self.media_type,
            'id': self.media_id,
            'imdb_id': self.media_id,
            'tmdb_id': self.tmdb_id,
            'title': self.title,
            'progress_seconds': self.progress_seconds,
            'duration_seconds': self.duration_seconds,
            'progress_percent': round(self.progress_percent, 2),
            'is_completed': self.is_completed,
            'last_watched': self.last_watched.isoformat() if self.last_watched else None,
            'poster_url': f'/poster/{self.media_type}/{self.tmdb_id}' if self.tmdb_id else None,
        }
        
        # Add episode info for series
        if self.media_type == 'series' and self.season_number and self.episode_number:
            result['season'] = self.season_number
            result['episode'] = self.episode_number
            result['episode_title'] = f"S{self.season_number}E{self.episode_number}"
        
        return result

class WatchedItems(Base):
    """Track items manually marked as watched by the user"""
    __tablename__ = 'watched_items'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    media_type = Column(String(10), nullable=False, index=True)  # 'movie' or 'series'
    media_id = Column(String(20), nullable=False, index=True)  # imdb_id
    tmdb_id = Column(Integer)
    title = Column(String(255), nullable=False)
    
    # Episode tracking (for TV shows)
    season_number = Column(Integer, nullable=True)
    episode_number = Column(Integer, nullable=True)
    
    # Metadata
    marked_at = Column(DateTime, default=datetime.utcnow, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Composite unique constraint for movies, unique per episode for series
    __table_args__ = (
        Index('idx_watched_items_user_lookup', 'user_id', 'media_type', 'media_id', 'season_number', 'episode_number', unique=True),
        Index('idx_watched_items_marked_at', 'marked_at'),
    )
    
    def to_dict(self):
        """Convert to dictionary for API responses"""
        result = {
            'type': self.media_type,
            'id': self.media_id,
            'imdb_id': self.media_id,
            'tmdb_id': self.tmdb_id,
            'title': self.title,
            'marked_at': self.marked_at.isoformat() if self.marked_at else None,
            'is_watched': True
        }
        
        # Add episode info for series
        if self.media_type == 'series' and self.season_number and self.episode_number:
            result['season'] = self.season_number
            result['episode'] = self.episode_number
            result['episode_title'] = f"S{self.season_number}E{self.episode_number}"
        
        return result


# Database setup with optimized connection pooling
engine = create_engine(
    db_config.URL,
    echo=db_config.ECHO,
    poolclass=QueuePool,
    pool_size=db_config.POOL_SIZE,
    max_overflow=db_config.MAX_OVERFLOW,
    pool_recycle=db_config.POOL_RECYCLE,
    pool_pre_ping=db_config.POOL_PRE_PING,
    connect_args={'check_same_thread': False} if 'sqlite' in db_config.URL else {}
)

# Thread-safe session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
ScopedSession = scoped_session(SessionLocal)


def init_db():
    """Initialize the database with all tables and indexes"""
    Base.metadata.create_all(bind=engine)
    _add_user_columns()
    print("✅ Database initialized successfully with optimized indexes")


def _add_user_columns():
    """Databases made before accounts existed: give each personal table a user_id.

    create_all doesn't change tables that already exist. Rows made before accounts keep
    user_id NULL until the first account is created, which takes them over.
    """
    old_indexes = {
        MyList: 'idx_mylist_type_id',
        WatchHistory: 'idx_watch_history_lookup',
        WatchedItems: 'idx_watched_items_lookup',
    }
    for model, old_index in old_indexes.items():
        table = model.__tablename__
        columns = {column['name'] for column in inspect(engine).get_columns(table)}
        with engine.begin() as conn:
            if 'user_id' not in columns:
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN user_id INTEGER'))
            # The old unique index would stop two people from saving the same title
            conn.execute(text(f'DROP INDEX IF EXISTS {old_index}'))
        for index in model.__table__.indexes:
            index.create(bind=engine, checkfirst=True)


def get_db():
    """
    Get database session
    Prefer using the context manager for automatic cleanup
    """
    return ScopedSession()


def close_db(db):
    """Close database session and return to pool"""
    if db:
        try:
            db.close()
        except Exception:
            pass


@contextmanager
def get_db_session():
    """
    Context manager for database sessions
    Automatically handles commits and rollbacks
    
    Usage:
        with get_db_session() as session:
            session.query(Movie).all()
    """
    session = get_db()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        close_db(session)
