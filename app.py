"""Entrypoint Vercel looks for: a Flask instance named `app` in app.py. The app itself is in media_server.py."""
from media_server import app  # noqa: F401
