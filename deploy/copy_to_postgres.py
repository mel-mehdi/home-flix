"""Copy HomeFlix's SQLite database into an empty Postgres database (for example Neon).

    python deploy/copy_to_postgres.py "postgresql://user:password@host/dbname?sslmode=require"
    python deploy/copy_to_postgres.py "postgresql://..." --catalogue-only

Reads homeflix.db (read-only) and copies accounts, My List, watch history, watched marks
and the catalogue. Refuses to write into a database that already has HomeFlix accounts,
so running it twice can't overwrite what people saved on the hosted site.

--catalogue-only adds the movies and series the hosted database is missing, and touches
nothing else: accounts, lists and titles already there stay as they are.
"""
import json
import os
import sqlite3
import sys
from datetime import datetime

CATALOGUE_ONLY = sys.argv[2:] == ['--catalogue-only']
if len(sys.argv) != 2 and not CATALOGUE_ONLY:
    sys.exit(__doc__)
if not sys.argv[1].startswith(('postgres://', 'postgresql://')):
    sys.exit('The first argument must be your Neon connection string, starting with postgresql:// '
             '(Neon project page -> Connect -> copy the string), in quotes.')

# Windows consoles default to cp1252, which can't print the emoji in init_db's status message
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# database.py builds its engine from DATABASE_URL when imported, so set it first
os.environ['DATABASE_URL'] = sys.argv[1]
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from sqlalchemy import Boolean, DateTime, JSON, func, insert, select, text  # noqa: E402
from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402
from database import Base, engine, init_db, Movie, TVShow, User, MyList, WatchHistory, WatchedItems  # noqa: E402

SOURCE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'homeflix.db')
MODELS = (User, Movie, TVShow, MyList, WatchHistory, WatchedItems)
CHUNK = 1000


def convert(column, value):
    """SQLite keeps JSON, booleans and dates as text or numbers; Postgres wants real types"""
    if value is None:
        return None
    if isinstance(column.type, JSON) and isinstance(value, str):
        return json.loads(value)
    if isinstance(column.type, Boolean):
        return bool(value)
    if isinstance(column.type, DateTime) and isinstance(value, str):
        return datetime.fromisoformat(value)
    return value


def add_missing_catalogue(source):
    """Insert the titles the database lacks; a title already there (same IMDb or TMDB ID) is skipped"""
    with engine.begin() as conn:
        for model in (Movie, TVShow):
            table = model.__table__
            before = conn.execute(select(func.count()).select_from(table)).scalar()
            source_columns = {row[1] for row in source.execute(f'pragma table_info({table.name})')}
            # Leave out id: the database numbers new rows itself, after the ones it already has
            columns = [c for c in table.columns if c.name in source_columns and c.name != 'id']
            cursor = source.execute(f"select {', '.join(c.name for c in columns)} from {table.name}")
            while rows := cursor.fetchmany(CHUNK):
                conn.execute(pg_insert(table).on_conflict_do_nothing(), [
                    {c.name: convert(c, value) for c, value in zip(columns, row)} for row in rows
                ])
            after = conn.execute(select(func.count()).select_from(table)).scalar()
            print(f'{table.name}: {after - before} added, {after} in total')


def main():
    if engine.dialect.name != 'postgresql':
        sys.exit('The address must be a Postgres database (postgres:// or postgresql://).')

    # Snapshot first, so a sync writing at the same moment can't leave the copy half-updated
    source = sqlite3.connect(':memory:')
    sqlite3.connect(f'file:{SOURCE}?mode=ro', uri=True).backup(source)
    init_db()

    if CATALOGUE_ONLY:
        add_missing_catalogue(source)
        print('Done.')
        return

    with engine.connect() as conn:
        if conn.execute(select(func.count()).select_from(User.__table__)).scalar():
            sys.exit('This database already has HomeFlix accounts; nothing was copied.')

    with engine.begin() as conn:
        for model in MODELS:
            table = model.__table__
            conn.execute(table.delete())  # catalogue rows from an earlier, interrupted run
            source_columns = {row[1] for row in source.execute(f'pragma table_info({table.name})')}
            columns = [c for c in table.columns if c.name in source_columns]
            names = ', '.join(c.name for c in columns)
            cursor = source.execute(f'select {names} from {table.name}')
            copied = 0
            while rows := cursor.fetchmany(CHUNK):
                conn.execute(insert(table), [
                    {c.name: convert(c, value) for c, value in zip(columns, row)} for row in rows
                ])
                copied += len(rows)
            # New rows must get ids after the copied ones
            conn.execute(text(
                f"select setval(pg_get_serial_sequence('{table.name}', 'id'), "
                f"coalesce((select max(id) from {table.name}), 0) + 1, false)"))
            print(f'{table.name}: {copied} rows')

    print('Done.')


if __name__ == '__main__':
    main()
