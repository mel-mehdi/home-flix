"""
Read by gunicorn automatically when it starts in the app folder without naming a config or the app,
as Back4app's start command does: gunicorn --worker-tmp-dir /dev/shm -b 0.0.0.0:$PORT
"""
import os

wsgi_app = 'media_server:app'
bind = f"0.0.0.0:{os.getenv('PORT', '5000')}"

# One process: a 256 MB container holds one copy of the app, and the in-app catalogue sync
# (SYNC_IN_APP) must run once. Threads let it serve several visitors at the same time.
workers = int(os.getenv('WEB_CONCURRENCY', '1'))
worker_class = 'gthread'
threads = int(os.getenv('GUNICORN_THREADS', '8'))
timeout = 60

accesslog = '-'
errorlog = '-'
