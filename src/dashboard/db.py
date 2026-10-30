from flask import g

from src.database.manager import DatabaseManager


def get_db():
    """One SQLite connection per web request, closed automatically."""
    if "db" not in g:
        g.db = DatabaseManager().get_connection()
    return g.db


def close_db(_error=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()
