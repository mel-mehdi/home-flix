"""
Configuration module for centralized settings management
Environment variables and constants in one place
"""
import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv

# Read settings such as TMDB_ACCESS_TOKEN from a .env file next to this one
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))


@dataclass
class CacheConfig:
    """Cache duration settings in seconds"""
    TMDB_DATA: int = 3600  # 1 hour
    VIDSRC_DATA: int = 600  # 10 minutes
    POSTER: int = 7200  # 2 hours
    BACKDROP: int = 7200  # 2 hours
    SEARCH_RESULTS: int = 300  # 5 minutes


@dataclass
class APIConfig:
    """API configuration"""
    TMDB_ACCESS_TOKEN: str = os.getenv('TMDB_ACCESS_TOKEN', '')
    TMDB_BASE_URL: str = 'https://api.themoviedb.org/3'
    TMDB_IMAGE_BASE_URL: str = 'https://image.tmdb.org/t/p/w500'
    TMDB_BACKDROP_BASE_URL: str = 'https://image.tmdb.org/t/p/w1280'
    
    # Request timeout in seconds
    REQUEST_TIMEOUT: int = 10
    
    # Max retries for failed requests
    MAX_RETRIES: int = 3


def _database_url() -> str:
    url = os.getenv('DATABASE_URL') or 'sqlite:///homeflix.db'
    # Neon and most hosts give postgres:// or postgresql:// links; SQLAlchemy needs the driver named
    for prefix in ('postgres://', 'postgresql://'):
        if url.startswith(prefix):
            return 'postgresql+psycopg://' + url[len(prefix):]
    return url


@dataclass
class DatabaseConfig:
    """Database configuration"""
    URL: str = _database_url()
    ECHO: bool = os.getenv('DB_ECHO', 'false').lower() == 'true'
    POOL_SIZE: int = int(os.getenv('DB_POOL_SIZE', '10'))
    MAX_OVERFLOW: int = int(os.getenv('DB_MAX_OVERFLOW', '20'))
    POOL_RECYCLE: int = 3600  # Recycle connections after 1 hour
    POOL_PRE_PING: bool = True  # Check connection health before using


@dataclass
class ServerConfig:
    """Flask server configuration"""
    HOST: str = os.getenv('FLASK_HOST', '0.0.0.0')
    # Fall back to PORT, which gunicorn_config.py and most hosts use
    PORT: int = int(os.getenv('FLASK_PORT', os.getenv('PORT', '5000')))
    DEBUG: bool = os.getenv('FLASK_ENV', 'production') == 'development'
    THREADED: bool = True

    # Invite code for creating accounts; empty = accounts can only be created from this PC
    PASSWORD: str = os.getenv('HOMEFLIX_PASSWORD', '')
    # Signs the login cookie; empty = a new random key each start (everyone signs in again)
    SECRET_KEY: str = os.getenv('FLASK_SECRET_KEY', '')
    
    # Static folder paths
    CSS_FOLDER: str = 'css'
    STATIC_FOLDER: str = 'static'
    TEMPLATE_FOLDER: str = 'templates'


@dataclass
class PaginationConfig:
    """Pagination settings"""
    # Titles per row page and per Load More. 18 fills whole rows on wide screens
    # (9 posters across); the filter API and navigation.js use this too.
    DEFAULT_PER_PAGE: int = 18
    SEARCH_PER_PAGE: int = 15
    MAX_PER_PAGE: int = 50
    TRENDING_LIMIT: int = 18
    TOP_LIST_SIZE: int = 250  # Titles on the /top page, per tab


# Global config instances
cache_config = CacheConfig()
api_config = APIConfig()
db_config = DatabaseConfig()
server_config = ServerConfig()
pagination_config = PaginationConfig()

# Vercel (it sets VERCEL=1) has no writable disk and runs several copies of the app at once:
# fail with a clear message instead of a database or sign-in error on every page
if os.getenv('VERCEL'):
    missing = [name for name, ok in (
        ('DATABASE_URL (a Postgres address, e.g. Neon)', not db_config.URL.startswith('sqlite')),
        ('FLASK_SECRET_KEY', bool(server_config.SECRET_KEY)),
    ) if not ok]
    if missing:
        raise RuntimeError('Set these in the Vercel project settings: ' + ', '.join(missing))


def get_embed_sources(media_type: str, identifier: str, season: Optional[int] = None, episode: Optional[int] = None) -> list[str]:
    """
    Generate embed source URLs for video players
    
    Args:
        media_type: 'movie', 'tv', or 'episode'
        identifier: TMDB ID or IMDB ID
        season: Season number (for episodes)
        episode: Episode number (for episodes)
    
    Returns:
        List of embed source URLs in priority order

    Checked 2026-11-10 with Fight Club (550) and Breaking Bad S1E1 (1396).
    Removed: xprime.tv and vidsrc.pro (connection reset), fmovies.gd, rivestream.org
    and vidsrc.xyz (domains gone), vidsrc.me (same player as vidsrc.to).
    vidsrc.su played the movie but had no servers for the episode, so it sits lower.
    """
    if media_type == 'movie':
        return [
            f"https://streamimdb.ru/embed/movie/{identifier}",
            f"https://vidfast.pro/movie/{identifier}?autoPlay=true&nextButton=true&autoNext=true",
            f"https://vidlink.pro/movie/{identifier}",
            f"https://vidrock.net/movie/{identifier}",
            f"https://vixsrc.to/movie/{identifier}",
            f"https://vidsrc.su/embed/movie/{identifier}",
            f"https://vidsrc.to/embed/movie/{identifier}",
            f"https://www.2embed.cc/embed/{identifier}",
            f"https://multiembed.mov/?video_id={identifier}&tmdb=1",
            f"https://autoembed.co/movie/tmdb/{identifier}",
        ]
    elif media_type == 'tv':
        # Sources that need an episode start at S1E1
        return [
            f"https://streamimdb.ru/embed/tv/{identifier}",
            f"https://vidfast.pro/tv/{identifier}?autoPlay=true&nextButton=true&autoNext=true",
            f"https://vidlink.pro/tv/{identifier}/1/1",
            f"https://vidrock.net/tv/{identifier}/1/1",
            f"https://vixsrc.to/tv/{identifier}/1/1",
            f"https://vidsrc.to/embed/tv/{identifier}",
            f"https://www.2embed.cc/embedtv/{identifier}",
            f"https://multiembed.mov/?video_id={identifier}&tmdb=1&s=1&e=1",
            f"https://autoembed.co/tv/tmdb/{identifier}-1-1",
        ]
    elif media_type == 'episode' and season is not None and episode is not None:
        return [
            f"https://streamimdb.ru/embed/tv/{identifier}/{season}/{episode}",
            f"https://vidfast.pro/tv/{identifier}/{season}/{episode}?autoPlay=true&nextButton=true&autoNext=true",
            f"https://vidlink.pro/tv/{identifier}/{season}/{episode}",
            f"https://vidrock.net/tv/{identifier}/{season}/{episode}",
            f"https://vixsrc.to/tv/{identifier}/{season}/{episode}",
            f"https://vidsrc.to/embed/tv/{identifier}/{season}/{episode}",
            f"https://www.2embed.cc/embedtv/{identifier}&s={season}&e={episode}",
            f"https://multiembed.mov/?video_id={identifier}&tmdb=1&s={season}&e={episode}",
            f"https://autoembed.co/tv/tmdb/{identifier}-{season}-{episode}",
            f"https://vidsrc.su/embed/tv/{identifier}/{season}/{episode}",
        ]
    return []
