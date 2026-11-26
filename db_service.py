from database import Movie, TVShow, get_db, close_db, MyList, WatchHistory, WatchedItems, User
from sqlalchemy import text, desc, func
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from typing import List, Optional, Dict, Any
from utils import measure_time
import logging

logger = logging.getLogger(__name__)

_DUMMY_HASH = generate_password_hash('not a real password')


class DatabaseService:
    """
    Optimized service for database operations with better error handling
    Context manager for automatic resource cleanup
    """
    
    def __init__(self, user_id: Optional[int] = None):
        self.db = get_db()
        # My List, watch history and watched marks are read and written for this user only
        self.user_id = user_id

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        close_db(self.db)

    def _is_sqlite(self) -> bool:
        return self.db.get_bind().dialect.name == 'sqlite'

    def _mine(self, model):
        """Query a personal table, limited to this user's rows"""
        return self.db.query(model).filter(model.user_id == self.user_id)

    # Account operations
    def get_user(self, user_id: int) -> Optional[User]:
        return self.db.query(User).filter(User.id == user_id).first()

    def get_user_by_username(self, username: str) -> Optional[User]:
        return self.db.query(User).filter(User.username == username.lower()).first()

    def create_user(self, username: str, password: str) -> Optional[User]:
        """Create an account; None if the username is taken.

        The first account takes over the My List, history and watched marks
        saved before accounts existed.
        """
        is_first = self.db.query(User).count() == 0
        user = User(username=username.lower(), password_hash=generate_password_hash(password))
        self.db.add(user)
        try:
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            return None
        if is_first:
            for model in (MyList, WatchHistory, WatchedItems):
                self.db.query(model).filter(model.user_id.is_(None)).update(
                    {model.user_id: user.id}, synchronize_session=False)
        self.db.commit()
        self.db.refresh(user)  # so its fields stay readable after the session closes
        return user

    def check_password(self, username: str, password: str) -> Optional[User]:
        """The user when the password matches, else None"""
        user = self.get_user_by_username(username)
        if user is None:
            # Hash anyway so a wrong username takes as long as a wrong password
            check_password_hash(_DUMMY_HASH, password)
            return None
        return user if check_password_hash(user.password_hash, password) else None

    def _upsert(self, model, data: Dict[str, Any], pending: Dict[Any, Any]):
        """Add or update one catalogue title.

        Finds the stored row by IMDb ID, or else by TMDB ID: sources sometimes list a title
        under a new IMDb ID, and inserting it again broke the unique TMDB ID and the whole sync.
        `pending` holds rows added earlier in the same batch, which queries can't see yet
        (autoflush is off).
        """
        imdb_id, tmdb_id = data.get('imdb_id'), data.get('tmdb_id')
        row = pending.get(('imdb', imdb_id)) or self.db.query(model).filter(model.imdb_id == imdb_id).first()
        if row is None and tmdb_id:
            row = pending.get(('tmdb', tmdb_id)) or self.db.query(model).filter(model.tmdb_id == tmdb_id).first()
            if row is not None:
                # Keep the stored IMDb ID: My List and watch history refer to it
                data = {k: v for k, v in data.items() if k != 'imdb_id'}
        elif row is not None and tmdb_id and tmdb_id != row.tmdb_id:
            if pending.get(('tmdb', tmdb_id)) or self.db.query(model.id).filter(model.tmdb_id == tmdb_id).first():
                data = {k: v for k, v in data.items() if k != 'tmdb_id'}  # another row already has it

        if row is None:
            row = model(**data)
            self.db.add(row)
        else:
            for key, value in data.items():
                if hasattr(row, key) and getattr(row, key) != value:
                    setattr(row, key, value)
            row.updated_at = datetime.utcnow()
        pending[('imdb', row.imdb_id)] = row
        if row.tmdb_id:
            pending[('tmdb', row.tmdb_id)] = row
        return row

    # Movie operations
    def get_movie_by_imdb_id(self, imdb_id):
        """Get movie by IMDB ID"""
        return self.db.query(Movie).filter(Movie.imdb_id == imdb_id).first()
    
    def get_movie_by_tmdb_id(self, tmdb_id):
        """Get movie by TMDB ID"""
        return self.db.query(Movie).filter(Movie.tmdb_id == tmdb_id).first()

    def get_movies_by_tmdb_ids(self, tmdb_ids: List[int]) -> List[Dict[str, Any]]:
        """Get movies for these TMDB IDs in the same order, skipping IDs not in the database"""
        movies = self.db.query(Movie).filter(Movie.tmdb_id.in_(tmdb_ids)).all()
        by_id = {movie.tmdb_id: movie.to_dict() for movie in movies}
        return [by_id[tmdb_id] for tmdb_id in tmdb_ids if tmdb_id in by_id]
    
    def create_or_update_movie(self, movie_data: Dict[str, Any]) -> Movie:
        """
        Create or update a movie with upsert logic
        
        Args:
            movie_data: Dictionary containing movie data
            
        Returns:
            Movie object
        """
        try:
            movie = self._upsert(Movie, movie_data, {})
            self.db.commit()
            self.db.refresh(movie)
            return movie
        except IntegrityError as e:
            self.db.rollback()
            logger.error(f"IntegrityError creating/updating movie: {e}")
            raise
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error creating/updating movie: {e}")
            raise
    
    def create_or_update_movies_batch(self, movies_data: List[Dict[str, Any]]) -> int:
        """
        Create or update multiple movies in batch with bulk operations
        Much faster than individual inserts
        
        Args:
            movies_data: List of movie data dictionaries
            
        Returns:
            Number of movies processed
        """
        try:
            processed_count = 0
            pending = {}
            for movie_data in movies_data:
                try:
                    self._upsert(Movie, movie_data, pending)
                    processed_count += 1
                except Exception as e:
                    logger.error(f"Error processing movie {movie_data.get('imdb_id')}: {e}")
                    continue
            
            self.db.commit()
            return processed_count
        except Exception as e:
            self.db.rollback()
            logger.error(f"Batch movie operation failed: {e}")
            raise
    
    @measure_time
    def get_latest_movies(self, page: int = 1, per_page: int = 16) -> List[Dict[str, Any]]:
        """
        Get latest movies from database with pagination
        Optimized with proper indexing
        
        Args:
            page: Page number (1-indexed)
            per_page: Number of items per page
            
        Returns:
            List of movie dictionaries
        """
        offset = (page - 1) * per_page
        movies = self.db.query(Movie)\
            .filter(Movie.imdb_id.isnot(None))\
            .order_by(desc(Movie.release_date).nullslast())\
            .offset(offset)\
            .limit(per_page)\
            .all()
        return [movie.to_dict() for movie in movies]
    
    def get_trending_movies(self, per_page: int = 16, offset: int = 0) -> List[Dict[str, Any]]:
        """
        Get trending movies using composite index for fast retrieval

        Args:
            per_page: Number of items to return
            offset: Number of items to skip (for the row's Show More button)

        Returns:
            List of trending movie dictionaries
        """
        movies = self.db.query(Movie)\
            .filter(Movie.is_trending == True, Movie.imdb_id.isnot(None))\
            .order_by(desc(Movie.popularity).nullslast())\
            .offset(offset)\
            .limit(per_page)\
            .all()
        return [movie.to_dict() for movie in movies]
    
    def get_movies_by_genre(self, genre: str, page: int = 1, per_page: int = 16) -> List[Dict[str, Any]]:
        """
        Get movies filtered by genre with pagination
        
        Args:
            genre: Genre name to filter by
            page: Page number (1-indexed)
            per_page: Number of items per page
            
        Returns:
            List of movie dictionaries
        """
        offset = (page - 1) * per_page
        
        # Use JSON search for genre (case-insensitive)
        # SQLite JSON functions to search within JSON array
        movies = self.db.query(Movie)\
            .filter(
                Movie.imdb_id.isnot(None),
                Movie.genres.isnot(None)
            )\
            .order_by(desc(Movie.popularity).nullslast())\
            .all()
        
        # Filter by genre in Python (SQLite JSON queries can be tricky)
        filtered_movies = []
        for movie in movies:
            if movie.genres and isinstance(movie.genres, list):
                # Case-insensitive genre matching
                movie_genres = [g.lower() if isinstance(g, str) else str(g).lower() for g in movie.genres]
                if genre.lower() in movie_genres:
                    filtered_movies.append(movie)
        
        # Apply pagination
        paginated_movies = filtered_movies[offset:offset + per_page]
        return [movie.to_dict() for movie in paginated_movies]
    
    def get_total_movies_by_genre(self, genre: str) -> int:
        """
        Get total count of movies for a specific genre
        
        Args:
            genre: Genre name to count
            
        Returns:
            Total count of movies with the genre
        """
        movies = self.db.query(Movie)\
            .filter(
                Movie.imdb_id.isnot(None),
                Movie.genres.isnot(None)
            )\
            .all()
        
        # Count movies with matching genre
        count = 0
        for movie in movies:
            if movie.genres and isinstance(movie.genres, list):
                movie_genres = [g.lower() if isinstance(g, str) else str(g).lower() for g in movie.genres]
                if genre.lower() in movie_genres:
                    count += 1
        
        return count
    
    @measure_time
    def search_movies(self, query: str, page: int = 1, per_page: int = 15) -> List[Dict[str, Any]]:
        """
        Search movies using FTS5 for ultra-fast full-text search
        Falls back to LIKE if FTS is not available
        
        Args:
            query: Search query string
            page: Page number (1-indexed)
            per_page: Number of results per page
            
        Returns:
            List of matching movie dictionaries
        """
        offset = (page - 1) * per_page
        
        # Use FTS5 for lightning-fast full-text search (SQLite only; Postgres uses the LIKE search below)
        try:
            if not self._is_sqlite():
                raise LookupError('no full-text index outside SQLite')
            # Escape special FTS characters and add prefix matching
            fts_query = query.replace('"', '""').replace('*', '')
            if len(fts_query) >= 2:
                fts_query = f'"{fts_query}"*'  # Quoted prefix search
            
            # FTS5 search with prefix matching for autocomplete
            sql = text("""
                SELECT m.* FROM movies m
                INNER JOIN movies_fts fts ON m.id = fts.rowid
                WHERE movies_fts MATCH :query
                ORDER BY 
                    CASE WHEN LOWER(m.title) LIKE :starts_with THEN 0 ELSE 1 END,
                    m.popularity DESC
                LIMIT :limit OFFSET :offset
            """)
            result = self.db.execute(sql, {
                'query': fts_query,
                'starts_with': f"{query.lower()}%",
                'limit': per_page,
                'offset': offset
            })
            
            movies = []
            for row in result:
                row_dict = dict(row._mapping)
                movie = Movie(**row_dict)
                movies.append(movie.to_dict())
            return movies
        except Exception as e:
            self.db.rollback()  # Postgres refuses further queries after a failed one until rolled back
            if self._is_sqlite():
                logger.warning(f"FTS search failed, falling back to LIKE: {e}")
            # Fallback to LIKE search if FTS fails
            search_term = f"%{query}%"
            movies = self.db.query(Movie)\
                .filter(Movie.title.ilike(search_term))\
                .order_by(desc(Movie.popularity).nullslast())\
                .offset(offset)\
                .limit(per_page)\
                .all()
            return [movie.to_dict() for movie in movies]

    def get_top_rated(self, kind: str, limit: int = 500) -> List[Dict[str, Any]]:
        """
        Rank titles with IMDb's Top 250 formula (a weighted rating), using TMDB votes

            WR = v / (v + m) * R + m / (v + m) * C

        R is the title's average rating and v its number of votes; C is the mean
        rating of all voted titles and m the votes needed to be listed. m is the
        95th percentile of vote counts, so only widely rated titles qualify, and a
        title's score leans toward C until it has many more votes than m.

        Args:
            kind: 'movie' or 'series'
            limit: Number of titles to return

        Returns:
            Title dictionaries, best first, with 'rank', 'weighted_rating' and 'vote_count' added
        """
        model = Movie if kind == 'movie' else TVShow
        voted = self.db.query(model).filter(model.vote_count > 0, model.imdb_id.isnot(None))
        voted_count = voted.count()
        if not voted_count:
            return []

        mean_rating = voted.with_entities(func.avg(model.vote_average)).scalar()
        min_votes = voted.with_entities(model.vote_count)\
            .order_by(model.vote_count)\
            .offset(int(voted_count * 0.95))\
            .limit(1)\
            .scalar()

        weighted = (model.vote_count * model.vote_average + min_votes * mean_rating) / (model.vote_count + min_votes)
        titles = voted.filter(model.vote_count >= min_votes)\
            .order_by(weighted.desc())\
            .limit(limit)\
            .all()

        result = []
        for rank, title in enumerate(titles, start=1):
            title_dict = title.to_dict()
            title_dict['rank'] = rank
            title_dict['vote_count'] = title.vote_count
            title_dict['weighted_rating'] = round(
                (title.vote_count * title.vote_average + min_votes * mean_rating) / (title.vote_count + min_votes), 2
            )
            result.append(title_dict)
        return result

    # TV Show operations
    def get_tvshow_by_imdb_id(self, imdb_id):
        """Get TV show by IMDB ID"""
        return self.db.query(TVShow).filter(TVShow.imdb_id == imdb_id).first()
    
    def get_tvshow_by_tmdb_id(self, tmdb_id):
        """Get TV show by TMDB ID"""
        return self.db.query(TVShow).filter(TVShow.tmdb_id == tmdb_id).first()

    def get_tvshows_by_tmdb_ids(self, tmdb_ids: List[int]) -> List[Dict[str, Any]]:
        """Get TV shows for these TMDB IDs in the same order, skipping IDs not in the database"""
        tvshows = self.db.query(TVShow).filter(TVShow.tmdb_id.in_(tmdb_ids)).all()
        by_id = {tvshow.tmdb_id: tvshow.to_dict() for tvshow in tvshows}
        return [by_id[tmdb_id] for tmdb_id in tmdb_ids if tmdb_id in by_id]
    
    def create_or_update_tvshow(self, tvshow_data):
        """Create or update a TV show"""
        tvshow = self._upsert(TVShow, tvshow_data, {})
        self.db.commit()
        self.db.refresh(tvshow)
        return tvshow
    
    def create_or_update_tvshows_batch(self, tvshows_data):
        """Create or update multiple TV shows in batch"""
        pending = {}
        for tvshow_data in tvshows_data:
            self._upsert(TVShow, tvshow_data, pending)
        self.db.commit()
        return len(tvshows_data)
    
    def get_latest_tvshows(self, page=1, per_page=16):
        """Get latest TV shows from database"""
        offset = (page - 1) * per_page
        tvshows = self.db.query(TVShow)\
            .order_by(TVShow.first_air_date.desc().nullslast())\
            .offset(offset)\
            .limit(per_page)\
            .all()
        return [tvshow.to_dict() for tvshow in tvshows]
    
    def get_trending_tvshows(self, per_page=16, offset=0):
        """Get trending TV shows from database, skipping `offset` items (for the row's Show More button)"""
        tvshows = self.db.query(TVShow)\
            .filter(TVShow.is_trending == True, TVShow.imdb_id.isnot(None))\
            .order_by(TVShow.popularity.desc().nullslast())\
            .offset(offset)\
            .limit(per_page)\
            .all()
        return [tvshow.to_dict() for tvshow in tvshows]
    
    def get_tvshows_by_genre(self, genre: str, page: int = 1, per_page: int = 16) -> List[Dict[str, Any]]:
        """
        Get TV shows filtered by genre with pagination
        
        Args:
            genre: Genre name to filter by
            page: Page number (1-indexed)
            per_page: Number of items per page
            
        Returns:
            List of TV show dictionaries
        """
        offset = (page - 1) * per_page
        
        # Get all TV shows with genres
        tvshows = self.db.query(TVShow)\
            .filter(
                TVShow.imdb_id.isnot(None),
                TVShow.genres.isnot(None)
            )\
            .order_by(desc(TVShow.popularity).nullslast())\
            .all()
        
        # Filter by genre in Python (SQLite JSON queries can be tricky)
        filtered_tvshows = []
        for tvshow in tvshows:
            if tvshow.genres and isinstance(tvshow.genres, list):
                # Case-insensitive genre matching
                tvshow_genres = [g.lower() if isinstance(g, str) else str(g).lower() for g in tvshow.genres]
                if genre.lower() in tvshow_genres:
                    filtered_tvshows.append(tvshow)
        
        # Apply pagination
        paginated_tvshows = filtered_tvshows[offset:offset + per_page]
        return [tvshow.to_dict() for tvshow in paginated_tvshows]
    
    def get_total_tvshows_by_genre(self, genre: str) -> int:
        """
        Get total count of TV shows for a specific genre
        
        Args:
            genre: Genre name to count
            
        Returns:
            Total count of TV shows with the genre
        """
        tvshows = self.db.query(TVShow)\
            .filter(
                TVShow.imdb_id.isnot(None),
                TVShow.genres.isnot(None)
            )\
            .all()
        
        # Count TV shows with matching genre
        count = 0
        for tvshow in tvshows:
            if tvshow.genres and isinstance(tvshow.genres, list):
                tvshow_genres = [g.lower() if isinstance(g, str) else str(g).lower() for g in tvshow.genres]
                if genre.lower() in tvshow_genres:
                    count += 1
        
        return count
    
    @measure_time
    def search_tvshows(self, query, page=1, per_page=15):
        """Search TV shows in database using FTS for ultra-fast results"""
        offset = (page - 1) * per_page
        
        # Use FTS5 for lightning-fast full-text search (SQLite only; Postgres uses the LIKE search below)
        try:
            if not self._is_sqlite():
                raise LookupError('no full-text index outside SQLite')
            # Escape special FTS characters and add prefix matching
            # Use * for prefix matching (e.g., "breaking*" matches "breaking bad")
            fts_query = query.replace('"', '""').replace('*', '')
            if len(fts_query) >= 2:
                fts_query = f'"{fts_query}"*'  # Quoted prefix search
            
            # FTS5 search with prefix matching for autocomplete
            sql = text("""
                SELECT t.* FROM tvshows t
                INNER JOIN tvshows_fts fts ON t.id = fts.rowid
                WHERE tvshows_fts MATCH :query
                ORDER BY 
                    CASE WHEN LOWER(t.title) LIKE :starts_with THEN 0 ELSE 1 END,
                    t.popularity DESC
                LIMIT :limit OFFSET :offset
            """)
            result = self.db.execute(sql, {
                'query': fts_query,
                'starts_with': f"{query.lower()}%",
                'limit': per_page,
                'offset': offset
            })
            
            tvshows = []
            for row in result:
                row_dict = dict(row._mapping)
                tvshow = TVShow(**row_dict)
                tvshows.append(tvshow.to_dict())
            return tvshows
        except Exception as e:
            self.db.rollback()
            # Fallback to LIKE search if FTS fails
            search_term = f"%{query}%"
            tvshows = self.db.query(TVShow)\
                .filter(TVShow.title.ilike(search_term))\
                .order_by(TVShow.popularity.desc().nullslast())\
                .offset(offset)\
                .limit(per_page)\
                .all()
            return [tvshow.to_dict() for tvshow in tvshows]
    
    def get_total_movies(self):
        """Get total number of movies"""
        return self.db.query(Movie).count()
    
    def get_total_tvshows(self):
        """Get total number of TV shows"""
        return self.db.query(TVShow).count()
    
    def movie_exists(self, imdb_id):
        """Check if a movie exists in the database"""
        return self.db.query(Movie).filter(Movie.imdb_id == imdb_id).first() is not None
    
    def tvshow_exists(self, imdb_id):
        """Check if a TV show exists in the database"""
        return self.db.query(TVShow).filter(TVShow.imdb_id == imdb_id).first() is not None
    
    def clear_trending_flags(self, media_type='all'):
        """Clear trending flags for media"""
        if media_type in ['movie', 'all']:
            self.db.query(Movie).update({Movie.is_trending: False})
        if media_type in ['tv', 'all']:
            self.db.query(TVShow).update({TVShow.is_trending: False})
        self.db.commit()
    
    # My List operations
    def get_my_list(self):
        """Get all items in My List"""
        items = self._mine(MyList).order_by(MyList.created_at.desc()).all()
        result = []
        
        for item in items:
            # Get the actual movie or TV show data
            if item.media_type == 'movie':
                media_item = self.get_movie_by_imdb_id(item.media_id)
            else:  # 'series'
                media_item = self.get_tvshow_by_imdb_id(item.media_id)
            
            if media_item:
                # Get the full item data
                item_dict = media_item.to_dict()
                item_dict['type'] = item.media_type
                item_dict['id'] = media_item.imdb_id  # Use imdb_id as id for frontend compatibility
                result.append(item_dict)
            else:
                # Fallback if item not found in database - skip it
                pass
        
        return result
    
    def add_to_my_list(self, media_type, media_id, tmdb_id, title):
        """Add an item to My List"""
        # Check if already in list
        existing = self._mine(MyList).filter(
            MyList.media_type == media_type,
            MyList.media_id == media_id
        ).first()
        
        if existing:
            return existing, False  # Already exists
        
        # Create new entry
        new_item = MyList(
            user_id=self.user_id,
            media_type=media_type,
            media_id=media_id,
            tmdb_id=tmdb_id,
            title=title
        )
        self.db.add(new_item)
        self.db.commit()
        self.db.refresh(new_item)
        return new_item, True  # Newly added
    
    def remove_from_my_list(self, media_type, media_id):
        """Remove an item from My List"""
        item = self._mine(MyList).filter(
            MyList.media_type == media_type,
            MyList.media_id == media_id
        ).first()
        
        if item:
            self.db.delete(item)
            self.db.commit()
            return True
        return False
    
    def is_in_my_list(self, media_type: str, media_id: str) -> bool:
        """Check if an item is in My List"""
        exists = self._mine(MyList).filter(
            MyList.media_type == media_type,
            MyList.media_id == media_id
        ).first()
        return exists is not None
    
    # Watch Progress operations
    def get_watch_progress(self, media_type: str, media_id: str, 
                          season: Optional[int] = None, 
                          episode: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """
        Get watch progress for a specific item
        
        Args:
            media_type: 'movie' or 'series'
            media_id: IMDB ID
            season: Season number (for series)
            episode: Episode number (for series)
            
        Returns:
            Watch progress dictionary or None
        """
        from database import WatchHistory
        
        query = self._mine(WatchHistory).filter(
            WatchHistory.media_type == media_type,
            WatchHistory.media_id == media_id
        )
        
        # Add episode filters for series
        if media_type == 'series' and season and episode:
            query = query.filter(
                WatchHistory.season_number == season,
                WatchHistory.episode_number == episode
            )
        
        progress = query.first()
        return progress.to_dict() if progress else None
    
    # Watch Mark operations (manually mark as watched)
    def mark_as_watched(self, media_type: str, media_id: str, tmdb_id: Optional[int] = None,
                       title: str = "Unknown", season: Optional[int] = None, 
                       episode: Optional[int] = None) -> bool:
        """
        Mark an item as watched manually
        
        Args:
            media_type: 'movie' or 'series'
            media_id: IMDB ID
            tmdb_id: TMDB ID (optional)
            title: Title of the media
            season: Season number (for series)
            episode: Episode number (for series)
            
        Returns:
            True if marked successfully
        """
        from database import WatchedItems
        
        try:
            # Check if already marked
            query = self._mine(WatchedItems).filter(
                WatchedItems.media_type == media_type,
                WatchedItems.media_id == media_id
            )
            
            if media_type == 'series' and season and episode:
                query = query.filter(
                    WatchedItems.season_number == season,
                    WatchedItems.episode_number == episode
                )
            
            existing = query.first()
            
            if existing:
                # Update timestamp
                existing.marked_at = datetime.utcnow()
                self.db.commit()
                return True
            
            # Create new watched mark
            watched_item = WatchedItems(
                user_id=self.user_id,
                media_type=media_type,
                media_id=media_id,
                tmdb_id=tmdb_id,
                title=title,
                season_number=season,
                episode_number=episode
            )
            self.db.add(watched_item)
            self.db.commit()
            return True
        except IntegrityError:
            self.db.rollback()
            # Already exists, just update it
            return True
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error marking as watched: {e}")
            return False
    
    def unmark_as_watched(self, media_type: str, media_id: str,
                         season: Optional[int] = None, 
                         episode: Optional[int] = None) -> bool:
        """
        Remove watched mark from an item
        
        Args:
            media_type: 'movie' or 'series'
            media_id: IMDB ID
            season: Season number (for series)
            episode: Episode number (for series)
            
        Returns:
            True if unmarked successfully
        """
        from database import WatchedItems
        
        try:
            query = self._mine(WatchedItems).filter(
                WatchedItems.media_type == media_type,
                WatchedItems.media_id == media_id
            )
            
            if media_type == 'series' and season and episode:
                query = query.filter(
                    WatchedItems.season_number == season,
                    WatchedItems.episode_number == episode
                )
            
            watched_item = query.first()
            
            if watched_item:
                self.db.delete(watched_item)
                self.db.commit()
                return True
            return False
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error unmarking as watched: {e}")
            return False
    
    def mark_season_as_watched(self, media_id: str, tmdb_id: Optional[int], 
                              series_title: str, season_number: int, 
                              episode_count: int) -> bool:
        """
        Mark all episodes in a season as watched
        
        Args:
            media_id: IMDB ID of the series
            tmdb_id: TMDB ID of the series
            series_title: Title of the series
            season_number: Season number
            episode_count: Total number of episodes in the season
            
        Returns:
            True if successful
        """
        from database import WatchedItems
        
        try:
            # Mark all episodes in the season
            for episode_num in range(1, episode_count + 1):
                # Check if already marked
                existing = self._mine(WatchedItems).filter(
                    WatchedItems.media_type == 'series',
                    WatchedItems.media_id == media_id,
                    WatchedItems.season_number == season_number,
                    WatchedItems.episode_number == episode_num
                ).first()
                
                if not existing:
                    watched_item = WatchedItems(
                        user_id=self.user_id,
                        media_type='series',
                        media_id=media_id,
                        tmdb_id=tmdb_id,
                        title=f"{series_title} - S{season_number}E{episode_num}",
                        season_number=season_number,
                        episode_number=episode_num
                    )
                    self.db.add(watched_item)
                else:
                    # Update timestamp
                    existing.marked_at = datetime.utcnow()
            
            self.db.commit()
            return True
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error marking season as watched: {e}")
            return False
    
    def unmark_season_as_watched(self, media_id: str, season_number: int) -> bool:
        """
        Remove watched marks from all episodes in a season
        
        Args:
            media_id: IMDB ID of the series
            season_number: Season number
            
        Returns:
            True if successful
        """
        from database import WatchedItems
        
        try:
            self._mine(WatchedItems).filter(
                WatchedItems.media_type == 'series',
                WatchedItems.media_id == media_id,
                WatchedItems.season_number == season_number
            ).delete()
            
            self.db.commit()
            return True
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error unmarking season as watched: {e}")
            return False
    
    def mark_series_as_watched(self, media_id: str, tmdb_id: Optional[int],
                              series_title: str, seasons_data: List[Dict[str, Any]]) -> bool:
        """
        Mark all episodes in all seasons as watched
        
        Args:
            media_id: IMDB ID of the series
            tmdb_id: TMDB ID of the series
            series_title: Title of the series
            seasons_data: List of season dictionaries with 'season_number' and 'episode_count'
            
        Returns:
            True if successful
        """
        try:
            for season in seasons_data:
                season_number = season.get('season_number')
                episode_count = season.get('episode_count', 0)
                
                if season_number and season_number > 0 and episode_count > 0:
                    success = self.mark_season_as_watched(
                        media_id=media_id,
                        tmdb_id=tmdb_id,
                        series_title=series_title,
                        season_number=season_number,
                        episode_count=episode_count
                    )
                    if not success:
                        return False
            
            return True
        except Exception as e:
            logger.error(f"Error marking series as watched: {e}")
            return False
    
    def unmark_series_as_watched(self, media_id: str) -> bool:
        """
        Remove watched marks from all episodes in a series
        
        Args:
            media_id: IMDB ID of the series
            
        Returns:
            True if successful
        """
        from database import WatchedItems
        
        try:
            self._mine(WatchedItems).filter(
                WatchedItems.media_type == 'series',
                WatchedItems.media_id == media_id
            ).delete()
            
            self.db.commit()
            return True
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error unmarking series as watched: {e}")
            return False
    
    def get_season_watch_status(self, media_id: str, season_number: int) -> Dict[str, Any]:
        """
        Get watched status for all episodes in a season
        
        Args:
            media_id: IMDB ID of the series
            season_number: Season number
            
        Returns:
            Dictionary with watched episode numbers and statistics
        """
        from database import WatchedItems
        
        watched_episodes = self._mine(WatchedItems).filter(
            WatchedItems.media_type == 'series',
            WatchedItems.media_id == media_id,
            WatchedItems.season_number == season_number
        ).all()
        
        watched_episode_numbers = [ep.episode_number for ep in watched_episodes]
        
        return {
            'watched_episodes': watched_episode_numbers,
            'watched_count': len(watched_episode_numbers)
        }
    
    def get_series_watch_status(self, media_id: str) -> Dict[str, Any]:
        """
        Get watched status for all episodes in a series
        
        Args:
            media_id: IMDB ID of the series
            
        Returns:
            Dictionary with watched episodes by season
        """
        from database import WatchedItems
        
        watched_episodes = self._mine(WatchedItems).filter(
            WatchedItems.media_type == 'series',
            WatchedItems.media_id == media_id
        ).all()
        
        # Group by season
        by_season = {}
        for ep in watched_episodes:
            season = ep.season_number
            if season not in by_season:
                by_season[season] = []
            by_season[season].append(ep.episode_number)
        
        return {
            'watched_by_season': by_season,
            'total_watched': len(watched_episodes)
        }

    def is_marked_watched(self, media_type: str, media_id: str,
                         season: Optional[int] = None, 
                         episode: Optional[int] = None) -> bool:
        """
        Check if an item is marked as watched
        
        Args:
            media_type: 'movie' or 'series'
            media_id: IMDB ID
            season: Season number (for series)
            episode: Episode number (for series)
            
        Returns:
            True if marked as watched
        """
        from database import WatchedItems
        
        query = self._mine(WatchedItems).filter(
            WatchedItems.media_type == media_type,
            WatchedItems.media_id == media_id
        )
        
        if media_type == 'series' and season and episode:
            query = query.filter(
                WatchedItems.season_number == season,
                WatchedItems.episode_number == episode
            )
        
        return query.first() is not None
    
    def get_watched_items(self, media_type: Optional[str] = None, 
                         limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get all items marked as watched
        
        Args:
            media_type: Filter by 'movie' or 'series' (optional)
            limit: Maximum number of items to return
            
        Returns:
            List of watched items
        """
        from database import WatchedItems
        
        query = self._mine(WatchedItems)
        
        if media_type:
            query = query.filter(WatchedItems.media_type == media_type)
        
        watched = query.order_by(desc(WatchedItems.marked_at)).limit(limit).all()
        
        result = []
        for item in watched:
            watched_dict = item.to_dict()
            
            # Enrich with media details
            if item.media_type == 'movie':
                media = self.get_movie_by_imdb_id(item.media_id)
                if media:
                    watched_dict.update({
                        'poster_url': media.to_dict().get('poster_url'),
                        'backdrop_url': media.to_dict().get('backdrop_url'),
                    })
            else:  # series
                media = self.get_tvshow_by_imdb_id(item.media_id)
                if media:
                    watched_dict.update({
                        'poster_url': media.to_dict().get('poster_url'),
                        'backdrop_url': media.to_dict().get('backdrop_url'),
                    })
            
            result.append(watched_dict)
        
        return result
    
    def save_watch_progress(self, media_type: str, media_id: str, 
                           progress_seconds: int, duration_seconds: int,
                           title: str, tmdb_id: Optional[int] = None,
                           season_number: Optional[int] = None, 
                           episode_number: Optional[int] = None,
                           poster_path: Optional[str] = None) -> 'WatchHistory':
        """
        Save or update watch progress for continue watching feature
        
        Args:
            media_type: 'movie' or 'series'
            media_id: IMDB ID
            progress_seconds: Current playback position in seconds
            duration_seconds: Total duration in seconds
            title: Title of the media
            tmdb_id: TMDB ID (optional)
            season_number: Season number (for series)
            episode_number: Episode number (for series)
            poster_path: Poster path (optional)
            
        Returns:
            WatchHistory object
        """
        from database import WatchHistory
        
        try:
            # Calculate progress percentage
            progress_percent = (progress_seconds / duration_seconds * 100) if duration_seconds > 0 else 0
            is_completed = progress_percent >= 90
            
            # Find existing record
            query = self._mine(WatchHistory).filter(
                WatchHistory.media_type == media_type,
                WatchHistory.media_id == media_id
            )
            
            # Add episode filters for series
            if media_type == 'series' and season_number and episode_number:
                query = query.filter(
                    WatchHistory.season_number == season_number,
                    WatchHistory.episode_number == episode_number
                )
            
            watch_record = query.first()
            
            if watch_record:
                # Update existing record
                watch_record.progress_seconds = progress_seconds
                watch_record.duration_seconds = duration_seconds
                watch_record.progress_percent = progress_percent
                watch_record.is_completed = is_completed
                watch_record.last_watched = datetime.utcnow()
                watch_record.updated_at = datetime.utcnow()
                if poster_path:
                    watch_record.poster_path = poster_path
            else:
                # Create new record
                watch_record = WatchHistory(
                    user_id=self.user_id,
                    media_type=media_type,
                    media_id=media_id,
                    tmdb_id=tmdb_id,
                    title=title,
                    progress_seconds=progress_seconds,
                    duration_seconds=duration_seconds,
                    progress_percent=progress_percent,
                    season_number=season_number,
                    episode_number=episode_number,
                    poster_path=poster_path,
                    is_completed=is_completed
                )
                self.db.add(watch_record)
            
            self.db.commit()
            self.db.refresh(watch_record)
            
            # If completed and progress > 90%, also mark as watched
            if is_completed:
                self.mark_as_watched(
                    media_type=media_type,
                    media_id=media_id,
                    tmdb_id=tmdb_id,
                    title=title,
                    season=season_number,
                    episode=episode_number
                )
            
            return watch_record
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error saving watch progress: {e}")
            raise
    
    def get_continue_watching(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Get continue watching items (5% - 90% progress)
        
        Args:
            limit: Maximum number of items to return
            
        Returns:
            List of continue watching items with enriched data
        """
        from database import WatchHistory
        
        continue_watching = self._mine(WatchHistory)\
            .filter(
                WatchHistory.progress_percent >= 5,
                WatchHistory.progress_percent < 90,
                WatchHistory.is_completed == False
            )\
            .order_by(desc(WatchHistory.last_watched))\
            .limit(limit)\
            .all()
        
        result = []
        for item in continue_watching:
            history_dict = item.to_dict()
            
            # Enrich with media details
            if item.media_type == 'movie':
                media = self.get_movie_by_imdb_id(item.media_id)
                if media:
                    media_dict = media.to_dict()
                    history_dict.update({
                        'poster_url': media_dict.get('poster_url'),
                        'backdrop_url': media_dict.get('backdrop_url'),
                        'overview': media_dict.get('overview'),
                    })
            else:  # series
                media = self.get_tvshow_by_imdb_id(item.media_id)
                if media:
                    media_dict = media.to_dict()
                    history_dict.update({
                        'poster_url': media_dict.get('poster_url'),
                        'backdrop_url': media_dict.get('backdrop_url'),
                        'overview': media_dict.get('overview'),
                    })
            
            # Normalize keys expected by templates/frontend:
            # - Templates expect `progress` and `duration` (in seconds) and may compute percent as progress/duration
            # - The DB model uses `progress_seconds` and `duration_seconds` so map them here and provide safe defaults
            try:
                progress_seconds = int(history_dict.get('progress_seconds', 0) or 0)
            except Exception:
                progress_seconds = 0

            try:
                duration_seconds = int(history_dict.get('duration_seconds', 0) or 0)
            except Exception:
                duration_seconds = 0

            # Avoid division by zero in templates by ensuring duration at least 1
            if duration_seconds <= 0:
                duration_seconds = 1

            history_dict['progress'] = progress_seconds
            history_dict['duration'] = duration_seconds

            # Provide a convenient percent value (rounded) for consumers that expect it
            try:
                history_dict['progress_percent'] = round((progress_seconds / duration_seconds) * 100, 2)
            except Exception:
                history_dict['progress_percent'] = 0.0

            result.append(history_dict)
        
        return result
    
    def remove_from_watch_history(self, media_type: str, media_id: str,
                                 season_number: Optional[int] = None, 
                                 episode_number: Optional[int] = None) -> bool:
        """
        Remove item from watch history
        
        Args:
            media_type: 'movie' or 'series'
            media_id: IMDB ID
            season_number: Season number (for series)
            episode_number: Episode number (for series)
            
        Returns:
            True if removed successfully
        """
        return self.clear_watch_progress(media_type, media_id, season_number, episode_number)
    
    def clear_watch_progress(self, media_type: str, media_id: str,
                            season_number: Optional[int] = None, 
                            episode_number: Optional[int] = None) -> bool:
        """
        Clear watch progress for an item (remove from Continue Watching)
        
        Args:
            media_type: 'movie' or 'series'
            media_id: IMDB ID
            season_number: Season number (optional, for series)
            episode_number: Episode number (optional, for series)
            
        Returns:
            True if cleared successfully
        """
        from database import WatchHistory
        
        try:
            query = self._mine(WatchHistory).filter(
                WatchHistory.media_type == media_type,
                WatchHistory.media_id == media_id
            )
            
            # Add episode filters for series if provided
            if media_type == 'series' and season_number and episode_number:
                query = query.filter(
                    WatchHistory.season_number == season_number,
                    WatchHistory.episode_number == episode_number
                )
            
            # Delete all matching records
            deleted_count = query.delete()
            self.db.commit()
            
            return deleted_count > 0
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error clearing watch progress: {e}")
            return False
