from flask import Flask, render_template, request, Response, send_file, send_from_directory, abort, redirect, jsonify, session, g, has_request_context
import requests
import hmac
import io
import logging
import os
import re
import sys
import threading
import time
from datetime import timedelta

# Windows consoles default to cp1252, which can't print the emoji in our status messages
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from database import init_db, tmdb_poster_url, tmdb_backdrop_url
from db_service import DatabaseService
from config import api_config, cache_config, server_config, pagination_config, get_embed_sources
from utils import cache_manager, make_api_request, measure_time
from functools import lru_cache
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse, quote

# Configure logging
logging.basicConfig(
    level=logging.WARNING,
    format='%(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
# Disable Flask's default request logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# Login cookie: lasts 30 days, unreadable by scripts, not sent by other sites' forms
app.secret_key = server_config.SECRET_KEY or os.urandom(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)

# The sign-in and sign-up pages need their stylesheets before anyone is signed in
_PUBLIC_PATHS = ('/login', '/signup', '/css/', '/static/', '/favicon.ico')
_USERNAME_PATTERN = re.compile(r'^[A-Za-z0-9_.-]{3,30}$')
_MIN_PASSWORD_LENGTH = 8
_LOGIN_MAX_FAILURES = 10
_LOGIN_WINDOW_SECONDS = 15 * 60
_login_failures: Dict[str, List[float]] = {}
_login_lock = threading.Lock()


def _client_ip() -> str:
    # Vercel sets X-Real-IP itself; there a visitor could send a fake Cf-Connecting-IP
    if os.getenv('VERCEL'):
        return request.headers.get('X-Real-IP') or request.remote_addr or 'unknown'
    # Behind a tunnel every request comes from the tunnel program; its header holds the visitor.
    # ngrok appends the visitor to X-Forwarded-For, so the last entry is the one a visitor can't fake.
    forwarded = request.headers.get('X-Forwarded-For', '').split(',')[-1].strip()
    return request.headers.get('Cf-Connecting-IP') or forwarded or request.remote_addr or 'unknown'


def _via_tunnel() -> bool:
    """True for visits through a tunnel or proxy; visits from this PC or the home network have neither header"""
    return bool(request.headers.get('Cf-Connecting-IP') or request.headers.get('X-Forwarded-For'))


def _safe_next(target: Optional[str]) -> str:
    """Only send people back to a page on this site after signing in"""
    if target and target.startswith('/') and not target.startswith('//') and '\\' not in target:
        return target
    return '/'


def _user_db() -> DatabaseService:
    """Database access for the signed-in user's My List, history and watched marks"""
    return DatabaseService(user_id=g.get('user_id') if has_request_context() else None)


@app.before_request
def require_login():
    if request.path.startswith(_PUBLIC_PATHS) or request.path == _CRON_SYNC_PATH:
        return None
    user_id = session.get('user_id')
    if user_id:
        with DatabaseService() as db_service:
            user = db_service.get_user(user_id)
        if user:
            g.user_id, g.username = user.id, user.username
            return None
        session.clear()  # the account was deleted
    if request.method == 'GET' and not request.path.startswith('/api/'):
        return redirect(f"/login?next={quote(request.full_path.rstrip('?'), safe='/')}")
    return jsonify({'error': 'sign in required'}), 401


@app.context_processor
def inject_current_user():
    return {'current_username': g.get('username')}


def _too_many_failures(ip: str, now: float) -> bool:
    with _login_lock:
        # Forget old failures so the table can't grow without end
        for key in [k for k, times in _login_failures.items() if now - times[-1] > _LOGIN_WINDOW_SECONDS]:
            del _login_failures[key]
        recent = [t for t in _login_failures.get(ip, []) if now - t < _LOGIN_WINDOW_SECONDS]
        return len(recent) >= _LOGIN_MAX_FAILURES


def _record_failure(ip: str, now: float) -> None:
    with _login_lock:
        _login_failures.setdefault(ip, []).append(now)


def _sign_in(user) -> None:
    session.clear()
    session.permanent = True
    session['user_id'] = user.id


@app.route('/login', methods=['GET', 'POST'])
def login():
    next_url = _safe_next(request.values.get('next'))
    if session.get('user_id'):
        return redirect(next_url)

    username = request.form.get('username', '').strip()
    error, status = None, 200
    if request.method == 'POST':
        ip, now = _client_ip(), time.time()
        if _too_many_failures(ip, now):
            error, status = 'Too many wrong tries. Try again in 15 minutes.', 429
        else:
            with DatabaseService() as db_service:
                user = db_service.check_password(username, request.form.get('password', ''))
            if user:
                _login_failures.pop(ip, None)
                _sign_in(user)
                return redirect(next_url)
            _record_failure(ip, now)
            error, status = 'Wrong username or password.', 401
    return render_template('login.html', mode='login', error=error, next_url=next_url,
                           username=username, needs_invite=False), status


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    """Create an account. Through a tunnel this needs the invite code (HOMEFLIX_PASSWORD in .env);
    without one set, accounts can only be made from this PC or the home network."""
    next_url = _safe_next(request.values.get('next'))
    if session.get('user_id'):
        return redirect(next_url)
    if not server_config.PASSWORD and _via_tunnel():
        return Response('New accounts can only be made from the PC running HOME FLIX until '
                        'HOMEFLIX_PASSWORD is set in .env.', status=403, mimetype='text/plain')

    username = request.form.get('username', '').strip()
    error, status = None, 200
    if request.method == 'POST':
        ip, now = _client_ip(), time.time()
        password = request.form.get('password', '')
        if _too_many_failures(ip, now):
            error, status = 'Too many wrong tries. Try again in 15 minutes.', 429
        elif server_config.PASSWORD and not hmac.compare_digest(
                request.form.get('invite', '').encode(), server_config.PASSWORD.encode()):
            _record_failure(ip, now)
            error, status = 'Wrong invite code.', 401
        elif not _USERNAME_PATTERN.match(username):
            error, status = 'Username: 3 to 30 letters, numbers, dots, dashes or underscores.', 400
        elif len(password) < _MIN_PASSWORD_LENGTH:
            error, status = f'Password: at least {_MIN_PASSWORD_LENGTH} characters.', 400
        elif password != request.form.get('confirm', ''):
            error, status = "The two passwords don't match.", 400
        else:
            with DatabaseService() as db_service:
                user = db_service.create_user(username, password)
            if user:
                _sign_in(user)
                return redirect(next_url)
            error, status = 'That username is taken.', 409
    return render_template('login.html', mode='signup', error=error, next_url=next_url,
                           username=username, needs_invite=bool(server_config.PASSWORD)), status


@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect('/login')

@app.context_processor
def inject_asset_version():
    """Cache-busting value for stylesheet links (?v={{ asset_version }}).

    /css/ responses are cached by browsers for an hour (serve_css). The newest
    stylesheet's modification time changes on every CSS edit, so browsers fetch
    the new file right away.
    """
    css_dir = os.path.join(app.root_path, server_config.CSS_FOLDER)
    try:
        version = max(int(os.path.getmtime(os.path.join(css_dir, name))) for name in os.listdir(css_dir))
    except (OSError, ValueError):
        version = 0
    return {'asset_version': version}

def _check_tmdb_token():
    """Warn at startup when TMDB rejects the token: seasons, episodes, cast and trailers all depend on it"""
    try:
        response = requests.get(
            f"{api_config.TMDB_BASE_URL}/authentication",
            headers={'Authorization': f'Bearer {api_config.TMDB_ACCESS_TOKEN}'},
            timeout=api_config.REQUEST_TIMEOUT
        )
        if response.status_code == 401:
            logger.warning(
                "TMDB rejected TMDB_ACCESS_TOKEN (401 Invalid API key): seasons, episodes, cast and trailers "
                "won't load. Put your TMDB 'API Read Access Token' in .env and restart."
            )
    except requests.RequestException as e:
        logger.warning(f"Couldn't reach TMDB to check TMDB_ACCESS_TOKEN: {e}")


if not api_config.TMDB_ACCESS_TOKEN:
    logger.warning(
        "TMDB_ACCESS_TOKEN is not set: posters, details and trailers won't load. "
        "Copy .env.example to .env and put your TMDB read access token in it."
    )
else:
    # In the background so a slow or offline TMDB doesn't delay startup
    threading.Thread(target=_check_tmdb_token, daemon=True).start()

# Initialize database on startup
init_db()


def _sync_loop():
    """Catalogue sync for one-container hosts (Back4app), instead of the homeflix-sync container.

    Only the newest pages: the full 500-page sync is too heavy for a 256 MB container and
    would keep a free Neon database awake. New titles always appear on the first pages.
    """
    import sync_data
    pages = int(os.getenv('SYNC_PAGES', '10'))
    interval = float(os.getenv('SYNC_INTERVAL_HOURS', '6')) * 3600
    while True:
        try:
            sync_data.sync_all_data(movie_pages=pages, tv_pages=pages, trending_pages=1)
        except Exception as e:
            logger.error(f"Catalogue sync failed: {e}")
        time.sleep(interval)


if os.getenv('SYNC_IN_APP', '').lower() in ('1', 'true', 'yes'):
    threading.Thread(target=_sync_loop, daemon=True, name='catalogue-sync').start()


# Vercel can't keep a background thread: its cron job (vercel.json) calls this once a day
_CRON_SYNC_PATH = '/api/cron/sync'


@app.route(_CRON_SYNC_PATH)
def cron_sync():
    """Run one small catalogue sync. Vercel sends CRON_SECRET; anyone else is refused."""
    secret = os.getenv('CRON_SECRET', '')
    sent = request.headers.get('Authorization', '')
    if not secret or not hmac.compare_digest(sent.encode(), f'Bearer {secret}'.encode()):
        return jsonify({'error': 'not allowed'}), 401
    import sync_data
    pages = int(os.getenv('SYNC_PAGES', '3'))
    sync_data.sync_all_data(movie_pages=pages, tv_pages=pages, trending_pages=1)
    return jsonify({'synced_pages': pages})

# Register monitoring routes
try:
    from monitoring import register_monitoring_routes
    register_monitoring_routes(app)
    logger.info("Monitoring endpoints registered: /health, /metrics, /cache/clear")
except ImportError:
    logger.warning("Monitoring module not available - health check endpoints disabled")

@lru_cache(maxsize=1000)
def get_cached_tmdb_data(url: str, params_str: str = "") -> Dict[str, Any]:
    """
    Get data from cache or fetch from TMDB with LRU cache decorator
    
    Args:
        url: TMDB API endpoint URL
        params_str: Stringified params for cache key
        
    Returns:
        JSON response as dictionary
    """
    cache_key = f"{url}_{params_str}"
    
    # Try to get from timed cache first
    cached_data = cache_manager.get('tmdb', cache_key, cache_config.TMDB_DATA)
    if cached_data is not None:
        return cached_data
    
    # Fetch from API
    headers = {'Authorization': f'Bearer {api_config.TMDB_ACCESS_TOKEN}'}
    # Parse params_str safely (it's always from str(dict) in this codebase)
    import json
    try:
        params = json.loads(params_str.replace("'", '"')) if params_str else None
    except (json.JSONDecodeError, ValueError):
        params = None
    
    try:
        data = make_api_request(url, headers=headers, params=params)
        cache_manager.set('tmdb', cache_key, data)
        return data
    except Exception as e:
        logger.error(f"Error fetching TMDB data from {url}: {e}")
        return {}

def _populate_image_cache(items: List[Dict[str, Any]], media_type: str):
    """
    Populate poster and backdrop cache from database results
    Optimized to reduce database queries
    
    Args:
        items: List of movie/TV show dictionaries
        media_type: 'movie', 'tv', or 'mixed'
    """
    if not items:
        return

    with _user_db() as db_service:
        for item in items:
            tmdb_id = item.get('tmdb_id')
            if not tmdb_id:
                continue

            # For mixed types (My List), determine type from item
            current_type = media_type
            if media_type == 'mixed':
                current_type = 'movie' if item.get('type') == 'movie' else 'tv'

            # Get the database object to access poster_path and backdrop_path
            try:
                if current_type == 'movie':
                    db_item = db_service.get_movie_by_tmdb_id(tmdb_id)
                else:
                    db_item = db_service.get_tvshow_by_tmdb_id(tmdb_id)

                if not db_item:
                    continue

                # Populate caches
                if getattr(db_item, 'poster_path', None):
                    cache_manager.set('posters', f"{current_type}_{tmdb_id}", db_item.poster_path)

                if getattr(db_item, 'backdrop_path', None):
                    cache_manager.set('backdrops', f"{current_type}_{tmdb_id}", db_item.backdrop_path)
            except Exception as e:
                logger.error(f"Error populating cache for {current_type} {tmdb_id}: {e}")


def _allows_framing(headers: Dict[str, str]) -> bool:
    """Return True if the response headers indicate the resource can be framed.

    Checks X-Frame-Options and Content-Security-Policy frame-ancestors.
    """
    xfo = headers.get('x-frame-options') or headers.get('X-Frame-Options')
    if xfo:
        xfo_val = xfo.lower()
        if 'deny' in xfo_val or 'sameorigin' in xfo_val:
            return False
    csp = headers.get('content-security-policy') or headers.get('Content-Security-Policy')
    if csp and 'frame-ancestors' in csp:
        try:
            # Parse frame-ancestors directive
            parts = [p.strip() for p in csp.split(';')]
            fa = [p for p in parts if p.startswith('frame-ancestors')]
            if fa:
                fa_vals = fa[0].split()[1:]
                # If frame-ancestors contains * or 'self', allow; otherwise block
                if any(v == '*' or "'self'" in v or 'self' in v for v in fa_vals):
                    return True
                return False
        except Exception:
            # If parsing fails, be conservative and disallow
            return False
    return True


@lru_cache(maxsize=1)
def _embed_hosts() -> frozenset:
    """Hosts of our own embed sources: the only ones /embed_check may contact"""
    urls = (get_embed_sources('movie', '0') + get_embed_sources('tv', '0')
            + get_embed_sources('episode', '0', 1, 1))
    return frozenset(urlparse(u).hostname for u in urls)


@app.route('/embed_check', methods=['POST'])
def embed_check():
    """Simple endpoint to test whether an embed url allows framing.

    Expects JSON: { "url": "https://..." }
    Returns JSON: { "url": "...", "allows": true/false, "status_code": int }
    """
    try:
        data = request.get_json(silent=True) or {}
        url = data.get('url')
        if not url:
            return jsonify({'error': 'missing url'}), 400

        # Only check our own embed sources, so this can't be used to fetch arbitrary URLs
        parsed = urlparse(url)
        if parsed.scheme != 'https' or parsed.hostname not in _embed_hosts():
            return jsonify({'error': 'url is not a known embed source'}), 400

        # Use HEAD first to be lighter; follow redirects but capture final headers
        try:
            resp = requests.head(url, allow_redirects=True, timeout=5)
        except Exception:
            # Fallback to GET if HEAD fails (some hosts don't support HEAD)
            resp = requests.get(url, allow_redirects=True, timeout=5)

        allows = _allows_framing({k.lower(): v for k, v in resp.headers.items()})
        return jsonify({'url': url, 'allows': allows, 'status_code': resp.status_code})
    except Exception as e:
        logger.error(f"Error in embed_check: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/favicon.ico')
def favicon():
    """Handle favicon requests"""
    return '', 204

@app.route('/')
@measure_time
def index():
    """Display all movies and series - optimized with caching"""
    movie_page = request.args.get('movie_page', 1, type=int)
    series_page = request.args.get('series_page', 1, type=int)
    try:
        # Use database instead of API calls
        with _user_db() as db_service:
            movies = db_service.get_latest_movies(movie_page, pagination_config.DEFAULT_PER_PAGE)
            series = db_service.get_latest_tvshows(series_page, pagination_config.DEFAULT_PER_PAGE)
            trending_movies = db_service.get_trending_movies(pagination_config.TRENDING_LIMIT)
            trending_series = db_service.get_trending_tvshows(pagination_config.TRENDING_LIMIT)
            my_list = db_service.get_my_list()
            continue_watching = db_service.get_continue_watching(limit=10)  # Get continue watching
        
        # Populate image caches from database results
        _populate_image_cache(movies, 'movie')
        _populate_image_cache(series, 'tv')
        _populate_image_cache(trending_movies, 'movie')
        _populate_image_cache(trending_series, 'tv')
        if my_list:
            _populate_image_cache(my_list, 'mixed')
        if continue_watching:
            _populate_image_cache(continue_watching, 'mixed')
        
        # Get backdrop URLs for hero section from trending movies
        backdrop_urls = []
        for movie in trending_movies:
            backdrop_url = movie.get('backdrop_url')
            if backdrop_url:
                backdrop_urls.append(backdrop_url)
        
        # If not enough backdrops, add from movies
        if len(backdrop_urls) < 5:
            for movie in movies:
                if len(backdrop_urls) >= 10:
                    break
                backdrop_url = movie.get('backdrop_url')
                if backdrop_url:
                    backdrop_urls.append(backdrop_url)
        
        return render_template('index.html', movies=movies, series=series, 
                             trending_movies=trending_movies, trending_series=trending_series, 
                             movie_page=movie_page, series_page=series_page, 
                             backdrop_urls=backdrop_urls, my_list=my_list,
                             continue_watching=continue_watching,
                             trending_limit=pagination_config.TRENDING_LIMIT)
    except Exception as e:
        logger.error(f"Error in index: {e}")
        return f"Error accessing data: {e}", 500

@app.route('/search')
@measure_time
def search():
    """Display search results for movies and series"""
    query = request.args.get('q', '').strip()
    
    if not query or len(query) < 2:
        return redirect('/')
    
    try:
        # Search database for movies and series
        with _user_db() as db_service:
            movies = db_service.search_movies(query, page=1, per_page=50)
            series = db_service.search_tvshows(query, page=1, per_page=50)
        
        # Populate image caches
        _populate_image_cache(movies, 'movie')
        _populate_image_cache(series, 'tv')
        
        return render_template('search_results.html', 
                             query=query,
                             movies=movies, 
                             series=series)
    except Exception as e:
        logger.error(f"Error in search: {e}")
        return f"Error performing search: {e}", 500

@app.route('/top')
@measure_time
def top_rated():
    """Top movies or TV shows ranked with IMDb's weighted-rating formula"""
    kind = 'series' if request.args.get('type') == 'tv' else 'movie'
    try:
        # Ratings only change when sync_data.py runs, so an hour-old ranking is fine
        cache_key = f"{kind}-{pagination_config.TOP_LIST_SIZE}"
        titles = cache_manager.get('top', cache_key, cache_config.TMDB_DATA)
        if titles is None:
            with _user_db() as db_service:
                titles = db_service.get_top_rated(kind, limit=pagination_config.TOP_LIST_SIZE)
            cache_manager.set('top', cache_key, titles)
        return render_template('top.html', titles=titles, kind=kind,
                               list_size=pagination_config.TOP_LIST_SIZE)
    except Exception as e:
        logger.error(f"Error in top_rated: {e}")
        return f"Error loading the top list: {e}", 500

@app.route('/load_more_movies/<int:page>')
def load_more_movies(page):
    """Load more movies for AJAX"""
    try:
        with _user_db() as db_service:
            movies = db_service.get_latest_movies(page, pagination_config.DEFAULT_PER_PAGE)
        _populate_image_cache(movies, 'movie')
        return {'movies': movies}
    except Exception as e:
        return {'error': str(e)}, 500

@app.route('/load_more_series/<int:page>')
def load_more_series(page):
    """Load more series for AJAX"""
    try:
        with _user_db() as db_service:
            series = db_service.get_latest_tvshows(page, pagination_config.DEFAULT_PER_PAGE)
        _populate_image_cache(series, 'tv')
        return {'series': series}
    except Exception as e:
        return {'error': str(e)}, 500

@app.route('/load_more_trending/<kind>/<int:page>')
def load_more_trending(kind, page):
    """Next page of a Trending row (kind: 'movie' or 'series') for its Show More button"""
    if kind not in ('movie', 'series') or page < 1:
        return {'error': "kind must be 'movie' or 'series' and page at least 1"}, 400
    per_page = pagination_config.TRENDING_LIMIT
    try:
        with _user_db() as db_service:
            get_trending = db_service.get_trending_movies if kind == 'movie' else db_service.get_trending_tvshows
            # Ask for one extra item: if it comes back, there is another page
            items = get_trending(per_page + 1, offset=(page - 1) * per_page)
        has_more = len(items) > per_page
        items = items[:per_page]
        _populate_image_cache(items, 'movie' if kind == 'movie' else 'tv')
        return {'items': items, 'has_more': has_more}
    except Exception as e:
        return {'error': str(e)}, 500

@app.route('/watch/movie/<imdb_id>')
@measure_time
def watch_movie(imdb_id):
    """Watch movie using embed URL with multiple fallback sources"""
    try:
        # Fetch movie details from TMDB for accurate info
        details = get_movie_details(imdb_id)
        tmdb_id = None
        title = 'Unknown Movie'
        
        if details:
            title = details['title']
            tmdb_id = details.get('tmdb_id')
        
        # Generate multiple embed sources using config
        embed_sources = get_embed_sources('movie', tmdb_id or imdb_id)
        embed_url = embed_sources[0] if embed_sources else ""
        
        return render_template('player.html', 
                             embed_url=embed_url, 
                             embed_sources=embed_sources,
                             title=title, 
                             type='movie',
                             imdb_id=imdb_id,
                             tmdb_id=tmdb_id)
    except Exception as e:
        logger.error(f"Error in watch_movie: {e}")
        return f"Error: {e}", 500

@app.route('/watch/series/<imdb_id>')
def watch_series(imdb_id):
    """Watch series using embed URL with multiple fallback sources"""
    try:
        # Fetch series details from TMDB for accurate info
        details = get_series_details(imdb_id)
        tmdb_id = None
        title = 'Unknown Series'
        
        if details:
            # TMDB returns a series' title as 'name'
            title = details.get('name') or details.get('title') or title
            tmdb_id = details.get('tmdb_id')

        # Generate multiple embed sources using config
        embed_sources = get_embed_sources('tv', tmdb_id or imdb_id)
        embed_url = embed_sources[0] if embed_sources else ""

        return render_template('player.html',
                             embed_url=embed_url,
                             embed_sources=embed_sources,
                             title=title,
                             type='series',
                             imdb_id=imdb_id,
                             tmdb_id=tmdb_id)
    except Exception as e:
        logger.error(f"Error in watch_series: {e}")
        return f"Error: {e}", 500

@app.route('/series/<imdb_id>')
@measure_time
def series_details(imdb_id):
    """Display series details with seasons and episodes"""
    try:
        # Fetch series details from database first
        with _user_db() as db_service:
            series = db_service.get_tvshow_by_imdb_id(imdb_id)
            my_list = db_service.get_my_list()
        
        if not series:
            # If not in database, try to fetch from TMDB using IMDB ID
            find_url = f"{api_config.TMDB_BASE_URL}/find/{imdb_id}"
            params = {'external_source': 'imdb_id'}
            params_str = str(params)
            find_data = get_cached_tmdb_data(find_url, params_str)
            
            tv_results = find_data.get('tv_results', [])
            if not tv_results:
                return "Series not found", 404
            
            # Get the TMDB ID from the results
            tmdb_id = tv_results[0].get('id')
            
            # Fetch full TV show details
            tv_url = f"{api_config.TMDB_BASE_URL}/tv/{tmdb_id}"
            tv_data = get_cached_tmdb_data(tv_url, "")
            
            # Create series_dict from TMDB data
            series_dict = {
                'title': tv_data.get('name'),
                'overview': tv_data.get('overview'),
                'poster_path': tv_data.get('poster_path'),
                'backdrop_path': tv_data.get('backdrop_path'),
                'first_air_date': tv_data.get('first_air_date'),
                'vote_average': tv_data.get('vote_average'),
                'vote_count': tv_data.get('vote_count'),
                'popularity': tv_data.get('popularity'),
                'tmdb_id': tmdb_id,
                'imdb_id': imdb_id
            }
        else:
            series_dict = series.to_dict()
        
        tmdb_id = series_dict.get('tmdb_id')
        
        # Fetch detailed information from TMDB
        if tmdb_id:
            # Get full series details, plus cast, ratings, videos and recommendations in the same call
            url = f"{api_config.TMDB_BASE_URL}/tv/{tmdb_id}"
            series_data = get_cached_tmdb_data(url, str(TV_DETAILS_APPEND))
            # Empty when TMDB failed (e.g. a rejected token): the page explains instead of looking blank
            series_dict['details_unavailable'] = not series_data

            # Get seasons information
            seasons = []
            for season_data in series_data.get('seasons', []):
                if season_data.get('season_number', 0) > 0:  # Skip specials (season 0)
                    seasons.append({
                        'season_number': season_data.get('season_number'),
                        'name': season_data.get('name'),
                        'episode_count': season_data.get('episode_count'),
                        'overview': season_data.get('overview'),
                        'air_date': season_data.get('air_date'),
                        'poster_path': season_data.get('poster_path')
                    })
            
            # Get cast information
            credits_data = series_data.get('credits', {})
            cast = credits_data.get('cast', [])[:10]  # Top 10 cast members

            # Get content rating
            ratings_data = series_data.get('content_ratings', {})
            rating = 'TV-MA'  # default
            for item in ratings_data.get('results', []):
                if item.get('iso_3166_1') == 'US':
                    rating = item.get('rating', 'TV-MA')
                    break
            
            # Update series dict with additional info
            series_dict['rating'] = rating
            series_dict['cast'] = cast
            series_dict['seasons'] = seasons
            series_dict['genres'] = series_data.get('genres', [])
            series_dict['created_by'] = series_data.get('created_by', [])
            series_dict['networks'] = series_data.get('networks', [])
            series_dict['status'] = series_data.get('status', '')
            series_dict['tagline'] = series_data.get('tagline', '')
            series_dict['trailer_key'] = _pick_trailer_key(series_data)
            series_dict['more_like_this'] = _more_like_this(series_data, 'tv')

        return render_template('series_details.html', series=series_dict, imdb_id=imdb_id, my_list=my_list)
    except Exception as e:
        logger.error(f"Error in series_details: {e}")
        return f"Error: {e}", 500

@app.route('/movie/<imdb_id>')
def movie_details(imdb_id):
    """Display movie details page"""
    try:
        # Fetch movie details from database first
        with _user_db() as db_service:
            movie = db_service.get_movie_by_imdb_id(imdb_id)
            my_list = db_service.get_my_list()  # Get My List items
        
        if not movie:
            return "Movie not found", 404
        
        movie_dict = movie.to_dict()
        tmdb_id = movie.tmdb_id
        
        # Fetch detailed information from TMDB
        if tmdb_id:
            # Get full movie details, plus cast, ratings, videos and recommendations in the same call
            url = f"{api_config.TMDB_BASE_URL}/movie/{tmdb_id}"
            movie_data = get_cached_tmdb_data(url, str(MOVIE_DETAILS_APPEND))
            # Empty when TMDB failed (e.g. a rejected token): the page explains instead of looking blank
            movie_dict['details_unavailable'] = not movie_data

            # Get cast information
            credits_data = movie_data.get('credits', {})
            cast = credits_data.get('cast', [])[:10]  # Top 10 cast members
            crew = credits_data.get('crew', [])
            
            # Get director
            director = next((person for person in crew if person.get('job') == 'Director'), None)
            
            # Get content rating
            releases_data = movie_data.get('release_dates', {})
            rating = 'NR'  # default
            for country in releases_data.get('results', []):
                if country.get('iso_3166_1') == 'US':
                    release_dates = country.get('release_dates', [])
                    if release_dates:
                        rating = release_dates[0].get('certification', 'NR')
                    break
            
            # Update movie dict with additional info
            movie_dict['rating'] = rating
            movie_dict['cast'] = cast
            movie_dict['director'] = director
            movie_dict['genres'] = movie_data.get('genres', [])
            movie_dict['runtime'] = movie_data.get('runtime', 0)
            movie_dict['tagline'] = movie_data.get('tagline', '')
            movie_dict['budget'] = movie_data.get('budget', 0)
            movie_dict['revenue'] = movie_data.get('revenue', 0)
            movie_dict['trailer_key'] = _pick_trailer_key(movie_data)
            movie_dict['more_like_this'] = _more_like_this(movie_data, 'movie')

        return render_template('movie_details.html', movie=movie_dict, imdb_id=imdb_id, my_list=my_list)
    except Exception as e:
        logger.error(f"Error in movie_details: {e}")
        return f"Error: {e}", 500

@app.route('/series/<imdb_id>/season/<int:season_number>')
def season_episodes(imdb_id, season_number):
    """Display episodes for a specific season"""
    try:
        # Fetch series details from database
        with _user_db() as db_service:
            series = db_service.get_tvshow_by_imdb_id(imdb_id)
        
        if not series:
            # If not in database, try to fetch from TMDB using IMDB ID
            find_url = f"{api_config.TMDB_BASE_URL}/find/{imdb_id}"
            params = {'external_source': 'imdb_id'}
            params_str = str(params)
            find_data = get_cached_tmdb_data(find_url, params_str)
            
            tv_results = find_data.get('tv_results', [])
            if not tv_results:
                return "Series not found", 404
            
            tmdb_id = tv_results[0].get('id')
            series_title = tv_results[0].get('name')
        else:
            tmdb_id = series.tmdb_id
            series_title = series.title
        
        # Fetch season details from TMDB
        if tmdb_id:
            url = f"{api_config.TMDB_BASE_URL}/tv/{tmdb_id}/season/{season_number}"
            season_data = get_cached_tmdb_data(url, "")
            
            episodes = []
            for ep_data in season_data.get('episodes', []):
                episodes.append({
                    'episode_number': ep_data.get('episode_number'),
                    'name': ep_data.get('name'),
                    'overview': ep_data.get('overview'),
                    'air_date': ep_data.get('air_date'),
                    'runtime': ep_data.get('runtime'),
                    'still_path': ep_data.get('still_path'),
                    'vote_average': ep_data.get('vote_average')
                })
            
            season_info = {
                'season_number': season_number,
                'name': season_data.get('name') or f"Season {season_number}",
                'overview': season_data.get('overview'),
                'air_date': season_data.get('air_date'),
                'episodes': episodes
            }
            
            # Create series dict for template
            if series:
                series_dict = series.to_dict()
            else:
                series_dict = {
                    'title': series_title,
                    'tmdb_id': tmdb_id,
                    'imdb_id': imdb_id
                }
            
            return render_template('season_details.html',
                                 series=series_dict,
                                 season=season_info,
                                 imdb_id=imdb_id,
                                 tmdb_id=tmdb_id,
                                 details_unavailable=not season_data)

        return "Season details are unavailable for this series", 404
    except Exception as e:
        logger.error(f" in season_episodes: {e}")
        return f"Error: {e}", 500

@app.route('/watch/series/<imdb_id>/<int:season_number>/<int:episode_number>')
def watch_episode(imdb_id, season_number, episode_number):
    """Watch a specific episode"""
    try:
        # Fetch series details from database
        with _user_db() as db_service:
            series = db_service.get_tvshow_by_imdb_id(imdb_id)
        
        if not series:
            # If not in database, try to fetch from TMDB using IMDB ID
            find_url = f"{api_config.TMDB_BASE_URL}/find/{imdb_id}"
            params = {'external_source': 'imdb_id'}
            params_str = str(params)
            find_data = get_cached_tmdb_data(find_url, params_str)
            
            tv_results = find_data.get('tv_results', [])
            if not tv_results:
                return "Series not found", 404
            
            tmdb_id = tv_results[0].get('id')
            title = tv_results[0].get('name')
        else:
            tmdb_id = series.tmdb_id
            title = series.title
        
        # Generate multiple embed sources using config
        embed_sources = get_embed_sources('episode', tmdb_id or imdb_id, season_number, episode_number)
        embed_url = embed_sources[0] if embed_sources else ""
        
        return render_template('player.html',
                             embed_url=embed_url,
                             embed_sources=embed_sources,
                             title=f"{title} - S{season_number}E{episode_number}",
                             series_title=title,
                             type='episode',
                             imdb_id=imdb_id,
                             tmdb_id=tmdb_id,
                             season=season_number,
                             episode=episode_number)
    except Exception as e:
        logger.error(f"Error in watch_episode: {e}")
        return f"Error: {e}", 500

@app.route('/css/<filename>')
def serve_css(filename):
    """Serve CSS files with caching headers"""
    try:
        response = send_from_directory(server_config.CSS_FOLDER, filename)
        # Add caching headers for better performance
        response.headers['Cache-Control'] = 'public, max-age=3600'
        return response
    except Exception as e:
        logger.error(f"Error serving CSS {filename}: {e}")
        abort(404)

@app.route('/poster/<media_type>/<int:tmdb_id>')
def get_poster(media_type, tmdb_id):
    """Serve poster image with caching"""
    if not api_config.TMDB_ACCESS_TOKEN:
        svg = '''<svg width="300" height="450" xmlns="http://www.w3.org/2000/svg">
        <rect width="300" height="450" fill="#333"/>
        <text x="150" y="225" text-anchor="middle" fill="white" font-size="20">No Poster</text>
        </svg>'''
        return Response(svg, mimetype='image/svg+xml')
    
    key = f"{media_type}_{tmdb_id}"
    poster_path = cache_manager.get('posters', key, cache_config.POSTER)
    
    # If not in cache, try to get from database
    if not poster_path:
        try:
            with _user_db() as db_service:
                if media_type == 'movie':
                    db_item = db_service.get_movie_by_tmdb_id(tmdb_id)
                else:
                    db_item = db_service.get_tvshow_by_tmdb_id(tmdb_id)
                
                if db_item and hasattr(db_item, 'poster_path') and db_item.poster_path:
                    poster_path = db_item.poster_path
                    cache_manager.set('posters', key, poster_path)
        except Exception as e:
            logger.error(f"Error fetching poster from database: {e}")
    
    if not poster_path:
        abort(404)

    return _redirect_to_image(tmdb_poster_url(poster_path))

@app.route('/backdrop/<media_type>/<int:tmdb_id>')
def get_backdrop(media_type, tmdb_id):
    """Serve backdrop image with caching"""
    if not api_config.TMDB_ACCESS_TOKEN:
        svg = '''<svg width="500" height="281" xmlns="http://www.w3.org/2000/svg">
        <rect width="500" height="281" fill="#333"/>
        <text x="250" y="140" text-anchor="middle" fill="white" font-size="20">No Backdrop</text>
        </svg>'''
        return Response(svg, mimetype='image/svg+xml')
    
    key = f"{media_type}_{tmdb_id}"
    backdrop_path = cache_manager.get('backdrops', key, cache_config.BACKDROP)
    
    # If not in cache, try to get from database first
    if not backdrop_path:
        try:
            with _user_db() as db_service:
                if media_type == 'movie':
                    db_item = db_service.get_movie_by_tmdb_id(tmdb_id)
                else:
                    db_item = db_service.get_tvshow_by_tmdb_id(tmdb_id)
                
                if db_item and hasattr(db_item, 'backdrop_path') and db_item.backdrop_path:
                    backdrop_path = db_item.backdrop_path
                    cache_manager.set('backdrops', key, backdrop_path)
        except Exception as e:
            logger.error(f"Error fetching backdrop from database: {e}")
    
    # If still not found, try to fetch from TMDB API
    if not backdrop_path:
        try:
            headers = {
                "Authorization": f"Bearer {api_config.TMDB_ACCESS_TOKEN}",
                "accept": "application/json"
            }
            tmdb_url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}"
            response = requests.get(tmdb_url, headers=headers, timeout=api_config.REQUEST_TIMEOUT)
            
            if response.ok:
                data = response.json()
                backdrop_path = data.get('backdrop_path')
                
                if backdrop_path:
                    # Cache the backdrop path
                    cache_manager.set('backdrops', key, backdrop_path)
                else:
                    # No backdrop available, return placeholder
                    logger.warning(f"No backdrop available for {media_type}/{tmdb_id}")
                    svg = '''<svg width="500" height="281" xmlns="http://www.w3.org/2000/svg">
                    <rect width="500" height="281" fill="#333"/>
                    <text x="250" y="140" text-anchor="middle" fill="white" font-size="16">No Backdrop Available</text>
                    </svg>'''
                    return Response(svg, mimetype='image/svg+xml')
            else:
                # TMDB API error, return placeholder
                logger.warning(f"TMDB API error for {media_type}/{tmdb_id}: {response.status_code}")
                svg = '''<svg width="500" height="281" xmlns="http://www.w3.org/2000/svg">
                <rect width="500" height="281" fill="#333"/>
                <text x="250" y="140" text-anchor="middle" fill="white" font-size="16">Backdrop Unavailable</text>
                </svg>'''
                return Response(svg, mimetype='image/svg+xml')
        except Exception as e:
            logger.error(f"Error fetching backdrop metadata from TMDB: {e}")
            # Return placeholder instead of aborting
            svg = '''<svg width="500" height="281" xmlns="http://www.w3.org/2000/svg">
            <rect width="500" height="281" fill="#333"/>
            <text x="250" y="140" text-anchor="middle" fill="white" font-size="16">Backdrop Error</text>
            </svg>'''
            return Response(svg, mimetype='image/svg+xml')
    
    return _redirect_to_image(tmdb_backdrop_url(backdrop_path))


def _redirect_to_image(image_url: str) -> Response:
    """Send the browser to TMDB's image servers.

    Copying the image through HomeFlix meant downloading it from TMDB and then
    uploading it through the home connection and the tunnel for every visitor.
    Browsers keep the redirect for a day, so a repeat visit skips HomeFlix entirely.
    """
    response = redirect(image_url, code=302)
    response.headers['Cache-Control'] = 'private, max-age=86400'
    return response

def search_tmdb_movies(query, page=1):
    """Search movies using TMDB API"""
    try:
        url = f"{api_config.TMDB_BASE_URL}/search/movie"
        params = {'query': query, 'page': page}
        data = get_cached_tmdb_data(url, str(params))
        movies = data.get('results', [])[:15]  # Limit to 15
        filtered_movies = []
        for movie in movies:
            movie['tmdb_id'] = movie['id']
            # Get IMDB ID
            imdb_id = get_imdb_id(movie['tmdb_id'], 'movie')
            if imdb_id:  # Only include movies with IMDB IDs
                movie['imdb_id'] = imdb_id
                # Build poster URL directly
                movie['poster_url'] = tmdb_poster_url(movie.get('poster_path'))
                movie['backdrop_url'] = tmdb_backdrop_url(movie.get('backdrop_path'))
                movie['quality'] = 'HD'  # Default
                # Cache the poster path if available
                if movie.get('poster_path'):
                    cache_manager.set('posters', f"movie_{movie['tmdb_id']}", movie['poster_path'])
                if movie.get('backdrop_path'):
                    cache_manager.set('backdrops', f"movie_{movie['tmdb_id']}", movie['backdrop_path'])
                filtered_movies.append(movie)
        return filtered_movies
    except Exception as e:
        logger.error(f" searching TMDB movies: {e}")
        return []

def search_tmdb_series(query, page=1):
    """Search TV series using TMDB API"""
    try:
        url = f"{api_config.TMDB_BASE_URL}/search/tv"
        params = {'query': query, 'page': page}
        data = get_cached_tmdb_data(url, str(params))
        series = data.get('results', [])[:15]  # Limit to 15
        filtered_series = []
        for show in series:
            show['tmdb_id'] = show['id']
            # Get IMDB ID
            imdb_id = get_imdb_id(show['tmdb_id'], 'tv')
            if imdb_id:  # Only include series with IMDB IDs
                show['imdb_id'] = imdb_id
                # Build poster URL directly
                show['poster_url'] = tmdb_poster_url(show.get('poster_path'))
                show['backdrop_url'] = tmdb_backdrop_url(show.get('backdrop_path'))
                # Cache the poster path if available
                if show.get('poster_path'):
                    cache_manager.set('posters', f"tv_{show['tmdb_id']}", show['poster_path'])
                if show.get('backdrop_path'):
                    cache_manager.set('backdrops', f"tv_{show['tmdb_id']}", show['backdrop_path'])
                filtered_series.append(show)
        return filtered_series
    except Exception as e:
        logger.error(f" searching TMDB series: {e}")
        return []

@lru_cache(maxsize=500)
def get_imdb_id(tmdb_id: int, media_type: str) -> Optional[str]:
    """
    Get IMDB ID from TMDB ID with caching
    
    Args:
        tmdb_id: TMDB ID
        media_type: 'movie' or 'tv'
        
    Returns:
        IMDB ID or None if not found
    """
    try:
        url = f"{api_config.TMDB_BASE_URL}/{media_type}/{tmdb_id}/external_ids"
        data = get_cached_tmdb_data(url, "")
        return data.get('imdb_id')
    except Exception as e:
        logger.error(f"Error getting IMDB ID for {tmdb_id}: {e}")
        return None

@lru_cache(maxsize=200)
def get_movie_details(imdb_id: str) -> Optional[Dict[str, Any]]:
    """
    Get movie details from TMDB by IMDB ID with caching
    
    Args:
        imdb_id: IMDB ID
        
    Returns:
        Movie details dictionary or None
    """
    try:
        url = f"{api_config.TMDB_BASE_URL}/find/{imdb_id}"
        params_str = str({'external_source': 'imdb_id'})
        data = get_cached_tmdb_data(url, params_str)
        
        if data.get('movie_results'):
            movie = data['movie_results'][0]
            movie['tmdb_id'] = movie['id']
            return movie
        return None
    except Exception as e:
        logger.error(f"Error getting movie details for {imdb_id}: {e}")
        return None


@lru_cache(maxsize=200)
def get_series_details(imdb_id: str) -> Optional[Dict[str, Any]]:
    """
    Get series details from TMDB by IMDB ID with caching
    
    Args:
        imdb_id: IMDB ID
        
    Returns:
        Series details dictionary or None
    """
    try:
        url = f"{api_config.TMDB_BASE_URL}/find/{imdb_id}"
        params_str = str({'external_source': 'imdb_id'})
        data = get_cached_tmdb_data(url, params_str)
        
        if data.get('tv_results'):
            series = data['tv_results'][0]
            series['tmdb_id'] = series['id']
            return series
        return None
    except Exception as e:
        logger.error(f"Error getting series details for {imdb_id}: {e}")
        return None


# TMDB extras fetched with a title's details in one call. The details pages and
# /api/title_info pass the same params, so they share one cache entry per title.
MOVIE_DETAILS_APPEND = {'append_to_response': 'credits,release_dates,videos,recommendations,similar'}
TV_DETAILS_APPEND = {'append_to_response': 'credits,content_ratings,videos,recommendations,similar'}


def _pick_trailer_key(details: Dict[str, Any]) -> Optional[str]:
    """
    Pick the best YouTube trailer from TMDB details fetched with append_to_response=videos

    Returns:
        YouTube video key, or None if TMDB has no trailer or teaser
    """
    videos = [
        video for video in details.get('videos', {}).get('results', [])
        if video.get('site') == 'YouTube' and video.get('key') and video.get('type') in ('Trailer', 'Teaser')
    ]
    if not videos:
        return None
    # Trailers before teasers, official before fan uploads
    videos.sort(key=lambda video: (video.get('type') != 'Trailer', not video.get('official')))
    return videos[0]['key']


def _more_like_this(details: Dict[str, Any], media_type: str, limit: int = 12) -> List[Dict[str, Any]]:
    """
    Get recommended titles from TMDB details fetched with append_to_response=recommendations,similar

    Only titles in our database are kept, so every card links to a page that works.

    Args:
        details: TMDB details response
        media_type: 'movie' or 'tv'
        limit: Maximum number of titles
    """
    own_id = details.get('id')
    tmdb_ids = []
    for section in ('recommendations', 'similar'):
        for result in details.get(section, {}).get('results', []):
            if result.get('id') and result['id'] != own_id and result['id'] not in tmdb_ids:
                tmdb_ids.append(result['id'])
    if not tmdb_ids:
        return []

    try:
        with _user_db() as db_service:
            if media_type == 'movie':
                items = db_service.get_movies_by_tmdb_ids(tmdb_ids)
            else:
                items = db_service.get_tvshows_by_tmdb_ids(tmdb_ids)
    except Exception as e:
        logger.error(f"Error loading More Like This for {media_type} {own_id}: {e}")
        return []
    # Cards need a poster to look right
    return [item for item in items if item.get('poster_url')][:limit]

@app.route('/api/next_episode/<imdb_id>/<int:season>/<int:episode>')
def get_next_episode(imdb_id, season, episode):
    """Get next episode information for series"""
    try:
        # Get series details to check total episodes
        series_details = get_series_details(imdb_id)
        if not series_details:
            return jsonify({'has_next': False})
        
        tmdb_id = series_details.get('tmdb_id')
        if not tmdb_id:
            return jsonify({'has_next': False})
        
        # Get season details to check episode count
        url = f"{api_config.TMDB_BASE_URL}/tv/{tmdb_id}/season/{season}"
        season_data = get_cached_tmdb_data(url, "")
        
        total_episodes = len(season_data.get('episodes', []))
        next_episode = episode + 1
        next_season = season
        
        # Check if there's a next episode in current season
        if next_episode <= total_episodes:
            # Next episode exists in current season
            episode_data = season_data['episodes'][next_episode - 1]  # 0-indexed
            
            return jsonify({
                'has_next': True,
                'next_season': next_season,
                'next_episode': next_episode,
                'next_title': episode_data.get('name', f'Episode {next_episode}'),
                'next_overview': episode_data.get('overview', ''),
                'next_still_path': f"{api_config.TMDB_IMAGE_BASE_URL}{episode_data['still_path']}" if episode_data.get('still_path') else None
            })
        else:
            # Check if there's a next season
            next_season = season + 1
            try:
                url = f"{api_config.TMDB_BASE_URL}/tv/{tmdb_id}/season/{next_season}"
                next_season_data = get_cached_tmdb_data(url, "")
                
                if next_season_data.get('episodes'):
                    first_episode = next_season_data['episodes'][0]
                    return jsonify({
                        'has_next': True,
                        'next_season': next_season,
                        'next_episode': 1,
                        'next_title': first_episode.get('name', 'Episode 1'),
                        'next_overview': first_episode.get('overview', ''),
                        'next_still_path': f"{api_config.TMDB_IMAGE_BASE_URL}{first_episode['still_path']}" if first_episode.get('still_path') else None
                    })
            except:
                pass
        
        return jsonify({'has_next': False})
        
    except Exception as e:
        logger.error(f"Error getting next episode for {imdb_id} S{season}E{episode}: {e}")
        return jsonify({'has_next': False})

@app.route('/api/title_info/<kind>/<imdb_id>')
def api_title_info(kind, imdb_id):
    """Compact details for the More Info popup on title cards and the hero banner"""
    if kind not in ('movie', 'series'):
        return jsonify({'success': False, 'error': "kind must be 'movie' or 'series'"}), 400
    
    try:
        with _user_db() as db_service:
            if kind == 'movie':
                title = db_service.get_movie_by_imdb_id(imdb_id)
            else:
                title = db_service.get_tvshow_by_imdb_id(imdb_id)
            in_my_list = any(item.get('id') == imdb_id for item in db_service.get_my_list())
        
        if not title:
            return jsonify({'success': False, 'error': 'Title not found'}), 404
        
        info = title.to_dict()
        info['type'] = kind
        info['in_my_list'] = in_my_list
        info['genres'] = info.get('genres') or []
        info['cast'] = []
        info['trailer_key'] = None
        
        if title.tmdb_id:
            if kind == 'movie':
                url = f"{api_config.TMDB_BASE_URL}/movie/{title.tmdb_id}"
                details = get_cached_tmdb_data(url, str(MOVIE_DETAILS_APPEND))
                info['runtime'] = details.get('runtime')
            else:
                url = f"{api_config.TMDB_BASE_URL}/tv/{title.tmdb_id}"
                details = get_cached_tmdb_data(url, str(TV_DETAILS_APPEND))
                info['number_of_seasons'] = details.get('number_of_seasons') or info.get('number_of_seasons')
            
            info['overview'] = details.get('overview') or info.get('overview')
            info['tagline'] = details.get('tagline', '')
            info['genres'] = [genre['name'] for genre in details.get('genres', []) if genre.get('name')] or info['genres']
            info['cast'] = [person['name'] for person in details.get('credits', {}).get('cast', [])[:5] if person.get('name')]
            info['trailer_key'] = _pick_trailer_key(details)
        
        return jsonify({'success': True, 'item': info})
    except Exception as e:
        logger.error(f"Error loading title info for {kind} {imdb_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/search_suggestions')
def search_suggestions():
    """Get search suggestions as user types - ULTRA FAST FTS search"""
    query = request.args.get('q', '').strip()
    if not query or len(query) < 2:
        return jsonify({'results': []})
    
    # For very short queries (2 chars), require exact start match for speed
    if len(query) == 2:
        per_page = 2  # Reduce results for very short queries
    else:
        per_page = 3
    
    try:
        suggestions = []
        
        # Search local database using FTS for instant results
        with _user_db() as db_service:
            movies = db_service.search_movies(query, page=1, per_page=per_page)
            series = db_service.search_tvshows(query, page=1, per_page=per_page)
        
        # Add movies to suggestions
        for movie in movies:
            suggestions.append({
                'id': movie.get('imdb_id'),
                'title': movie.get('title'),
                'type': 'movie',
                'year': movie.get('release_date', '')[:4] if movie.get('release_date') else '',
                'poster_url': movie.get('poster_url'),
                'url': f"/movie/{movie.get('imdb_id')}"
            })
        
        # Add series to suggestions
        for show in series:
            suggestions.append({
                'id': show.get('imdb_id'),
                'title': show.get('title'),
                'type': 'series',
                'year': show.get('first_air_date', '')[:4] if show.get('first_air_date') else '',
                'poster_url': show.get('poster_url'),
                'url': f"/series/{show.get('imdb_id')}"
            })
        
        # Sort by relevance (title starts with query) and limit to 6 results
        suggestions.sort(key=lambda x: (
            not x['title'].lower().startswith(query.lower()),  # Prioritize starts-with matches
            x['title'].lower()  # Then alphabetically
        ))
        
        return jsonify({'results': suggestions[:6]})
        
    except Exception as e:
        logger.error(f"Error in search_suggestions: {e}")
        return jsonify({'results': []})

@app.route('/api/my-list', methods=['GET', 'POST'])
def api_my_list():
    """Get My List items or add/remove items via AJAX"""
    if request.method == 'GET':
        # Get My List items
        try:
            with _user_db() as db_service:
                my_list = db_service.get_my_list()
            
            return jsonify({
                'success': True,
                'items': my_list
            })
        except Exception as e:
            logger.error(f"Error fetching My List: {e}")
            return jsonify({
                'success': False,
                'error': str(e),
                'items': []
            }), 500
    
    elif request.method == 'POST':
        # Add or remove item from My List
        try:
            data = request.get_json(silent=True) or {}
            action = data.get('action')
            media_type = data.get('type')
            media_id = data.get('id')
            tmdb_id = data.get('tmdb_id')
            title = data.get('title')
            
            if not all([action, media_type, media_id]):
                return jsonify({
                    'success': False,
                    'error': 'Missing required fields'
                }), 400
            
            with _user_db() as db_service:
                if action == 'add':
                    item, added = db_service.add_to_my_list(media_type, media_id, tmdb_id, title)
                    return jsonify({
                        'success': True,
                        'action': 'added',
                        'message': f'Added to My List'
                    })
                elif action == 'remove':
                    removed = db_service.remove_from_my_list(media_type, media_id)
                    return jsonify({
                        'success': True,
                        'action': 'removed',
                        'message': f'Removed from My List'
                    })
                else:
                    return jsonify({
                        'success': False,
                        'error': 'Invalid action'
                    }), 400
        
        except Exception as e:
            logger.error(f"Error updating My List: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

@app.route('/api/series_watch_status/<imdb_id>')
def api_series_watch_status(imdb_id):
    """Get watch status for all episodes in a series"""
    try:
        with _user_db() as db_service:
            watch_status = db_service.get_series_watch_status(imdb_id)
        
        return jsonify({
            'success': True,
            'watched_by_season': watch_status.get('watched_by_season', {}),
            'total_watched': watch_status.get('total_watched', 0)
        })
    except Exception as e:
        logger.error(f"Error fetching series watch status for {imdb_id}: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'watched_by_season': {},
            'total_watched': 0
        }), 500

@app.route('/api/season_watch_status/<imdb_id>/<int:season_number>')
def api_season_watch_status(imdb_id, season_number):
    """Get watch status for all episodes in a season"""
    try:
        with _user_db() as db_service:
            watch_status = db_service.get_season_watch_status(imdb_id, season_number)
        
        return jsonify({
            'success': True,
            'watched_episodes': watch_status.get('watched_episodes', []),
            'watched_count': watch_status.get('watched_count', 0)
        })
    except Exception as e:
        logger.error(f"Error fetching season watch status for {imdb_id} S{season_number}: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'watched_episodes': [],
            'watched_count': 0
        }), 500

@app.route('/api/watch_progress', methods=['POST'])
def api_watch_progress():
    """Save watch progress for continue watching feature"""
    try:
        data = request.get_json(silent=True) or {}
        media_type = data.get('type')
        media_id = data.get('id')
        progress_seconds = data.get('progress', 0)
        duration_seconds = data.get('duration', 0)
        title = data.get('title', 'Unknown')
        tmdb_id = data.get('tmdb_id')
        season = data.get('season')
        episode = data.get('episode')
        poster_path = data.get('poster_path')
        
        if not all([media_type, media_id]):
            return jsonify({
                'success': False,
                'error': 'Missing required fields'
            }), 400
        
        with _user_db() as db_service:
            watch_history = db_service.save_watch_progress(
                media_type=media_type,
                media_id=media_id,
                progress_seconds=progress_seconds,
                duration_seconds=duration_seconds,
                title=title,
                tmdb_id=tmdb_id,
                season_number=season,
                episode_number=episode,
                poster_path=poster_path
            )
            
            # Calculate progress percentage
            progress_percent = (progress_seconds / duration_seconds * 100) if duration_seconds > 0 else 0
            is_completed = progress_percent >= 95
        
        return jsonify({
            'success': True,
            'message': 'Progress saved',
            'progress_percent': round(progress_percent, 2),
            'is_completed': is_completed
        })
    except Exception as e:
        logger.error(f"Error saving watch progress: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/watch_progress/<media_type>/<media_id>', methods=['GET'])
def get_watch_progress_api(media_type, media_id):
    """Get watch progress for specific content"""
    try:
        season = request.args.get('season', type=int)
        episode = request.args.get('episode', type=int)
        
        with _user_db() as db_service:
            watch_record = db_service.get_watch_progress(
                media_type=media_type,
                media_id=media_id,
                season=season,
                episode=episode
            )
            
            if watch_record:
                return jsonify({
                    'success': True,
                    'progress': watch_record
                })
            else:
                return jsonify({
                    'success': True,
                    'progress': None
                })
        
    except Exception as e:
        logger.error(f"Error getting watch progress: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/mark_watched', methods=['POST'])
def api_mark_watched():
    """Mark an item as watched or unmark it"""
    try:
        data = request.get_json(silent=True) or {}
        action = data.get('action', 'mark')  # 'mark' or 'unmark'
        media_type = data.get('type')
        media_id = data.get('id')
        tmdb_id = data.get('tmdb_id')
        title = data.get('title', 'Unknown')
        season = data.get('season')
        episode = data.get('episode')
        
        if not all([media_type, media_id]):
            return jsonify({
                'success': False,
                'error': 'Missing required fields'
            }), 400
        
        with _user_db() as db_service:
            if action == 'mark':
                success = db_service.mark_as_watched(
                    media_type=media_type,
                    media_id=media_id,
                    tmdb_id=tmdb_id,
                    title=title,
                    season=season,
                    episode=episode
                )
                message = 'Marked as watched'
            else:  # unmark
                success = db_service.unmark_as_watched(
                    media_type=media_type,
                    media_id=media_id,
                    season=season,
                    episode=episode
                )
                message = 'Unmarked as watched'
        
        return jsonify({
            'success': success,
            'message': message,
            'is_watched': action == 'mark'
        })
    except Exception as e:
        logger.error(f"Error marking watched status: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/unmark_watched', methods=['POST'])
def api_unmark_watched():
    """Unmark an item as watched (dedicated endpoint)"""
    try:
        data = request.get_json(silent=True) or {}
        media_type = data.get('type')
        media_id = data.get('id') or data.get('imdb_id')
        season = data.get('season')
        episode = data.get('episode')
        
        if not all([media_type, media_id]):
            return jsonify({
                'success': False,
                'error': 'Missing required fields'
            }), 400
        
        with _user_db() as db_service:
            success = db_service.unmark_as_watched(
                media_type=media_type,
                media_id=media_id,
                season=season,
                episode=episode
            )
        
        return jsonify({
            'success': success,
            'message': 'Unmarked as watched',
            'is_watched': False
        })
    except Exception as e:
        logger.error(f"Error unmarking watched status: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/mark_season_watched', methods=['POST'])
def mark_season_as_watched_api():
    """Mark entire season as watched"""
    try:
        data = request.get_json(silent=True) or {}
        media_id = data.get('id') or data.get('imdb_id')
        tmdb_id = data.get('tmdb_id')
        series_title = data.get('title', 'Unknown')
        season_number = data.get('season_number')
        episode_count = data.get('episode_count')
        
        if not media_id or not season_number or not episode_count:
            return jsonify({'error': 'Missing required fields'}), 400
        
        with _user_db() as db_service:
            success = db_service.mark_season_as_watched(
                media_id=media_id,
                tmdb_id=tmdb_id,
                series_title=series_title,
                season_number=season_number,
                episode_count=episode_count
            )
            
            if success:
                logger.info(f"Marked season {season_number} as watched: {series_title}")
            
            return jsonify({'success': success})
        
    except Exception as e:
        logger.error(f"Error marking season as watched: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/unmark_season_watched', methods=['POST'])
def unmark_season_as_watched_api():
    """Remove watched marks from entire season"""
    try:
        data = request.get_json(silent=True) or {}
        media_id = data.get('id') or data.get('imdb_id')
        season_number = data.get('season_number')
        
        if not media_id or not season_number:
            return jsonify({'error': 'Missing required fields'}), 400
        
        with _user_db() as db_service:
            success = db_service.unmark_season_as_watched(
                media_id=media_id,
                season_number=season_number
            )
            
            return jsonify({'success': success})
        
    except Exception as e:
        logger.error(f"Error unmarking season as watched: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/mark_series_watched', methods=['POST'])
def mark_series_as_watched_api():
    """Mark entire series as watched"""
    try:
        data = request.get_json(silent=True) or {}
        media_id = data.get('id') or data.get('imdb_id')
        tmdb_id = data.get('tmdb_id')
        series_title = data.get('title', 'Unknown')
        seasons_data = data.get('seasons', [])
        
        if not media_id or not seasons_data:
            return jsonify({'error': 'Missing required fields'}), 400
        
        with _user_db() as db_service:
            success = db_service.mark_series_as_watched(
                media_id=media_id,
                tmdb_id=tmdb_id,
                series_title=series_title,
                seasons_data=seasons_data
            )
            
            if success:
                logger.info(f"Marked entire series as watched: {series_title}")
            
            return jsonify({'success': success})
        
    except Exception as e:
        logger.error(f"Error marking series as watched: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/unmark_series_watched', methods=['POST'])
def unmark_series_as_watched_api():
    """Remove watched marks from entire series"""
    try:
        data = request.get_json(silent=True) or {}
        media_id = data.get('id') or data.get('imdb_id')
        
        if not media_id:
            return jsonify({'error': 'Missing required fields'}), 400
        
        with _user_db() as db_service:
            success = db_service.unmark_series_as_watched(media_id=media_id)
            
            return jsonify({'success': success})
        
    except Exception as e:
        logger.error(f"Error unmarking series as watched: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/watched_status/<media_type>/<media_id>')
def api_watched_status(media_type, media_id):
    """Check if an item is marked as watched"""
    try:
        season = request.args.get('season', type=int)
        episode = request.args.get('episode', type=int)
        
        with _user_db() as db_service:
            is_watched = db_service.is_marked_watched(
                media_type=media_type,
                media_id=media_id,
                season=season,
                episode=episode
            )
        
        return jsonify({
            'success': True,
            'is_watched': is_watched
        })
    except Exception as e:
        logger.error(f"Error checking watched status for {media_type}/{media_id}: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'is_watched': False
        }), 500

@app.route('/api/clear_watch_progress', methods=['POST'])
def api_clear_watch_progress():
    """Clear watch progress for an item (remove from Continue Watching)"""
    try:
        data = request.get_json(silent=True) or {}
        media_type = data.get('type')
        media_id = data.get('id')
        
        if not all([media_type, media_id]):
            return jsonify({
                'success': False,
                'error': 'Missing required fields'
            }), 400
        
        with _user_db() as db_service:
            success = db_service.clear_watch_progress(media_type, media_id)
        
        return jsonify({
            'success': success,
            'message': 'Watch progress cleared'
        })
    except Exception as e:
        logger.error(f"Error clearing watch progress: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/filter')
def api_filter_content():
    """
    API endpoint to filter content by type and/or genre
    Query params:
        - type: 'movie' or 'series' (required)
        - genre: genre name (optional, e.g., 'Action', 'Comedy')
        - page: page number for pagination (default: 1)
        - limit: number of items to return (default: pagination_config.DEFAULT_PER_PAGE)
    """
    try:
        content_type = request.args.get('type', 'movie')
        genre = request.args.get('genre', None)
        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', pagination_config.DEFAULT_PER_PAGE, type=int)
        
        with _user_db() as db_service:
            if content_type == 'movie':
                if genre:
                    # Get movies filtered by genre
                    items = db_service.get_movies_by_genre(genre, page=page, per_page=limit)
                    total_count = db_service.get_total_movies_by_genre(genre)
                else:
                    # Get all movies
                    items = db_service.get_latest_movies(page=page, per_page=limit)
                    total_count = db_service.get_total_movies()
                
                # Format movie data
                results = []
                for movie in items:
                    genres = movie.get('genres', [])
                    if isinstance(genres, str):
                        genres = genres.split(',') if genres else []
                    
                    results.append({
                        'title': movie.get('title', ''),
                        'type': 'movie',
                        'imdb_id': movie.get('imdb_id', ''),
                        'tmdb_id': movie.get('tmdb_id', 0),
                        'poster_url': movie.get('poster_url'),
                        'quality': movie.get('quality', 'HD'),
                        'genres': genres
                    })
                
            else:  # series
                if genre:
                    # Get TV shows filtered by genre
                    items = db_service.get_tvshows_by_genre(genre, page=page, per_page=limit)
                    total_count = db_service.get_total_tvshows_by_genre(genre)
                else:
                    # Get all TV shows
                    items = db_service.get_latest_tvshows(page=page, per_page=limit)
                    total_count = db_service.get_total_tvshows()
                
                # Format series data
                results = []
                for show in items:
                    genres = show.get('genres', [])
                    if isinstance(genres, str):
                        genres = genres.split(',') if genres else []
                    
                    results.append({
                        'title': show.get('title', ''),
                        'type': 'series',
                        'imdb_id': show.get('imdb_id', ''),
                        'tmdb_id': show.get('tmdb_id', 0),
                        'poster_url': show.get('poster_url'),
                        'quality': 'Series',
                        'genres': genres
                    })
            
            return jsonify({
                'success': True,
                'items': results,
                'total': total_count,
                'type': content_type,
                'genre': genre,
                'page': page,
                'limit': limit,
                'has_more': (page * limit) < total_count
            })
            
    except Exception as e:
        logger.error(f"Error filtering content: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'items': [],
            'total': 0
        }), 500

if __name__ == '__main__':
    app.run(
        host=server_config.HOST,
        port=server_config.PORT,
        debug=server_config.DEBUG,
        threaded=True
    )
